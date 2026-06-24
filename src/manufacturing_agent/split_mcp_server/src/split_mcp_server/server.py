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
PLAN_WORK_ORDER_TYPES = ("出库", "加工", "质检", "贴标", "入库", "运输")
PLAN_TYPE_PROCESS_MAP = {
    "出库": "OUTPUT-001",
    "质检": "DETECT-001",
    "贴标": "LABEL-001",
    "入库": "INPUT-001",
    "运输": "AGV-TRANSPORT",
}
PLAN_PROCESS_TYPE_MAP = {process_id: work_order_type for work_order_type, process_id in PLAN_TYPE_PROCESS_MAP.items()}
PLAN_PROCESS_DEVICE_MAP = {
    "OUTPUT-001": "DEV001",
    "PROC-001": "DEV002",
    "DETECT-001": "DEV003",
    "LABEL-001": "DEV004",
    "INPUT-001": "DEV001",
    "AGV-TRANSPORT": "DEV005",
}
PLAN_MATERIAL_EFFECT_MAP = {
    "出库": "move_out",
    "加工": "transform",
    "质检": "inspect",
    "贴标": "label",
    "入库": "store_in",
    "运输": "transfer",
}
PLAN_FIXED_PROCESS_IDS = {"OUTPUT-001", "DETECT-001", "LABEL-001", "INPUT-001"}
PLAN_FIXED_OUTPUT_PROCESS_ID = "OUTPUT-001"
PLAN_FINAL_PRODUCT_PROCESS_IDS = {"DETECT-001", "LABEL-001", "INPUT-001"}


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
        OPTIONAL MATCH (step)-[product_next_rel]->(product_next_step)<-[:has_step]-(p)
        WHERE toLower(type(product_next_rel)) = 'to'
          AND product_next_rel.product_id = coalesce(p.product_id, p.productId, p.name)
        OPTIONAL MATCH (step)-[legacy_next_rel]->(legacy_next_step)<-[:has_step]-(p)
        WHERE toLower(type(legacy_next_rel)) = 'to'
          AND product_next_rel IS NULL
          AND legacy_next_rel.product_id IS NULL
        RETURN
          properties(step) AS step_props,
          properties(step) AS process_props,
          properties(step_device) AS device_props,
          properties(coalesce(product_next_step, legacy_next_step)) AS next_props,
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
        "起始设备": "`起始设备` VARCHAR(128) DEFAULT ''",
        "目标设备": "`目标设备` VARCHAR(128) DEFAULT ''",
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


def fetch_existing_order(cursor: Any, order_id: str) -> dict[str, Any] | None:
    order_id_col = safe_column_name(order_id_column(cursor))
    cursor.execute(
        f"""
        SELECT {order_id_col} AS order_id, `产品名称` AS product_name, `订单状态` AS order_status
        FROM `orders`
        WHERE {order_id_col} = %s
        LIMIT 1
        """,
        (order_id,),
    )
    return cursor.fetchone()


