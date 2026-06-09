from __future__ import annotations

import os
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv
from neo4j import GraphDatabase

from .reasoning_service import run_reasoning


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env", override=False)


ENTITY_CONFIG: dict[str, dict[str, Any]] = {
    "device": {
        "database": "device",
        "include_keywords": ("device", "workstation", "station", "agv"),
        "exclude_keywords": (),
        "id_keys": ("设备ID", "设备编号", "AGV编号", "工站编号", "工作站编号", "device_id", "deviceId", "deviceCode", "device_code", "workstation_id", "workstationId", "station_id", "stationId", "agv_id", "agvId", "code", "id"),
        "label_keys": ("设备名称", "设备名", "AGV名称", "小车名称", "工站名称", "工作站名称", "device_name", "deviceName", "workstation_name", "workstationName", "station_name", "stationName", "agv_name", "agvName", "name"),
        "subtitle_keys": ("设备编号", "设备类型", "类型", "device_code", "deviceCode", "workstation_code", "workstationCode", "station_code", "stationCode", "agv_code", "agvCode", "code", "type", "device_type", "deviceType"),
        "status_keys": ("运行状态", "设备状态", "启动状态", "状态", "工单状态", "订单状态", "运输状态", "任务状态", "status", "state", "runtime_status", "runtimeStatus", "work_status", "workStatus", "transport_status", "transportStatus"),
    },
    "material": {
        "database": "store",
        "include_keywords": ("material", "inventory", "store"),
        "exclude_keywords": (),
        "id_keys": ("物料编号", "物料ID", "物料编码", "material_id", "materialId", "material_code", "materialCode", "id", "code"),
        "label_keys": ("物料名称", "物料名", "material_name", "materialName", "name"),
        "subtitle_keys": ("库位", "库位编号", "仓位", "location", "slot", "material_location"),
        "status_keys": ("运行状态", "设备状态", "启动状态", "状态", "工单状态", "订单状态", "运输状态", "任务状态", "status", "state", "runtime_status", "runtimeStatus", "work_status", "workStatus", "transport_status", "transportStatus"),
    },
    "order": {
        "database": "order",
        "include_keywords": ("order",),
        "exclude_keywords": ("work", "backup", "history", "archive", "scheduler", "queue"),
        "id_keys": ("订单编号", "订单ID", "order_id", "orderId", "id", "code"),
        "label_keys": ("订单名称", "产品名称", "客户名称", "order_name", "orderName", "name", "customer_name", "product_name"),
        "subtitle_keys": ("产品名称", "客户名称", "product_name", "productName", "customer_name"),
        "status_keys": ("运行状态", "设备状态", "启动状态", "状态", "工单状态", "订单状态", "运输状态", "任务状态", "status", "state", "runtime_status", "runtimeStatus", "work_status", "workStatus", "transport_status", "transportStatus"),
    },
    "work_order": {
        "database": "order",
        "include_keywords": ("work_order", "workorder", "work order", "task"),
        "exclude_keywords": ("backup", "history", "archive"),
        "id_keys": ("工单编号", "工单ID", "任务编号", "work_order_id", "workOrderId", "id", "task_id", "taskId", "code"),
        "label_keys": ("工单名称", "任务名称", "阶段", "work_order_name", "workOrderName", "name", "title"),
        "subtitle_keys": ("工序名称", "所属订单", "订单编号", "process_name", "source_order_id", "order_id"),
        "status_keys": ("运行状态", "设备状态", "启动状态", "状态", "工单状态", "订单状态", "运输状态", "任务状态", "status", "state", "runtime_status", "runtimeStatus", "work_status", "workStatus", "transport_status", "transportStatus"),
    },
}

DEVICE_RUNTIME_TABLE = "device_event_runtime"

NEO4J_CANONICAL_LABELS = [
    "Class",
    "Product",
    "Craft",
    "Process",
    "ProcessInstance",
    "AssemblyStep",
    "Device",
    "Material",
    "Part",
]

CANONICAL_CLASS_RELATIONS = [
    ("User", "Order", "create"),
    ("Order", "Work_order", "split into"),
    ("Work_order", "Workstation", "assigned to"),
    ("Order", "Product", "produces"),
    ("Product", "Process", "has_step"),
    ("Workstation", "Craft", "can_execute"),
    ("Warehouse", "Material", "stores"),
    ("AGV", "Material", "transports"),
    ("Material", "Workstation", "supplied to"),
]

TOPOLOGY_CLASS_NODES: list[dict[str, Any]] = [
    {"id": "user", "label": "User", "entityType": "class", "tone": "tone-violet", "x": 6, "y": 14, "moduleType": ""},
    {"id": "order", "label": "Order", "entityType": "order", "tone": "tone-pink", "x": 22, "y": 14, "moduleType": "order"},
    {"id": "work-order", "label": "Work_order", "entityType": "work_order", "tone": "tone-violet", "x": 43, "y": 14, "moduleType": "work_order"},
    {"id": "workstation", "label": "Workstation", "entityType": "device", "tone": "tone-cyan", "x": 72, "y": 14, "moduleType": "device"},
    {"id": "product", "label": "Product", "entityType": "product", "tone": "tone-pink", "x": 22, "y": 43, "moduleType": "product"},
    {"id": "craft", "label": "Craft", "entityType": "craft", "tone": "tone-violet", "x": 43, "y": 43, "moduleType": "craft"},
    {"id": "process", "label": "Process", "entityType": "process", "tone": "tone-cyan", "x": 72, "y": 43, "moduleType": "process"},
    {"id": "warehouse", "label": "Warehouse", "entityType": "device", "tone": "tone-cyan", "x": 43, "y": 72, "moduleType": "device"},
    {"id": "material", "label": "Material", "entityType": "material", "tone": "tone-violet", "x": 72, "y": 72, "moduleType": "material"},
    {"id": "agv", "label": "AGV", "entityType": "device", "tone": "tone-pink", "x": 22, "y": 84, "moduleType": "device"},
]

TOPOLOGY_CLASS_EDGES: list[dict[str, str]] = [
    {"source": "user", "target": "order", "label": "create", "type": "CREATE"},
    {"source": "order", "target": "work-order", "label": "split into", "type": "SPLIT_INTO"},
    {"source": "work-order", "target": "workstation", "label": "assigned to", "type": "ASSIGNED_TO"},
    {"source": "order", "target": "product", "label": "produces", "type": "PRODUCES"},
    {"source": "product", "target": "process", "label": "has_step", "type": "HAS_STEP"},
    {"source": "workstation", "target": "craft", "label": "can_execute", "type": "CAN_EXECUTE"},
    {"source": "warehouse", "target": "material", "label": "stores", "type": "STORES"},
    {"source": "agv", "target": "material", "label": "transports", "type": "TRANSPORTS"},
    {"source": "material", "target": "workstation", "label": "supplied to", "type": "SUPPLIED_TO"},
]

def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def json_safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, list):
        return [json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    return value


def json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_safe_value(value) for key, value in row.items()}


def clean_value(value: Any) -> Any:
    return json_safe_value(value)


def first_present(data: dict[str, Any], keys: tuple[str, ...] | list[str]) -> Any:
    if not isinstance(data, dict):
        return None
    normalized = {normalize_text(key): key for key in data.keys()}
    for key in keys:
        actual = normalized.get(normalize_text(key))
        if actual is None:
            continue
        value = data.get(actual)
        if value not in (None, ""):
            return value
    return None


def mysql_connection(database: str):
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def mysql_server_connection():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


DATA_DATABASE = os.environ.get("MYSQL_DATA_DATABASE", "Data")
AGV_DATABASE = os.environ.get("MYSQL_AGV_DATABASE", "AGV")


