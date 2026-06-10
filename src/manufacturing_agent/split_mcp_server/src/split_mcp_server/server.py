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


ORDER_STATUSES = ("已创建", "已计划", "已下发", "生产中", "已完成", "失败")
WORK_ORDER_STATUSES = ("已创建", "受阻", "已下发", "已接收", "执行中", "已完成", "失败")
ORDER_LEGACY_STATUSES = ("等待中", "已分配", "已取消", "已下单", "异常", "已接收", "执行中")
WORK_ORDER_LEGACY_STATUSES = ("等待中", "已分配", "已取消", "已下单", "异常")
SCHEDULER_QUEUE_TABLE = "scheduler_order_queue"
WORK_ORDER_DELIVERY_LOG_TABLE = "work_order_delivery_log"


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
    cursor.execute(
        """
        SELECT
            `工单ID` AS work_order_id,
            `工单名称` AS work_order_name,
            `所属订单号` AS order_id,
            `工单状态` AS status,
            `工序编号` AS process_id,
            `前置工单` AS predecessor_work_orders,
            `分配工站` AS device_id,
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
        ORDER BY submitted_at, updated_at
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
        "properties": props,
    }


def material_display(material: dict[str, Any]) -> str:
    material_id = material.get("material_id")
    material_name = material.get("material_name")
    if material_id and material_name and str(material_id) != str(material_name):
        return f"{material_id}({material_name})"
    return str(material_id or material_name or "")


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
                cursor.execute(
                    """
                    SELECT *
                    FROM `materials`
                    ORDER BY `物料编号`, `物料ID`
                    """
                )
                store_rows = [normalize_props(row) for row in cursor.fetchall()]
    except Exception as exc:
        print(f"store material allocation skipped: {exc}", file=sys.stderr, flush=True)
        return []

    allocated: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    required_count = max(1, quantity)
    for requirement in requirements:
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
            allocated.append(store_material_to_payload(row, requirement))
    return allocated


def product_label_codes(order_id: str, quantity: int) -> list[str]:
    count = max(1, quantity)
    return [f"{order_id}-LABEL-{index:03d}" for index in range(1, count + 1)]


def first_present(data: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def compact_identity(value: Any) -> str:
    return str(value or "").strip().lower()


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


def get_step_identity(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": first_present(step, ("stepId", "step_id", "process_code", "code", "order", "name")),
        "step_name": first_present(step, ("process_name", "name", "title")),
    }


def process_code_for_step(step: dict[str, Any], process: dict[str, Any], fallback: Any) -> str:
    explicit_code = step.get("process_code") or step.get("processCode") or process.get("code")
    if explicit_code:
        return str(explicit_code)
    process_name = str(step.get("process_name") or process.get("name") or step.get("name") or "").strip()
    if process_name == "堆积" or "堆积工序" in process_name:
        return "PROC-001"
    return str(fallback)


def extract_assigned_device(step: dict[str, Any]) -> dict[str, Any] | None:
    nested_sources = [
        step,
        step.get("device") if isinstance(step.get("device"), dict) else {},
        step.get("assigned_device") if isinstance(step.get("assigned_device"), dict) else {},
        step.get("equipment") if isinstance(step.get("equipment"), dict) else {},
    ]
    device_id_keys = (
        "assigned_device_id",
        "assignedDeviceId",
        "device_id",
        "deviceId",
        "device_code",
        "deviceCode",
        "equipment_id",
        "equipmentId",
        "equipment_code",
        "equipmentCode",
    )
    device_name_keys = (
        "assigned_device_name",
        "assignedDeviceName",
        "device_name",
        "deviceName",
        "equipment_name",
        "equipmentName",
        "station_name",
        "stationName",
        "name",
    )
    location_keys = (
        "location",
        "station",
        "position",
        "area",
        "device_location",
        "deviceLocation",
    )
    device_type_keys = (
        "type",
        "device_type",
        "deviceType",
        "category",
    )

    device_id = None
    device_name = None
    location = None
    device_type = None
    for source in nested_sources:
        device_id = device_id or first_present(source, device_id_keys)
        device_name = device_name or first_present(source, device_name_keys)
        location = location or first_present(source, location_keys)
        device_type = device_type or first_present(source, device_type_keys)

    if not device_id and not device_name:
        return None

    return {
        "device_id": clean_value(device_id),
        "device_name": clean_value(device_name),
        "location": clean_value(location),
        "device_type": clean_value(device_type),
        "source": "neo4j:craft.can_execute",
    }


WORKSTATION_ID_KEYS = (
    "工站编号",
    "工作站编号",
    "设备编号",
    "设备ID",
    "workstation_id",
    "workstationId",
    "workstation_code",
    "workstationCode",
    "station_id",
    "stationId",
    "station_code",
    "stationCode",
    "device_id",
    "deviceId",
    "device_code",
    "deviceCode",
    "code",
    "id",
)
WORKSTATION_NAME_KEYS = (
    "工站名称",
    "工作站名称",
    "设备名称",
    "workstation_name",
    "workstationName",
    "station_name",
    "stationName",
    "device_name",
    "deviceName",
    "name",
)
WORKSTATION_STATUS_KEYS = (
    "状态",
    "工站状态",
    "工作站状态",
    "设备状态",
    "启动状态",
    "运行状态",
    "status",
    "state",
    "work_status",
    "workStatus",
)
WORKSTATION_CAPABILITY_KEYS = (
    "工序",
    "工序名称",
    "工序编号",
    "工艺",
    "工艺类型",
    "能力",
    "可执行工序",
    "process",
    "process_name",
    "processName",
    "process_code",
    "processCode",
    "process_type",
    "processType",
    "craft",
    "craft_name",
    "craftName",
    "capability",
    "capabilities",
)


def read_workstations() -> list[dict[str, Any]]:
    try:
        with get_mysql_connection("device") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM `devices` WHERE `设备编号` <> 'DEV005'")
                return [normalize_props(row) for row in cursor.fetchall()]
    except Exception:
        return []


def workstation_to_device(workstation: dict[str, Any]) -> dict[str, Any]:
    workstation_id = first_present_normalized(workstation, WORKSTATION_ID_KEYS)
    workstation_name = first_present_normalized(workstation, WORKSTATION_NAME_KEYS)
    status = first_present_normalized(workstation, WORKSTATION_STATUS_KEYS)
    return {
        "device_id": clean_value(workstation_id),
        "device_name": clean_value(workstation_name or workstation_id),
        "location": clean_value(workstation_name),
        "workstation_id": clean_value(workstation_id),
        "workstation_name": clean_value(workstation_name),
        "status": clean_value(status),
        "source": "mysql:device.devices",
    }


def route_step_process_values(step: dict[str, Any]) -> list[str]:
    process = step.get("process") if isinstance(step.get("process"), dict) else {}
    keys = (
        "process_name",
        "processName",
        "process_code",
        "processCode",
        "process_type",
        "processType",
        "craft",
        "craft_name",
        "craftName",
        "name",
        "code",
        "type",
    )
    values = []
    for source in (step, process):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                values.append(str(value))
    return values


def workstation_matches_step(workstation: dict[str, Any], step: dict[str, Any]) -> bool:
    process_values = {normalize_match_text(value) for value in route_step_process_values(step)}
    process_values.discard("")
    if not process_values:
        return False

    capability_values = []
    for key in WORKSTATION_CAPABILITY_KEYS:
        value = first_present_normalized(workstation, (key,))
        if isinstance(value, list):
            capability_values.extend(str(item) for item in value)
        elif value not in (None, ""):
            capability_values.extend(str(value).replace("，", ",").replace("、", ",").split(","))

    normalized_capabilities = {normalize_match_text(value) for value in capability_values}
    normalized_capabilities.discard("")
    return any(
        process in capability or capability in process
        for process in process_values
        for capability in normalized_capabilities
    )


def device_name_match_key(value: Any) -> str:
    text = normalize_match_text(value)
    for token in ("自动化", "机器人", "加工", "工作站", "工站", "设备"):
        text = text.replace(normalize_match_text(token), "")
    return text


def workstation_matches_assigned_device(workstation: dict[str, Any], assigned_device: dict[str, Any]) -> bool:
    workstation_id = normalize_match_text(first_present_normalized(workstation, WORKSTATION_ID_KEYS))
    workstation_name = first_present_normalized(workstation, WORKSTATION_NAME_KEYS)
    assigned_id = normalize_match_text(assigned_device.get("device_id") or assigned_device.get("workstation_id"))
    assigned_name = assigned_device.get("device_name") or assigned_device.get("workstation_name")
    if assigned_id and workstation_id and assigned_id == workstation_id:
        return True
    workstation_key = device_name_match_key(workstation_name)
    assigned_key = device_name_match_key(assigned_name)
    if workstation_key and assigned_key and (workstation_key in assigned_key or assigned_key in workstation_key):
        return True
    assigned_type = normalize_match_text(assigned_device.get("device_type"))
    workstation_text = normalize_match_text(f"{workstation_name} {workstation.get('设备名称')} {workstation.get('设备编号')}")
    if assigned_type == "processing" and ("协作" in workstation_text or "加工" in workstation_text):
        return True
    if assigned_type == "storage" and ("仓库" in workstation_text or "立体" in workstation_text):
        return True
    return False


def resolve_assigned_device(
    assigned_device: dict[str, Any] | None,
    workstations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not assigned_device:
        return None
    for workstation in workstations:
        if workstation_matches_assigned_device(workstation, assigned_device):
            device = workstation_to_device(workstation)
            device["source"] = assigned_device.get("source") or device.get("source")
            return device
    return assigned_device


def assign_workstation(step: dict[str, Any], workstations: list[dict[str, Any]]) -> dict[str, Any] | None:
    for workstation in workstations:
        if workstation_matches_step(workstation, step):
            return workstation_to_device(workstation)
    assigned_device = resolve_assigned_device(extract_assigned_device(step), workstations)
    if assigned_device:
        return assigned_device
    if len(workstations) == 1:
        return workstation_to_device(workstations[0])
    return None


def device_changed(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> bool:
    if not previous or not current:
        return False
    previous_key = compact_identity(previous.get("device_id") or previous.get("device_name"))
    current_key = compact_identity(current.get("device_id") or current.get("device_name"))
    return bool(previous_key and current_key and previous_key != current_key)


def process_group_key(step: dict[str, Any]) -> str:
    process = step.get("process") if isinstance(step.get("process"), dict) else {}
    key_value = (
        step.get("process_code")
        or step.get("processCode")
        or process.get("code")
        or step.get("process_name")
        or step.get("processName")
        or process.get("name")
        or step.get("name")
        or step.get("stepId")
        or step.get("order")
    )
    return normalize_match_text(key_value)


def group_route_steps_by_process(route_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for step in route_steps:
        key = process_group_key(step)
        if groups and groups[-1]["process_key"] == key:
            groups[-1]["steps"].append(step)
            continue
        groups.append({"process_key": key, "steps": [step]})
    return groups


def find_product(session, product_id: str, product_name: str) -> dict[str, Any] | None:
    result = session.run(
        """
        MATCH (p)
        WHERE
          any(label IN labels(p) WHERE toLower(label) = 'product')
          AND (
            ($product_id <> '' AND toString(p.productId) = $product_id)
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
        OPTIONAL MATCH (proc)
        WHERE any(label IN labels(proc) WHERE toLower(label) = 'process')
          AND toString(proc.name) = toString(step.process_name)
        OPTIONAL MATCH (craft)-[can_execute]-(device)
        WHERE any(label IN labels(craft) WHERE toLower(label) = 'craft')
          AND toLower(type(can_execute)) = 'can_execute'
          AND any(label IN labels(device) WHERE toLower(label) = 'device')
          AND (
            toString(craft.name) = toString(step.process_name)
            OR toString(craft.name) = toString(step.name)
            OR toString(craft.name) = toString(proc.name)
            OR toString(craft.name) = toString(proc.process_name)
          )
        OPTIONAL MATCH (step)-[use_rel]->(used)
        WHERE toLower(type(use_rel)) = 'uses'
        OPTIONAL MATCH (step)-[produce_rel]->(produced)
        WHERE toLower(type(produce_rel)) = 'produces'
        RETURN
          properties(step) AS step_props,
          CASE WHEN proc IS NULL THEN properties(step) ELSE properties(proc) END AS process_props,
          properties(device) AS device_props,
          collect(DISTINCT properties(used)) AS uses,
          collect(DISTINCT properties(produced)) AS produces,
          coalesce(step.order, step.stepId, step.name, step.process_name, '') AS sort_key
        ORDER BY sort_key
        """,
        product_node_id=product_node_id,
    )
    process_steps = []
    for record in process_instance_route:
        step_props = normalize_props(record["step_props"])
        process_props = normalize_props(record["process_props"] or {})
        device_props = normalize_props(record["device_props"] or {})
        uses = [normalize_props(item) for item in record["uses"] if item]
        produces = [normalize_props(item) for item in record["produces"] if item]
        step_props["process"] = process_props
        if device_props:
            step_props["device"] = device_props
        step_props["uses"] = uses
        step_props["produces"] = produces
        process_steps.append(step_props)
    if process_steps:
        return process_steps

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


def make_work_order(
    *,
    order_id: str,
    sequence: int,
    stage: str,
    title: str,
    content: str,
    product: dict[str, Any],
    quantity: int,
    route_step: dict[str, Any] | None = None,
    assigned_device: dict[str, Any] | None = None,
    previous_step: dict[str, Any] | None = None,
    next_step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    work_order = {
        "work_order_id": f"{order_id}-WO-{sequence:03d}",
        "source_order_id": order_id,
        "sequence": sequence,
        "stage": stage,
        "title": title,
        "content": content,
        "description": content,
        "product_id": product.get("productId"),
        "product_name": product.get("name"),
        "quantity": quantity,
        "status": "已创建",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if route_step:
        work_order["route_step"] = route_step
    if assigned_device:
        work_order["assigned_device"] = assigned_device
    if previous_step:
        work_order["previous_step"] = previous_step
    if next_step:
        work_order["next_step"] = next_step
    return work_order


def warehouse_device() -> dict[str, Any]:
    return {
        "device_id": "DEV001",
        "device_name": "立体库",
        "location": "立体库",
        "workstation_id": "DEV001",
        "workstation_name": "立体库",
        "source": "default:warehouse",
    }


def quality_device() -> dict[str, Any]:
    return {
        "device_id": "DEV003",
        "device_name": "质检工作站",
        "location": "质检工作站",
        "workstation_id": "DEV003",
        "workstation_name": "质检工作站",
        "source": "default:quality",
    }


def labeling_device() -> dict[str, Any]:
    return {
        "device_id": "DEV004",
        "device_name": "贴标工作站",
        "location": "贴标工作站",
        "workstation_id": "DEV004",
        "workstation_name": "贴标工作站",
        "source": "default:labeling",
    }


def make_agv_transport_order(
    *,
    order_id: str,
    sequence: int,
    from_work_order: dict[str, Any],
    to_work_order_id: str,
    to_step: dict[str, Any],
    from_device: dict[str, Any],
    to_device: dict[str, Any],
    product: dict[str, Any],
    quantity: int,
    pallet_id: str,
    agv_id: str,
) -> dict[str, Any]:
    from_name = from_device.get("device_name") or from_device.get("device_id") or "上一执行设备"
    to_name = to_device.get("device_name") or to_device.get("device_id") or "下一执行设备"
    task_id = f"{order_id}-AGV-{sequence:03d}"
    assigned_agv = {
        "device_id": agv_id,
        "device_name": agv_id,
        "location": "AGV",
        "workstation_id": agv_id,
        "workstation_name": agv_id,
        "source": "scheduler:agv",
    }
    description = (
        f"前置工单 {from_work_order.get('work_order_id')} 完成后，执行设备由 {from_name} "
        f"切换至 {to_name}，调度 {agv_id} 将物料盘 {pallet_id} 运输至下一工位。"
    )
    transport_task = {
        "transport_task_id": task_id,
        "agv_id": agv_id,
        "pallet_id": pallet_id,
        "source_work_order_id": from_work_order.get("work_order_id"),
        "target_work_order_id": to_work_order_id,
        "source_device": from_device,
        "target_device": to_device,
        "target_step": to_step,
        "trigger_condition": "previous_work_order_completed_and_device_changed",
        "status": "已创建",
    }
    description = (
        f"{description}\n"
        f"TRANSPORT_TASK_JSON:{json.dumps(transport_task, ensure_ascii=False, separators=(',', ':'))}"
    )
    return {
        "work_order_id": task_id,
        "source_order_id": order_id,
        "sequence": sequence,
        "stage": "AGV运输",
        "title": f"AGV运输: {from_name} -> {to_name}",
        "content": description,
        "description": description,
        "product_id": product.get("productId"),
        "product_name": product.get("name"),
        "quantity": quantity,
        "status": "已创建",
        "task_type": "agv_transport",
        "process_id": "AGV-TRANSPORT",
        "process_name": "AGV运输",
        "assigned_device": assigned_agv,
        "source_station": from_device.get("device_id") or from_device.get("workstation_id") or from_name,
        "source_station_name": from_name,
        "target_station": to_device.get("device_id") or to_device.get("workstation_id") or to_name,
        "target_station_name": to_name,
        "predecessor_work_order_id": from_work_order.get("work_order_id"),
        "successor_work_order_id": to_work_order_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "transport_task": transport_task,
    }


def normalize_work_order_chain(work_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, work_order in enumerate(work_orders):
        previous_id = work_orders[index - 1]["work_order_id"] if index > 0 else None
        next_id = work_orders[index + 1]["work_order_id"] if index + 1 < len(work_orders) else None
        work_order.setdefault("predecessor_work_order_id", previous_id)
        work_order.setdefault("successor_work_order_id", next_id)
        assigned_device = work_order.get("assigned_device") if isinstance(work_order.get("assigned_device"), dict) else {}
        work_order["工单ID"] = work_order.get("work_order_id")
        work_order["工单名称"] = work_order.get("title") or work_order.get("work_order_id")
        work_order["所属订单号"] = work_order.get("source_order_id")
        work_order["工单类型"] = work_order.get("stage") or work_order.get("task_type") or ""
        work_order["工序数量"] = work_order.get("grouped_step_count") or 1
        work_order["已完成工序数量"] = 0
        work_order["工序编号"] = str(work_order.get("process_id") or work_order.get("task_type") or work_order.get("stage") or "")
        work_order["前置工单"] = work_order.get("predecessor_work_order_id")
        work_order["后续工单"] = work_order.get("successor_work_order_id")
        work_order["分配工站"] = assigned_device.get("device_id") or assigned_device.get("workstation_id") or ""
        work_order["起始工站"] = work_order.get("source_station") or ""
        work_order["目标工站"] = work_order.get("target_station") or ""
        work_order["工单状态"] = work_order.get("status") or "已创建"
    return work_orders


def ensure_live_order_tables(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS `orders` (
            `订单ID` VARCHAR(64) PRIMARY KEY,
            `产品名称` VARCHAR(128) DEFAULT '',
            `生产数量` INT NOT NULL DEFAULT 1,
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
            `工序数量` INT NOT NULL DEFAULT 1,
            `已完成工序数量` INT NOT NULL DEFAULT 0,
            `工序编号` VARCHAR(64) DEFAULT '',
            `前置工单` VARCHAR(64) DEFAULT NULL,
            `后续工单` VARCHAR(64) DEFAULT NULL,
            `分配工站` VARCHAR(64) DEFAULT '',
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
    order_additions = {
        "产品名称": "`产品名称` VARCHAR(128) DEFAULT ''",
        "生产数量": "`生产数量` INT NOT NULL DEFAULT 1",
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
    work_order_additions = {
        "工单ID": "`工单ID` VARCHAR(64) PRIMARY KEY",
        "工单名称": "`工单名称` VARCHAR(128) NOT NULL",
        "所属订单号": "`所属订单号` VARCHAR(64) NOT NULL",
        "工单类型": "`工单类型` VARCHAR(64) DEFAULT ''",
        "工序数量": "`工序数量` INT NOT NULL DEFAULT 1",
        "已完成工序数量": "`已完成工序数量` INT NOT NULL DEFAULT 0",
        "工序编号": "`工序编号` VARCHAR(64) DEFAULT ''",
        "前置工单": "`前置工单` VARCHAR(64) DEFAULT NULL",
        "后续工单": "`后续工单` VARCHAR(64) DEFAULT NULL",
        "分配工站": "`分配工站` VARCHAR(64) DEFAULT ''",
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
                    {order_id_col}, `产品名称`, `生产数量`, `订单状态`, `订单创建时间`, `更新时间`, `备注`
                ) VALUES (%s, %s, %s, '已创建', %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `产品名称` = VALUES(`产品名称`),
                    `生产数量` = VALUES(`生产数量`),
                    `更新时间` = VALUES(`更新时间`)
                """,
                (
                    order_id,
                    product_name,
                    quantity,
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
                            `工单ID`, `工单名称`, `所属订单号`, `工单类型`, `工序数量`, `已完成工序数量`,
                            `工序编号`, `前置工单`, `后续工单`, `分配工站`, `起始工站`, `目标工站`, `工单状态`, `创建时间`,
                            `更新时间`, `description`
                        ) VALUES (
                            %(work_order_id)s, %(work_order_name)s, %(order_id)s, %(work_order_type)s,
                            %(process_quantity)s, 0, %(process_id)s, %(predecessor)s, %(successor)s,
                            %(assigned_device)s, %(source_station)s, %(target_station)s, '已创建', %(created_at)s, %(updated_at)s, %(description)s
                        )
                        """,
                        {
                            "work_order_id": str(work_order.get("work_order_id") or work_order.get("工单ID") or ""),
                            "work_order_name": str(work_order.get("title") or work_order.get("工单名称") or work_order.get("work_order_id") or ""),
                            "order_id": order_id,
                            "work_order_type": str(work_order.get("stage") or work_order.get("task_type") or work_order.get("工单类型") or ""),
                            "process_quantity": int(work_order.get("grouped_step_count") or work_order.get("工序数量") or 1),
                            "process_id": str(work_order.get("process_id") or work_order.get("工序编号") or ""),
                            "predecessor": work_order.get("predecessor_work_order_id") or work_order.get("前置工单"),
                            "successor": work_order.get("successor_work_order_id") or work_order.get("后续工单"),
                            "assigned_device": str(
                                (work_order.get("assigned_device") or {}).get("device_id")
                                or (work_order.get("assigned_device") or {}).get("workstation_id")
                                or work_order.get("分配工站")
                                or ""
                            ),
                            "source_station": str(work_order.get("source_station") or work_order.get("起始工站") or ""),
                            "target_station": str(work_order.get("target_station") or work_order.get("目标工站") or ""),
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
    order_id = str(arguments.get("order_id") or arguments.get("orderId") or "").strip()
    product_id = str(arguments.get("product_id") or arguments.get("productId") or "").strip()
    product_name = str(arguments.get("product_name") or arguments.get("productName") or "").strip()
    quantity = int(arguments.get("quantity") or 1)
    pallet_id = str(arguments.get("pallet_id") or arguments.get("palletId") or f"{order_id}-PALLET").strip()
    agv_id = str(arguments.get("agv_id") or arguments.get("agvId") or "DEV005").strip()

    if not order_id:
        raise ValueError("缺少 order_id")
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
        route_step_groups = group_route_steps_by_process(route_steps)
        required_materials = dedupe_materials(
            collect_argument_materials(arguments)
            or collect_part_materials(parts)
            or collect_route_input_materials(route_steps)
        )
        allocated_materials = allocate_store_materials(required_materials, quantity)
        outbound_materials = allocated_materials or required_materials
        label_codes = product_label_codes(order_id, quantity)
        sequence = 1
        work_orders: list[dict[str, Any]] = []
        material_summary = ", ".join(material_display(item) for item in outbound_materials[:12] if material_display(item))
        if len(outbound_materials) > 12:
            material_summary += f" 等 {len(outbound_materials)} 项"
        outbound_description = f"物料出库：{material_summary or '未查询到BOM部件或选择物料'}"

        outbound_work_order = make_work_order(
            order_id=order_id,
            sequence=sequence,
            stage="出库",
            title="产品物料出库",
            content=outbound_description,
            product=product,
            quantity=quantity,
            assigned_device=warehouse_device(),
        )
        outbound_work_order["process_id"] = "OUTPUT-001"
        outbound_work_order["material_ids"] = [item["material_id"] for item in outbound_materials if item.get("material_id")]
        outbound_work_order["required_materials"] = required_materials
        outbound_work_order["allocated_materials"] = allocated_materials
        outbound_work_order["materials"] = outbound_materials
        outbound_work_order["description"] = (
            f"{outbound_description}\n"
            f"出库物料编号：{', '.join(outbound_work_order['material_ids']) or '无'}"
        )
        outbound_work_order["content"] = outbound_work_order["description"]
        work_orders.append(outbound_work_order)
        sequence += 1

        last_device_order: dict[str, Any] | None = outbound_work_order
        for index, group in enumerate(route_step_groups):
            grouped_steps = group["steps"]
            step = grouped_steps[0]
            step_id = step.get("stepId") or step.get("order") or sequence - 1
            process = step.get("process") or {}
            uses = [item for grouped_step in grouped_steps for item in (grouped_step.get("uses") or [])]
            produces = [item for grouped_step in grouped_steps for item in (grouped_step.get("produces") or [])]
            process_name = step.get("process_name") or process.get("name") or step.get("name") or f"工序 {step_id}"
            use_names = ", ".join(dict.fromkeys(str(item.get("name") or item) for item in uses)) or "未查询到输入物料"
            produce_names = ", ".join(dict.fromkeys(str(item.get("name") or item) for item in produces)) or "未查询到输出物料"
            instructions = [
                str(
                    grouped_step.get("instruction")
                    or grouped_step.get("description")
                    or (grouped_step.get("process") or {}).get("description")
                    or ""
                ).strip()
                for grouped_step in grouped_steps
            ]
            instruction = "；".join(dict.fromkeys(item for item in instructions if item)) or "按工艺路线执行加工"
            grouped_note = f"本工单合并 {len(grouped_steps)} 个相同工序步骤。" if len(grouped_steps) > 1 else "本工单仅包含一个工序。"
            content = f"{grouped_note}{instruction}。输入物料：{use_names}。输出物料：{produce_names}。"
            assigned_device = assign_workstation(step, workstations)
            previous_step = get_step_identity(route_step_groups[index - 1]["steps"][-1]) if index > 0 else None
            next_step = get_step_identity(route_step_groups[index + 1]["steps"][0]) if index + 1 < len(route_step_groups) else None

            if device_changed(last_device_order.get("assigned_device") if last_device_order else None, assigned_device):
                current_work_order_id = f"{order_id}-WO-{sequence + 1:03d}"
                work_orders.append(
                    make_agv_transport_order(
                        order_id=order_id,
                        sequence=sequence,
                        from_work_order=last_device_order,
                        to_work_order_id=current_work_order_id,
                        to_step=get_step_identity(step),
                        from_device=last_device_order["assigned_device"],
                        to_device=assigned_device,
                        product=product,
                        quantity=quantity,
                        pallet_id=pallet_id,
                        agv_id=agv_id,
                    )
                )
                sequence += 1

            route_step_payload = {
                **step,
                "grouped_step_count": len(grouped_steps),
                "route_steps": grouped_steps,
            }
            work_order = make_work_order(
                order_id=order_id,
                sequence=sequence,
                stage="加工",
                title=f"加工工序 {step_id}: {process_name}",
                content=str(content),
                product=product,
                quantity=quantity,
                route_step=route_step_payload,
                assigned_device=assigned_device,
                previous_step=previous_step,
                next_step=next_step,
            )
            work_order["process_name"] = process_name
            work_order["process_id"] = process_code_for_step(step, process, step_id)
            work_order["grouped_step_count"] = len(grouped_steps)
            work_orders.append(work_order)
            if assigned_device:
                last_device_order = work_order
            sequence += 1

        quality_assigned_device = quality_device()
        if last_device_order and device_changed(last_device_order.get("assigned_device"), quality_assigned_device):
            quality_work_order_id = f"{order_id}-WO-{sequence + 1:03d}"
            work_orders.append(
                make_agv_transport_order(
                    order_id=order_id,
                    sequence=sequence,
                    from_work_order=last_device_order,
                    to_work_order_id=quality_work_order_id,
                    to_step={"step_id": "DETECT-001", "step_name": "产品质量检验"},
                    from_device=last_device_order["assigned_device"],
                    to_device=quality_assigned_device,
                    product=product,
                    quantity=quantity,
                    pallet_id=pallet_id,
                    agv_id=agv_id,
                )
            )
            sequence += 1

        work_orders.append(
            make_work_order(
                order_id=order_id,
                sequence=sequence,
                stage="质检",
                title="产品质量检验",
                content=f"按产品 {product.get('name')} 的工艺要求进行完工质检，确认数量 {quantity} 的产品状态。",
                product=product,
                quantity=quantity,
                assigned_device=quality_assigned_device,
            )
        )
        work_orders[-1]["process_id"] = "DETECT-001"
        work_orders[-1]["process_name"] = "产品质量检验"
        last_device_order = work_orders[-1]
        sequence += 1

        labeling_assigned_device = labeling_device()
        if last_device_order and device_changed(last_device_order.get("assigned_device"), labeling_assigned_device):
            labeling_work_order_id = f"{order_id}-WO-{sequence + 1:03d}"
            work_orders.append(
                make_agv_transport_order(
                    order_id=order_id,
                    sequence=sequence,
                    from_work_order=last_device_order,
                    to_work_order_id=labeling_work_order_id,
                    to_step={"step_id": "LABEL-001", "step_name": "产品贴标"},
                    from_device=last_device_order["assigned_device"],
                    to_device=labeling_assigned_device,
                    product=product,
                    quantity=quantity,
                    pallet_id=pallet_id,
                    agv_id=agv_id,
                )
            )
            sequence += 1

        work_orders.append(
            make_work_order(
                order_id=order_id,
                sequence=sequence,
                stage="贴标",
                title="产品贴标",
                content=f"对质检后的产品 {product.get('name')} 按订单 {order_id} 执行贴标，确认标签内容、数量 {quantity} 与产品状态一致。",
                product=product,
                quantity=quantity,
                assigned_device=labeling_assigned_device,
            )
        )
        work_orders[-1]["process_id"] = "LABEL-001"
        work_orders[-1]["process_name"] = "产品贴标"
        work_orders[-1]["label_codes"] = label_codes
        work_orders[-1]["description"] = (
            f"{work_orders[-1]['description']}\n"
            f"成品标签编号：{', '.join(label_codes)}"
        )
        work_orders[-1]["content"] = work_orders[-1]["description"]
        last_device_order = work_orders[-1]
        sequence += 1

        inbound_assigned_device = warehouse_device()
        if last_device_order and device_changed(last_device_order.get("assigned_device"), inbound_assigned_device):
            inbound_work_order_id = f"{order_id}-WO-{sequence + 1:03d}"
            work_orders.append(
                make_agv_transport_order(
                    order_id=order_id,
                    sequence=sequence,
                    from_work_order=last_device_order,
                    to_work_order_id=inbound_work_order_id,
                    to_step={"step_id": "INPUT-001", "step_name": "成品入库"},
                    from_device=last_device_order["assigned_device"],
                    to_device=inbound_assigned_device,
                    product=product,
                    quantity=quantity,
                    pallet_id=pallet_id,
                    agv_id=agv_id,
                )
            )
            sequence += 1

        work_orders.append(
            make_work_order(
                order_id=order_id,
                sequence=sequence,
                stage="入库",
                title="成品入库",
                content=f"贴标完成后，将产品 {product.get('name')} 按订单 {order_id} 办理成品入库。",
                product=product,
                quantity=quantity,
                assigned_device=inbound_assigned_device,
            )
        )
        work_orders[-1]["process_id"] = "INPUT-001"
        work_orders[-1]["process_name"] = "成品入库"
        work_orders[-1]["label_codes"] = label_codes
        work_orders[-1]["description"] = (
            f"{work_orders[-1]['description']}\n"
            f"成品标签编号：{', '.join(label_codes)}"
        )
        work_orders[-1]["content"] = work_orders[-1]["description"]

        normalize_work_order_chain(work_orders)

        result = {
            "success": True,
            "message": "产品订单已按 出库-加工-质检-贴标-入库 流程创建并提交调度。",
            "order_id": order_id,
            "product": {key: value for key, value in product.items() if key != "_node_id"},
            "quantity": quantity,
            "agv_id": agv_id,
            "pallet_id": pallet_id,
            "route_step_count": len(route_steps),
            "process_work_order_count": len(route_step_groups),
            "workstation_source": "mysql:device.devices",
            "workstation_count": len(workstations),
            "agv_transport_count": sum(1 for item in work_orders if item.get("task_type") == "agv_transport"),
            "work_order_count": len(work_orders),
            "work_orders": work_orders,
        }
        production_persist = persist_production_order(arguments, result)
        scheduler_submission = submit_order_to_scheduler({"order_id": order_id})
        return {
            **result,
            "production_persist": production_persist,
            "scheduler_submission": scheduler_submission,
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
                "固定生产入口。创建或更新订单，读取 Neo4j 产品/BOM/工艺路线，从 MySQL store.materials 分配库存物料，"
                "按出库-加工-质检-贴标-入库生成工单并写入 MySQL order.work_orders，最后提交后台调度队列。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "产品订单编号，例如 PO-20260421-001",
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Neo4j Product.productId，可选；product_id 和 product_name 至少提供一个。",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "Neo4j Product.name，可选；product_id 和 product_name 至少提供一个。",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "订单产品数量，默认 1。",
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
                },
                "required": ["order_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    if name == "split_product_order":
        result = split_order(arguments or {})
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