def create_production_order(arguments: dict[str, Any]) -> dict[str, Any]:
    product_id = str(arguments.get("product_id") or arguments.get("productId") or "").strip()
    product_name = str(arguments.get("product_name") or arguments.get("productName") or "").strip()
    quantity = positive_int(arguments.get("quantity")) or 1
    order_id = str(arguments.get("order_id") or arguments.get("orderId") or "").strip() or generate_order_id_for_today()
    if not product_id:
        raise ValueError("product_id is required")
    if not product_name:
        raise ValueError("product_name is required")

    now = datetime.now()
    with get_mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_live_order_tables(cursor)
            ensure_live_order_columns(cursor)
            order_id_col = safe_column_name(order_id_column(cursor))
            existing_order = fetch_existing_order(cursor, order_id)
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
        conn.commit()

    return {
        "success": True,
        "order_id": order_id,
        "product_id": product_id,
        "product_name": product_name,
        "quantity": quantity,
        "created": existing_order is None,
        "order_status": "已创建",
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
                            `工序编号`, `前置工单`, `后续工单`, `分配设备`, `起始设备`, `目标设备`, `工单状态`, `创建时间`,
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
                                or ""
                            ),
                            "source_station": str(
                                work_order.get("source_station")
                                or work_order.get("起始设备")
                                or (work_order.get("assigned_device") or {}).get("device_id")
                                or (work_order.get("assigned_device") or {}).get("workstation_id")
                                or work_order.get("分配设备")
                                or ""
                            ),
                            "target_station": str(
                                work_order.get("target_station")
                                or work_order.get("目标设备")
                                or (work_order.get("assigned_device") or {}).get("device_id")
                                or (work_order.get("assigned_device") or {}).get("workstation_id")
                                or work_order.get("分配设备")
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


def add_plan_issue(
    issues: list[dict[str, Any]],
    code: str,
    path: str,
    message: str,
    **extra: Any,
) -> None:
    issue = {"code": code, "path": path, "message": message}
    issue.update({key: value for key, value in extra.items() if value not in (None, "")})
    issues.append(issue)


def positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def read_plan_device_ids() -> set[str]:
    device_ids: set[str] = set()
    try:
        with get_mysql_connection("device") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT `设备编号` AS device_id FROM `devices`")
                for row in cursor.fetchall():
                    device_id = str(row.get("device_id") or "").strip()
                    if device_id:
                        device_ids.add(device_id)
    except Exception as exc:
        print(f"mysql device validation skipped: {exc}", file=sys.stderr, flush=True)

    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = get_neo4j_driver()
    try:
        with driver.session(database=database) as session:
            result = session.run(
                """
                MATCH (d)
                WHERE any(label IN labels(d) WHERE toLower(label) = 'device')
                RETURN coalesce(d.deviceId, d.device_id, d.id, d.name) AS device_id
                """
            )
            for record in result:
                device_id = str(record.get("device_id") or "").strip()
                if device_id:
                    device_ids.add(device_id)
    except Exception as exc:
        print(f"neo4j device validation skipped: {exc}", file=sys.stderr, flush=True)
    finally:
        driver.close()
    return device_ids


def read_plan_process_specs(product_id: str, product_name: str) -> dict[str, Any]:
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = get_neo4j_driver()
    try:
        with driver.session(database=database) as session:
            product = find_product(session, product_id, product_name)
            if not product:
                return {"product": None, "route": [], "process_specs": {}, "material_catalog": set()}
            result = session.run(
                """
                MATCH (p)-[rel]->(proc)
                WHERE elementId(p) = $product_node_id
                  AND toLower(type(rel)) = 'has_step'
                  AND any(label IN labels(proc) WHERE toLower(label) IN ['process_instance', 'process'])
                OPTIONAL MATCH (proc)-[use_rel]->(used)
                WHERE toLower(type(use_rel)) = 'uses'
                OPTIONAL MATCH (proc)-[produce_rel]->(produced)
                WHERE toLower(type(produce_rel)) = 'produces'
                OPTIONAL MATCH (proc)-[:CAN_RUN_ON]->(dev)
                WHERE any(label IN labels(dev) WHERE toLower(label) = 'device')
                RETURN
                  coalesce(proc.process_id, proc.processId, proc.process_code, proc.code, proc.stepId) AS process_id,
                  coalesce(proc.process_type, proc.processType, '') AS process_type,
                  coalesce(rel.order, rel.sequence, proc.order, proc.stepId, proc.process_id, proc.name, '') AS sort_key,
                  collect(DISTINCT CASE WHEN used IS NULL THEN NULL ELSE {
                    material_type: coalesce(used.name, used.type, used.material_type, used.materialType),
                    quantity: coalesce(use_rel.quantity, 1)
                  } END) AS uses,
                  collect(DISTINCT CASE WHEN produced IS NULL THEN NULL ELSE {
                    material_type: coalesce(produced.name, produced.type, produced.material_type, produced.materialType),
                    quantity: coalesce(produce_rel.quantity, 1)
                  } END) AS produces,
                  collect(DISTINCT coalesce(dev.deviceId, dev.device_id, dev.id, dev.name)) AS devices
                ORDER BY sort_key
                """,
                product_node_id=str(product["_node_id"]),
            )
            route: list[str] = []
            process_specs: dict[str, Any] = {}
            material_catalog: set[str] = set()
            produced_keys: set[str] = set()
            for record in result:
                process_id = str(record.get("process_id") or "").strip()
                if not process_id:
                    continue
                route.append(process_id)
                if process_id in PLAN_FIXED_PROCESS_IDS:
                    uses = []
                    produces = []
                else:
                    uses = [
                        normalize_plan_material_requirement(item)
                        for item in (record.get("uses") or [])
                        if item
                    ]
                    produces = [
                        normalize_plan_material_requirement(item)
                        for item in (record.get("produces") or [])
                        if item
                    ]
                for material in (*uses, *produces):
                    material_type = normalize_match_text(material.get("material_type"))
                    if material_type:
                        material_catalog.add(material_type)
                for material in produces:
                    key = normalize_match_text(material.get("material_type"))
                    if key:
                        produced_keys.add(key)
                process_specs[process_id] = {
                    "process_id": process_id,
                    "process_type": str(record.get("process_type") or PLAN_PROCESS_TYPE_MAP.get(process_id) or "加工"),
                    "uses": uses,
                    "produces": produces,
                    "devices": [str(device_id) for device_id in (record.get("devices") or []) if str(device_id or "").strip()],
                }
            raw_inputs: list[dict[str, Any]] = []
            final_outputs: list[dict[str, Any]] = []
            for process_id in route:
                if process_id in PLAN_FIXED_PROCESS_IDS:
                    continue
                spec = process_specs.get(process_id) or {}
                for material in spec.get("uses") or []:
                    if normalize_match_text(material.get("material_type")) not in produced_keys:
                        raw_inputs.append(material)
                if spec.get("produces"):
                    final_outputs = list(spec.get("produces") or [])
            if raw_inputs and PLAN_FIXED_OUTPUT_PROCESS_ID in process_specs:
                process_specs[PLAN_FIXED_OUTPUT_PROCESS_ID]["uses"] = raw_inputs
                process_specs[PLAN_FIXED_OUTPUT_PROCESS_ID]["produces"] = raw_inputs
                for material in raw_inputs:
                    material_type = normalize_match_text(material.get("material_type"))
                    if material_type:
                        material_catalog.add(material_type)
            if final_outputs:
                for fixed_process_id in PLAN_FINAL_PRODUCT_PROCESS_IDS:
                    if fixed_process_id in process_specs:
                        process_specs[fixed_process_id]["uses"] = final_outputs
                        process_specs[fixed_process_id]["produces"] = final_outputs
                        for material in final_outputs:
                            material_type = normalize_match_text(material.get("material_type"))
                            if material_type:
                                material_catalog.add(material_type)
            return {
                "product": {key: value for key, value in product.items() if key != "_node_id"},
                "route": route,
                "process_specs": process_specs,
                "material_catalog": material_catalog,
            }
    finally:
        driver.close()


def normalize_plan_material_requirement(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"material_type": str(item or "").strip(), "quantity": 1}
    material_type = str(
        first_present_normalized(
            item,
            ("material_type", "materialType", "type", "name", "物料类型", "物料名称"),
        )
        or ""
    ).strip()
    quantity = positive_int(first_present_normalized(item, ("quantity", "qty", "数量"))) or 1
    return {"material_type": material_type, "quantity": quantity}


def normalize_plan_material_entry(
    item: Any,
    path: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        add_plan_issue(errors, "invalid_material", path, "物料项必须是对象，并包含物料大类和数量。")
        return None
    material_type = str(
        first_present_normalized(
            item,
            ("material_type", "materialType", "type", "name", "物料类型", "物料名称"),
        )
        or ""
    ).strip()
    quantity = positive_int(first_present_normalized(item, ("quantity", "qty", "数量")))
    if not material_type:
        add_plan_issue(errors, "missing_material_type", path, "物料项缺少物料大类。")
    if quantity is None:
        add_plan_issue(errors, "invalid_material_quantity", path, "物料数量必须是大于 0 的整数。")
    if not material_type or quantity is None:
        return None
    return {
        "material_type": material_type,
        "quantity": quantity,
        "allocation_status": "pending",
        "material_instances": [],
    }


def normalize_plan_material_list(
    work_order: dict[str, Any],
    field_name: str,
    path: str,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw = work_order.get(field_name)
    if raw is None:
        chinese_field = "输入物料" if field_name == "input_materials" else "输出物料"
        raw = work_order.get(chinese_field)
    if not isinstance(raw, list):
        add_plan_issue(errors, "invalid_material_list", path, f"{field_name} 必须提供，且必须是列表。")
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        material = normalize_plan_material_entry(item, f"{path}[{index}]", errors)
        if material:
            normalized.append(material)
    return normalized


def material_quantity_by_type(materials: list[dict[str, Any]]) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for material in materials:
        key = normalize_match_text(material.get("material_type"))
        if not key:
            continue
        quantities[key] = quantities.get(key, 0) + int(material.get("quantity") or 0)
    return quantities


def validate_required_materials(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    path: str,
    direction: str,
    errors: list[dict[str, Any]],
) -> None:
    actual_quantities = material_quantity_by_type(actual)
    for requirement in expected:
        material_type = str(requirement.get("material_type") or "").strip()
        expected_quantity = int(requirement.get("quantity") or 1)
        actual_quantity = actual_quantities.get(normalize_match_text(material_type), 0)
        if actual_quantity < expected_quantity:
            add_plan_issue(
                errors,
                "material_requirement_not_met",
                path,
                f"{direction}物料不满足工艺要求：{material_type} 需要 {expected_quantity}，当前 {actual_quantity}。",
                material_type=material_type,
                expected_quantity=expected_quantity,
                actual_quantity=actual_quantity,
            )


def validate_plan_materials(
    work_order: dict[str, Any],
    process_spec: dict[str, Any] | None,
    material_catalog: set[str],
    path: str,
    errors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    input_materials = normalize_plan_material_list(work_order, "input_materials", f"{path}.input_materials", errors)
    output_materials = normalize_plan_material_list(work_order, "output_materials", f"{path}.output_materials", errors)
    if material_catalog:
        for direction, materials in (("输入", input_materials), ("输出", output_materials)):
            for material in materials:
                material_type = str(material.get("material_type") or "").strip()
                if normalize_match_text(material_type) not in material_catalog:
                    add_plan_issue(
                        errors,
                        "unknown_material_type",
                        path,
                        f"{direction}物料大类不在 Neo4j 产品工艺物料范围内：{material_type}。",
                        material_type=material_type,
                    )
    if process_spec:
        validate_required_materials(input_materials, process_spec.get("uses") or [], path, "输入", errors)
        validate_required_materials(output_materials, process_spec.get("produces") or [], path, "输出", errors)
    if str(work_order.get("工单类型") or "") == "运输" and input_materials and output_materials:
        if material_quantity_by_type(input_materials) != material_quantity_by_type(output_materials):
            add_plan_issue(errors, "transport_material_mismatch", path, "运输工单的输入物料和输出物料应保持一致。")
    return input_materials, output_materials


def validate_existing_plan_order(order_id: str, allow_existing: bool, errors: list[dict[str, Any]]) -> None:
    if allow_existing:
        return
    try:
        with get_mysql_connection("order") as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM `work_orders` WHERE `所属订单号` = %s", (order_id,))
                total = int((cursor.fetchone() or {}).get("total") or 0)
    except Exception as exc:
        add_plan_issue(errors, "database_check_failed", "order.order_id", f"检查现有工单失败：{exc}")
        return
    if total > 0:
        add_plan_issue(
            errors,
            "order_work_orders_already_exist",
            "order.order_id",
            "该订单已经存在工单，校验层不会覆盖已有工单。",
            existing_work_order_count=total,
        )


def plan_work_order_id(order_id: str, item_no: int, sequence: int, work_order_type: str) -> str:
    suffix = "TP" if work_order_type == "运输" else "WO"
    return f"{order_id}-I{item_no:03d}-{suffix}-{sequence:03d}"


def validate_item_transport_links(
    work_orders: list[dict[str, Any]],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    for index, work_order in enumerate(work_orders):
        if work_order.get("工单类型") != "运输":
            continue
        previous_work_order = work_orders[index - 1] if index > 0 else {}
        next_work_order = work_orders[index + 1] if index + 1 < len(work_orders) else {}
        if previous_work_order.get("工单类型") == "运输" or next_work_order.get("工单类型") == "运输":
            add_plan_issue(errors, "invalid_transport_position", f"{path}.work_orders[{index}]", "运输工单必须位于两个非运输工单之间。")
            continue
        source_station = str(work_order.get("起始设备") or "").strip()
        target_station = str(work_order.get("目标设备") or "").strip()
        previous_device = str(previous_work_order.get("分配设备") or "").strip()
        next_device = str(next_work_order.get("分配设备") or "").strip()
        if not source_station or not target_station:
            add_plan_issue(errors, "missing_transport_station", f"{path}.work_orders[{index}]", "运输工单必须填写起始设备和目标设备。")
        if source_station and previous_device and source_station != previous_device:
            add_plan_issue(errors, "transport_source_mismatch", f"{path}.work_orders[{index}].起始设备", "运输起始设备应等于前一张工单的分配设备。")
        if target_station and next_device and target_station != next_device:
            add_plan_issue(errors, "transport_target_mismatch", f"{path}.work_orders[{index}].目标设备", "运输目标设备应等于后一张工单的分配设备。")

    non_transport_indices = [index for index, work_order in enumerate(work_orders) if work_order.get("工单类型") != "运输"]
    for left, right in zip(non_transport_indices, non_transport_indices[1:]):
        left_device = str(work_orders[left].get("分配设备") or "").strip()
        right_device = str(work_orders[right].get("分配设备") or "").strip()
        transports_between = [item for item in work_orders[left + 1:right] if item.get("工单类型") == "运输"]
        if left_device and right_device and left_device != right_device and len(transports_between) != 1:
            add_plan_issue(
                errors,
                "missing_transport_work_order",
                f"{path}.work_orders",
                "相邻非运输工单分配设备不同时，中间必须有且仅有一张运输工单。",
                source_device=left_device,
                target_device=right_device,
            )
        if left_device and right_device and left_device == right_device and transports_between:
            add_plan_issue(
                errors,
                "unnecessary_transport_work_order",
                f"{path}.work_orders",
                "相邻非运输工单分配设备相同时，不应插入运输工单。",
                device_id=left_device,
            )


def validate_work_order_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = arguments.get("plan") if isinstance(arguments.get("plan"), dict) else arguments
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        add_plan_issue(errors, "invalid_plan", "", "计划必须是 JSON 对象。")
        return {"success": False, "errors": errors, "warnings": warnings}

    order = plan.get("order") if isinstance(plan.get("order"), dict) else {}
    order_id = str(order.get("order_id") or order.get("orderId") or "").strip()
    product_id = str(order.get("product_id") or order.get("productId") or "").strip()
    product_name = str(order.get("product_name") or order.get("productName") or "").strip()
    quantity = positive_int(order.get("quantity"))
    if not order_id:
        add_plan_issue(errors, "missing_order_id", "order.order_id", "order_id 必填。")
    if not product_id:
        add_plan_issue(errors, "missing_product_id", "order.product_id", "product_id 必填。")
    if not product_name:
        add_plan_issue(errors, "missing_product_name", "order.product_name", "product_name 必填。")
    if quantity is None:
        add_plan_issue(errors, "invalid_quantity", "order.quantity", "quantity 必须是大于 0 的整数。")
    if order_id:
        try:
            with get_mysql_connection("order") as conn:
                with conn.cursor() as cursor:
                    ensure_live_order_tables(cursor)
                    ensure_live_order_columns(cursor)
                    existing_order = fetch_existing_order(cursor, order_id)
        except Exception as exc:
            add_plan_issue(errors, "database_check_failed", "order.order_id", f"检查订单是否存在失败：{exc}")
            existing_order = None
        if existing_order is None:
            add_plan_issue(errors, "order_not_created", "order.order_id", "订单必须先创建，再基于订单拆分工单。")
        elif product_name and str(existing_order.get("product_name") or "").strip() != product_name:
            add_plan_issue(
                errors,
                "order_product_name_mismatch",
                "order.product_name",
                "WorkOrderPlan 中的 product_name 必须和已创建订单的产品名称一致。",
                expected=str(existing_order.get("product_name") or "").strip(),
                actual=product_name,
            )

    process_context = {"product": None, "route": [], "process_specs": {}, "material_catalog": set()}
    if product_id and product_name:
        try:
            process_context = read_plan_process_specs(product_id, product_name)
        except Exception as exc:
            add_plan_issue(errors, "neo4j_validation_failed", "order.product_id", f"读取 Neo4j 产品/工艺失败：{exc}")
        if not process_context.get("product"):
            add_plan_issue(errors, "product_not_found", "order.product_id", "Neo4j 中未找到同时匹配 product_id 和 product_name 的产品。")

    device_ids = read_plan_device_ids()
    allow_existing = bool(arguments.get("allow_existing") or arguments.get("allowExisting"))
    if order_id:
        validate_existing_plan_order(order_id, allow_existing, errors)

    items = plan.get("items")
    if not isinstance(items, list) or not items:
        add_plan_issue(errors, "invalid_items", "items", "items 必须是非空列表。")
        items = []
    if quantity is not None and len(items) != quantity:
        add_plan_issue(errors, "item_count_mismatch", "items", "items 数量必须等于 order.quantity。", expected=quantity, actual=len(items))

    expected_item_nos = list(range(1, len(items) + 1))
    actual_item_nos: list[int] = []
    normalized_items: list[dict[str, Any]] = []
    expected_route = list(process_context.get("route") or [])
    if not expected_route:
        expected_route = [process_id for process_id in PLAN_TYPE_PROCESS_MAP.values() if process_id != "AGV-TRANSPORT"]
    process_specs = process_context.get("process_specs") if isinstance(process_context.get("process_specs"), dict) else {}
    material_catalog = process_context.get("material_catalog")
    if not isinstance(material_catalog, set):
        material_catalog = set()
    created_at = datetime.now()
    created_at_text = created_at.isoformat(timespec="seconds")

    for item_index, item in enumerate(items):
        item_path = f"items[{item_index}]"
        if not isinstance(item, dict):
            add_plan_issue(errors, "invalid_item", item_path, "item 必须是对象。")
            continue
        item_no = positive_int(item.get("item_no") or item.get("itemNo"))
        if item_no is None:
            add_plan_issue(errors, "invalid_item_no", f"{item_path}.item_no", "item_no 必须是大于 0 的整数。")
            item_no = item_index + 1
        actual_item_nos.append(item_no)
        item_id = f"{order_id}-ITEM-{item_no:03d}" if order_id else ""
        raw_work_orders = item.get("work_orders")
        if not isinstance(raw_work_orders, list) or not raw_work_orders:
            add_plan_issue(errors, "invalid_work_orders", f"{item_path}.work_orders", "work_orders 必须是非空列表。")
            normalized_items.append({"item_no": item_no, "item_id": item_id, "work_orders": []})
            continue

        sequence_values: list[int] = []
        prepared_work_orders: list[dict[str, Any]] = []
        for work_order_index, raw_work_order in enumerate(raw_work_orders):
            work_order_path = f"{item_path}.work_orders[{work_order_index}]"
            if not isinstance(raw_work_order, dict):
                add_plan_issue(errors, "invalid_work_order", work_order_path, "工单必须是对象。")
                continue
            sequence = positive_int(raw_work_order.get("sequence"))
            if sequence is None:
                add_plan_issue(errors, "invalid_sequence", f"{work_order_path}.sequence", "sequence 必填，且必须是大于 0 的整数。")
                sequence = 0
            else:
                sequence_values.append(sequence)
            for field_name in ("工单类型", "工序编号", "工单名称", "分配设备", "起始设备", "目标设备", "description"):
                if not str(raw_work_order.get(field_name) or "").strip():
                    add_plan_issue(errors, "missing_work_order_field", f"{work_order_path}.{field_name}", f"{field_name} 必填。")
            work_order_type = str(raw_work_order.get("工单类型") or "").strip()
            process_id_value = str(raw_work_order.get("工序编号") or "").strip()
            assigned_device = str(raw_work_order.get("分配设备") or "").strip()
            source_device = str(raw_work_order.get("起始设备") or "").strip()
            target_device = str(raw_work_order.get("目标设备") or "").strip()
            if work_order_type and work_order_type not in PLAN_WORK_ORDER_TYPES:
                add_plan_issue(errors, "invalid_work_order_type", f"{work_order_path}.工单类型", "工单类型不在允许范围内。", allowed=list(PLAN_WORK_ORDER_TYPES))
            expected_process_id = PLAN_TYPE_PROCESS_MAP.get(work_order_type)
            if expected_process_id and process_id_value != expected_process_id:
                add_plan_issue(
                    errors,
                    "process_type_mismatch",
                    f"{work_order_path}.工序编号",
                    "工单类型和工序编号不匹配。",
                    expected=expected_process_id,
                    actual=process_id_value,
                )
            if work_order_type == "加工" and process_id_value in (*PLAN_FIXED_PROCESS_IDS, "AGV-TRANSPORT"):
                add_plan_issue(
                    errors,
                    "process_type_mismatch",
                    f"{work_order_path}.工序编号",
                    "加工工单必须使用产品加工路线中的加工工序编号。",
                    actual=process_id_value,
                )
            process_spec = process_specs.get(process_id_value)
            expected_devices = list((process_spec or {}).get("devices") or [])
            expected_device = PLAN_PROCESS_DEVICE_MAP.get(process_id_value)
            if assigned_device and device_ids and assigned_device not in device_ids:
                add_plan_issue(errors, "unknown_device", f"{work_order_path}.分配设备", "分配设备不存在。", device_id=assigned_device)
            if expected_devices and assigned_device and assigned_device not in expected_devices:
                add_plan_issue(
                    errors,
                    "device_process_mismatch",
                    f"{work_order_path}.分配设备",
                    "分配设备和工序编号不匹配。",
                    expected=expected_devices,
                    actual=assigned_device,
                )
            elif expected_device and assigned_device and assigned_device != expected_device:
                add_plan_issue(
                    errors,
                    "device_process_mismatch",
                    f"{work_order_path}.分配设备",
                    "分配设备和工序编号不匹配。",
                    expected=expected_device,
                    actual=assigned_device,
                )
            if work_order_type and work_order_type != "运输":
                if assigned_device and source_device and source_device != assigned_device:
                    add_plan_issue(
                        errors,
                        "non_transport_source_mismatch",
                        f"{work_order_path}.起始设备",
                        "非运输工单的起始设备必须等于分配设备。",
                        expected=assigned_device,
                        actual=source_device,
                    )
                if assigned_device and target_device and target_device != assigned_device:
                    add_plan_issue(
                        errors,
                        "non_transport_target_mismatch",
                        f"{work_order_path}.目标设备",
                        "非运输工单的目标设备必须等于分配设备。",
                        expected=assigned_device,
                        actual=target_device,
                    )
            input_materials, output_materials = validate_plan_materials(
                raw_work_order,
                process_spec,
                material_catalog,
                work_order_path,
                errors,
            )
            prepared_work_order = {
                **raw_work_order,
                "sequence": sequence,
                "input_materials": input_materials,
                "output_materials": output_materials,
            }
            prepared_work_orders.append(prepared_work_order)

        expected_sequences = list(range(1, len(raw_work_orders) + 1))
        if sorted(sequence_values) != expected_sequences:
            add_plan_issue(
                errors,
                "non_continuous_sequence",
                f"{item_path}.work_orders",
                "sequence 必须从 1 开始且连续。",
                expected=expected_sequences,
                actual=sorted(sequence_values),
            )
        prepared_work_orders.sort(key=lambda work_order: int(work_order.get("sequence") or 0))
        actual_route = [str(work_order.get("工序编号") or "") for work_order in prepared_work_orders if work_order.get("工单类型") != "运输"]
        if expected_route and actual_route != expected_route:
            add_plan_issue(
                errors,
                "route_mismatch",
                f"{item_path}.work_orders",
                "非运输工单的工艺路线必须和 Neo4j 产品工艺路线一致。",
                expected=expected_route,
                actual=actual_route,
            )
        validate_item_transport_links(prepared_work_orders, item_path, errors)

        normalized_work_orders: list[dict[str, Any]] = []
        for work_order in prepared_work_orders:
            sequence = int(work_order.get("sequence") or 0)
            work_order_type = str(work_order.get("工单类型") or "")
            work_order_id = plan_work_order_id(order_id, item_no, sequence, work_order_type) if order_id else ""
            assigned_station = str(work_order.get("分配设备") or "")
            source_station = str(work_order.get("起始设备") or "")
            target_station = str(work_order.get("目标设备") or "")
            if work_order_type != "运输":
                source_station = assigned_station
                target_station = assigned_station
            normalized_work_orders.append(
                {
                    "工单ID": work_order_id,
                    "工单名称": str(work_order.get("工单名称") or work_order_id),
                    "所属订单号": order_id,
                    "item_no": item_no,
                    "item_id": item_id,
                    "sequence": sequence,
                    "工单类型": work_order_type,
                    "工序数量": 1,
                    "已完成工序数量": 0,
                    "工序编号": str(work_order.get("工序编号") or ""),
                    "前置工单": None,
                    "后续工单": None,
                    "分配设备": assigned_station,
                    "起始设备": source_station,
                    "目标设备": target_station,
                    "工单状态": "已创建",
                    "创建时间": created_at_text,
                    "更新时间": created_at_text,
                    "结束时间": None,
                    "description": str(work_order.get("description") or ""),
                    "input_materials": work_order.get("input_materials") or [],
                    "output_materials": work_order.get("output_materials") or [],
                    "material_effect": PLAN_MATERIAL_EFFECT_MAP.get(work_order_type, ""),
                }
            )
        for index, work_order in enumerate(normalized_work_orders):
            work_order["前置工单"] = normalized_work_orders[index - 1]["工单ID"] if index > 0 else None
            work_order["后续工单"] = normalized_work_orders[index + 1]["工单ID"] if index + 1 < len(normalized_work_orders) else None
        normalized_items.append({"item_no": item_no, "item_id": item_id, "work_orders": normalized_work_orders})

    if actual_item_nos and sorted(actual_item_nos) != expected_item_nos:
        add_plan_issue(
            errors,
            "item_no_not_continuous",
            "items",
            "item_no 必须从 1 开始且连续。",
            expected=expected_item_nos,
            actual=sorted(actual_item_nos),
        )

    normalized_plan = {
        "order": {
            "order_id": order_id,
            "product_id": product_id,
            "product_name": product_name,
            "quantity": quantity,
            "订单状态": "已创建",
            "订单创建时间": created_at_text,
            "更新时间": created_at_text,
        },
        "items": normalized_items,
        "work_orders": [
            work_order
            for item in normalized_items
            for work_order in item.get("work_orders", [])
        ],
    }
    return {
        "success": not errors,
        "errors": errors,
        "warnings": warnings,
        "normalized_plan": normalized_plan if not errors else None,
        "draft_normalized_plan": normalized_plan,
        "summary": {
            "order_id": order_id,
            "item_count": len(normalized_items),
            "work_order_count": len(normalized_plan["work_orders"]),
            "expected_route": expected_route,
            "material_allocation": "pending",
        },
    }


def persist_work_order_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    validation_result = validate_work_order_plan(arguments)
    if not validation_result.get("success"):
        return {
            "success": False,
            "message": "WorkOrderPlan 未通过校验，未写入工单。",
            "validation": validation_result,
        }

    normalized_plan = validation_result["normalized_plan"]
    order = normalized_plan["order"]
    split_result = {
        "order_id": order["order_id"],
        "product": {
            "product_id": order["product_id"],
            "productId": order["product_id"],
            "name": order["product_name"],
        },
        "quantity": order["quantity"],
        "work_orders": normalized_plan["work_orders"],
    }
    persist_result = persist_production_order(
        {
            "order_id": order["order_id"],
            "product_id": order["product_id"],
            "product_name": order["product_name"],
            "quantity": order["quantity"],
        },
        split_result,
    )
    return {
        "success": True,
        "message": "订单已基于 WorkOrderPlan 拆分工单并写入 MySQL，尚未投入调度。",
        "validation": validation_result,
        "production_persist": persist_result,
        "scheduler_submission": None,
        "scheduler_submission_required": True,
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_production_order",
            description="创建生产订单，只写入 order.orders，不拆分工单，不提交调度。拆分工单必须基于已创建订单继续执行。",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单编号。可选；缺省时按 PO-YYYYMMDD-序号 自动生成。",
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Neo4j 产品 ID，必填。",
                    },
                    "product_name": {
                        "type": "string",
                        "description": "产品名称，必填。",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "订单内产品件数。当前订单表不保存生产数量，但后续 WorkOrderPlan 必须使用该数量生成 items。",
                        "default": 1,
                    },
                    "remark": {
                        "type": "string",
                        "description": "订单备注，可选。",
                    },
                },
                "required": ["product_id", "product_name"],
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
        Tool(
            name="validate_work_order_plan",
            description=(
                "基于已创建订单校验生产智能体生成的 WorkOrderPlan。要求 order_id 对应订单已存在，order.product_id 和 product_name 同时存在，"
                "按 item 独立链路校验工单 sequence、类型、工序、设备、AGV 运输、Neo4j 工艺路线和物料大类数量，"
                "并补齐 item_id、工单ID、前后置关系、状态、创建时间、更新时间，返回可落库的规范化工单。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "object",
                        "description": "生产智能体输出的 WorkOrderPlan；也可以直接把 WorkOrderPlan 作为工具参数传入。",
                    },
                    "allow_existing": {
                        "type": "boolean",
                        "description": "是否允许订单已存在工单。默认 false，存在工单时返回校验错误。",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="persist_work_order_plan",
            description=(
                "基于已创建订单拆分并落库工单。内部先调用 validate_work_order_plan 校验和补全，"
                "校验通过后写入 order.work_orders，并把订单推进到已计划；不自动投入调度。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "object",
                        "description": "生产智能体输出的 WorkOrderPlan；也可以直接把 WorkOrderPlan 作为工具参数传入。",
                    },
                    "allow_existing": {
                        "type": "boolean",
                        "description": "是否允许订单已存在工单。默认 false，存在工单时返回校验错误。",
                        "default": False,
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    if name == "create_production_order":
        result = create_production_order(arguments or {})
    elif name == "submit_order_to_scheduler":
        result = submit_order_to_scheduler(arguments or {})
    elif name == "validate_work_order_plan":
        result = validate_work_order_plan(arguments or {})
    elif name == "persist_work_order_plan":
        result = persist_work_order_plan(arguments or {})
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
