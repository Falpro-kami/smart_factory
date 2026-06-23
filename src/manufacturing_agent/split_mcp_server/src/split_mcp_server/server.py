import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import pymysql
from dotenv import load_dotenv
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from neo4j import GraphDatabase

try:
    from .work_order_validation import (
        WorkOrderDraftValidationError,
        build_rule_based_work_order_draft,
        validate_and_complete_work_order_draft,
    )
except ImportError:
    from work_order_validation import (
        WorkOrderDraftValidationError,
        build_rule_based_work_order_draft,
        validate_and_complete_work_order_draft,
    )


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

app = Server("split_mcp_server")


def load_env() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)


def agent_backend_base_url() -> str:
    load_env()
    return os.environ.get("AGENT_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def notify_digital_twin_event(event_type: str, data: dict[str, Any]) -> None:
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{agent_backend_base_url()}/api/digital-twin/events",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            pass
    except Exception:
        pass


def get_neo4j_driver():
    load_env()
    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    return GraphDatabase.driver(uri, auth=(username, password))


def get_mysql_connection(database: str):
    load_env()
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def safe_column_name(name: str) -> str:
    if not re.fullmatch(r"[\w\u4e00-\u9fff]+", name):
        raise ValueError(f"unsafe column name: {name}")
    return f"`{name}`"


def table_columns(cursor: Any, database: str, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (database, table_name),
    )
    return {str(row.get("COLUMN_NAME")) for row in cursor.fetchall()}


def first_existing_column(columns: set[str], candidates: tuple[str, ...]) -> str:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in columns:
            return candidate
        actual = lowered.get(candidate.lower())
        if actual:
            return actual
    return ""


def order_id_column(cursor: Any) -> str:
    columns = table_columns(cursor, "order", "orders")
    column = first_existing_column(columns, ("订单编号", "订单ID", "order_id", "orderId", "id"))
    if not column:
        raise RuntimeError("orders table has no order id column")
    return column


def work_order_assigned_device_column(cursor: Any) -> str:
    columns = table_columns(cursor, "order", "work_orders")
    column = first_existing_column(columns, ("分配设备", "分配工站", "assigned_device_id", "device_id"))
    return column or "分配设备"


ORDER_STATUSES = ("已创建", "已计划", "已下发", "生产中", "已完成", "失败")
WORK_ORDER_STATUSES = ("已创建", "受阻", "已下发", "已接收", "执行中", "已完成", "失败")
ORDER_LEGACY_STATUSES = ("等待中", "已分配", "已取消", "已下单", "异常", "已接收", "执行中")
WORK_ORDER_LEGACY_STATUSES = ("等待中", "已分配", "已取消", "已下单", "异常")
SCHEDULER_QUEUE_TABLE = "scheduler_order_queue"
WORK_ORDER_DELIVERY_LOG_TABLE = "work_order_delivery_log"
ORDER_ID_SEQUENCE_WIDTH = 3


def ensure_order_status_schema(cursor: Any) -> None:
    order_current_and_legacy = ",".join(f"'{status}'" for status in (*ORDER_STATUSES, *ORDER_LEGACY_STATUSES))
    order_target_only = ",".join(f"'{status}'" for status in ORDER_STATUSES)
    work_order_current_and_legacy = ",".join(f"'{status}'" for status in (*WORK_ORDER_STATUSES, *WORK_ORDER_LEGACY_STATUSES))
    work_order_target_only = ",".join(f"'{status}'" for status in WORK_ORDER_STATUSES)
    try:
        cursor.execute(f"ALTER TABLE `work_orders` MODIFY `工单状态` ENUM({work_order_current_and_legacy}) NOT NULL DEFAULT '已创建'")
        cursor.execute("UPDATE `work_orders` SET `工单状态` = '已创建' WHERE `工单状态` IN ('等待中', '已下单')")
        cursor.execute("UPDATE `work_orders` SET `工单状态` = '已下发' WHERE `工单状态` = '已分配'")
        cursor.execute("UPDATE `work_orders` SET `工单状态` = '失败' WHERE `工单状态` IN ('已取消', '异常')")
        cursor.execute(f"ALTER TABLE `work_orders` MODIFY `工单状态` ENUM({work_order_target_only}) NOT NULL DEFAULT '已创建'")
    except Exception as exc:
        print(f"work order status schema sync skipped: {exc}", file=sys.stderr, flush=True)

    try:
        cursor.execute(f"ALTER TABLE `orders` MODIFY `订单状态` ENUM({order_current_and_legacy}) NOT NULL DEFAULT '已创建'")
        cursor.execute("UPDATE `orders` SET `订单状态` = '已创建' WHERE `订单状态` IN ('等待中', '已下单')")
        cursor.execute("UPDATE `orders` SET `订单状态` = '已下发' WHERE `订单状态` = '已分配'")
        cursor.execute("UPDATE `orders` SET `订单状态` = '生产中' WHERE `订单状态` IN ('已接收', '执行中')")
        cursor.execute("UPDATE `orders` SET `订单状态` = '失败' WHERE `订单状态` IN ('已取消', '异常')")
        cursor.execute(f"ALTER TABLE `orders` MODIFY `订单状态` ENUM({order_target_only}) NOT NULL DEFAULT '已创建'")
    except Exception as exc:
        print(f"order status schema sync skipped: {exc}", file=sys.stderr, flush=True)


def ensure_scheduler_queue_schema(cursor: Any) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEDULER_QUEUE_TABLE} (
            order_id VARCHAR(64) PRIMARY KEY,
            queue_status ENUM('pending','active','completed','failed') NOT NULL DEFAULT 'pending',
            submitted_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            last_run_at DATETIME NULL,
            last_summary_json JSON NULL,
            INDEX idx_scheduler_queue_status (queue_status),
            INDEX idx_scheduler_queue_updated (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def ensure_work_order_delivery_log_schema(cursor: Any) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {WORK_ORDER_DELIVERY_LOG_TABLE} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            work_order_id VARCHAR(64) NOT NULL,
            device_id VARCHAR(64) NOT NULL,
            topic VARCHAR(128) NOT NULL,
            tag VARCHAR(128) DEFAULT '',
            message_key VARCHAR(128) NOT NULL,
            message_id VARCHAR(128) DEFAULT '',
            send_result VARCHAR(64) DEFAULT '',
            send_output TEXT,
            sent_at DATETIME NOT NULL,
            INDEX idx_delivery_log_work_order (work_order_id),
            INDEX idx_delivery_log_message_key (message_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def extract_mqadmin_send_result(output: str) -> dict[str, str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if "SEND_OK" not in line:
            continue
        parts = re.split(r"\s+", line)
        return {
            "send_result": next((part for part in parts if part == "SEND_OK"), "SEND_OK"),
            "message_id": parts[-1] if parts else "",
        }
    return {"send_result": "", "message_id": ""}


def record_work_order_delivery_log(message_payload: dict[str, Any], send_result: dict[str, Any]) -> None:
    sent_at = datetime.now()
    body = message_payload.get("body") if isinstance(message_payload.get("body"), dict) else {}
    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_work_order_delivery_log_schema(cursor)
            cursor.execute(
                f"""
                INSERT INTO {WORK_ORDER_DELIVERY_LOG_TABLE} (
                    work_order_id, device_id, topic, tag, message_key,
                    message_id, send_result, send_output, sent_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(body.get("work_order_id") or message_payload.get("key") or ""),
                    str(body.get("device_id") or message_payload.get("tag") or ""),
                    str(message_payload.get("topic") or ""),
                    str(message_payload.get("tag") or ""),
                    str(message_payload.get("key") or ""),
                    str(send_result.get("message_id") or ""),
                    str(send_result.get("send_result") or ""),
                    str(send_result.get("send_output") or send_result.get("send_result") or ""),
                    sent_at,
                ),
            )
        conn.commit()


def rocketmq_config() -> dict[str, str | int]:
    load_env()
    return {
        "namesrv_addr": os.environ.get("ROCKETMQ_NAMESRV_ADDR", "127.0.0.1:9876"),
        "producer_group": os.environ.get("ROCKETMQ_PRODUCER_GROUP", "PID_WORK_ORDER_DELIVERY"),
        "topic": "WorkOrderDeliver",
        "send_timeout_ms": int(os.environ.get("ROCKETMQ_SEND_TIMEOUT_MS", "30000")),
    }


def normalize_work_order_delivery(arguments: dict[str, Any]) -> dict[str, Any]:
    device_id = str(arguments.get("device_id") or arguments.get("deviceId") or "").strip()
    work_order_id = str(arguments.get("work_order_id") or arguments.get("workOrderId") or "").strip()
    process_id = str(arguments.get("process_id") or arguments.get("processId") or "").strip()
    process_description = str(
        arguments.get("process_description")
        or arguments.get("processDescription")
        or arguments.get("description")
        or ""
    ).strip()
    if not device_id:
        raise ValueError("device_id is required")
    if not work_order_id:
        raise ValueError("work_order_id is required")
    if not process_id:
        raise ValueError("process_id is required")
    if not process_description:
        raise ValueError("process_description is required")

    return {
        "device_id": device_id,
        "work_order_id": work_order_id,
        "process_id": process_id,
        "process_description": process_description,
    }


def build_work_order_delivery_message(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_work_order_delivery(arguments)
    config = rocketmq_config()
    body = {
        "delivery_id": str(arguments.get("delivery_id") or arguments.get("deliveryId") or uuid.uuid4()),
        "device_id": normalized["device_id"],
        "work_order_id": normalized["work_order_id"],
        "process_id": normalized["process_id"],
        "process_description": normalized["process_description"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    for field in ("source_station", "target_station", "source_station_name", "target_station_name"):
        value = arguments.get(field)
        if value not in (None, ""):
            body[field] = str(value)
    return {
        "topic": config["topic"],
        "key": normalized["work_order_id"],
        "tag": normalized["device_id"],
        "body": body,
    }


def send_rocketmq_message(message_payload: dict[str, Any]) -> dict[str, Any]:
    if os.name == "nt":
        return send_rocketmq_message_with_mqadmin(message_payload)

    try:
        from rocketmq.client import Message, Producer
    except ImportError as exc:
        raise RuntimeError("rocketmq-client-python is not installed") from exc

    config = rocketmq_config()
    message = Message(str(message_payload["topic"]))
    message.set_keys(str(message_payload["key"]))
    message.set_tags(str(message_payload["tag"]))
    message.set_body(json.dumps(message_payload["body"], ensure_ascii=False).encode("utf-8"))

    producer = Producer(str(config["producer_group"]))
    producer.set_name_server_address(str(config["namesrv_addr"]))
    producer.start()
    try:
        result = producer.send_sync(message)
    finally:
        producer.shutdown()

    return {
        "namesrv_addr": config["namesrv_addr"],
        "producer_group": config["producer_group"],
        "send_result": str(result),
    }


def send_rocketmq_message_with_mqadmin(message_payload: dict[str, Any]) -> dict[str, Any]:
    config = rocketmq_config()
    rocketmq_home = Path(
        os.environ.get("ROCKETMQ_HOME")
        or ROOT_DIR / "rocketmq" / "rocketmq-all-5.3.2-bin-release"
    )
    mqadmin = rocketmq_home / "bin" / "mqadmin.cmd"
    if not mqadmin.exists():
        raise RuntimeError(f"mqadmin.cmd not found: {mqadmin}")

    body_json = json.dumps(message_payload["body"], ensure_ascii=False)
    command = [
        str(mqadmin),
        "sendMessage",
        "-n",
        str(config["namesrv_addr"]),
        "-t",
        str(message_payload["topic"]),
        "-k",
        str(message_payload["key"]),
        "-c",
        str(message_payload["tag"]),
        "-p",
        body_json,
    ]
    env = os.environ.copy()
    env["ROCKETMQ_HOME"] = str(rocketmq_home)
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=max(30, int(config["send_timeout_ms"]) // 1000 + 5),
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(error or output or f"mqadmin sendMessage failed: {completed.returncode}")
    parsed = extract_mqadmin_send_result(output or error)
    if parsed.get("send_result") != "SEND_OK":
        raise RuntimeError(output or error or "mqadmin sendMessage did not return SEND_OK")

    return {
        "namesrv_addr": config["namesrv_addr"],
        "producer_group": config["producer_group"],
        "send_result": parsed.get("send_result") or "SEND_OK",
        "message_id": parsed.get("message_id") or "",
        "send_output": output or error or "",
    }


def mark_order_planned(order_id: str) -> dict[str, Any]:
    planned_at = datetime.now()
    try:
        with get_mysql_connection("order") as conn:
            with conn.cursor() as cursor:
                ensure_order_status_schema(cursor)
                order_id_col = safe_column_name(order_id_column(cursor))
                cursor.execute(
                    f"""
                    UPDATE `orders`
                    SET `订单状态` = '已计划'
                    WHERE {order_id_col} = %s AND `订单状态` = '已创建'
                    """,
                    (order_id,),
                )
                updated = cursor.rowcount
            conn.commit()
    except Exception as exc:
        return {
            "order_id": order_id,
            "status": "已计划",
            "updated": False,
            "updated_rows": 0,
            "updated_at": planned_at.isoformat(timespec="seconds"),
            "error": str(exc),
        }

    status_update = {
        "order_id": order_id,
        "status": "已计划",
        "updated": bool(updated),
        "updated_rows": updated,
        "updated_at": planned_at.isoformat(timespec="seconds"),
    }
    if updated:
        notify_digital_twin_event("order_status_changed", status_update)
    return status_update


def mark_work_order_dispatched(work_order_id: str) -> dict[str, Any]:
    dispatched_at = datetime.now()
    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_order_status_schema(cursor)
            cursor.execute(
                """
                UPDATE `work_orders`
                SET `工单状态` = '已下发', `更新时间` = %s
                WHERE (`工单ID` = %s OR `工单名称` = %s)
                  AND `工单状态` NOT IN ('已接收', '执行中', '已完成', '失败')
                """,
                (dispatched_at, work_order_id, work_order_id),
            )
            updated = cursor.rowcount
            cursor.execute(
                """
                SELECT `所属订单号`
                FROM `work_orders`
                WHERE `工单ID` = %s OR `工单名称` = %s
                LIMIT 1
                """,
                (work_order_id, work_order_id),
            )
            row = cursor.fetchone() or {}
            order_id = str(row.get("所属订单号") or "")
            if order_id:
                order_id_col = safe_column_name(order_id_column(cursor))
                cursor.execute(
                    f"""
                    UPDATE `orders`
                    SET `订单状态` = '已下发'
                    WHERE {order_id_col} = %s AND `订单状态` IN ('已创建', '已计划')
                    """,
                    (order_id,),
                )
        conn.commit()

    status_update = {
        "work_order_id": work_order_id,
        "status": "已下发",
        "updated": bool(updated),
        "updated_rows": updated,
        "updated_at": dispatched_at.isoformat(timespec="seconds"),
    }
    if updated:
        notify_digital_twin_event("work_order_status_changed", status_update)
    return status_update


def work_order_delivery(arguments: dict[str, Any]) -> dict[str, Any]:
    message_payload = build_work_order_delivery_message(arguments)
    send_result = send_rocketmq_message(message_payload)
    record_work_order_delivery_log(message_payload, send_result)
    status_update = mark_work_order_dispatched(str(message_payload["key"]))
    result = {
        "success": True,
        "tool": "WorkOrderDelivery",
        "sent": True,
        "status_update": status_update,
        **message_payload,
        **send_result,
    }
    return result


def split_dependency_ids(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text in {"无", "none", "null", "None", "NULL"}:
        return []
    return [
        item.strip()
        for item in re.split(r"[,，;；、\s]+", text)
        if item.strip() and item.strip() not in {"无", "none", "null", "None", "NULL"}
    ]


def set_work_order_status(
    cursor: Any,
    work_order_id: str,
    status: str,
    event_time: datetime,
) -> int:
    cursor.execute(
        """
        UPDATE `work_orders`
        SET `工单状态` = %s, `更新时间` = %s
        WHERE (`工单ID` = %s OR `工单名称` = %s)
          AND `工单状态` NOT IN ('已接收', '执行中', '已完成', '失败')
        """,
        (status, event_time, work_order_id, work_order_id),
    )
    return int(cursor.rowcount or 0)


def fetch_scheduler_candidates(cursor: Any, order_id: str, limit: int) -> list[dict[str, Any]]:
    assigned_device_col = safe_column_name(work_order_assigned_device_column(cursor))
    cursor.execute(
        f"""
        SELECT
            `工单ID` AS work_order_id,
            `工单名称` AS work_order_name,
            `所属订单号` AS order_id,
            `工单状态` AS status,
            `工序编号` AS process_id,
            `前置工单` AS predecessor_work_orders,
            {assigned_device_col} AS device_id,
            `description` AS process_description,
            `工单ID` AS sort_id
        FROM `work_orders`
        WHERE `所属订单号` = %s
          AND `工单状态` IN ('已创建', '受阻')
        ORDER BY `工单ID`
        LIMIT %s
        """,
        (order_id, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def fetch_dependency_statuses(cursor: Any, order_id: str, dependencies: list[str]) -> dict[str, str]:
    if not dependencies:
        return {}
    cursor.execute(
        """
        SELECT `工单ID` AS work_order_db_id, `工单名称` AS work_order_name, `工单状态` AS status
        FROM `work_orders`
        WHERE `所属订单号` = %s
        ORDER BY `工单ID`
        """,
        (order_id,),
    )
    status_by_key: dict[str, str] = {}
    for index, row in enumerate(cursor.fetchall(), start=1):
        status = str(row.get("status") or "")
        for key in (
            row.get("work_order_db_id"),
            row.get("work_order_name"),
            f"{order_id}-WO-{index:03d}",
        ):
            text = str(key or "").strip()
            if text:
                status_by_key[text] = status
    return {dependency: status_by_key.get(dependency, "missing") for dependency in dependencies}


def dependency_check(cursor: Any, work_order: dict[str, Any]) -> dict[str, Any]:
    dependencies = split_dependency_ids(work_order.get("predecessor_work_orders"))
    if not dependencies:
        return {"ready": True, "dependencies": [], "unmet_dependencies": []}
    statuses = fetch_dependency_statuses(cursor, str(work_order.get("order_id") or ""), dependencies)
    unmet = [
        {"work_order_id": dependency, "status": statuses.get(dependency, "missing")}
        for dependency in dependencies
        if statuses.get(dependency) != "已完成"
    ]
    return {
        "ready": not unmet,
        "dependencies": [{"work_order_id": item, "status": statuses.get(item, "missing")} for item in dependencies],
        "unmet_dependencies": unmet,
    }


def fetch_device_runtime(device_id: str) -> dict[str, Any]:
    if not device_id:
        return {}
    try:
        with get_mysql_connection("device") as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        `设备编号` AS device_id,
                        `设备名称` AS device_name,
                        `连接状态` AS connection_state,
                        `运行状态` AS status,
                        `更新时间` AS updated_at
                    FROM devices
                    WHERE `设备编号` = %s OR `设备名称` = %s
                    LIMIT 1
                    """,
                    (device_id, device_id),
                )
                return dict(cursor.fetchone() or {})
    except Exception as exc:
        return {"device_id": device_id, "error": str(exc)}


def device_is_online_idle(device: dict[str, Any]) -> bool:
    connection_state = str(device.get("connection_state") or "").strip().lower()
    status = str(device.get("status") or "").strip().lower()
    return connection_state == "online" and status == "idle"


def scheduler_delivery_arguments(work_order: dict[str, Any]) -> dict[str, Any]:
    work_order_id = str(work_order.get("work_order_id") or "").strip()
    device_id = str(work_order.get("device_id") or "").strip()
    process_id = str(work_order.get("process_id") or work_order_id).strip()
    process_description = str(
        work_order.get("process_description")
        or f"执行工单 {work_order_id}"
    ).strip()
    delivery_arguments = {
        "device_id": device_id,
        "work_order_id": work_order_id,
        "process_id": process_id,
        "process_description": process_description,
        "delivery_id": f"scheduler-{uuid.uuid4()}",
    }
    transport_fields = extract_transport_fields_from_description(process_description)
    delivery_arguments.update(transport_fields)
    return delivery_arguments


def extract_transport_fields_from_description(description: str) -> dict[str, str]:
    marker = "TRANSPORT_TASK_JSON:"
    if marker not in description:
        return {}
    payload_text = description.rsplit(marker, 1)[1].strip()
    try:
        payload = json.loads(payload_text)
    except Exception:
        return {}
    source_device = payload.get("source_device") if isinstance(payload.get("source_device"), dict) else {}
    target_device = payload.get("target_device") if isinstance(payload.get("target_device"), dict) else {}
    fields = {
        "source_station": str(source_device.get("device_id") or source_device.get("workstation_id") or ""),
        "target_station": str(target_device.get("device_id") or target_device.get("workstation_id") or ""),
        "source_station_name": str(source_device.get("device_name") or source_device.get("workstation_name") or ""),
        "target_station_name": str(target_device.get("device_name") or target_device.get("workstation_name") or ""),
    }
    return {key: value for key, value in fields.items() if value}


def work_order_scheduler(arguments: dict[str, Any]) -> dict[str, Any]:
    from split_mcp_server.scheduler_service import work_order_scheduler as scheduler_impl

    return scheduler_impl(arguments)


def submit_order_to_scheduler(arguments: dict[str, Any]) -> dict[str, Any]:
    order_id = str(arguments.get("order_id") or arguments.get("orderId") or "").strip()
    if not order_id:
        raise ValueError("order_id is required")
    submitted_at = datetime.now()
    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_scheduler_queue_schema(cursor)
            cursor.execute(
                f"""
                INSERT INTO {SCHEDULER_QUEUE_TABLE} (
                    order_id, queue_status, submitted_at, updated_at
                ) VALUES (%s, 'pending', %s, %s)
                ON DUPLICATE KEY UPDATE
                    queue_status = CASE
                        WHEN queue_status IN ('completed', 'failed') THEN 'pending'
                        ELSE queue_status
                    END,
                    updated_at = VALUES(updated_at)
                """,
                (order_id, submitted_at, submitted_at),
            )
        conn.commit()
    payload = {
        "order_id": order_id,
        "queue_status": "pending",
        "submitted_at": submitted_at.isoformat(timespec="seconds"),
    }
    notify_digital_twin_event("scheduler_order_submitted", payload)
    return {
        "success": True,
        "tool": "WorkOrderScheduler",
        "mode": "submit_only",
        "message": "订单已投入后台调度器，后续由常驻调度服务自动调度工单。",
        **payload,
    }


def order_status_for_scheduler(cursor: Any, order_id: str) -> str:
    order_id_col = safe_column_name(order_id_column(cursor))
    cursor.execute(
        f"""
        SELECT COALESCE(`订单状态`, '') AS order_status
        FROM `orders`
        WHERE {order_id_col} = %s
        LIMIT 1
        """,
        (order_id,),
    )
    row = cursor.fetchone() or {}
    return str(row.get("order_status") or "")


def scheduler_queue_rows(cursor: Any, limit: int) -> list[dict[str, Any]]:
    ensure_scheduler_queue_schema(cursor)
    cursor.execute(
        f"""
        SELECT order_id, queue_status
        FROM {SCHEDULER_QUEUE_TABLE}
        WHERE queue_status IN ('pending', 'active')
        ORDER BY submitted_at, order_id, updated_at
        LIMIT %s
        """,
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def run_scheduler_queue_once(limit: int = 20) -> dict[str, Any]:
    from split_mcp_server.scheduler_service import run_scheduler_queue_once as scheduler_impl

    return scheduler_impl(limit=limit)


def clean_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [clean_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): clean_value(item) for key, item in value.items()}
    return str(value)


def normalize_props(props: dict[str, Any]) -> dict[str, Any]:
    return {str(key): clean_value(value) for key, value in props.items()}


def normalize_material_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        props = normalize_props(item)
    else:
        props = {"name": str(item)}
    material_id = first_present_normalized(
        props,
        (
            "物料编号",
            "物料ID",
            "物料编码",
            "material_code",
            "materialCode",
            "material_id",
            "materialId",
            "partId",
            "part_id",
            "code",
            "id",
        ),
    )
    material_name = first_present_normalized(
        props,
        ("物料名称", "物料名", "material_name", "materialName", "name", "label", "title"),
    )
    return {
        "material_id": clean_value(material_id or material_name),
        "material_name": clean_value(material_name or material_id),
        "material_type": clean_value(first_present_normalized(props, ("物料类型", "material_type", "materialType", "type"))),
        "quantity": int(float(props.get("quantity") or props.get("数量") or 1)),
        "properties": props,
    }


def collect_argument_materials(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    raw_materials = (
        arguments.get("materials")
        or arguments.get("selected_materials")
        or arguments.get("selectedMaterials")
        or arguments.get("material_list")
        or arguments.get("materialList")
        or arguments.get("material_ids")
        or arguments.get("materialIds")
        or []
    )
    if isinstance(raw_materials, str):
        raw_materials = [item.strip() for item in raw_materials.replace("，", ",").replace("、", ",").split(",")]
    if not isinstance(raw_materials, list):
        raw_materials = [raw_materials]
    return [normalize_material_item(item) for item in raw_materials if item not in (None, "")]


def collect_part_materials(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_material_item(part.get("properties") or part) for part in parts]


def collect_route_input_materials(route_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    for step in route_steps:
        for item in step.get("uses") or []:
            item_type = normalize_match_text(item.get("type") or item.get("material_type") or item.get("物料类型"))
            if item_type in {"产品", "product"}:
                continue
            materials.append(normalize_material_item(item))
    return materials


def dedupe_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for material in materials:
        key = normalize_match_text(material.get("material_id") or material.get("material_name"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(material)
    return deduped


def store_material_to_payload(row: dict[str, Any], requirement: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "material_id": clean_value(row.get("物料编号") or row.get("material_id") or row.get("id")),
        "material_name": clean_value(row.get("物料名称") or row.get("material_name") or row.get("name")),
        "material_type": clean_value(row.get("物料类型") or row.get("material_type") or row.get("type")),
        "location": clean_value(row.get("库位号") or row.get("location") or row.get("slot")),
        "requirement": requirement or {},
        "properties": normalize_props(row),
        "source": "mysql:store.materials",
    }


def material_requirement_values(material: dict[str, Any]) -> dict[str, str]:
    props = material.get("properties") if isinstance(material.get("properties"), dict) else {}
    material_id = normalize_match_text(
        material.get("material_id")
        or props.get("物料编号")
        or props.get("material_id")
        or props.get("code")
    )
    material_name = normalize_match_text(
        material.get("material_name")
        or props.get("物料名称")
        or props.get("material_name")
        or props.get("name")
    )
    if material_id and material_name and material_id == material_name:
        material_id = ""
    return {
        "id": material_id,
        "name": material_name,
        "type": normalize_match_text(
            material.get("material_type")
            or props.get("物料类型")
            or props.get("material_type")
            or props.get("type")
        ),
    }


def store_row_matches_material(row: dict[str, Any], material: dict[str, Any], *, allow_type_fallback: bool = False) -> bool:
    requirement = material_requirement_values(material)
    row_id = normalize_match_text(row.get("物料编号"))
    row_name = normalize_match_text(row.get("物料名称"))
    row_type = normalize_match_text(row.get("物料类型"))
    if requirement["id"]:
        return requirement["id"] == row_id or requirement["id"] in row_id or row_id in requirement["id"]
    if requirement["name"]:
        name_matches = requirement["name"] == row_name or requirement["name"] in row_name or row_name in requirement["name"]
        if name_matches:
            return True
        return bool(allow_type_fallback and row_type and row_type in requirement["name"])
    if requirement["type"]:
        return requirement["type"] == row_type or requirement["type"] in row_type or row_type in requirement["type"]
    return False


def allocate_store_materials(requirements: list[dict[str, Any]], quantity: int) -> list[dict[str, Any]]:
    if not requirements:
        return []
    try:
        with get_mysql_connection("store") as conn:
            with conn.cursor() as cursor:
                columns = table_columns(cursor, "store", "materials")
                order_columns = [column for column in ("物料编号", "编号", "material_id", "id", "物料ID") if column in columns]
                order_by = ", ".join(safe_column_name(column) for column in order_columns) or "1"
                cursor.execute(
                    f"""
                    SELECT *
                    FROM `materials`
                    ORDER BY {order_by}
                    """
                )
                store_rows = [normalize_props(row) for row in cursor.fetchall()]
    except Exception as exc:
        print(f"store material allocation skipped: {exc}", file=sys.stderr, flush=True)
        return []

    allocated: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for requirement in requirements:
        required_count = max(1, int(requirement.get("quantity") or 1) * max(1, quantity))
        matched_rows = [
            row for row in store_rows
            if str(row.get("物料编号") or "") not in used_ids and store_row_matches_material(row, requirement)
        ]
        if not matched_rows:
            matched_rows = [
                row for row in store_rows
                if str(row.get("物料编号") or "") not in used_ids and store_row_matches_material(row, requirement, allow_type_fallback=True)
            ]
        for row in matched_rows[:required_count]:
            material_id = str(row.get("物料编号") or "")
            if material_id:
                used_ids.add(material_id)
            allocated.append(store_material_to_payload(row, {**requirement, "required_total_quantity": required_count}))
    return allocated


def normalize_match_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def first_present_normalized(data: dict[str, Any], keys: Sequence[str]) -> Any:
    normalized = {normalize_match_text(key): key for key in data.keys()}
    for key in keys:
        actual = normalized.get(normalize_match_text(key))
        if actual is None:
            continue
        value = data.get(actual)
        if value not in (None, ""):
            return value
    return None


def read_workstations() -> list[dict[str, Any]]:
    try:
        with get_mysql_connection("device") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM `devices` WHERE `设备编号` <> 'DEV005'")
                return [normalize_props(row) for row in cursor.fetchall()]
    except Exception:
        return []


def route_process_id(step: dict[str, Any]) -> str:
    process = step.get("process") if isinstance(step.get("process"), dict) else {}
    return str(
        step.get("process_id")
        or step.get("processId")
        or process.get("process_id")
        or process.get("processId")
        or process.get("code")
        or step.get("name")
        or ""
    ).strip()


def order_route_steps_by_to(route_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_process = {route_process_id(step): step for step in route_steps if route_process_id(step)}
    if not by_process:
        return route_steps
    next_map = {
        process_id: str(step.get("_next_process_id") or "").strip()
        for process_id, step in by_process.items()
        if str(step.get("_next_process_id") or "").strip() in by_process
    }
    if not next_map:
        return route_steps
    next_values = set(next_map.values())
    starts = [process_id for process_id in by_process if process_id not in next_values]
    if len(starts) != 1:
        return route_steps
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = starts[0]
    while current and current not in seen and current in by_process:
        seen.add(current)
        ordered.append(by_process[current])
        current = next_map.get(current, "")
    if len(ordered) != len(by_process):
        return route_steps
    return ordered


def find_product(session, product_id: str, product_name: str) -> dict[str, Any] | None:
    result = session.run(
        """
        MATCH (p)
        WHERE
          any(label IN labels(p) WHERE toLower(label) = 'product')
          AND (
            ($product_id <> '' AND toString(p.product_id) = $product_id)
            OR ($product_id <> '' AND toString(p.productId) = $product_id)
            OR ($product_name <> '' AND toLower(toString(p.name)) CONTAINS toLower($product_name))
          )
        RETURN elementId(p) AS node_id, properties(p) AS props
        LIMIT 1
        """,
        product_id=product_id,
        product_name=product_name,
    )
    record = result.single()
    if not record:
        return None
    props = normalize_props(record["props"])
    props["_node_id"] = record["node_id"]
    return props


def find_product_parts(session, product_node_id: str) -> list[dict[str, Any]]:
    result = session.run(
        """
        MATCH (p)-[*1..3]->(part)
        WHERE elementId(p) = $product_node_id
          AND any(label IN labels(part) WHERE toLower(label) = 'part')
        RETURN labels(part) AS labels, properties(part) AS props
        ORDER BY coalesce(part.order, part.partId, part.name, part.type, '')
        """,
        product_node_id=product_node_id,
    )
    return [
        {
            "labels": clean_value(record["labels"]),
            "properties": normalize_props(record["props"]),
        }
        for record in result
    ]


def find_route_steps(session, product_node_id: str) -> list[dict[str, Any]]:
    process_instance_route = session.run(
        """
        MATCH (p)-[rel]->(step)
        WHERE elementId(p) = $product_node_id
          AND toLower(type(rel)) = 'has_step'
          AND any(label IN labels(step) WHERE toLower(label) IN ['process_instance', 'process'])
        OPTIONAL MATCH (step)-[step_device_rel]-(step_device)
        WHERE any(label IN labels(step_device) WHERE toLower(label) = 'device')
          AND toLower(type(step_device_rel)) = 'can_run_on'
        OPTIONAL MATCH (step)-[use_rel]->(used)
        WHERE toLower(type(use_rel)) = 'uses'
        OPTIONAL MATCH (step)-[produce_rel]->(produced)
        WHERE toLower(type(produce_rel)) = 'produces'
        OPTIONAL MATCH (step)-[next_rel]->(next_step)<-[:has_step]-(p)
        WHERE toLower(type(next_rel)) = 'to'
        RETURN
          properties(step) AS step_props,
          properties(step) AS process_props,
          properties(step_device) AS device_props,
          properties(next_step) AS next_props,
          collect(DISTINCT {node: properties(used), rel: properties(use_rel)}) AS uses,
          collect(DISTINCT {node: properties(produced), rel: properties(produce_rel)}) AS produces,
          coalesce(rel.order, rel.sequence, step.stepId, step.name, '') AS sort_key
        ORDER BY sort_key
        """,
        product_node_id=product_node_id,
    )
    process_steps = []
    for record in process_instance_route:
        step_props = normalize_props(record["step_props"])
        process_props = normalize_props(record["process_props"] or {})
        device_props = normalize_props(record["device_props"] or {})
        next_props = normalize_props(record["next_props"] or {})
        uses = []
        for item in record["uses"]:
            if not item or not item.get("node"):
                continue
            node_props = normalize_props(item.get("node") or {})
            rel_props = normalize_props(item.get("rel") or {})
            uses.append({**node_props, **{key: value for key, value in rel_props.items() if key not in node_props}})
        produces = []
        for item in record["produces"]:
            if not item or not item.get("node"):
                continue
            node_props = normalize_props(item.get("node") or {})
            rel_props = normalize_props(item.get("rel") or {})
            produces.append({**node_props, **{key: value for key, value in rel_props.items() if key not in node_props}})
        step_props["process"] = process_props
        if device_props:
            step_props["device"] = device_props
        if next_props:
            step_props["_next_process_id"] = (
                next_props.get("process_id")
                or next_props.get("processId")
                or next_props.get("code")
                or next_props.get("name")
            )
        step_props["uses"] = uses
        step_props["produces"] = produces
        process_steps.append(step_props)
    if process_steps:
        return order_route_steps_by_to(process_steps)

    product_route = session.run(
        """
        MATCH (p)-[*1..4]-(s)
        WHERE elementId(p) = $product_node_id
          AND any(label IN labels(s) WHERE toLower(label) = 'assemblystep')
        WITH DISTINCT s, coalesce(s.stepId, s.order, 0) AS sort_key
        RETURN properties(s) AS props, sort_key
        ORDER BY sort_key
        """,
        product_node_id=product_node_id,
    )
    steps = [normalize_props(record["props"]) for record in product_route]
    if steps:
        return steps

    fallback_route = session.run(
        """
        MATCH (s)
        WHERE any(label IN labels(s) WHERE toLower(label) = 'assemblystep')
        RETURN properties(s) AS props
        ORDER BY coalesce(s.stepId, s.order, 0)
        """
    )
    return [normalize_props(record["props"]) for record in fallback_route]


def ensure_live_order_tables(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS `orders` (
            `订单ID` VARCHAR(64) PRIMARY KEY,
            `产品名称` VARCHAR(128) DEFAULT '',
            `订单状态` ENUM('已创建','已计划','已下发','生产中','已完成','失败') NOT NULL DEFAULT '已创建',
            `订单创建时间` DATETIME NOT NULL,
            `更新时间` DATETIME NULL,
            `订单结束时间` DATETIME NULL,
            `备注` VARCHAR(255) DEFAULT ''
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS `work_orders` (
            `工单ID` VARCHAR(64) PRIMARY KEY,
            `工单名称` VARCHAR(128) NOT NULL,
            `所属订单号` VARCHAR(64) NOT NULL,
            `工单类型` VARCHAR(64) DEFAULT '',
            `工序编号` VARCHAR(64) DEFAULT '',
            `前置工单` VARCHAR(64) DEFAULT NULL,
            `后续工单` VARCHAR(64) DEFAULT NULL,
            `分配设备` VARCHAR(64) DEFAULT '',
            `工单状态` ENUM('已创建','受阻','已下发','已接收','执行中','已完成','失败') NOT NULL DEFAULT '已创建',
            `创建时间` DATETIME NOT NULL,
            `更新时间` DATETIME NULL,
            `开始时间` DATETIME NULL,
            `结束时间` DATETIME NULL,
            `description` TEXT,
            INDEX idx_work_orders_order (`所属订单号`),
            INDEX idx_work_orders_status (`工单状态`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    ensure_order_status_schema(cursor)


def ensure_live_order_columns(cursor: Any) -> None:
    order_columns = table_columns(cursor, "order", "orders")
    if "生产数量" in order_columns:
        cursor.execute("ALTER TABLE `orders` DROP COLUMN `生产数量`")
        order_columns.remove("生产数量")
    order_additions = {
        "产品名称": "`产品名称` VARCHAR(128) DEFAULT ''",
        "订单状态": "`订单状态` ENUM('已创建','已计划','已下发','生产中','已完成','失败') NOT NULL DEFAULT '已创建'",
        "订单创建时间": "`订单创建时间` DATETIME NULL",
        "更新时间": "`更新时间` DATETIME NULL",
        "订单结束时间": "`订单结束时间` DATETIME NULL",
        "备注": "`备注` VARCHAR(255) DEFAULT ''",
    }
    if not first_existing_column(order_columns, ("订单编号", "订单ID", "order_id", "orderId", "id")):
        cursor.execute("ALTER TABLE `orders` ADD COLUMN `订单ID` VARCHAR(64) PRIMARY KEY FIRST")
        order_columns.add("订单ID")
    for column, definition in order_additions.items():
        if column not in order_columns:
            cursor.execute(f"ALTER TABLE `orders` ADD COLUMN {definition}")

    work_order_columns = table_columns(cursor, "order", "work_orders")
    if "工序数量" in work_order_columns:
        cursor.execute("ALTER TABLE `work_orders` DROP COLUMN `工序数量`")
        work_order_columns.remove("工序数量")
    if "已完成工序数量" in work_order_columns:
        cursor.execute("ALTER TABLE `work_orders` DROP COLUMN `已完成工序数量`")
        work_order_columns.remove("已完成工序数量")
    if "分配工站" in work_order_columns and "分配设备" not in work_order_columns:
        cursor.execute("ALTER TABLE `work_orders` CHANGE COLUMN `分配工站` `分配设备` VARCHAR(64) DEFAULT ''")
        work_order_columns.remove("分配工站")
        work_order_columns.add("分配设备")
    elif "分配工站" in work_order_columns and "分配设备" in work_order_columns:
        cursor.execute("UPDATE `work_orders` SET `分配设备` = COALESCE(NULLIF(`分配设备`, ''), `分配工站`) WHERE COALESCE(`分配设备`, '') = ''")
        cursor.execute("ALTER TABLE `work_orders` DROP COLUMN `分配工站`")
        work_order_columns.remove("分配工站")
    work_order_additions = {
        "工单ID": "`工单ID` VARCHAR(64) PRIMARY KEY",
        "工单名称": "`工单名称` VARCHAR(128) NOT NULL",
        "所属订单号": "`所属订单号` VARCHAR(64) NOT NULL",
        "工单类型": "`工单类型` VARCHAR(64) DEFAULT ''",
        "工序编号": "`工序编号` VARCHAR(64) DEFAULT ''",
        "前置工单": "`前置工单` VARCHAR(64) DEFAULT NULL",
        "后续工单": "`后续工单` VARCHAR(64) DEFAULT NULL",
        "分配设备": "`分配设备` VARCHAR(64) DEFAULT ''",
        "起始工站": "`起始工站` VARCHAR(128) DEFAULT ''",
        "目标工站": "`目标工站` VARCHAR(128) DEFAULT ''",
        "工单状态": "`工单状态` ENUM('已创建','受阻','已下发','已接收','执行中','已完成','失败') NOT NULL DEFAULT '已创建'",
        "创建时间": "`创建时间` DATETIME NULL",
        "更新时间": "`更新时间` DATETIME NULL",
        "开始时间": "`开始时间` DATETIME NULL",
        "结束时间": "`结束时间` DATETIME NULL",
        "description": "`description` TEXT",
    }
    for column, definition in work_order_additions.items():
        if column not in work_order_columns:
            cursor.execute(f"ALTER TABLE `work_orders` ADD COLUMN {definition}")
    try:
        cursor.execute("ALTER TABLE `work_orders` MODIFY `description` TEXT")
    except Exception as exc:
        print(f"work order description schema sync skipped: {exc}", file=sys.stderr, flush=True)
    ensure_order_status_schema(cursor)


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    return datetime.now()


def extract_order_sequence(order_id: str, prefix: str) -> int:
    match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", str(order_id or "").strip())
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def fetch_max_order_sequence(cursor: Any, table_name: str, order_id_col: str, prefix: str) -> int:
    safe_table = safe_column_name(table_name)
    safe_col = safe_column_name(order_id_col)
    cursor.execute(
        f"SELECT DISTINCT {safe_col} AS order_id FROM {safe_table} WHERE {safe_col} LIKE %s",
        (f"{prefix}%",),
    )
    return max((extract_order_sequence(str(row.get("order_id") or ""), prefix) for row in cursor.fetchall()), default=0)


def generate_order_id_for_today() -> str:
    prefix = f"PO-{datetime.now().strftime('%Y%m%d')}-"
    max_sequence = 0
    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_live_order_tables(cursor)
            ensure_live_order_columns(cursor)
            max_sequence = max(max_sequence, fetch_max_order_sequence(cursor, "orders", order_id_column(cursor), prefix))
        conn.commit()
    try:
        with get_mysql_connection("data") as conn:
            with conn.cursor() as cursor:
                columns = table_columns(cursor, "data", "order_work_order_history")
                if "order_id" in columns:
                    max_sequence = max(max_sequence, fetch_max_order_sequence(cursor, "order_work_order_history", "order_id", prefix))
    except Exception as exc:
        print(f"history order id scan skipped: {exc}", file=sys.stderr, flush=True)
    return f"{prefix}{max_sequence + 1:0{ORDER_ID_SEQUENCE_WIDTH}d}"


def parse_work_order_draft_argument(arguments: dict[str, Any]) -> dict[str, Any] | None:
    raw = (
        arguments.get("work_order_draft")
        or arguments.get("workOrderDraft")
        or arguments.get("draft")
        or arguments.get("agent_draft")
        or arguments.get("agentDraft")
    )
    if raw in (None, "") and ("items" in arguments or "work_orders" in arguments or "order" in arguments):
        raw = arguments
    if raw in (None, ""):
        return None
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict):
        raise ValueError("work_order_draft 必须是 JSON 对象")
    return parsed


def build_split_context(
    *,
    order_id: str,
    product: dict[str, Any],
    parts: list[dict[str, Any]],
    route_steps: list[dict[str, Any]],
    workstations: list[dict[str, Any]],
    arguments: dict[str, Any],
    quantity: int,
    pallet_id: str,
    agv_id: str,
) -> dict[str, Any]:
    required_materials = dedupe_materials(
        collect_argument_materials(arguments)
        or collect_part_materials(parts)
        or collect_route_input_materials(route_steps)
    )
    allocated_materials = allocate_store_materials(required_materials, quantity)
    return {
        "order_id": order_id,
        "product": product,
        "parts": parts,
        "route_steps": route_steps,
        "workstations": workstations,
        "required_materials": required_materials,
        "allocated_materials": allocated_materials,
        "outbound_materials": allocated_materials or required_materials,
        "pallet_id": pallet_id,
        "agv_id": agv_id,
        "quantity": quantity,
        "include_transport": arguments.get("include_transport", arguments.get("includeTransport", True)),
    }


def persist_production_order(arguments: dict[str, Any], split_result: dict[str, Any]) -> dict[str, Any]:
    order_id = str(split_result.get("order_id") or arguments.get("order_id") or arguments.get("orderId") or "").strip()
    if not order_id:
        raise ValueError("order_id is required")
    product = split_result.get("product") or {}
    product_name = str(
        arguments.get("product_name")
        or arguments.get("productName")
        or product.get("name")
        or product.get("productName")
        or product.get("product_id")
        or product.get("productId")
        or ""
    )
    quantity = int(split_result.get("quantity") or arguments.get("quantity") or 1)
    now = datetime.now()
    work_orders = list(split_result.get("work_orders") or [])

    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_live_order_tables(cursor)
            ensure_live_order_columns(cursor)
            order_id_col = safe_column_name(order_id_column(cursor))
            cursor.execute(
                f"""
                INSERT INTO `orders` (
                    {order_id_col}, `产品名称`, `订单状态`, `订单创建时间`, `更新时间`, `备注`
                ) VALUES (%s, %s, '已创建', %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `产品名称` = VALUES(`产品名称`),
                    `更新时间` = VALUES(`更新时间`)
                """,
                (
                    order_id,
                    product_name,
                    now,
                    now,
                    str(arguments.get("remark") or arguments.get("备注") or ""),
                ),
            )
            cursor.execute("SELECT COUNT(*) AS total FROM `work_orders` WHERE `所属订单号` = %s", (order_id,))
            existing_work_orders = int((cursor.fetchone() or {}).get("total") or 0)
            inserted_work_orders = 0
            if existing_work_orders == 0:
                for work_order in work_orders:
                    created_at = parse_datetime(work_order.get("created_at"))
                    cursor.execute(
                        """
                        INSERT INTO `work_orders` (
                            `工单ID`, `工单名称`, `所属订单号`, `工单类型`,
                            `工序编号`, `前置工单`, `后续工单`, `分配设备`, `起始工站`, `目标工站`, `工单状态`, `创建时间`,
                            `更新时间`, `description`
                        ) VALUES (
                            %(work_order_id)s, %(work_order_name)s, %(order_id)s, %(work_order_type)s,
                            %(process_id)s, %(predecessor)s, %(successor)s,
                            %(assigned_device)s, %(source_station)s, %(target_station)s, '已创建', %(created_at)s, %(updated_at)s, %(description)s
                        )
                        """,
                        {
                            "work_order_id": str(work_order.get("work_order_id") or work_order.get("工单ID") or ""),
                            "work_order_name": str(work_order.get("title") or work_order.get("工单名称") or work_order.get("work_order_id") or ""),
                            "order_id": order_id,
                            "work_order_type": str(work_order.get("stage") or work_order.get("task_type") or work_order.get("工单类型") or ""),
                            "process_id": str(work_order.get("process_id") or work_order.get("工序编号") or ""),
                            "predecessor": work_order.get("predecessor_work_order_id") or work_order.get("前置工单"),
                            "successor": work_order.get("successor_work_order_id") or work_order.get("后续工单"),
                            "assigned_device": str(
                                (work_order.get("assigned_device") or {}).get("device_id")
                                or (work_order.get("assigned_device") or {}).get("workstation_id")
                                or work_order.get("分配设备")
                                or work_order.get("分配工站")
                                or ""
                            ),
                            "source_station": str(
                                work_order.get("source_station")
                                or work_order.get("起始工站")
                                or (work_order.get("assigned_device") or {}).get("device_id")
                                or (work_order.get("assigned_device") or {}).get("workstation_id")
                                or work_order.get("分配设备")
                                or work_order.get("分配工站")
                                or ""
                            ),
                            "target_station": str(
                                work_order.get("target_station")
                                or work_order.get("目标工站")
                                or (work_order.get("assigned_device") or {}).get("device_id")
                                or (work_order.get("assigned_device") or {}).get("workstation_id")
                                or work_order.get("分配设备")
                                or work_order.get("分配工站")
                                or ""
                            ),
                            "created_at": created_at,
                            "updated_at": now,
                            "description": str(work_order.get("description") or work_order.get("content") or ""),
                        },
                    )
                    inserted_work_orders += 1
            conn.commit()

    order_status_update = mark_order_planned(order_id)
    notify_digital_twin_event(
        "production_order_created",
        {
            "order_id": order_id,
            "product_name": product_name,
            "quantity": quantity,
            "work_order_count": len(work_orders),
            "inserted_work_order_count": inserted_work_orders,
        },
    )
    return {
        "order_id": order_id,
        "order_created_or_updated": True,
        "existing_work_order_count": existing_work_orders,
        "inserted_work_order_count": inserted_work_orders,
        "work_order_count": len(work_orders),
        "order_status_update": order_status_update,
    }


def split_order(arguments: dict[str, Any]) -> dict[str, Any]:
    agent_draft = parse_work_order_draft_argument(arguments)
    draft_order = agent_draft.get("order") if isinstance(agent_draft, dict) and isinstance(agent_draft.get("order"), dict) else {}
    order_id = str(
        arguments.get("order_id")
        or arguments.get("orderId")
        or (agent_draft or {}).get("order_id")
        or draft_order.get("order_id")
        or ""
    ).strip() or generate_order_id_for_today()
    product_id = str(
        arguments.get("product_id")
        or arguments.get("productId")
        or (agent_draft or {}).get("product_id")
        or draft_order.get("product_id")
        or draft_order.get("productId")
        or ""
    ).strip()
    product_name = str(
        arguments.get("product_name")
        or arguments.get("productName")
        or (agent_draft or {}).get("product_name")
        or draft_order.get("product_name")
        or draft_order.get("productName")
        or ""
    ).strip()
    quantity = int(arguments.get("quantity") or (agent_draft or {}).get("quantity") or draft_order.get("quantity") or 1)
    pallet_id = str(arguments.get("pallet_id") or arguments.get("palletId") or f"{order_id}-PALLET").strip()
    agv_id = str(arguments.get("agv_id") or arguments.get("agvId") or "DEV005").strip()

    if not product_id and not product_name:
        raise ValueError("必须提供 product_id 或 product_name")
    if quantity <= 0:
        raise ValueError("quantity 必须大于 0")

    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = get_neo4j_driver()
    try:
        with driver.session(database=database) as session:
            product = find_product(session, product_id, product_name)
            if not product:
                return {
                    "success": False,
                    "message": "Neo4j 中未找到对应产品，未生成工单。",
                    "order_id": order_id,
                    "product_id": product_id,
                    "product_name": product_name,
                    "work_orders": [],
                }

            parts = find_product_parts(session, str(product["_node_id"]))
            route_steps = find_route_steps(session, str(product["_node_id"]))

        workstations = read_workstations()
        split_context = build_split_context(
            order_id=order_id,
            product=product,
            parts=parts,
            route_steps=route_steps,
            workstations=workstations,
            arguments=arguments,
            quantity=quantity,
            pallet_id=pallet_id,
            agv_id=agv_id,
        )
        draft = agent_draft or build_rule_based_work_order_draft(split_context)
        try:
            validation_result = validate_and_complete_work_order_draft(draft, split_context)
        except WorkOrderDraftValidationError as exc:
            return {
                "success": False,
                "message": "工单草案未通过校验，未写入 MySQL。",
                "order_id": order_id,
                "product": {key: value for key, value in product.items() if key != "_node_id"},
                "quantity": quantity,
                "validation": {
                    "ok": False,
                    "errors": exc.errors,
                    "warnings": exc.warnings,
                    "source": "work_order_validation",
                },
                "work_orders": [],
            }

        result = {
            **validation_result,
            "success": True,
            "message": "工单草案已通过校验补全并写入 MySQL，尚未投入调度；用户明确下发订单后再调用调度工具。",
            "order_id": order_id,
            "product": {key: value for key, value in product.items() if key != "_node_id"},
            "quantity": quantity,
            "agv_id": agv_id,
            "pallet_id": pallet_id,
            "route_step_count": len(route_steps),
            "workstation_source": "mysql:device.devices",
            "workstation_count": len(workstations),
            "draft_source": "agent" if agent_draft else "rule_based_validation",
        }
        production_persist = persist_production_order(arguments, result)
        return {
            **result,
            "production_persist": production_persist,
            "scheduler_submission": None,
            "scheduler_submission_required": True,
            "order_status_update": production_persist.get("order_status_update"),
        }
    finally:
        driver.close()


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="split_product_order",
            description=(
                "三层生产拆单入口。数据工具层读取 Neo4j 产品/BOM/工艺路线/设备能力和 MySQL 库存/工站/订单；"
                "智能体可传入 work_order_draft 草案 JSON；校验层会补全并校验工单链、设备、物料和前后置关系，"
                "通过后只写入 MySQL order.work_orders，不自动投入后台调度队列。用户明确下发订单后再调用调度提交工具。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "产品订单编号，可选；缺省由后端按 PO-YYYYMMDD-序号 生成，例如 PO-20260421-001。",
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Neo4j product.product_id，可选；product_id 和 product_name 至少提供一个。",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "Neo4j Product.name，可选；product_id 和 product_name 至少提供一个。",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "订单内产品件数。大于 1 时校验层会按 items 拆分；未传 items 时按 quantity 自动生成 ITEM 工单链。",
                        "default": 1,
                    },
                    "pallet_id": {
                        "type": "string",
                        "description": "物料盘编号，可选；默认使用 {order_id}-PALLET。",
                    },
                    "agv_id": {
                        "type": "string",
                        "description": "执行运输任务的 AGV 设备编号，可选；默认 DEV005。",
                    },
                    "materials": {
                        "type": "array",
                        "description": "本次订单选择的出库物料，可选；元素可为物料编号字符串或包含物料编号/物料名称的对象。",
                    },
                    "material_ids": {
                        "type": "array",
                        "description": "本次订单选择的出库物料编号列表，可选。",
                    },
                    "work_order_draft": {
                        "type": "object",
                        "description": (
                            "智能体规划层生成的工单草案 JSON，可选。推荐结构为 order + items，"
                            "每个 item 包含 item_no、item_id、work_orders。每条工单至少提供 sequence、工单类型、工序编号、分配设备、description。"
                            "校验层会按 Neo4j 工序顺序、MySQL 设备和库存上下文补全工单ID、前后置工单、起始/目标工站、AGV转运和物料明细。"
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="submit_order_to_scheduler",
            description=(
                "将已创建并拆分完成的订单投入后台调度队列。只有用户明确要求下发订单、投入调度或开始执行订单时才调用。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "要下发到后台调度器的订单编号，例如 PO-20260421-001。",
                    },
                },
                "required": ["order_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    if name == "split_product_order":
        result = split_order(arguments or {})
    elif name == "submit_order_to_scheduler":
        result = submit_order_to_scheduler(arguments or {})
    else:
        raise ValueError(f"unknown tool: {name}")
    return [
        TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


async def run_stdio() -> None:
    load_env()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    asyncio.run(run_stdio())
