# -*- coding: utf-8 -*-
import json
import locale
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]


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


def env_config() -> dict[str, str]:
    load_env()
    return {
        "namesrv_addr": os.environ.get("ROCKETMQ_NAMESRV_ADDR", "127.0.0.1:9876"),
        "consumer_group": os.environ.get(
            "ROCKETMQ_DEVICE_EVENT_CONSUMER_GROUP",
            "CID_DEVICE_EVENT_REPORT_CONSUMER",
        ),
        "topic": os.environ.get("ROCKETMQ_DEVICE_EVENT_TOPIC", "DeviceEventReport"),
        "topic_cluster": os.environ.get("ROCKETMQ_DEVICE_EVENT_TOPIC_CLUSTER", "DefaultCluster"),
        "expression": os.environ.get("ROCKETMQ_DEVICE_EVENT_TAG", "*"),
        "batch_size": os.environ.get("ROCKETMQ_DEVICE_EVENT_BATCH_SIZE", "32"),
        "poll_interval_seconds": os.environ.get("ROCKETMQ_DEVICE_EVENT_POLL_SECONDS", "2"),
    }


def mysql_connection(database: str):
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


WORK_ORDER_STATUSES = ("已创建", "受阻", "已下发", "已接收", "执行中", "已完成", "失败")
ORDER_STATUSES = ("已创建", "已计划", "已下发", "生产中", "已完成", "失败")
WORK_ORDER_LEGACY_STATUSES = ("等待中", "已分配", "已取消", "已下单", "异常")


def ensure_order_status_schema(cursor: Any) -> None:
    work_order_current_and_legacy = ",".join(f"'{status}'" for status in (*WORK_ORDER_STATUSES, *WORK_ORDER_LEGACY_STATUSES))
    work_order_target_only = ",".join(f"'{status}'" for status in WORK_ORDER_STATUSES)
    order_current_and_legacy = ",".join(f"'{status}'" for status in (*ORDER_STATUSES, "已接收", "执行中", *WORK_ORDER_LEGACY_STATUSES))
    order_target_only = ",".join(f"'{status}'" for status in ORDER_STATUSES)
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


DEVICE_RUNTIME_TABLE = "devices"
DEVICE_ID_COLUMNS = (
    "device_id",
    "deviceId",
    "device_code",
    "deviceCode",
    "\u8bbe\u5907ID",
    "\u8bbe\u5907\u7f16\u53f7",
    "\u5de5\u7ad9\u7f16\u53f7",
    "\u5de5\u4f5c\u7ad9\u7f16\u53f7",
    "agv_id",
    "agvId",
    "AGV\u7f16\u53f7",
    "id",
    "code",
)
DEVICE_NAME_COLUMNS = (
    "device_name",
    "deviceName",
    "\u8bbe\u5907\u540d\u79f0",
    "\u8bbe\u5907\u540d",
    "\u5de5\u7ad9\u540d\u79f0",
    "\u5de5\u4f5c\u7ad9\u540d\u79f0",
    "agv_name",
    "agvName",
    "AGV\u540d\u79f0",
    "\u5c0f\u8f66\u540d\u79f0",
    "name",
)
DEVICE_STATUS_COLUMNS = (
    "status",
    "state",
    "runtime_status",
    "runtimeStatus",
    "work_status",
    "workStatus",
    "\u8fd0\u884c\u72b6\u6001",
    "\u8bbe\u5907\u72b6\u6001",
    "\u72b6\u6001",
)
DEVICE_CONNECTION_COLUMNS = (
    "connection_state",
    "connectionState",
    "online_state",
    "onlineState",
    "\u8fde\u63a5\u72b6\u6001",
    "\u5728\u7ebf\u72b6\u6001",
    "\u542f\u52a8\u72b6\u6001",
)
DEVICE_TIME_COLUMNS = (
    "last_seen_at",
    "lastSeenAt",
    "updated_at",
    "updatedAt",
    "\u66f4\u65b0\u65f6\u95f4",
    "\u6700\u540e\u5fc3\u8df3\u65f6\u95f4",
)
DEVICE_ID_ALIASES = {
    "DEV005": ("AGV-001",),
    "AGV-001": ("DEV005",),
}
DEVICE_DEFAULT_NAMES = {
    "DEV001": "立体仓库",
    "DEV002": "协作加工工作站",
    "DEV003": "scara工作站1",
    "DEV004": "scara工作站2",
    "DEV005": "AGV小车",
}


def heartbeat_timeout_seconds() -> int:
    load_env()
    seconds = int(os.environ.get("DEVICE_HEARTBEAT_SECONDS", "10"))
    missed = int(os.environ.get("DEVICE_HEARTBEAT_MISSED_LIMIT", "5"))
    return max(1, seconds) * max(1, missed)


def normalize_device_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"", "none", "null"}:
        return ""
    if text in {"idle", "\u7a7a\u95f2"}:
        return "idle"
    if text in {"busy", "running", "processing", "executing", "working", "\u6b63\u5728\u6267\u884c\u4efb\u52a1", "\u6267\u884c\u4e2d"}:
        return "busy"
    if text in {"error", "fault", "failed", "failure", "maintenance", "maintaining", "debug", "debugging", "\u5f02\u5e38", "\u6545\u969c", "\u8c03\u8bd5", "\u7ef4\u62a4", "\u8c03\u8bd5/\u7ef4\u62a4"}:
        return "error"
    if text in {"paused", "pause", "suspended", "\u6682\u505c"}:
        return "paused"
    if text in {"online", "\u5728\u7ebf"}:
        return "idle"
    return "idle"


def normalize_connection_state(value: Any, default: str = "offline") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"offline", "lost", "disconnected", "\u79bb\u7ebf"}:
        return "offline"
    return "online"


def extract_device_id(event: dict[str, Any]) -> str:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    return str(
        event.get("device_id")
        or event.get("deviceId")
        or event.get("device_code")
        or event.get("deviceCode")
        or details.get("device_id")
        or details.get("deviceId")
        or details.get("device_code")
        or details.get("deviceCode")
        or ""
    ).strip()