DATA_SCHEMA_SQL = [
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
        description VARCHAR(255) DEFAULT '',
        INDEX idx_order_history_order (order_id),
        INDEX idx_order_history_work_order (work_order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS device_run_history (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        device_id VARCHAR(64) NOT NULL,
        device_name VARCHAR(128) NOT NULL,
        device_type VARCHAR(64) DEFAULT '',
        work_order_id VARCHAR(64) NOT NULL,
        work_order_name VARCHAR(128) DEFAULT '',
        run_start_time DATETIME NOT NULL,
        run_end_time DATETIME NOT NULL,
        run_status ENUM('已创建','已下发','已接收','执行中','已完成','失败') NOT NULL DEFAULT '已完成',
        avg_load_percent DECIMAL(5,2) DEFAULT 0,
        peak_load_percent DECIMAL(5,2) DEFAULT 0,
        load_curve_json JSON NULL,
        operator_name VARCHAR(64) DEFAULT '',
        remark VARCHAR(255) DEFAULT '',
        INDEX idx_device_run_device (device_id),
        INDEX idx_device_run_work_order (work_order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS quality_trace_history (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        inspection_id VARCHAR(64) NOT NULL,
        product_id VARCHAR(64) NOT NULL,
        product_name VARCHAR(128) NOT NULL,
        work_order_id VARCHAR(64) NOT NULL,
        process_name VARCHAR(128) NOT NULL DEFAULT '质检',
        inspection_device_id VARCHAR(64) DEFAULT '',
        inspection_device_name VARCHAR(128) DEFAULT '',
        inspection_start_time DATETIME NOT NULL,
        inspection_end_time DATETIME NOT NULL,
        inspection_result ENUM('合格','不合格','已取消') NOT NULL DEFAULT '合格',
        label_product_code VARCHAR(128) DEFAULT '',
        material_batch_ids VARCHAR(255) DEFAULT '',
        part_codes VARCHAR(255) DEFAULT '',
        inspector_name VARCHAR(64) DEFAULT '',
        trace_note VARCHAR(255) DEFAULT '',
        INDEX idx_quality_product (product_id),
        INDEX idx_quality_label (label_product_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS reasoning_results (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        reasoning_id VARCHAR(64) NOT NULL,
        trigger_source VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'ok',
        rule_count INT NOT NULL DEFAULT 0,
        violation_count INT NOT NULL DEFAULT 0,
        summary_json JSON NULL,
        result_json JSON NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_reasoning_results_reasoning_id (reasoning_id),
        INDEX idx_reasoning_results_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


DATA_SAMPLE_SQL = [
    (
        "order_work_order_history",
        """
        INSERT INTO order_work_order_history (
            order_id, order_name, product_id, product_name, customer_name, order_status,
            order_start_time, order_end_time, work_order_id, work_order_name, process_name,
            assigned_device_id, assigned_device_name, work_order_status,
            work_order_start_time, work_order_end_time, material_batch_ids, description
        ) VALUES
        ('ORD-20260514-001', '立方堆生产订单', 'PD-CUBE-STACK', '立方堆', '示例客户A', '已完成',
         '2026-05-14 08:00:00', '2026-05-14 10:42:00', 'WO-20260514-001-01', '堆积工序1', '堆积',
         'SCARA-WS-01', 'scara工作站1', '已完成', '2026-05-14 08:10:00', '2026-05-14 09:05:00',
         'MAT-CUBE-001,MAT-CUBE-002', '使用立方体1与立方体2生成堆积体1'),
        ('ORD-20260514-001', '立方堆生产订单', 'PD-CUBE-STACK', '立方堆', '示例客户A', '已完成',
         '2026-05-14 08:00:00', '2026-05-14 10:42:00', 'WO-20260514-001-02', '堆积工序2', '堆积',
         'COOP-WS-01', '协作加工工作站', '已完成', '2026-05-14 09:12:00', '2026-05-14 10:10:00',
         'MAT-CUBE-003,PART-STACK-001', '使用立方体3与堆积体1完成产品'),
        ('ORD-20260514-002', '贴标追溯订单', 'PD-LABEL-DEMO', '贴标示例产品', '示例客户B', '失败',
         '2026-05-14 11:00:00', '2026-05-14 11:35:00', 'WO-20260514-002-01', '质检工序', '质检',
         'QC-WS-01', '质检工作站', '失败', '2026-05-14 11:05:00', '2026-05-14 11:35:00',
         'MAT-LABEL-001', '质检前取消')
        """,
    ),
    (
        "device_run_history",
        """
        INSERT INTO device_run_history (
            device_id, device_name, device_type, work_order_id, work_order_name,
            run_start_time, run_end_time, run_status, avg_load_percent, peak_load_percent,
            load_curve_json, operator_name, remark
        ) VALUES
        ('SCARA-WS-01', 'scara工作站1', 'Workstation', 'WO-20260514-001-01', '堆积工序1',
         '2026-05-14 08:10:00', '2026-05-14 09:05:00', '已完成', 58.40, 82.10,
         JSON_ARRAY(22, 48, 63, 75, 82, 60, 41), 'operator-a', '负载曲线为示例模块数据'),
        ('COOP-WS-01', '协作加工工作站', 'Workstation', 'WO-20260514-001-02', '堆积工序2',
         '2026-05-14 09:12:00', '2026-05-14 10:10:00', '已完成', 61.20, 88.60,
         JSON_ARRAY(28, 45, 66, 88, 77, 52, 34), 'operator-b', '负载曲线为示例模块数据'),
        ('QC-WS-01', '质检工作站', 'Quality', 'WO-20260514-002-01', '质检工序',
         '2026-05-14 11:05:00', '2026-05-14 11:35:00', '失败', 31.00, 45.00,
         JSON_ARRAY(10, 22, 45, 31, 18), 'operator-qc', '取消工单')
        """,
    ),
    (
        "quality_trace_history",
        """
        INSERT INTO quality_trace_history (
            inspection_id, product_id, product_name, work_order_id, process_name,
            inspection_device_id, inspection_device_name, inspection_start_time, inspection_end_time,
            inspection_result, label_product_code, material_batch_ids, part_codes, inspector_name, trace_note
        ) VALUES
        ('QC-20260514-001', 'PD-CUBE-STACK', '立方堆', 'WO-20260514-001-QC', '质检',
         'QC-WS-01', '质检工作站', '2026-05-14 10:12:00', '2026-05-14 10:28:00',
         '合格', 'LBL-PD-CUBE-STACK-0001', 'MAT-CUBE-001,MAT-CUBE-002,MAT-CUBE-003', 'PART-STACK-001', 'qc-a',
         '质检合格后进入贴标工序'),
        ('QC-20260514-002', 'PD-LABEL-DEMO', '贴标示例产品', 'WO-20260514-002-01', '质检',
         'QC-WS-01', '质检工作站', '2026-05-14 11:05:00', '2026-05-14 11:35:00',
         '已取消', '', 'MAT-LABEL-001', '', 'qc-a', '取消后未贴标')
        """,
    ),
]


AGV_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS tasks (
        `运输编号` VARCHAR(64) PRIMARY KEY,
        `任务类型` ENUM('仓库到工站','工站间转运','工站到仓库') NOT NULL,
        `任务状态` ENUM('等待中','运输中','已完成','失败','已取消') NOT NULL DEFAULT '等待中',
        `起始工站/仓库` VARCHAR(128) NOT NULL,
        `目标工站/仓库` VARCHAR(128) NOT NULL,
        `创建时间` DATETIME NOT NULL,
        `实际开始时间` DATETIME NULL,
        `结束时间` DATETIME NULL,
        `AGV编号` VARCHAR(64) DEFAULT 'AGV-01',
        `订单编号` VARCHAR(64) DEFAULT '',
        `工单编号` VARCHAR(64) DEFAULT '',
        INDEX idx_agv_task_status (`任务状态`),
        INDEX idx_agv_task_work_order (`工单编号`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


AGV_SAMPLE_SQL = [
    (
        "tasks",
        """
        INSERT INTO tasks (
            `运输编号`, `任务类型`, `任务状态`, `起始工站/仓库`, `目标工站/仓库`,
            `创建时间`, `实际开始时间`, `结束时间`, `AGV编号`, `订单编号`, `工单编号`
        ) VALUES
        ('AGV-TR-20260514-001', '仓库到工站', '已完成', '立体仓库', 'scara工作站1',
         '2026-05-14 08:02:00', '2026-05-14 08:03:00', '2026-05-14 08:09:00',
         'AGV-01', 'ORD-20260514-001', 'WO-20260514-001-01'),
        ('AGV-TR-20260514-002', '工站间转运', '已完成', 'scara工作站1', '协作加工工作站',
         '2026-05-14 09:05:30', '2026-05-14 09:06:00', '2026-05-14 09:11:00',
         'AGV-01', 'ORD-20260514-001', 'WO-20260514-001-02'),
        ('AGV-TR-20260514-003', '工站到仓库', '运输中', '协作加工工作站', '成品仓库',
         '2026-05-14 10:10:30', '2026-05-14 10:11:00', NULL,
         'AGV-02', 'ORD-20260514-001', 'WO-20260514-001-02')
        """,
    ),
]


def build_agv_task_seed_rows(order_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in order_rows:
        order_id = str(row.get("order_id") or "")
        if order_id:
            orders[order_id].append(row)

    tasks: list[dict[str, Any]] = []
    for order_id, rows in orders.items():
        rows = sorted(rows, key=lambda item: str(item.get("work_order_start_time") or ""))
        if not rows:
            continue

        for index, row in enumerate(rows):
            station = str(row.get("assigned_device_name") or row.get("assigned_device_id") or "目标工站")
            work_status = str(row.get("work_order_status") or "")
            previous_station = (
                str(rows[index - 1].get("assigned_device_name") or rows[index - 1].get("assigned_device_id") or "上一工站")
                if index > 0
                else "立体仓库"
            )
            task_type = "仓库到工站" if index == 0 else "工站间转运"
            tasks.append(
                {
                    "transport_id": f"AGV-TR-{order_id}-{index + 1:02d}",
                    "task_type": task_type,
                    "status": "失败" if work_status == "失败" else "运输中" if work_status == "执行中" else "已完成",
                    "source": previous_station,
                    "target": station,
                    "created_at": row.get("work_order_start_time") or row.get("order_start_time"),
                    "started_at": row.get("work_order_start_time"),
                    "ended_at": row.get("work_order_end_time") if str(row.get("work_order_status") or "") == "已完成" else None,
                    "agv_id": f"AGV-{(index % 2) + 1:02d}",
                    "order_id": order_id,
                    "work_order_id": row.get("work_order_id") or "",
                }
            )

        last = rows[-1]
        order_status = str(last.get("order_status") or "")
        last_station = str(last.get("assigned_device_name") or last.get("assigned_device_id") or "末工站")
        tasks.append(
            {
                "transport_id": f"AGV-TR-{order_id}-OUT",
                "task_type": "工站到仓库",
                "status": "失败" if order_status == "失败" else "运输中" if order_status == "执行中" else "已完成",
                "source": last_station,
                "target": "成品仓库",
                "created_at": last.get("work_order_end_time") or last.get("order_end_time"),
                "started_at": last.get("work_order_end_time"),
                "ended_at": last.get("order_end_time") if str(last.get("order_status") or "") == "已完成" else None,
                "agv_id": "AGV-02",
                "order_id": order_id,
                "work_order_id": last.get("work_order_id") or "",
            }
        )

    return tasks


def insert_agv_task_seed_rows(cursor, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cursor.executemany(
        """
        INSERT INTO tasks (
            `运输编号`, `任务类型`, `任务状态`, `起始工站/仓库`, `目标工站/仓库`,
            `创建时间`, `实际开始时间`, `结束时间`, `AGV编号`, `订单编号`, `工单编号`
        ) VALUES (
            %(transport_id)s, %(task_type)s, %(status)s, %(source)s, %(target)s,
            %(created_at)s, %(started_at)s, %(ended_at)s, %(agv_id)s, %(order_id)s, %(work_order_id)s
        )
        """,
        rows,
    )


def ensure_data_schema() -> None:
    database = DATA_DATABASE.replace("`", "``")
    with mysql_server_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    with mysql_connection(DATA_DATABASE) as conn:
        with conn.cursor() as cursor:
            for statement in DATA_SCHEMA_SQL:
                cursor.execute(statement)
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'order_work_order_history'
                """
            )
            order_history_columns = {str(row.get("COLUMN_NAME") or "") for row in cursor.fetchall()}
            if "description" not in order_history_columns:
                cursor.execute("ALTER TABLE order_work_order_history ADD COLUMN description VARCHAR(255) DEFAULT ''")
            for table_name, statement in DATA_SAMPLE_SQL:
                cursor.execute(f"SELECT COUNT(*) AS count FROM `{table_name}`")
                count = int((cursor.fetchone() or {}).get("count") or 0)
                if count == 0:
                    cursor.execute(statement)
        conn.commit()


def ensure_agv_schema() -> None:
    database = AGV_DATABASE.replace("`", "``")
    with mysql_server_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    with mysql_connection(AGV_DATABASE) as conn:
        with conn.cursor() as cursor:
            for statement in AGV_SCHEMA_SQL:
                cursor.execute(statement)
            cursor.execute(
                """
                DELETE FROM `tasks`
                WHERE `运输编号` IN (
                    'AGV-TR-20260514-001',
                    'AGV-TR-20260514-002',
                    'AGV-TR-20260514-003'
                )
                """
            )
            cursor.execute("SELECT COUNT(*) AS count FROM `tasks`")
            count = int((cursor.fetchone() or {}).get("count") or 0)
            if count == 0:
                try:
                    ensure_data_schema()
                    insert_agv_task_seed_rows(cursor, build_agv_task_seed_rows(read_mysql_table(DATA_DATABASE, "order_work_order_history", limit=200)))
                except Exception:
                    for _, statement in AGV_SAMPLE_SQL:
                        cursor.execute(statement)
        conn.commit()


def read_data_table(table_name: str, limit: int = 200) -> list[dict[str, Any]]:
    ensure_data_schema()
    return read_mysql_table(DATA_DATABASE, table_name, limit=limit)


def read_reasoning_results(limit: int = 50) -> list[dict[str, Any]]:
    ensure_data_schema()
    with mysql_connection(DATA_DATABASE) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM `reasoning_results` ORDER BY created_at DESC, id DESC LIMIT %s", (limit,))
            return [json_safe_row(row) for row in cursor.fetchall()]


def read_agv_tasks(limit: int = 200) -> list[dict[str, Any]]:
    ensure_agv_schema()
    return read_mysql_table(AGV_DATABASE, "tasks", limit=limit)


def is_archived_order_status(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(token in text for token in ("已完成", "失败", "已取消", "完成", "取消", "complete", "done", "finished", "failed", "failure", "cancel"))


def archived_order_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    archived_order_ids = {
        str(row.get("order_id") or "")
        for row in rows
        if is_archived_order_status(row.get("order_status"))
    }
    return [row for row in rows if str(row.get("order_id") or "") in archived_order_ids]


def build_order_history_tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    orders: dict[str, dict[str, Any]] = {}
    for row in rows:
        order_id = str(row.get("order_id") or "")
        order = orders.setdefault(
            order_id,
            {
                "order_id": order_id,
                "order_name": row.get("order_name"),
                "product_id": row.get("product_id"),
                "product_name": row.get("product_name"),
                "customer_name": row.get("customer_name"),
                "status": row.get("order_status"),
                "start_time": row.get("order_start_time"),
                "end_time": row.get("order_end_time"),
                "work_orders": [],
            },
        )
        order["work_orders"].append(
            {
                "work_order_id": row.get("work_order_id"),
                "work_order_name": row.get("work_order_name"),
                "process_name": row.get("process_name"),
                "assigned_device_id": row.get("assigned_device_id"),
                "assigned_device_name": row.get("assigned_device_name"),
                "status": row.get("work_order_status"),
                "start_time": row.get("work_order_start_time"),
                "end_time": row.get("work_order_end_time"),
                "material_batch_ids": row.get("material_batch_ids"),
            "description": row.get("description") or row.get("remark"),
            }
        )
    return list(orders.values())


def safe_device_catalog() -> list[dict[str, Any]]:
    catalogs: list[dict[str, Any]] = []
    try:
        catalogs.extend(merge_device_runtime_status(build_mysql_catalog("device", limit=200)))
    except Exception:
        pass
    try:
        catalogs.extend(build_neo4j_catalog("device", limit=100))
    except Exception:
        pass

    return merge_device_catalog_items(catalogs)


def production_device_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    code = device_display_code(item)
    if code:
        match = re.search(r"\d+", code)
        if match:
            return (int(match.group(0)), normalize_text(code))
    label = normalize_text(device_display_name(item) or item.get("label") or "")
    if "立体" in label or "仓库" in label or "storage" in label:
        return (1, label)
    if "协作" in label or "cobot" in label or "processing" in label:
        return (2, label)
    match = re.search(r"\d+", label)
    if match:
        return (int(match.group(0)) + 2, label)
    return (999, label)


def is_agv_catalog_item(item: dict[str, Any]) -> bool:
    text = normalize_text(" ".join(str(value) for value in (
        item.get("id"),
        item.get("label"),
        item.get("subtitle"),
        " ".join(str(source) for source in (item.get("source") or [])),
        json.dumps(item.get("properties") or {}, ensure_ascii=False),
    )))
    return "agv" in text or "小车" in text


def normalized_device_name_key(item: dict[str, Any]) -> str:
    text = normalize_text(device_display_name(item) or item.get("label") or "")
    for token in ("自动化", "加工", "机器人", "用于", "设备"):
        text = text.replace(token, "")
    return text


def merge_device_catalog_pair(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    source = [primary.get("source"), secondary.get("source")]
    display_name = device_display_name(primary) or device_display_name(secondary) or str(primary.get("label") or secondary.get("label") or "Device")
    display_code = device_display_code(primary) or device_display_code(secondary) or str(primary.get("subtitle") or secondary.get("subtitle") or "")
    return {
        **secondary,
        **primary,
        "label": display_name,
        "subtitle": display_code,
        "summary": " / ".join(part for part in (primary.get("status") or secondary.get("status") or "", display_code) if part),
        "source": list(dict.fromkeys([value for value in source for value in (value if isinstance(value, list) else [value]) if value])),
        "properties": {**(secondary.get("properties") or {}), **(primary.get("properties") or {})},
        "runtime": {**(secondary.get("runtime") or {}), **(primary.get("runtime") or {})},
    }


def merge_device_catalog_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    coded_production_indexes: list[int] = []
    uncoded_production_items: list[dict[str, Any]] = []

    for item in items:
        code = normalize_text(device_display_code(item))
        label_key = normalized_device_name_key(item)
        if not label_key and not code:
            continue
        if is_agv_catalog_item(item):
            key = device_catalog_identity_key(item)
            existing_index = next((index for index, existing in enumerate(merged) if is_agv_catalog_item(existing) and device_catalog_identity_key(existing) == key), None)
            if existing_index is None:
                merged.append(item)
            else:
                merged[existing_index] = merge_device_catalog_pair(merged[existing_index], item)
            continue
        if code:
            existing_index = next((index for index, existing in enumerate(merged) if normalize_text(device_display_code(existing)) == code), None)
            if existing_index is None:
                coded_production_indexes.append(len(merged))
                merged.append(item)
            else:
                merged[existing_index] = merge_device_catalog_pair(merged[existing_index], item)
            continue
        uncoded_production_items.append(item)

    coded_production_indexes.sort(key=lambda index: production_device_sort_key(merged[index]))
    uncoded_production_items.sort(key=production_device_sort_key)

    for item in uncoded_production_items:
        item_key = normalized_device_name_key(item)
        match_index = next(
            (
                index
                for index in coded_production_indexes
                if item_key
                and (
                    item_key in normalized_device_name_key(merged[index])
                    or normalized_device_name_key(merged[index]) in item_key
                )
            ),
            None,
        )
        if match_index is None and coded_production_indexes:
            match_index = coded_production_indexes.pop(0)
        if match_index is None:
            merged.append(item)
        else:
            merged[match_index] = merge_device_catalog_pair(merged[match_index], item)

    return merged


def persist_reasoning_result(inference: dict[str, Any], *, trigger_source: str = "api.digital_twin.data") -> dict[str, Any] | None:
    reasoning_id = f"RSN-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    summary = inference.get("summary") or {}
    violations = inference.get("violations") or []
    rules = inference.get("rules") or []
    status = "blocked" if violations else "ok"
    row = {
        "reasoning_id": reasoning_id,
        "trigger_source": trigger_source,
        "status": status,
        "rule_count": len(rules),
        "violation_count": len(violations),
        "summary_json": json.dumps(json_safe_value(summary), ensure_ascii=False),
        "result_json": json.dumps(json_safe_value(inference), ensure_ascii=False),
    }
    try:
        with mysql_connection(DATA_DATABASE) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reasoning_results (
                        reasoning_id, trigger_source, status, rule_count, violation_count,
                        summary_json, result_json
                    ) VALUES (
                        %(reasoning_id)s, %(trigger_source)s, %(status)s, %(rule_count)s,
                        %(violation_count)s, %(summary_json)s, %(result_json)s
                    )
                    """,
                    row,
                )
            conn.commit()
        return row
    except Exception:
        return None


def get_data_payload() -> dict[str, Any]:
    order_rows = read_data_table("order_work_order_history")
    archived_order_rows = archived_order_history_rows(order_rows)
    raw_device_rows = read_data_table("device_run_history")
    quality_rows = read_data_table("quality_trace_history")
    agv_task_rows = read_agv_tasks()
    reasoning = run_reasoning(
        order_rows=order_rows,
        device_history_rows=raw_device_rows,
        quality_rows=quality_rows,
        agv_task_rows=agv_task_rows,
        device_catalog=safe_device_catalog(),
    )
    device_rows = reasoning["deviceHistory"]
    invalid_device_rows = reasoning["invalidDeviceHistory"]
    inference = reasoning["inference"]
    persisted_reasoning = persist_reasoning_result(inference)
    reasoning_rows = read_reasoning_results(limit=50)
    return {
        "ok": True,
        "database": DATA_DATABASE,
        "tables": {
            "order_work_order_history": order_rows,
            "device_run_history": device_rows,
            "quality_trace_history": quality_rows,
            "agv_tasks": agv_task_rows,
            "reasoning_results": reasoning_rows,
        },
        "orderTree": build_order_history_tree(archived_order_rows),
        "deviceHistory": device_rows,
        "qualityTrace": quality_rows,
        "agvTasks": agv_task_rows,
        "reasoningResults": reasoning_rows,
        "loadCurveModule": {
            "title": "设备负载曲线",
            "status": "module-only",
            "description": "当前为前端展示模块，暂未接入实时负载数据源。",
        },
        "summary": {
            "orderCount": len({row.get("order_id") for row in order_rows}),
            "workOrderCount": len(order_rows),
            "archivedOrderCount": len({row.get("order_id") for row in archived_order_rows}),
            "archivedWorkOrderCount": len(archived_order_rows),
            "deviceRunCount": len(device_rows),
            "invalidDeviceRunCount": len(invalid_device_rows),
            "qualityTraceCount": len(quality_rows),
            "agvTaskCount": len(agv_task_rows),
        },
        "inference": inference,
        "persistedReasoning": persisted_reasoning,
        "warnings": [item["type"] for item in inference["violations"]],
    }


def get_agv_tasks_payload() -> dict[str, Any]:
    tasks = read_agv_tasks()
    return {
        "ok": True,
        "database": AGV_DATABASE,
        "table": "tasks",
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "waiting": len([row for row in tasks if row.get("任务状态") == "等待中"]),
            "transporting": len([row for row in tasks if row.get("任务状态") == "运输中"]),
            "completed": len([row for row in tasks if row.get("任务状态") == "已完成"]),
            "failed": len([row for row in tasks if row.get("任务状态") == "失败"]),
            "cancelled": len([row for row in tasks if row.get("任务状态") == "已取消"]),
        },
    }


def neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    return GraphDatabase.driver(uri, auth=(username, password))


def run_neo4j_read(query: str, **params: Any) -> list[dict[str, Any]]:
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = neo4j_driver()
    try:
        with driver.session(database=database) as session:
            result = session.run(query, **params)
            return [dict(record) for record in result]
    finally:
        driver.close()


def run_neo4j_write(query: str, **params: Any) -> None:
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = neo4j_driver()
    try:
        with driver.session(database=database) as session:
            session.run(query, **params).consume()
    finally:
        driver.close()


def ensure_topology_classes_in_neo4j() -> None:
    """Store the frontend Class topology as Neo4j :Class nodes for Agent reads."""
    node_comment = "Ontology Class 部分：该节点来自前端拓扑图，并对应 Neo4j 中可查询的产线 Class 拓扑。"
    relation_comment = "Ontology Class 部分：该关系来自前端拓扑图，用于描述 Class 之间的拓扑关系。"
    nodes = [
        {
            **node,
            "comment": node_comment,
            "ontology": "smart-production-ontology",
            "source": "frontend-class-topology",
        }
        for node in TOPOLOGY_CLASS_NODES
    ]
    run_neo4j_write(
        """
        MATCH (class:Class {ontology: $ontology, source: $source})
        WHERE NOT class.id IN $node_ids
        DETACH DELETE class
        """,
        ontology="smart-production-ontology",
        source="frontend-class-topology",
        node_ids=[node["id"] for node in nodes],
    )
    run_neo4j_write(
        """
        UNWIND $nodes AS node
        MERGE (class:Class {ontology: node.ontology, id: node.id})
        SET class.name = node.label,
            class.label = node.label,
            class.entityType = node.entityType,
            class.moduleType = node.moduleType,
            class.tone = node.tone,
            class.x = node.x,
            class.y = node.y,
            class.source = node.source,
            class.comment = node.comment,
            class.updatedAt = datetime()
        """,
        nodes=nodes,
    )
    run_neo4j_write(
        """
        MATCH (class:Class {ontology: $ontology, source: $source})-[relation]->(:Class {ontology: $ontology, source: $source})
        DELETE relation
        """,
        ontology="smart-production-ontology",
        source="frontend-class-topology",
    )
    for edge in TOPOLOGY_CLASS_EDGES:
        # Relationship types are fixed by TOPOLOGY_CLASS_EDGES, so this interpolation is not user-controlled.
        relation_type = edge["type"]
        run_neo4j_write(
            f"""
            MATCH (source:Class {{ontology: $ontology, id: $source_id}})
            MATCH (target:Class {{ontology: $ontology, id: $target_id}})
            MERGE (source)-[relation:{relation_type}]->(target)
            SET relation.label = $label,
                relation.source = $source,
                relation.comment = $comment,
                relation.updatedAt = datetime()
            """,
            ontology="smart-production-ontology",
            source_id=edge["source"],
            target_id=edge["target"],
            label=edge["label"],
            source="frontend-class-topology",
            comment=relation_comment,
        )


def discover_tables(database: str) -> list[str]:
    with mysql_connection(database) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            table_key = f"Tables_in_{database}"
            rows = cursor.fetchall()
            return [str(row.get(table_key) or next(iter(row.values()))) for row in rows]


def find_tables(database: str, include_keywords: tuple[str, ...], exclude_keywords: tuple[str, ...]) -> list[str]:
    tables = discover_tables(database)
    normalized_includes = tuple(normalize_text(item) for item in include_keywords if item)
    normalized_excludes = tuple(normalize_text(item) for item in exclude_keywords if item)

    if normalized_includes:
        tables = [
            table
            for table in tables
            if any(keyword in normalize_text(table) for keyword in normalized_includes)
        ]

    if normalized_excludes:
        tables = [
            table
            for table in tables
            if not any(keyword in normalize_text(table) for keyword in normalized_excludes)
        ]

    return tables


def read_mysql_table(database: str, table_name: str, limit: int = 50) -> list[dict[str, Any]]:
    with mysql_connection(database) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{table_name.replace('`', '``')}` LIMIT %s", (limit,))
            return [json_safe_row(row) for row in cursor.fetchall()]


def read_mysql_tables(database: str, include_keywords: tuple[str, ...], exclude_keywords: tuple[str, ...], limit: int = 50) -> list[dict[str, Any]]:
    tables = find_tables(database, include_keywords, exclude_keywords)
    result: list[dict[str, Any]] = []
    for table_name in tables:
        rows = read_mysql_table(database, table_name, limit=limit)
        result.append(
            {
                "name": table_name,
                "columns": list(rows[0].keys()) if rows else [],
                "rows": rows,
            }
        )
    return result


def entity_identity_from_row(entity_type: str, row: dict[str, Any], table_name: str, index: int) -> str:
    config = ENTITY_CONFIG[entity_type]
    identity = first_present(row, config["id_keys"])
    if identity not in (None, ""):
        return f"{entity_type}:{identity}"
    label = first_present(row, config["label_keys"])
    if label not in (None, ""):
        return f"{entity_type}:{normalize_text(label)}"
    return f"{entity_type}:{normalize_text(table_name)}:{index}"


def build_mysql_entity_item(entity_type: str, row: dict[str, Any], table_name: str, index: int) -> dict[str, Any]:
    config = ENTITY_CONFIG[entity_type]
    entity_id = entity_identity_from_row(entity_type, row, table_name, index)
    label_source = first_present(row, config["label_keys"])
    label = label_source or first_present(row, config["id_keys"]) or table_name
    if entity_type == "device" and not label_source and "agv" in normalize_text(table_name):
        label = "AGV"
    subtitle = first_present(row, config["subtitle_keys"]) or table_name
    status = first_present(row, config["status_keys"]) or ""
    summary = []
    if status:
        summary.append(str(status))
    if subtitle and subtitle != label:
        summary.append(str(subtitle))
    return {
        "id": entity_id,
        "entityType": entity_type,
        "label": str(label),
        "subtitle": str(subtitle),
        "status": str(status),
        "summary": " · ".join(summary) if summary else str(subtitle),
        "source": [f"mysql:{config['database']}.{table_name}"],
        "properties": row,
    }


def build_mysql_entity_detail(entity_type: str, entity_id: str) -> dict[str, Any] | None:
    config = ENTITY_CONFIG[entity_type]
    tables = read_mysql_tables(config["database"], config["include_keywords"], config["exclude_keywords"], limit=50)

    target_suffix = normalize_text(entity_id.split(":", 1)[1] if ":" in entity_id else entity_id)

    for table in tables:
        for index, row in enumerate(table["rows"]):
            candidate_id = entity_identity_from_row(entity_type, row, table["name"], index)
            if normalize_text(candidate_id) == target_suffix or normalize_text(candidate_id) == normalize_text(entity_id):
                label_source = first_present(row, config["label_keys"])
                label = label_source or first_present(row, config["id_keys"]) or table["name"]
                if entity_type == "device" and not label_source and "agv" in normalize_text(table["name"]):
                    label = "AGV"
                return {
                    "id": candidate_id,
                    "entityType": entity_type,
                    "label": str(label),
                    "subtitle": str(first_present(row, config["subtitle_keys"]) or table["name"]),
                    "status": str(first_present(row, config["status_keys"]) or ""),
                    "source": [f"mysql:{config['database']}.{table['name']}"],
                    "properties": row,
                    "runtime": row,
                    "relations": [],
                    "warnings": [],
                }
    return None

def build_mysql_catalog(entity_type: str, limit: int = 50) -> list[dict[str, Any]]:
    config = ENTITY_CONFIG[entity_type]
    tables = read_mysql_tables(
        config["database"],
        config["include_keywords"],
        config["exclude_keywords"],
        limit=limit,
    )
    items: list[dict[str, Any]] = []
    for table in tables:
        for index, row in enumerate(table["rows"]):
            items.append(build_mysql_entity_item(entity_type, row, table["name"], index))
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        deduped.append(item)
    return deduped


def read_device_runtime_status(limit: int = 200) -> list[dict[str, Any]]:
    try:
        with mysql_connection("device") as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        device_id,
                        device_name,
                        connection_state,
                        status,
                        previous_status,
                        last_seen_at,
                        last_heartbeat_at,
                        updated_at
                    FROM device_event_runtime
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = [dict(row) for row in cursor.fetchall()]
                timeout_seconds = max(1, int(os.environ.get("DEVICE_HEARTBEAT_SECONDS", "10"))) * max(
                    1,
                    int(os.environ.get("DEVICE_HEARTBEAT_MISSED_LIMIT", "5")),
                )
                stale_before = datetime.now() - timedelta(seconds=timeout_seconds)
                for row in rows:
                    connection_state = str(row.get("connection_state") or "").strip().lower()
                    heartbeat_at = row.get("last_heartbeat_at") or row.get("updated_at")
                    if connection_state == "online" and isinstance(heartbeat_at, datetime) and heartbeat_at <= stale_before:
                        row["connection_state"] = "offline"
                        row["status"] = ""
                return [json_safe_row(row) for row in rows]
    except Exception:
        return []


def device_runtime_display_status(runtime: dict[str, Any]) -> str:
    connection_state = str(runtime.get("connection_state") or "").strip().lower()
    if connection_state != "online":
        return "offline"
    return str(runtime.get("status") or "idle").strip() or "idle"


def device_runtime_state(runtime: dict[str, Any]) -> dict[str, str]:
    connection_state = str(runtime.get("connection_state") or "offline").strip().lower()
    connection_state = "online" if connection_state == "online" else "offline"
    status = "" if connection_state == "offline" else str(runtime.get("status") or "idle").strip().lower()
    if status not in {"idle", "busy", "error", "paused"}:
        status = "idle" if connection_state == "online" else ""
    return {"connection_state": connection_state, "runtime_status": status}


def non_empty_runtime_fields(runtime: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in runtime.items() if value not in (None, "")}


def device_display_name(item: dict[str, Any]) -> str:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    return str(first_present(props, ENTITY_CONFIG["device"]["label_keys"]) or item.get("label") or "").strip()


def device_display_code(item: dict[str, Any]) -> str:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    code = first_present(
        props,
        (
            "设备编号",
            "AGV编号",
            "工站编号",
            "工作站编号",
            "device_code",
            "deviceCode",
            "device_id",
            "deviceId",
            "workstation_code",
            "workstationCode",
            "station_code",
            "stationCode",
            "agv_code",
            "agvCode",
            "agv_id",
            "agvId",
            "code",
        ),
    )
    if code not in (None, ""):
        return str(code).strip()
    subtitle = str(item.get("subtitle") or "").strip()
    return subtitle if re.search(r"\d", subtitle) else ""


def device_catalog_identity_key(item: dict[str, Any]) -> str:
    key = normalize_text(device_display_code(item) or item.get("id") or item.get("label") or "")
    if ":" in key:
        key = key.split(":", 1)[1]
    return key


def device_runtime_keys(runtime: dict[str, Any]) -> set[str]:
    keys = set()
    for key in ("device_id", "device_name"):
        value = runtime.get(key)
        if value not in (None, ""):
            keys.add(normalize_text(value))
    return keys


def item_device_keys(item: dict[str, Any]) -> set[str]:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    keys = set()
    for value in (
        item.get("id"),
        item.get("label"),
        item.get("subtitle"),
        first_present(props, ENTITY_CONFIG["device"]["id_keys"]),
        first_present(props, ENTITY_CONFIG["device"]["label_keys"]),
    ):
        if value not in (None, ""):
            text = str(value)
            keys.add(normalize_text(text))
            if ":" in text:
                keys.add(normalize_text(text.split(":", 1)[1]))
    return keys


def is_device_runtime_catalog_item(item: dict[str, Any]) -> bool:
    sources = item.get("source") or []
    if isinstance(sources, str):
        sources = [sources]
    source_text = " ".join(str(source) for source in sources)
    subtitle = str(item.get("subtitle") or "")
    return DEVICE_RUNTIME_TABLE in source_text or normalize_text(subtitle) == normalize_text(DEVICE_RUNTIME_TABLE)


def merge_device_runtime_status(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime_rows = read_device_runtime_status()
    asset_devices = [item for item in devices if not is_device_runtime_catalog_item(item)]
    if not runtime_rows:
        return asset_devices

    runtime_by_key: dict[str, dict[str, Any]] = {}
    for runtime in runtime_rows:
        for key in device_runtime_keys(runtime):
            runtime_by_key[key] = runtime

    merged: list[dict[str, Any]] = []
    matched_keys: set[str] = set()
    for item in asset_devices:
        runtime = next((runtime_by_key[key] for key in item_device_keys(item) if key in runtime_by_key), None)
        if runtime:
            display_status = device_runtime_display_status(runtime)
            runtime_state = device_runtime_state(runtime)
            runtime_fields = non_empty_runtime_fields(runtime)
            display_name = device_display_name(item) or str(runtime.get("device_name") or runtime.get("device_id") or item.get("label") or "Device")
            display_code = device_display_code(item) or str(runtime.get("device_id") or item.get("subtitle") or "")
            properties = {**(item.get("properties") or {}), **runtime_fields, **runtime_state, "status": display_status}
            merged.append(
                {
                    **item,
                    "label": display_name,
                    "subtitle": display_code or str(item.get("subtitle") or ""),
                    "status": display_status,
                    "summary": " / ".join(part for part in (display_status, display_code or str(item.get("subtitle") or "")) if part),
                    "properties": properties,
                    "runtime": {**(item.get("runtime") or {}), **runtime_fields, **runtime_state, "status": display_status},
                    "source": list(dict.fromkeys([*(item.get("source") or []), "mysql:device.device_event_runtime"])),
                }
            )
            matched_keys.update(device_runtime_keys(runtime))
        else:
            merged.append(item)

    known_keys = set().union(*(item_device_keys(item) for item in asset_devices)) if asset_devices else set()
    for runtime in runtime_rows:
        keys = device_runtime_keys(runtime)
        if keys & known_keys or keys & matched_keys:
            continue
        display_status = device_runtime_display_status(runtime)
        runtime_state = device_runtime_state(runtime)
        device_id = str(runtime.get("device_id") or "")
        label = str(runtime.get("device_name") or device_id or "Device")
        merged.append(
            {
                "id": f"device:{device_id or normalize_text(label)}",
                "entityType": "device",
                "label": label,
                "subtitle": device_id or DEVICE_RUNTIME_TABLE,
                "status": display_status,
                "summary": display_status,
                "source": ["mysql:device.device_event_runtime"],
                "properties": {**runtime, **runtime_state, "status": display_status},
                "runtime": {**runtime, **runtime_state, "status": display_status},
                "relations": [],
                "warnings": [],
            }
        )
    return merged


def query_neo4j_nodes(label: str, limit: int = 50) -> list[dict[str, Any]]:
    query = """
    MATCH (n)
    WHERE any(label IN labels(n) WHERE toLower(label) = $label)
    RETURN elementId(n) AS node_id, labels(n) AS labels, properties(n) AS props
    LIMIT $limit
    """
    return run_neo4j_read(query, label=normalize_text(label), limit=limit)


def neo4j_graph_node(record: dict[str, Any], entity_type: str, x: int, y: int, tone: str) -> dict[str, Any]:
    item = build_neo4j_entity_item(entity_type, record)
    return {
        "id": item["id"],
        "entityType": entity_type,
        "label": item["label"],
        "subtitle": item["subtitle"],
        "status": item.get("status") or "",
        "source": item.get("source") or ["neo4j"],
        "properties": item.get("properties") or {},
        "neo4jNodeId": item.get("neo4jNodeId") or record.get("node_id"),
        "tone": tone,
        "x": x,
        "y": y,
    }


def compact_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_seen: set[str] = set()
    compact_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if node["id"] in node_seen:
            continue
        node_seen.add(node["id"])
        compact_nodes.append(node)

    edge_seen: set[str] = set()
    compact_edges: list[dict[str, Any]] = []
    for edge in edges:
        if edge["source"] not in node_seen or edge["target"] not in node_seen:
            continue
        edge_id = edge.get("id") or f"{edge['source']}__{edge.get('label', '')}__{edge['target']}"
        if edge_id in edge_seen:
            continue
        edge_seen.add(edge_id)
        compact_edges.append({**edge, "id": edge_id})

    return {"nodes": compact_nodes, "edges": compact_edges}


def entity_type_from_labels(record: dict[str, Any], fallback: str) -> str:
    labels = {str(label).lower() for label in record.get("labels") or []}
    if "product" in labels:
        return "product"
    if "part" in labels:
        return "part"
    if "material" in labels:
        return "material"
    if "processinstance" in labels or "assemblystep" in labels or "process" in labels:
        return "process"
    if "craft" in labels:
        return "craft"
    if "device" in labels:
        return "device"
    return fallback


def topology_graph_from_query(query: str, entity_types: dict[str, str], layout: dict[str, dict[str, Any]], limit: int = 80) -> dict[str, Any]:
    records = run_neo4j_read(query, limit=limit)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    counters: dict[str, int] = defaultdict(int)

    for record in records:
        source_key = "source"
        target_key = "target"
        source_type = entity_types["source"]
        target_type = entity_types["target"]
        source_record = {"node_id": record.get("source_node_id"), "labels": record.get("source_labels") or [], "props": record.get("source_props") or {}}
        target_record = {"node_id": record.get("target_node_id"), "labels": record.get("target_labels") or [], "props": record.get("target_props") or {}}

        for key, entity_type, node_record in ((source_key, source_type, source_record), (target_key, target_type, target_record)):
            props = node_record.get("props") or {}
            if not props:
                continue
            node_id = build_neo4j_entity_item(entity_type, node_record)["id"]
            if not any(node["id"] == node_id for node in nodes):
                index = counters[key]
                counters[key] += 1
                cfg = layout[key]
                y_values = cfg.get("y_values") or [70 + index * 140]
                y = y_values[index % len(y_values)] + (index // len(y_values)) * int(cfg.get("row_step", 0))
                nodes.append(neo4j_graph_node(node_record, entity_type, int(cfg["x"]), int(y), str(cfg["tone"])))

        source_item = build_neo4j_entity_item(source_type, source_record)
        target_item = build_neo4j_entity_item(target_type, target_record)
        relation = str(record.get("relation") or "")
        edges.append(
            {
                "source": source_item["id"],
                "target": target_item["id"],
                "label": relation,
                "sourceClass": source_item["label"],
                "targetClass": target_item["label"],
                "sourceType": source_type,
                "targetType": target_type,
            }
        )

    return compact_graph(nodes, edges)


def build_product_process_topology(limit: int = 120) -> dict[str, Any]:
    records = run_neo4j_read(
        """
        MATCH (p)-[step_rel]->(step)
        WHERE any(label IN labels(p) WHERE toLower(label) = 'product')
          AND any(label IN labels(step) WHERE toLower(label) IN ['process', 'processinstance', 'assemblystep'])
        OPTIONAL MATCH (step)-[use_rel]->(used)
        WHERE toLower(type(use_rel)) IN ['uses', 'consumes']
          AND any(label IN labels(used) WHERE toLower(label) IN ['material', 'part'])
        OPTIONAL MATCH (step)-[produce_rel]->(produced)
        WHERE toLower(type(produce_rel)) = 'produces'
          AND any(label IN labels(produced) WHERE toLower(label) IN ['material', 'part', 'product'])
        RETURN elementId(p) AS product_node_id, labels(p) AS product_labels, properties(p) AS product_props,
               elementId(step) AS step_node_id, labels(step) AS step_labels, properties(step) AS step_props,
               type(step_rel) AS step_relation,
               collect(DISTINCT CASE WHEN used IS NULL THEN null ELSE {node_id: elementId(used), labels: labels(used), props: properties(used), relation: type(use_rel)} END) AS used_nodes,
               collect(DISTINCT CASE WHEN produced IS NULL THEN null ELSE {node_id: elementId(produced), labels: labels(produced), props: properties(produced), relation: type(produce_rel)} END) AS produced_nodes,
               coalesce(p.name, '') AS product_sort,
               coalesce(step.order, step.name, step.process_name, '') AS step_sort
        ORDER BY product_sort, step_sort
        LIMIT $limit
        """,
        limit=limit,
    )
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    counters: dict[str, int] = defaultdict(int)

    def add_node(record: dict[str, Any], entity_type: str, x: int, base_y: int, tone: str) -> dict[str, Any]:
        item = build_neo4j_entity_item(entity_type, record)
        if not any(node["id"] == item["id"] for node in nodes):
            index = counters[entity_type]
            counters[entity_type] += 1
            nodes.append(neo4j_graph_node(record, entity_type, x, base_y + index * 135, tone))
        return item

    for record in records:
        product_record = {"node_id": record.get("product_node_id"), "labels": record.get("product_labels") or [], "props": record.get("product_props") or {}}
        step_record = {"node_id": record.get("step_node_id"), "labels": record.get("step_labels") or [], "props": record.get("step_props") or {}}
        product = add_node(product_record, "product", 1280, 170, "yellow")
        step = add_node(step_record, "process", 610, 95, "green")
        edges.append({"source": product["id"], "target": step["id"], "label": record.get("step_relation") or "HAS_STEP", "sourceClass": product["label"], "targetClass": step["label"], "sourceType": "product", "targetType": "process"})

        for used in record.get("used_nodes") or []:
            if not used or not used.get("props"):
                continue
            used_record = {"node_id": used.get("node_id"), "labels": used.get("labels") or [], "props": used.get("props") or {}}
            used_type = entity_type_from_labels(used_record, "material")
            used_tone = "amber" if used_type == "part" else "yellow"
            used_node = add_node(used_record, used_type, 90, 90, used_tone)
            edges.append({"source": step["id"], "target": used_node["id"], "label": "uses", "sourceClass": step["label"], "targetClass": used_node["label"], "sourceType": "process", "targetType": used_type})

        for produced in record.get("produced_nodes") or []:
            if not produced or not produced.get("props"):
                continue
            produced_record = {"node_id": produced.get("node_id"), "labels": produced.get("labels") or [], "props": produced.get("props") or {}}
            produced_type = entity_type_from_labels(produced_record, "part")
            produced_tone = "yellow" if produced_type == "material" else "amber"
            produced_node = add_node(produced_record, produced_type, 1320, 450, produced_tone)
            edges.append({"source": step["id"], "target": produced_node["id"], "label": "produces", "sourceClass": step["label"], "targetClass": produced_node["label"], "sourceType": "process", "targetType": produced_type})

    graph = compact_graph(nodes, edges)
    return {"key": "product-process", "title": "产品-工序拓扑图", "description": "Neo4j Product、Process、输入物料与产出部件的 ISA-95 / IEC 62264 拓扑关系。", **graph}

def build_process_material_topology(limit: int = 100) -> dict[str, Any]:
    graph = topology_graph_from_query(
        """
        MATCH (pi)-[r]->(m)
        WHERE any(label IN labels(pi) WHERE toLower(label) = 'process_instance')
          AND any(label IN labels(m) WHERE toLower(label) = 'material')
          AND toLower(type(r)) IN ['uses', 'produces', 'consumes']
        RETURN elementId(pi) AS source_node_id, labels(pi) AS source_labels, properties(pi) AS source_props,
               elementId(m) AS target_node_id, labels(m) AS target_labels, properties(m) AS target_props,
               type(r) AS relation
        ORDER BY coalesce(pi.order, pi.name, ''), coalesce(m.name, '')
        LIMIT $limit
        """,
        {"source": "process_instance", "target": "material"},
        {
            "source": {"x": 160, "y_values": [160, 420], "row_step": 130, "tone": "green"},
            "target": {"x": 860, "y_values": [90, 250, 410, 570], "row_step": 80, "tone": "yellow"},
        },
        limit,
    )
    return {"key": "process-material", "title": "工序-物料拓扑图", "description": "Neo4j process_instance 与关联 material 的 uses / produces 关系。", **graph}


def build_device_process_topology(limit: int = 100) -> dict[str, Any]:
    graph = topology_graph_from_query(
        """
        MATCH (d)-[r]->(p)
        WHERE any(label IN labels(d) WHERE toLower(label) = 'device')
          AND any(label IN labels(p) WHERE toLower(label) = 'craft')
        RETURN elementId(d) AS source_node_id, labels(d) AS source_labels, properties(d) AS source_props,
               elementId(p) AS target_node_id, labels(p) AS target_labels, properties(p) AS target_props,
               type(r) AS relation
        ORDER BY coalesce(d.name, ''), coalesce(p.name, '')
        LIMIT $limit
        """,
        {"source": "device", "target": "craft"},
        {
            "source": {"x": 140, "y_values": [100, 260, 420, 580], "row_step": 80, "tone": "cyan"},
            "target": {"x": 880, "y_values": [100, 260, 420, 580], "row_step": 80, "tone": "violet"},
        },
        limit,
    )
    return {"key": "device-craft", "title": "设备-工艺能力拓扑图", "description": "Neo4j device 与关联 Craft 的 CAN_EXECUTE 能力关系。", **graph}


def build_topologies_payload() -> dict[str, Any]:
    topologies = [
        build_product_process_topology(),
        build_device_process_topology(),
    ]
    return {"ok": True, "topologies": topologies, "warnings": []}


def build_neo4j_entity_item(entity_type: str, record: dict[str, Any]) -> dict[str, Any]:
    props = clean_value(record.get("props") or {})
    node_id = str(record.get("node_id") or "")
    labels = clean_value(record.get("labels") or [])
    if entity_type == "product":
        identity = props.get("productId") or props.get("product_id") or props.get("name") or node_id
        label = props.get("name") or props.get("title") or identity
        subtitle = props.get("productId") or props.get("product_code") or "Product"
        status = props.get("status") or props.get("state") or ""
    elif entity_type == "process":
        identity = props.get("code") or props.get("processCode") or props.get("process_id") or props.get("name") or node_id
        label = props.get("process_name") or props.get("name") or identity
        subtitle = props.get("type") or props.get("stage") or "Product Process"
        status = props.get("status") or ""
    elif entity_type == "craft":
        identity = props.get("craftId") or props.get("craft_id") or props.get("code") or props.get("name") or node_id
        label = props.get("name") or props.get("craft_name") or identity
        subtitle = props.get("type") or props.get("description") or "Craft"
        status = props.get("status") or ""
    elif entity_type in {"process_instance", "assembly_step"}:
        identity = props.get("stepId") or props.get("step_id") or props.get("order") or props.get("name") or node_id
        label = props.get("process_name") or props.get("name") or props.get("title") or identity
        subtitle = props.get("instruction") or props.get("description") or "Step"
        status = props.get("status") or ""
    elif entity_type == "device":
        identity = props.get("deviceId") or props.get("device_id") or props.get("deviceCode") or props.get("device_code") or props.get("name") or node_id
        label = props.get("name") or props.get("device_name") or identity
        subtitle = props.get("type") or props.get("location") or "Device"
        status = props.get("status") or props.get("state") or ""
    elif entity_type == "part":
        identity = props.get("partId") or props.get("part_id") or props.get("name") or node_id
        label = props.get("name") or props.get("partId") or identity
        subtitle = props.get("type") or props.get("order") or "Part"
        status = props.get("status") or ""
    else:
        identity = props.get("name") or node_id
        label = props.get("name") or identity
        subtitle = "Neo4j"
        status = props.get("status") or ""

    entity_id = f"{entity_type}:{identity}"
    return {
        "id": entity_id,
        "entityType": entity_type,
        "label": str(label),
        "subtitle": str(subtitle),
        "status": str(status),
        "summary": str(subtitle),
        "source": ["neo4j"],
        "properties": props,
        "labels": labels,
        "neo4jNodeId": node_id,
    }


def build_neo4j_catalog(entity_type: str, limit: int = 50) -> list[dict[str, Any]]:
    label_map = {
        "product": "Product",
        "process": "Process",
        "craft": "Craft",
        "process_instance": "ProcessInstance",
        "assembly_step": "AssemblyStep",
        "device": "Device",
        "part": "Part",
    }
    records = query_neo4j_nodes(label_map[entity_type], limit=limit)
    return [build_neo4j_entity_item(entity_type, record) for record in records]


def find_product_record(entity_id: str | None = None) -> dict[str, Any] | None:
    params: dict[str, Any] = {"entity_id": entity_id or "", "name": entity_id or "", "limit": 1}
    query = """
    MATCH (p)
    WHERE any(label IN labels(p) WHERE toLower(label) = 'product')
      AND (
        $entity_id = ''
        OR toString(p.productId) = $entity_id
        OR toLower(toString(p.name)) CONTAINS toLower($name)
      )
    RETURN elementId(p) AS node_id, labels(p) AS labels, properties(p) AS props
    LIMIT 1
    """
    records = run_neo4j_read(query, **params)
    return records[0] if records else None


def find_product_parts(product_node_id: str) -> list[dict[str, Any]]:
    query = """
    MATCH (p)-[*1..3]->(part)
    WHERE elementId(p) = $product_node_id
      AND any(label IN labels(part) WHERE toLower(label) = 'part')
    WITH part, coalesce(part.order, part.partId, part.name, part.type, '') AS sort_key
    RETURN labels(part) AS labels, properties(part) AS props
    ORDER BY sort_key
    """
    records = run_neo4j_read(query, product_node_id=product_node_id)
    return [clean_value(record) for record in records]


def find_route_steps(product_node_id: str) -> list[dict[str, Any]]:
    query = """
    MATCH (p)-[rel]->(step)
    WHERE elementId(p) = $product_node_id
      AND toLower(type(rel)) = 'has_step'
      AND any(label IN labels(step) WHERE toLower(label) = 'processinstance')
    OPTIONAL MATCH (proc)
    WHERE any(label IN labels(proc) WHERE toLower(label) = 'process')
      AND toString(proc.name) = toString(step.process_name)
    OPTIONAL MATCH (step)-[use_rel]->(used)
    WHERE toLower(type(use_rel)) = 'uses'
    OPTIONAL MATCH (step)-[produce_rel]->(produced)
    WHERE toLower(type(produce_rel)) = 'produces'
    RETURN
      elementId(step) AS step_node_id,
      properties(step) AS step_props,
      properties(proc) AS process_props,
      collect(DISTINCT properties(used)) AS uses,
      collect(DISTINCT properties(produced)) AS produces,
      coalesce(step.order, step.stepId, step.name, step.process_name, '') AS sort_key
    ORDER BY sort_key
    """
    records = run_neo4j_read(query, product_node_id=product_node_id)
    steps: list[dict[str, Any]] = []
    for record in records:
        step_props = clean_value(record.get("step_props") or {})
        process_props = clean_value(record.get("process_props") or {})
        step_props["process"] = process_props
        step_props["uses"] = [clean_value(item) for item in (record.get("uses") or []) if item]
        step_props["produces"] = [clean_value(item) for item in (record.get("produces") or []) if item]
        step_props["neo4jNodeId"] = record.get("step_node_id")
        steps.append(step_props)
    if steps:
        return steps

    fallback_query = """
    MATCH (s)
    WHERE any(label IN labels(s) WHERE toLower(label) = 'assemblystep')
    WITH s, coalesce(s.stepId, s.order, s.name, s.process_name, 0) AS sort_key
    RETURN elementId(s) AS step_node_id, properties(s) AS step_props
    ORDER BY sort_key
    LIMIT 20
    """
    fallback_records = run_neo4j_read(fallback_query)
    return [clean_value(record.get("step_props") or {}) for record in fallback_records]


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
    )
    location_keys = (
        "location",
        "station",
        "position",
        "area",
        "device_location",
        "deviceLocation",
    )

    device_id = None
    device_name = None
    location = None
    for source in nested_sources:
        device_id = device_id or first_present(source, device_id_keys)
        device_name = device_name or first_present(source, device_name_keys)
        location = location or first_present(source, location_keys)

    if not device_id and not device_name:
        return None

    return {
        "device_id": clean_value(device_id),
        "device_name": clean_value(device_name),
        "location": clean_value(location),
    }


def build_instance_graph(selected_product: dict[str, Any] | None, catalogs: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not selected_product:
        nodes = [
            {"id": "root", "label": "智能产线 Ontology", "subtitle": "Live", "tone": "tone-cyan", "x": 50, "y": 50, "entityType": "ontology"},
        ]
        edges = []
        return {"nodes": nodes, "edges": edges}

    product_node_id = str(selected_product.get("neo4jNodeId") or "")
    parts = find_product_parts(product_node_id) if product_node_id else []
    steps = find_route_steps(product_node_id) if product_node_id else []

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    root_x, root_y = 52, 52
    nodes.append(
        {
            "id": selected_product["id"],
            "label": selected_product["label"],
            "subtitle": selected_product["subtitle"],
            "tone": "tone-cyan",
            "x": root_x,
            "y": root_y,
            "entityType": "product",
        }
    )

    part_positions = [
        (18, 24),
        (18, 50),
        (18, 76),
    ]
    for index, part in enumerate(parts[:6]):
        props = part.get("properties") or {}
        label = str(first_present(props, ("name", "partId", "part_id", "type")) or "Part")
        subtitle = str(first_present(props, ("type", "order", "partId", "part_id")) or "Part")
        x, y = part_positions[index % len(part_positions)]
        y = min(86, y + (index // len(part_positions)) * 16)
        node_id = f"part:{label}:{index}"
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "subtitle": subtitle,
                "tone": "tone-violet",
                "x": x,
                "y": y,
                "entityType": "material",
            }
        )
        edges.append({"x1": root_x, "y1": root_y, "x2": x, "y2": y, "label": "HAS_PART", "style": "solid"})

    step_positions = [
        (82, 18),
        (82, 40),
        (82, 62),
        (82, 84),
    ]
    step_node_ids: list[str] = []
    for index, step in enumerate(steps[:8]):
        step_id = str(step.get("stepId") or step.get("step_id") or step.get("order") or step.get("name") or index)
        step_name = str(step.get("process_name") or step.get("name") or step.get("title") or step_id)
        step_subtitle = str(step.get("instruction") or step.get("description") or step.get("process", {}).get("name") or "ProcessInstance")
        x, y = step_positions[index % len(step_positions)]
        y = min(88, y + (index // len(step_positions)) * 14)
        node_id = f"step:{step_id}"
        step_node_ids.append(node_id)
        nodes.append(
            {
                "id": node_id,
                "label": step_name,
                "subtitle": step_subtitle,
                "tone": "tone-pink",
                "x": x,
                "y": y,
                "entityType": "work_order",
                "sourceEntityType": "process_instance",
            }
        )
        edges.append({"x1": root_x, "y1": root_y, "x2": x, "y2": y, "label": "HAS_STEP", "style": "solid"})

        device = extract_assigned_device(step)
        if device:
            device_label = str(device.get("device_name") or device.get("device_id") or "Device")
            device_id = f"device:{normalize_text(device_label) or normalize_text(device.get('device_id')) or index}"
            device_x = 50 if index % 2 == 0 else 72
            device_y = 20 + (index * 14) % 58
            if not any(node["id"] == device_id for node in nodes):
                nodes.append(
                    {
                        "id": device_id,
                        "label": device_label,
                        "subtitle": str(device.get("location") or "Device"),
                        "tone": "tone-cyan",
                        "x": device_x,
                        "y": device_y,
                        "entityType": "device",
                    }
                )
            edges.append({"x1": x, "y1": y, "x2": device_x, "y2": device_y, "label": "ASSIGNED_TO", "style": "solid"})

        for material_index, material in enumerate((step.get("uses") or [])[:2]):
            material_name = str(first_present(material, ("name", "partId", "part_id", "type")) or f"Material {material_index + 1}")
            material_id = f"material:{normalize_text(material_name) or index}-{material_index}"
            material_x = 18 + material_index * 10
            material_y = 12 + (index * 8) % 72
            if not any(node["id"] == material_id for node in nodes):
                nodes.append(
                    {
                        "id": material_id,
                        "label": material_name,
                        "subtitle": str(first_present(material, ("type", "partId", "part_id")) or "Material"),
                        "tone": "tone-violet",
                        "x": material_x,
                        "y": material_y,
                        "entityType": "material",
                    }
                )
            edges.append({"x1": x, "y1": y, "x2": material_x, "y2": material_y, "label": "USES", "style": "solid"})

        for material_index, material in enumerate((step.get("produces") or [])[:2]):
            material_name = str(first_present(material, ("name", "partId", "part_id", "type")) or f"Output {material_index + 1}")
            material_id = f"material-out:{normalize_text(material_name) or index}-{material_index}"
            material_x = 28 + material_index * 12
            material_y = 84 - (index * 8) % 72
            if not any(node["id"] == material_id for node in nodes):
                nodes.append(
                    {
                        "id": material_id,
                        "label": material_name,
                        "subtitle": str(first_present(material, ("type", "partId", "part_id")) or "Material"),
                        "tone": "tone-green",
                        "x": material_x,
                        "y": material_y,
                        "entityType": "material",
                    }
                )
            edges.append({"x1": x, "y1": y, "x2": material_x, "y2": material_y, "label": "PRODUCES", "style": "solid"})

    if not steps:
        order_count = len(catalogs.get("order", []))
        work_count = len(catalogs.get("work_order", []))
        nodes.extend(
            [
                {"id": "orders-root", "label": f"Orders {order_count}", "subtitle": "MySQL", "tone": "tone-pink", "x": 82, "y": 30, "entityType": "order"},
                {"id": "work-root", "label": f"Work Orders {work_count}", "subtitle": "MySQL", "tone": "tone-violet", "x": 82, "y": 70, "entityType": "work_order"},
            ]
        )
        edges.extend(
            [
                {"x1": root_x, "y1": root_y, "x2": 82, "y2": 30, "label": "RELATED_ORDER", "style": "solid"},
                {"x1": root_x, "y1": root_y, "x2": 82, "y2": 70, "label": "RELATED_WORK_ORDER", "style": "solid"},
            ]
        )

    return {"nodes": nodes, "edges": edges}


def build_class_graph(summary: dict[str, int]) -> dict[str, Any]:
    count_keys = {
        "order": "orderCount",
        "work_order": "workOrderCount",
        "device": "deviceCount",
        "product": "productCount",
        "process": "processCount",
        "material": "materialCount",
    }
    nodes = []
    for node in TOPOLOGY_CLASS_NODES:
        count_key = count_keys.get(str(node.get("moduleType") or node.get("entityType") or ""))
        subtitle = f"{summary.get(count_key, 0)} live" if count_key else "Class"
        nodes.append({**node, "subtitle": subtitle})

    node_lookup = {node["id"]: node for node in nodes}
    edges = []
    for edge in TOPOLOGY_CLASS_EDGES:
        source = node_lookup.get(edge["source"])
        target = node_lookup.get(edge["target"])
        if not source or not target:
            continue
        edges.append(
            {
                "source": edge["source"],
                "target": edge["target"],
                "x1": source["x"],
                "y1": source["y"],
                "x2": target["x"],
                "y2": target["y"],
                "label": edge["label"],
                "style": "solid",
            }
        )
    return {"nodes": nodes, "edges": edges}


def get_neo4j_label_types() -> list[str]:
    try:
        records = run_neo4j_read("CALL db.labels() YIELD label RETURN label ORDER BY label")
        return [str(record.get("label")) for record in records]
    except Exception:
        return []


def get_neo4j_relationship_types() -> list[str]:
    try:
        records = run_neo4j_read("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType")
        return [str(record.get("relationshipType")) for record in records]
    except Exception:
        return []


def build_product_detail(entity_id: str | None = None) -> dict[str, Any] | None:
    record = find_product_record(entity_id)
    if not record:
        return None

    props = clean_value(record.get("props") or {})
    node_id = str(record.get("node_id") or "")
    product_id = props.get("productId") or props.get("product_id") or props.get("name") or node_id
    label = props.get("name") or props.get("title") or product_id
    subtitle = props.get("productId") or props.get("product_code") or "Product"
    parts = find_product_parts(node_id) if node_id else []
    steps = find_route_steps(node_id) if node_id else []
    relations: list[dict[str, Any]] = []
    for part in parts[:20]:
        part_props = part.get("properties") or {}
        part_name = part_props.get("name") or part_props.get("partId") or part_props.get("type") or "Part"
        relations.append(
            {
                "type": "HAS_PART",
                "targetType": "material",
                "targetId": f"material:{normalize_text(part_name)}",
                "label": str(part_name),
            }
        )
    for step in steps[:20]:
        step_name = step.get("process_name") or step.get("name") or step.get("title") or "Step"
        relations.append(
            {
                "type": "HAS_STEP",
                "targetType": "work_order",
                "targetId": f"work_order:{normalize_text(step_name)}",
                "label": str(step_name),
            }
        )

    return {
        "id": f"product:{product_id}",
        "entityType": "product",
        "label": str(label),
        "subtitle": str(subtitle),
        "status": str(props.get("status") or props.get("state") or ""),
        "source": ["neo4j"],
        "properties": props,
        "runtime": {},
        "relations": relations,
        "warnings": [],
        "neo4jNodeId": node_id,
        "parts": parts,
        "steps": steps,
    }


def build_neo4j_catalog_from_products(limit: int = 50) -> list[dict[str, Any]]:
    records = query_neo4j_nodes("Product", limit=limit)
    items: list[dict[str, Any]] = []
    for record in records:
        props = clean_value(record.get("props") or {})
        node_id = str(record.get("node_id") or "")
        identity = props.get("productId") or props.get("product_id") or props.get("name") or node_id
        label = props.get("name") or props.get("title") or identity
        subtitle = props.get("productId") or props.get("product_code") or "Product"
        items.append(
            {
                "id": f"product:{identity}",
                "entityType": "product",
                "label": str(label),
                "subtitle": str(subtitle),
                "status": str(props.get("status") or props.get("state") or ""),
                "summary": str(props.get("description") or subtitle),
                "source": ["neo4j"],
                "properties": props,
                "neo4jNodeId": node_id,
            }
        )
    return items


def build_live_ontology_payload() -> dict[str, Any]:
    devices = safe_device_catalog()
    materials = build_mysql_catalog("material")
    orders = build_mysql_catalog("order")
    work_orders = build_mysql_catalog("work_order")
    products = build_neo4j_catalog_from_products()
    processes = build_neo4j_catalog("process")
    crafts = build_neo4j_catalog("craft")

    craft_records = query_neo4j_nodes("Craft", limit=50)
    process_records = query_neo4j_nodes("Process", limit=50)
    process_instances = query_neo4j_nodes("ProcessInstance", limit=50)
    assembly_steps = query_neo4j_nodes("AssemblyStep", limit=50)
    neo4j_devices = query_neo4j_nodes("Device", limit=50)

    summary = {
        "deviceCount": len(devices) or len(neo4j_devices),
        "materialCount": len(materials),
        "productCount": len(products),
        "orderCount": len(orders),
        "workOrderCount": len(work_orders),
        "craftCount": len(craft_records),
        "processCount": len(process_records),
        "processInstanceCount": len(process_instances),
        "assemblyStepCount": len(assembly_steps),
    }

    selected_product = build_product_detail(products[0]["id"].split(":", 1)[1]) if products else None
    class_graph = build_class_graph(summary)
    instance_graph = build_instance_graph(selected_product, {
        "device": devices,
        "material": materials,
        "order": orders,
        "work_order": work_orders,
        "product": products,
            "craft": crafts,
    })

    warnings: list[str] = []
    if not orders:
        warnings.append("未发现真实订单表，Orders 页面将显示空状态。")
    if not work_orders:
        warnings.append("未发现真实订单表，Orders 页面将显示空状态。")
    if not products:
        warnings.append("Neo4j 中未发现 Product 节点，Products 页面将显示空状态。")
    try:
        ensure_topology_classes_in_neo4j()
    except Exception as exc:
        warnings.append(f"Neo4j Class 拓扑同步失败：{exc}")

    return {
        "ok": True,
        "ontology": {
            "id": "smart-production-ontology",
            "name": "智能产线 Ontology",
            "version": "live",
            "status": "Live",
            "description": "基于 Neo4j 产品/工艺图与 MySQL 设备、库存、订单数据构建的实时智能产线本体。",
        },
        "summary": summary,
        "classGraph": class_graph,
        "instanceGraph": instance_graph,
        "catalogs": {
            "device": devices,
            "material": materials,
            "order": orders,
            "work_order": work_orders,
            "product": products,
            "craft": crafts,
            "process": processes,
        },
        "warnings": warnings,
    }


def list_entities(entity_type: str, limit: int = 50, q: str | None = None) -> dict[str, Any]:
    entity_type = entity_type.lower().replace("-", "_")
    if entity_type == "product":
        items = build_neo4j_catalog_from_products(limit=limit)
    elif entity_type == "process":
        items = build_neo4j_catalog("process", limit=limit)
    elif entity_type == "craft":
        items = build_neo4j_catalog("craft", limit=limit)
    elif entity_type == "device":
        items = safe_device_catalog()[:limit]
    elif entity_type in ENTITY_CONFIG:
        items = build_mysql_catalog(entity_type, limit=limit)
    else:
        return {"ok": False, "entity_type": entity_type, "items": [], "warnings": ["Unsupported entity type"]}

    if q:
        qn = normalize_text(q)
        items = [
            item
            for item in items
            if qn in normalize_text(item.get("label"))
            or qn in normalize_text(item.get("subtitle"))
            or qn in normalize_text(item.get("summary"))
            or qn in normalize_text(item.get("id"))
        ]

    return {"ok": True, "entity_type": entity_type, "items": items[:limit], "warnings": []}


def get_entity_detail(entity_type: str, entity_id: str) -> dict[str, Any]:
    entity_type = entity_type.lower().replace("-", "_")
    entity_id = str(entity_id or "").strip()
    if not entity_id:
        return {"ok": False, "entity_type": entity_type, "entity_id": entity_id, "warnings": ["entity_id is required"]}

    if entity_type == "product":
        detail = build_product_detail(entity_id.split(":", 1)[1] if ":" in entity_id else entity_id)
        if detail:
            return {"ok": True, "entity": detail, "warnings": []}
        return {"ok": False, "entity_type": entity_type, "entity_id": entity_id, "warnings": ["Product not found"]}

    if entity_type in ENTITY_CONFIG:
        detail = build_mysql_entity_detail(entity_type, entity_id)
        if detail:
            # enrich device detail with related live order/work order/product info when possible
            if entity_type == "device":
                current_work_order = first_present(detail.get("properties", {}), ("current_work_order_id", "work_order_id", "task_id", "当前工单编号"))
                relations: list[dict[str, Any]] = []
                if current_work_order:
                    relations.append({"type": "CURRENT_WORK_ORDER", "targetType": "work_order", "targetId": f"work_order:{current_work_order}", "label": str(current_work_order)})
                detail["relations"] = relations
            return {"ok": True, "entity": detail, "warnings": []}
        return {"ok": False, "entity_type": entity_type, "entity_id": entity_id, "warnings": [f"{entity_type} not found or no real table configured"]}

    return {"ok": False, "entity_type": entity_type, "entity_id": entity_id, "warnings": ["Unsupported entity type"]}


def get_schema_payload() -> dict[str, Any]:
    mysql_summary = {}
    for entity_type in ("device", "material", "order", "work_order"):
        cfg = ENTITY_CONFIG[entity_type]
        try:
            tables = find_tables(cfg["database"], cfg["include_keywords"], cfg["exclude_keywords"])
            mysql_summary[entity_type] = {"database": cfg["database"], "tables": tables}
        except Exception as exc:
            mysql_summary[entity_type] = {"database": cfg["database"], "tables": [], "error": str(exc)}

    return {
        "ok": True,
        "neo4j": {
            "labels": get_neo4j_label_types(),
            "relationshipTypes": get_neo4j_relationship_types(),
        },
        "mysql": mysql_summary,
    }