def extract_device_name(event: dict[str, Any]) -> str:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    return str(
        event.get("device_name")
        or event.get("deviceName")
        or event.get("name")
        or details.get("device_name")
        or details.get("deviceName")
        or details.get("name")
        or ""
    ).strip()


def ensure_device_runtime_schema(cursor: Any) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DEVICE_RUNTIME_TABLE} (
            `设备编号` VARCHAR(50) PRIMARY KEY,
            `设备名称` VARCHAR(100) NOT NULL,
            `连接状态` VARCHAR(32) DEFAULT 'offline',
            `运行状态` VARCHAR(32) DEFAULT '',
            `执行工单编号` VARCHAR(50) DEFAULT NULL,
            `工序编号` VARCHAR(50) DEFAULT NULL,
            `当前任务开始时间` DATETIME NULL,
            `更新时间` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            `创建时间` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_devices_connection (`连接状态`),
            INDEX idx_devices_status (`运行状态`),
            INDEX idx_devices_work_order (`执行工单编号`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    try:
        cursor.execute(
            f"ALTER TABLE {DEVICE_RUNTIME_TABLE} MODIFY `连接状态` VARCHAR(32) DEFAULT 'offline'"
        )
    except Exception as exc:
        print(f"device runtime schema default sync skipped: {exc}", file=sys.stderr, flush=True)


def ensure_device_state_columns_are_text(cursor: Any) -> None:
    startup_column = "\u542f\u52a8\u72b6\u6001"
    connection_column = "\u8fde\u63a5\u72b6\u6001"
    for table_name in ("agv", "workstation"):
        columns = table_columns(cursor, "device", table_name)
        if startup_column in columns and connection_column not in columns:
            try:
                cursor.execute(
                    f"ALTER TABLE {safe_column_name(table_name)} CHANGE {safe_column_name(startup_column)} {safe_column_name(connection_column)} VARCHAR(32) DEFAULT 'offline'"
                )
                columns = table_columns(cursor, "device", table_name)
            except Exception as exc:
                print(
                    f"device connection column rename skipped for {table_name}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        if connection_column not in columns:
            try:
                cursor.execute(
                    f"ALTER TABLE {safe_column_name(table_name)} ADD {safe_column_name(connection_column)} VARCHAR(32) DEFAULT 'offline'"
                )
                columns = table_columns(cursor, "device", table_name)
            except Exception as exc:
                print(
                    f"device connection column add skipped for {table_name}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
        column_types = table_column_types(cursor, "device", table_name)
        for column in (*DEVICE_STATUS_COLUMNS, *DEVICE_CONNECTION_COLUMNS):
            actual = column if column in columns else {item.lower(): item for item in columns}.get(column.lower())
            if not actual:
                continue
            if is_numeric_mysql_type(column_types.get(actual, "")):
                try:
                    cursor.execute(
                        f"ALTER TABLE {safe_column_name(table_name)} MODIFY {safe_column_name(actual)} VARCHAR(32) DEFAULT ''"
                    )
                except Exception as exc:
                    print(
                        f"device status column schema sync skipped for {table_name}.{actual}: {exc}",
                        file=sys.stderr,
                        flush=True,
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


def table_column_types(cursor: Any, database: str, table_name: str) -> dict[str, str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """,
        (database, table_name),
    )
    return {str(row.get("COLUMN_NAME")): str(row.get("DATA_TYPE") or "").lower() for row in cursor.fetchall()}


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


def is_numeric_mysql_type(data_type: str) -> bool:
    return data_type.lower() in {
        "bit",
        "tinyint",
        "smallint",
        "mediumint",
        "int",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "float",
        "double",
        "real",
    }


def is_numeric_text(value: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value.strip()))


def normalize_match_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def first_device_id_column(
    columns: set[str],
    column_types: dict[str, str],
    device_id: str,
) -> str:
    lowered = {column.lower(): column for column in columns}
    for candidate in DEVICE_ID_COLUMNS:
        actual = candidate if candidate in columns else lowered.get(candidate.lower())
        if not actual:
            continue
        if is_numeric_mysql_type(column_types.get(actual, "")) and not is_numeric_text(device_id):
            continue
        return actual
    return ""


def device_id_values_for_table(device_id: str, table_name: str) -> tuple[str, ...]:
    values = [device_id]
    if table_name.lower() == "agv":
        values.extend(DEVICE_ID_ALIASES.get(device_id, ()))
    return tuple(dict.fromkeys(value for value in values if value))


def sync_existing_device_tables(
    cursor: Any,
    device_id: str,
    connection_state: str,
    status: str,
    event_time: datetime,
) -> None:
    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
        """
    )
    for row in cursor.fetchall():
        table_name = str(row.get("TABLE_NAME") or "")
        if not table_name or table_name == DEVICE_RUNTIME_TABLE:
            continue
        columns = table_columns(cursor, "device", table_name)
        column_types = table_column_types(cursor, "device", table_name)
        id_column = first_device_id_column(columns, column_types, device_id)
        if not id_column:
            continue
        assignments: list[str] = []
        values: list[Any] = []
        status_column = first_existing_column(columns, DEVICE_STATUS_COLUMNS)
        connection_column = first_existing_column(columns, DEVICE_CONNECTION_COLUMNS)
        time_column = first_existing_column(columns, DEVICE_TIME_COLUMNS)
        if status_column:
            assignments.append(f"{safe_column_name(status_column)} = %s")
            values.append(status)
        if connection_column:
            assignments.append(f"{safe_column_name(connection_column)} = %s")
            values.append(connection_state)
        if time_column:
            assignments.append(f"{safe_column_name(time_column)} = %s")
            values.append(event_time)
        if not assignments:
            continue
        id_values = device_id_values_for_table(device_id, table_name)
        values.extend(id_values)
        placeholders = ", ".join(["%s"] * len(id_values))
        try:
            cursor.execute(
                f"""
                UPDATE {safe_column_name(table_name)}
                SET {", ".join(assignments)}
                WHERE {safe_column_name(id_column)} IN ({placeholders})
                """,
                tuple(values),
            )
        except Exception as exc:
            print(f"device table sync skipped for {table_name}: {exc}", file=sys.stderr, flush=True)


def upsert_device_runtime(event: dict[str, Any], is_heartbeat: bool) -> None:
    device_id = extract_device_id(event)
    if not device_id:
        return
    if device_id == "AGV-001":
        device_id = "DEV005"
    event_time = parse_event_time(event.get("timestamp") or event.get("created_at"))
    default_connection = "online" if event.get("_device_agent_event") else "offline"
    connection_state = normalize_connection_state(
        event.get("connection_state") or event.get("connectionState"),
        default=default_connection,
    )
    keep_existing_status = is_heartbeat and "status" not in event and "state" not in event
    status = normalize_device_status(event.get("status"))
    if connection_state == "offline":
        status = ""
        keep_existing_status = False
    elif keep_existing_status:
        status = "idle"
    previous_status = normalize_device_status(event.get("previous_status") or event.get("previousStatus")) if event.get("previous_status") or event.get("previousStatus") else ""
    device_name = extract_device_name(event) or DEVICE_DEFAULT_NAMES.get(device_id, "")
    raw_event_json = json.dumps(event, ensure_ascii=False)

    with mysql_connection("device") as conn:
        with conn.cursor() as cursor:
            ensure_device_runtime_schema(cursor)
            ensure_device_state_columns_are_text(cursor)
            cursor.execute(
                f"""
                INSERT INTO {DEVICE_RUNTIME_TABLE} (
                    `设备编号`, `设备名称`, `连接状态`, `运行状态`, `更新时间`
                ) VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `设备名称` = CASE
                        WHEN VALUES(`设备名称`) <> '' AND VALUES(`设备名称`) <> VALUES(`设备编号`) THEN VALUES(`设备名称`)
                        ELSE `设备名称`
                    END,
                    `连接状态` = VALUES(`连接状态`),
                    `运行状态` = CASE WHEN %s THEN `运行状态` ELSE VALUES(`运行状态`) END,
                    `更新时间` = VALUES(`更新时间`)
                """,
                (
                    device_id,
                    device_name or device_id,
                    connection_state,
                    status,
                    event_time,
                    keep_existing_status,
                ),
            )
            if not keep_existing_status:
                sync_existing_device_tables(cursor, device_id, connection_state, status, event_time)
        conn.commit()
    notify_digital_twin_event(
        "device_status_changed",
        {
            "device_id": device_id,
            "connection_state": connection_state,
            "status": status,
            "updated_at": event_time.isoformat(timespec="seconds"),
            "event_type": "device_heartbeat" if is_heartbeat else "device_status_changed",
        },
    )


def mark_stale_device_heartbeats() -> None:
    timeout_seconds = heartbeat_timeout_seconds()
    stale_devices: list[dict[str, Any]] = []
    with mysql_connection("device") as conn:
        with conn.cursor() as cursor:
            ensure_device_runtime_schema(cursor)
            cursor.execute(
                f"""
                SELECT `设备编号` AS device_id
                FROM {DEVICE_RUNTIME_TABLE}
                WHERE `连接状态` <> 'offline'
                  AND TIMESTAMPDIFF(SECOND, `更新时间`, NOW()) >= %s
                """,
                (timeout_seconds,),
            )
            stale_devices = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                f"""
                UPDATE {DEVICE_RUNTIME_TABLE}
                SET `连接状态` = 'offline',
                    `运行状态` = '',
                    `更新时间` = NOW()
                WHERE `连接状态` <> 'offline'
                  AND TIMESTAMPDIFF(SECOND, `更新时间`, NOW()) >= %s
                """,
                (timeout_seconds,),
            )
            event_time = datetime.now()
            for row in stale_devices:
                device_id = str(row.get("device_id") or "")
                if device_id:
                    sync_existing_device_tables(cursor, device_id, "offline", "", event_time)
        conn.commit()
    for row in stale_devices:
        device_id = str(row.get("device_id") or "")
        if device_id:
            notify_digital_twin_event(
                "device_status_changed",
                {
                    "device_id": device_id,
                    "connection_state": "offline",
                    "status": "",
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "event_type": "device_heartbeat_timeout",
                },
            )


def is_archived_status(status: Any) -> bool:
    text = str(status or "").strip().lower()
    return any(token in text for token in ("已完成", "失败", "已取消", "完成", "取消", "complete", "done", "finished", "failed", "failure", "cancel"))


def ensure_data_order_history_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS order_work_order_history (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            order_id VARCHAR(64) NOT NULL,
            order_name VARCHAR(128) NOT NULL,
            product_id VARCHAR(64) NOT NULL,
            product_name VARCHAR(128) NOT NULL,
            customer_name VARCHAR(128) DEFAULT '',
            order_status ENUM('已创建','已计划','已下发','生产中','已完成','失败') NOT NULL DEFAULT '已创建',
            order_start_time DATETIME NOT NULL,
            order_end_time DATETIME NOT NULL,
            work_order_id VARCHAR(64) NOT NULL,
            work_order_name VARCHAR(128) NOT NULL,
            process_name VARCHAR(128) NOT NULL,
            assigned_device_id VARCHAR(64) DEFAULT '',
            assigned_device_name VARCHAR(128) DEFAULT '',
            work_order_status ENUM('已创建','受阻','已下发','已接收','执行中','已完成','失败') NOT NULL DEFAULT '已创建',
            work_order_start_time DATETIME NOT NULL,
            work_order_end_time DATETIME NOT NULL,
            material_batch_ids VARCHAR(255) DEFAULT '',
            description TEXT,
            INDEX idx_order_history_order (order_id),
            INDEX idx_order_history_work_order (work_order_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'order_work_order_history'
        """
    )
    columns = {str(row.get("COLUMN_NAME") or "") for row in cursor.fetchall()}
    if "description" not in columns:
        cursor.execute("ALTER TABLE order_work_order_history ADD COLUMN description TEXT")
    else:
        try:
            cursor.execute("ALTER TABLE order_work_order_history MODIFY description TEXT")
        except Exception as exc:
            print(f"history description schema sync skipped: {exc}", file=sys.stderr, flush=True)


def fetch_order_rows_for_history(order_id: str) -> list[dict[str, Any]]:
    with mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_order_status_schema(cursor)
            order_id_col = safe_column_name(order_id_column(cursor))
            cursor.execute(
                f"""
                SELECT
                    o.{order_id_col} AS order_id,
                    o.{order_id_col} AS order_name,
                    '' AS product_id,
                    COALESCE(o.`产品名称`, '') AS product_name,
                    '' AS customer_name,
                    COALESCE(o.`订单状态`, '') AS order_status,
                    COALESCE(o.`订单创建时间`, NOW()) AS order_start_time,
                    COALESCE(o.`完结时间`, NOW()) AS order_end_time
                FROM `orders` o
                WHERE o.{order_id_col} = %s
                LIMIT 1
                """,
                (order_id,),
            )
            order_row = cursor.fetchone()
            if not order_row:
                return []

            cursor.execute(
                """
                SELECT
                    COALESCE(w.`工单ID`, w.`工单名称`, '') AS work_order_id,
                    COALESCE(w.`工单名称`, '') AS work_order_name,
                    COALESCE(w.`工单类型`, w.`工单名称`, '') AS process_name,
                    COALESCE(w.`分配工站`, '') AS assigned_device_id,
                    COALESCE(w.`分配工站`, '') AS assigned_device_name,
                    COALESCE(w.`工单状态`, '') AS work_order_status,
                    COALESCE(w.`创建时间`, NOW()) AS work_order_start_time,
                    COALESCE(w.`结束时间`, %s, NOW()) AS work_order_end_time,
                    '' AS material_batch_ids,
                    COALESCE(w.`description`, '') AS description
                FROM `work_orders` w
                WHERE w.`所属订单号` = %s
                ORDER BY w.`工单ID`
                """,
                (order_row.get("order_end_time"), order_id),
            )
            rows = []
            for work_order_row in cursor.fetchall():
                rows.append({**order_row, **work_order_row})
            return rows


def sync_archived_order_to_data(order_id: str) -> None:
    if not order_id:
        return
    rows = fetch_order_rows_for_history(order_id)
    if not rows or not is_archived_status(rows[0].get("order_status")):
        return
    if not all_order_work_orders_archived(order_id):
        return

    with mysql_connection("Data") as conn:
        with conn.cursor() as cursor:
            ensure_data_order_history_schema(cursor)
            cursor.execute("DELETE FROM order_work_order_history WHERE order_id = %s", (order_id,))
            cursor.executemany(
                """
                INSERT INTO order_work_order_history (
                    order_id, order_name, product_id, product_name, customer_name, order_status,
                    order_start_time, order_end_time, work_order_id, work_order_name, process_name,
                    assigned_device_id, assigned_device_name, work_order_status,
                    work_order_start_time, work_order_end_time, material_batch_ids, description
                ) VALUES (
                    %(order_id)s, %(order_name)s, %(product_id)s, %(product_name)s, %(customer_name)s, %(order_status)s,
                    %(order_start_time)s, %(order_end_time)s, %(work_order_id)s, %(work_order_name)s, %(process_name)s,
                    %(assigned_device_id)s, %(assigned_device_name)s, %(work_order_status)s,
                    %(work_order_start_time)s, %(work_order_end_time)s, %(material_batch_ids)s, %(description)s
                )
                """,
                rows,
            )
        conn.commit()
    remove_archived_order_from_live_tables(order_id)


def all_order_work_orders_archived(order_id: str) -> bool:
    if not order_id:
        return False
    try:
        with mysql_connection("order") as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT `工单状态` AS status
                    FROM `work_orders`
                    WHERE `所属订单号` = %s
                    """,
                    (order_id,),
                )
                rows = cursor.fetchall()
                return bool(rows) and all(is_archived_status(row.get("status")) for row in rows)
    except Exception as exc:
        print(f"order archive completeness check skipped for {order_id}: {exc}", file=sys.stderr, flush=True)
        return False


def archived_order_history_exists(order_id: str) -> bool:
    if not order_id:
        return False
    try:
        with mysql_connection("Data") as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS row_count
                    FROM order_work_order_history
                    WHERE order_id = %s
                    """,
                    (order_id,),
                )
                row = cursor.fetchone() or {}
                return int(row.get("row_count") or 0) > 0
    except Exception as exc:
        print(f"archived order history check skipped for {order_id}: {exc}", file=sys.stderr, flush=True)
        return False


def remove_archived_order_from_live_tables(order_id: str, require_history: bool = True) -> dict[str, int]:
    if not order_id:
        return {"orders": 0, "work_orders": 0}
    if require_history and not archived_order_history_exists(order_id):
        return {"orders": 0, "work_orders": 0}
    if not all_order_work_orders_archived(order_id):
        return {"orders": 0, "work_orders": 0}

    with mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_order_status_schema(cursor)
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
            if not is_archived_status(row.get("order_status")):
                return {"orders": 0, "work_orders": 0}

            cursor.execute("DELETE FROM `work_orders` WHERE `所属订单号` = %s", (order_id,))
            work_order_count = int(cursor.rowcount or 0)
            cursor.execute(f"DELETE FROM `orders` WHERE {order_id_col} = %s", (order_id,))
            order_count = int(cursor.rowcount or 0)
        conn.commit()

    if order_count or work_order_count:
        print(
            f"archived order removed from live tables: {order_id}, orders={order_count}, work_orders={work_order_count}",
            file=sys.stderr,
            flush=True,
        )
        notify_digital_twin_event(
            "order_archived_removed_from_live",
            {
                "order_id": order_id,
                "orders_removed": order_count,
                "work_orders_removed": work_order_count,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
    return {"orders": order_count, "work_orders": work_order_count}


def cleanup_archived_live_orders(limit: int = 200) -> None:
    try:
        with mysql_connection("order") as conn:
            with conn.cursor() as cursor:
                ensure_order_status_schema(cursor)
                order_id_col = safe_column_name(order_id_column(cursor))
                cursor.execute(
                    f"""
                    SELECT {order_id_col} AS order_id
                    FROM `orders`
                    WHERE `订单状态` IN ('已完成', '失败')
                    ORDER BY COALESCE(`完结时间`, `订单创建时间`, NOW()) ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                order_ids = [str(row.get("order_id") or "") for row in cursor.fetchall()]
            conn.commit()
        for archived_order_id in order_ids:
            remove_archived_order_from_live_tables(archived_order_id)
    except Exception as exc:
        print(f"archived live order cleanup skipped: {exc}", file=sys.stderr, flush=True)


def refresh_order_rollup_status(order_id: str, event_time: datetime) -> None:
    if not order_id:
        return
    with mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_order_status_schema(cursor)
            order_id_col = safe_column_name(order_id_column(cursor))
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN `工单状态` = '已完成' THEN 1 ELSE 0 END) AS completed_count,
                    SUM(CASE WHEN `工单状态` = '失败' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN `工单状态` = '已接收' THEN 1 ELSE 0 END) AS received_count,
                    SUM(CASE WHEN `工单状态` = '执行中' THEN 1 ELSE 0 END) AS running_count
                FROM `work_orders`
                WHERE `所属订单号` = %s
                """,
                (order_id,),
            )
            summary = cursor.fetchone() or {}
            total_count = int(summary.get("total_count") or 0)
            completed_count = int(summary.get("completed_count") or 0)
            failed_count = int(summary.get("failed_count") or 0)
            received_count = int(summary.get("received_count") or 0)
            running_count = int(summary.get("running_count") or 0)
            if total_count <= 0:
                return
            if failed_count > 0:
                status = "失败"
                end_time = event_time
            elif completed_count == total_count:
                status = "已完成"
                end_time = event_time
            elif received_count > 0 or running_count > 0 or completed_count > 0:
                status = "生产中"
                end_time = None
            else:
                cursor.execute(
                    f"""
                    SELECT COALESCE(`订单状态`, '') AS order_status
                    FROM `orders`
                    WHERE {order_id_col} = %s
                    LIMIT 1
                    """,
                    (order_id,),
                )
                current_order = cursor.fetchone() or {}
                current_status = str(current_order.get("order_status") or "")
                if current_status == "已下发":
                    return
                status = "已计划"
                end_time = None

            if end_time is not None:
                cursor.execute(
                    f"""
                    UPDATE `orders`
                    SET `订单状态` = %s, `完结时间` = %s
                    WHERE {order_id_col} = %s
                    """,
                    (status, end_time, order_id),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE `orders`
                    SET `订单状态` = %s
                    WHERE {order_id_col} = %s AND `订单状态` NOT IN ('已完成', '失败')
                    """,
                    (status, order_id),
                )
        conn.commit()


def decode_body(body: Any) -> Any:
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_event_time(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value))
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.now()


def normalize_workorder_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"created", "create", "new", "pending", "queued", "waiting", "wait", "已创建", "等待中", "待创建"}:
        return "已创建"
    if text in {"blocked", "block", "blocked_by_dependency", "dependency_blocked", "受阻", "阻塞", "依赖未满足"}:
        return "受阻"
    if text in {"dispatched", "dispatch", "sent", "issued", "delivered", "assigned", "已下发", "已分配", "已派发"}:
        return "已下发"
    if text in {"received", "accepted", "ready", "ack", "acknowledged", "已接收", "待执行"}:
        return "已接收"
    if text in {"running", "processing", "in_progress", "started", "executing", "执行中", "加工中"}:
        return "执行中"
    if text in {"completed", "complete", "done", "finished", "success", "succeeded", "已完成", "完成"}:
        return "已完成"
    if text in {"failed", "failure", "error", "cancelled", "canceled", "cancel", "aborted", "异常", "失败", "已取消", "取消"}:
        return "失败"
    return str(status or "已创建")


def work_order_is_stage(work_order: dict[str, Any], process_id: str, keyword: str) -> bool:
    text = normalize_match_text(
        " ".join(
            str(work_order.get(key) or "")
            for key in ("工序编号", "工单类型", "工单名称", "description")
        )
    )
    return normalize_match_text(process_id) in text or normalize_match_text(keyword) in text


def extract_material_ids_from_description(description: str) -> list[str]:
    ids: list[str] = []
    for token in re.split(r"[,，、;；\s()\uff08\uff09]+", str(description or "")):
        value = token.strip()
        if not value:
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*-\w[\w-]*", value):
            ids.append(value)
    return list(dict.fromkeys(ids))


def extract_label_codes_from_description(description: str, order_id: str, quantity: int = 1) -> list[str]:
    codes = [
        token.strip()
        for token in re.split(r"[,，、;；\s]+", str(description or ""))
        if token.strip().startswith(f"{order_id}-LABEL-")
    ]
    if codes:
        return list(dict.fromkeys(codes))
    return [f"{order_id}-LABEL-{index:03d}" for index in range(1, max(1, quantity) + 1)]


def consume_outbound_materials(work_order: dict[str, Any], event_time: datetime) -> dict[str, Any]:
    description = str(work_order.get("description") or "")
    explicit_ids = set(extract_material_ids_from_description(description))
    with mysql_connection("store") as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT `物料编号`, `物料名称`, `物料类型`, `库位号` FROM `materials`")
            rows = cursor.fetchall()
            matched_ids = [
                str(row.get("物料编号") or "")
                for row in rows
                if str(row.get("物料编号") or "") in explicit_ids
            ]
            if not matched_ids:
                matched_ids = [
                    str(row.get("物料编号") or "")
                    for row in rows
                    if str(row.get("物料名称") or "") and str(row.get("物料名称") or "") in description
                ]
            matched_ids = [item for item in dict.fromkeys(matched_ids) if item]
            if not matched_ids:
                return {"removed": 0, "material_ids": []}
            placeholders = ",".join(["%s"] * len(matched_ids))
            cursor.execute(f"DELETE FROM `materials` WHERE `物料编号` IN ({placeholders})", tuple(matched_ids))
            removed = int(cursor.rowcount or 0)
        conn.commit()
    if removed:
        notify_digital_twin_event(
            "store_materials_outbound",
            {
                "order_id": work_order.get("所属订单号"),
                "work_order_id": work_order.get("工单ID"),
                "material_ids": matched_ids,
                "removed": removed,
                "updated_at": event_time.isoformat(timespec="seconds"),
            },
        )
    return {"removed": removed, "material_ids": matched_ids}


def ensure_store_product_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS `product` (
            `产品编号` VARCHAR(64) NOT NULL PRIMARY KEY,
            `产品名称` VARCHAR(128) NOT NULL,
            `所属订单号` VARCHAR(64) NOT NULL,
            `贴标编号` VARCHAR(64) NOT NULL,
            `库位号` VARCHAR(50) DEFAULT 'FINISHED-GOODS',
            `入库时间` DATETIME NOT NULL,
            `创建时间` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            `更新时间` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_store_product_order (`所属订单号`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def order_product_name(cursor: Any, order_id: str) -> str:
    try:
        order_id_col = safe_column_name(order_id_column(cursor))
        cursor.execute(
            f"""
            SELECT COALESCE(`产品名称`, '') AS product_name
            FROM `orders`
            WHERE {order_id_col} = %s
            LIMIT 1
            """,
            (order_id,),
        )
        row = cursor.fetchone() or {}
        return str(row.get("product_name") or "")
    except Exception:
        return ""


def store_labeled_products(work_order: dict[str, Any], event_time: datetime) -> dict[str, Any]:
    order_id = str(work_order.get("所属订单号") or "")
    if not order_id:
        return {"inserted": 0, "product_codes": []}
    try:
        quantity = max(1, int(work_order.get("工序数量") or 1))
    except (TypeError, ValueError):
        quantity = 1
    description = str(work_order.get("description") or "")
    label_codes = extract_label_codes_from_description(description, order_id, quantity)

    with mysql_connection("order") as order_conn:
        with order_conn.cursor() as order_cursor:
            product_name = order_product_name(order_cursor, order_id) or order_id

    rows = [
        {
            "product_code": label_code,
            "product_name": product_name,
            "order_id": order_id,
            "label_code": label_code,
            "stored_at": event_time,
        }
        for label_code in label_codes
    ]
    with mysql_connection("store") as conn:
        with conn.cursor() as cursor:
            ensure_store_product_schema(cursor)
            cursor.executemany(
                """
                INSERT INTO `product` (
                    `产品编号`, `产品名称`, `所属订单号`, `贴标编号`, `入库时间`
                ) VALUES (
                    %(product_code)s, %(product_name)s, %(order_id)s, %(label_code)s, %(stored_at)s
                )
                ON DUPLICATE KEY UPDATE
                    `产品名称` = VALUES(`产品名称`),
                    `所属订单号` = VALUES(`所属订单号`),
                    `贴标编号` = VALUES(`贴标编号`),
                    `入库时间` = VALUES(`入库时间`)
                """,
                rows,
            )
        conn.commit()

    notify_digital_twin_event(
        "store_product_inbound",
        {
            "order_id": order_id,
            "work_order_id": work_order.get("工单ID"),
            "product_codes": label_codes,
            "updated_at": event_time.isoformat(timespec="seconds"),
        },
    )
    return {"inserted": len(rows), "product_codes": label_codes}


def apply_work_order_completion_side_effects(work_order: dict[str, Any], event_time: datetime) -> None:
    if work_order_is_stage(work_order, "OUTPUT-001", "出库"):
        try:
            result = consume_outbound_materials(work_order, event_time)
            print(f"outbound materials consumed: {result}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"outbound material consume skipped: {exc}", file=sys.stderr, flush=True)
    if work_order_is_stage(work_order, "INPUT-001", "入库"):
        try:
            result = store_labeled_products(work_order, event_time)
            print(f"labeled product stored: {result}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"labeled product store skipped: {exc}", file=sys.stderr, flush=True)


def extract_work_order_id(event: dict[str, Any]) -> str:
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    return str(
        event.get("work_order_id")
        or event.get("workOrderId")
        or event.get("workorder_id")
        or details.get("work_order_id")
        or details.get("workOrderId")
        or details.get("workorder_id")
        or ""
    ).strip()


def run_scheduler_after_workorder_event(order_id: str, status: str) -> None:
    if not order_id or status not in {"已完成", "失败"}:
        return
    try:
        from split_mcp_server.server import run_scheduler_queue_once, submit_order_to_scheduler

        submit_order_to_scheduler({"order_id": order_id})
        result = run_scheduler_queue_once(limit=20)
        summary = result.get("summary") if isinstance(result, dict) else {}
        print(
            f"scheduler queue triggered after work order event: order_id={order_id}, summary={summary}",
            file=sys.stderr,
            flush=True,
        )
    except Exception as exc:
        print(f"scheduler trigger skipped for order {order_id}: {exc}", file=sys.stderr, flush=True)


def run_scheduler_queue_tick(limit: int = 20) -> None:
    try:
        from split_mcp_server.server import run_scheduler_queue_once

        result = run_scheduler_queue_once(limit=limit)
        processed_count = int(result.get("processed_count") or 0) if isinstance(result, dict) else 0
        if processed_count:
            print(
                f"scheduler queue tick processed {processed_count} order(s)",
                file=sys.stderr,
                flush=True,
            )
    except Exception as exc:
        print(f"scheduler queue tick skipped: {exc}", file=sys.stderr, flush=True)


def release_device_after_workorder_event(event: dict[str, Any], status: str) -> None:
    if status not in {"已完成", "失败"}:
        return
    device_id = extract_device_id(event)
    if not device_id:
        return
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    runtime_event = {
        "event_type": "device_status_changed",
        "device_id": device_id,
        "device_name": extract_device_name(event),
        "connection_state": event.get("connection_state") or event.get("connectionState") or "online",
        "status": event.get("device_status") or event.get("deviceStatus") or details.get("device_status") or details.get("deviceStatus") or "idle",
        "timestamp": event.get("timestamp") or event.get("created_at") or datetime.now().isoformat(timespec="seconds"),
    }
    try:
        upsert_device_runtime(runtime_event, is_heartbeat=False)
        clear_device_current_task(device_id, parse_event_time(runtime_event["timestamp"]))
    except Exception as exc:
        print(f"device release after work order event skipped: {exc}", file=sys.stderr, flush=True)


def clear_device_current_task(device_id: str, event_time: datetime) -> None:
    if not device_id:
        return
    if device_id == "AGV-001":
        device_id = "DEV005"
    with mysql_connection("device") as conn:
        with conn.cursor() as cursor:
            ensure_device_runtime_schema(cursor)
            cursor.execute(
                f"""
                UPDATE {DEVICE_RUNTIME_TABLE}
                SET
                    `执行工单编号` = NULL,
                    `工序编号` = NULL,
                    `当前任务开始时间` = NULL,
                    `运行状态` = CASE WHEN `连接状态` = 'offline' THEN '' ELSE 'idle' END,
                    `更新时间` = %s
                WHERE `设备编号` IN ({", ".join(["%s"] * len(device_id_values_for_table(device_id, DEVICE_RUNTIME_TABLE)))})
                """,
                (event_time, *device_id_values_for_table(device_id, DEVICE_RUNTIME_TABLE)),
            )
        conn.commit()


def handle_workorder_status_changed(event: dict[str, Any]) -> None:
    work_order_id = extract_work_order_id(event)
    if not work_order_id:
        return

    status = normalize_workorder_status(event.get("status"))
    event_time = parse_event_time(event.get("timestamp") or event.get("created_at"))
    finished = status in {"已完成", "失败"}
    completed = status == "已完成"
    release_device_after_workorder_event(event, status)

    with mysql_connection("order") as conn:
        with conn.cursor() as cursor:
            ensure_order_status_schema(cursor)
            order_id_col = safe_column_name(order_id_column(cursor))
            cursor.execute(
                """
                SELECT
                    `工单ID`,
                    `工单名称`,
                    `所属订单号`,
                    `工单类型`,
                    `工序数量`,
                    `工序编号`,
                    `description`
                FROM `work_orders`
                WHERE `工单ID` = %s OR `工单名称` = %s
                LIMIT 1
                """,
                (work_order_id, work_order_id),
            )
            work_order = cursor.fetchone()
            if not work_order:
                return
            if finished:
                clear_device_current_task(str(work_order.get("分配工站") or ""), event_time)

            cursor.execute(
                """
                UPDATE `work_orders`
                SET
                    `工单状态` = %s,
                    `已完成工序数量` = CASE WHEN %s THEN COALESCE(`工序数量`, 1) ELSE `已完成工序数量` END,
                    `更新时间` = %s,
                    `结束时间` = CASE WHEN %s THEN %s ELSE `结束时间` END
                WHERE `工单ID` = %s OR `工单名称` = %s
                """,
                (status, completed, event_time, finished, event_time, work_order_id, work_order_id),
            )

            order_id = str(work_order.get("所属订单号") or "")
            if completed:
                apply_work_order_completion_side_effects(work_order, event_time)
            if order_id:
                cursor.execute(
                    """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN `工单状态` = '已完成' THEN 1 ELSE 0 END) AS completed_count,
                    SUM(CASE WHEN `工单状态` = '失败' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN `工单状态` = '已接收' THEN 1 ELSE 0 END) AS received_count,
                    SUM(CASE WHEN `工单状态` = '执行中' THEN 1 ELSE 0 END) AS running_count
                    FROM `work_orders`
                    WHERE `所属订单号` = %s
                    """,
                    (order_id,),
                )
                summary = cursor.fetchone() or {}
                total_count = int(summary.get("total_count") or 0)
                completed_count = int(summary.get("completed_count") or 0)
                failed_count = int(summary.get("failed_count") or 0)
                received_count = int(summary.get("received_count") or 0)
                running_count = int(summary.get("running_count") or 0)
                if total_count > 0 and failed_count > 0:
                    cursor.execute(
                        f"""
                        UPDATE `orders`
                        SET `订单状态` = '失败', `完结时间` = %s
                        WHERE {order_id_col} = %s
                        """,
                        (event_time, order_id),
                    )
                elif total_count > 0 and completed_count == total_count:
                    cursor.execute(
                        f"""
                        UPDATE `orders`
                        SET `订单状态` = '已完成', `完结时间` = %s
                        WHERE {order_id_col} = %s
                        """,
                        (event_time, order_id),
                    )
                elif received_count > 0 or running_count > 0 or completed_count > 0:
                    cursor.execute(
                        f"""
                        UPDATE `orders`
                        SET `订单状态` = '生产中'
                        WHERE {order_id_col} = %s AND `订单状态` NOT IN ('已完成', '失败')
                        """,
                        (order_id,),
                    )
        conn.commit()

    refresh_order_rollup_status(order_id, event_time)
    sync_archived_order_to_data(order_id)
    notify_digital_twin_event(
        "work_order_status_changed",
        {
            "work_order_id": work_order_id,
            "order_id": order_id,
            "status": status,
            "updated_at": event_time.isoformat(timespec="seconds"),
        },
    )
    run_scheduler_after_workorder_event(order_id, status)


def handle_device_event(body: Any) -> None:
    event = decode_body(body)
    if not isinstance(event, dict):
        return

    event_type = str(event.get("event_type") or event.get("eventType") or "").strip()
    normalized_type = event_type.lower().replace("-", "_")
    if normalized_type == "device_heartbeat":
        event["_device_agent_event"] = True
        upsert_device_runtime(event, is_heartbeat=True)
        return
    if normalized_type == "device_status_changed":
        event["_device_agent_event"] = True
        upsert_device_runtime(event, is_heartbeat=False)
        return
    if normalized_type in {
        "workorder_status_changed",
        "work_order_status_changed",
        "workorder_completed",
        "work_order_completed",
        "workorder_finished",
        "work_order_finished",
        "workorder_done",
        "work_order_done",
    }:
        if "status" not in event and normalized_type not in {"workorder_status_changed", "work_order_status_changed"}:
            event["status"] = "completed"
        handle_workorder_status_changed(event)


def handle_device_event_safely(body: Any) -> None:
    try:
        handle_device_event(body)
    except Exception as exc:
        print(f"device event update failed: {exc}", file=sys.stderr, flush=True)


def parse_mqadmin_bodies(output: str) -> list[tuple[str, str]]:
    bodies: list[tuple[str, str]] = []
    current_msg_id = ""
    for line in output.splitlines():
        msg_id_match = re.search(r"MSGID:\s+(\S+)", line)
        if msg_id_match:
            current_msg_id = msg_id_match.group(1)
        if "BODY:" not in line:
            continue
        bodies.append((current_msg_id, line.rsplit("BODY:", 1)[1].strip()))
    return bodies


def mqadmin_timestamp(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d#%H:%M:%S:%f")[:23]


def rocketmq_home() -> Path:
    return Path(
        os.environ.get("ROCKETMQ_HOME")
        or ROOT_DIR / "rocketmq" / "rocketmq-all-5.3.2-bin-release"
    )


def ensure_rocketmq_topic(mqadmin: Path, env: dict[str, str], config: dict[str, str]) -> None:
    command = [
        str(mqadmin),
        "updateTopic",
        "-n",
        config["namesrv_addr"],
        "-c",
        config["topic_cluster"],
        "-t",
        config["topic"],
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            env=env,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print(f"RocketMQ topic ensure timed out for {config['topic']}", file=sys.stderr, flush=True)
        return

    if completed.returncode != 0:
        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        print(
            f"RocketMQ topic ensure skipped for {config['topic']}: {error or output or completed.returncode}",
            file=sys.stderr,
            flush=True,
        )


def run_windows_consumer() -> None:
    config = env_config()
    home = rocketmq_home()
    mqadmin = home / "bin" / "mqadmin.cmd"
    if not mqadmin.exists():
        raise RuntimeError(f"mqadmin.cmd not found: {mqadmin}")

    env = os.environ.copy()
    env["ROCKETMQ_HOME"] = str(home)
    interval = max(1, int(config["poll_interval_seconds"]))
    seen_msg_ids: set[str] = set()
    begin_timestamp_ms = int(time.time() * 1000)
    ensure_rocketmq_topic(mqadmin, env, config)
    cleanup_archived_live_orders()

    try:
        while True:
            end_timestamp_ms = int(time.time() * 1000)
            command = [
                str(mqadmin),
                "consumeMessage",
                "-n",
                config["namesrv_addr"],
                "-t",
                config["topic"],
                "-g",
                config["consumer_group"],
                "-c",
                config["batch_size"],
                "-s",
                mqadmin_timestamp(begin_timestamp_ms),
                "-e",
                mqadmin_timestamp(end_timestamp_ms),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    encoding=locale.getpreferredencoding(False),
                    errors="replace",
                    env=env,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                print(
                    f"mqadmin consumeMessage timed out for topic {config['topic']}; retrying",
                    file=sys.stderr,
                    flush=True,
                )
                begin_timestamp_ms = end_timestamp_ms + 1
                time.sleep(interval)
                continue
            output = (completed.stdout or "").strip()
            error = (completed.stderr or "").strip()
            bodies = parse_mqadmin_bodies(output) if output else []
            if "No topic route info" in error or "Can not find Message Queue" in error:
                ensure_rocketmq_topic(mqadmin, env, config)
            if bodies:
                for msg_id, body in bodies:
                    if msg_id and msg_id in seen_msg_ids:
                        continue
                    if msg_id:
                        seen_msg_ids.add(msg_id)
                    handle_device_event_safely(body)
            if error:
                print(error, file=sys.stderr, flush=True)
            if completed.returncode != 0:
                print(f"mqadmin consumeMessage exited with code {completed.returncode}", file=sys.stderr, flush=True)
            try:
                mark_stale_device_heartbeats()
            except Exception as exc:
                print(f"device heartbeat stale check skipped: {exc}", file=sys.stderr, flush=True)
            run_scheduler_queue_tick()
            if len(bodies) >= int(config["batch_size"]):
                print(
                    f"mqadmin returned full batch ({len(bodies)}); retrying same time window",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                begin_timestamp_ms = end_timestamp_ms + 1
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def run_python_client_consumer() -> None:
    try:
        from rocketmq.client import ConsumeStatus, PushConsumer
    except ImportError as exc:
        raise RuntimeError("rocketmq-client-python is not installed") from exc

    config = env_config()
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    def callback(message: Any) -> Any:
        body = getattr(message, "body", b"")
        handle_device_event_safely(body)
        return ConsumeStatus.CONSUME_SUCCESS

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    consumer = PushConsumer(config["consumer_group"])
    consumer.set_name_server_address(config["namesrv_addr"])
    consumer.subscribe(config["topic"], callback, config["expression"])
    consumer.start()
    cleanup_archived_live_orders()

    try:
        while running:
            mark_stale_device_heartbeats()
            run_scheduler_queue_tick()
            time.sleep(1)
    finally:
        consumer.shutdown()


def main() -> None:
    if os.name == "nt":
        run_windows_consumer()
    else:
        run_python_client_consumer()


if __name__ == "__main__":
    main()
