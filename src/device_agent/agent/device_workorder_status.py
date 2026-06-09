#!/usr/bin/env python3
"""Work-order status persistence and event reporting for the device agent."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sqlite3
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
STATUS_DB_FILE = AGENT_DIR / "device_workorder_status.sqlite3"
ROCKETMQ_NAMESRV = os.getenv("ROCKETMQ_NAMESRV", "192.168.1.10:9876")
DEVICE_ID = os.getenv("DEVICE_AGENT_TAG", "DEV002")
EVENT_TOPIC = os.getenv("DEVICE_EVENT_TOPIC", "DeviceEventReport")
EVENT_PRODUCER_GROUP = os.getenv("DEVICE_EVENT_PRODUCER_GROUP", "device-agent-event-producer")
VALID_STATUSES = {"received", "running", "succeeded", "failed"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_db() -> None:
    STATUS_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATUS_DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workorder_status (
                work_order_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                previous_status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workorder_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                previous_status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        migrate_drop_details(connection, "workorder_status")
        migrate_drop_details(connection, "workorder_status_history")


def migrate_drop_details(connection: sqlite3.Connection, table_name: str) -> None:
    columns = [
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]
    if "details" not in columns:
        return

    if table_name == "workorder_status":
        connection.execute(
            """
            CREATE TABLE workorder_status_new (
                work_order_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                previous_status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO workorder_status_new
                (work_order_id, status, previous_status, updated_at)
            SELECT work_order_id, status, previous_status, updated_at
            FROM workorder_status
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE workorder_status_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                previous_status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO workorder_status_history_new
                (id, work_order_id, status, previous_status, updated_at)
            SELECT id, work_order_id, status, previous_status, updated_at
            FROM workorder_status_history
            """
        )

    connection.execute(f"DROP TABLE {table_name}")
    connection.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")


def get_status(work_order_id: str) -> dict | None:
    init_db()
    with sqlite3.connect(STATUS_DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT work_order_id, status, previous_status, updated_at
            FROM workorder_status
            WHERE work_order_id = ?
            """,
            (work_order_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "work_order_id": row[0],
        "status": row[1],
        "previous_status": row[2],
        "updated_at": row[3],
    }


def set_status(work_order_id: str, status: str, _details: dict | None = None, emit: bool = True) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid work-order status: {status}")

    init_db()
    updated_at = now_iso()
    current = get_status(work_order_id)
    previous_status = current["status"] if current else None

    with sqlite3.connect(STATUS_DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO workorder_status
                (work_order_id, status, previous_status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(work_order_id) DO UPDATE SET
                status = excluded.status,
                previous_status = excluded.previous_status,
                updated_at = excluded.updated_at
            """,
            (work_order_id, status, previous_status, updated_at),
        )
        connection.execute(
            """
            INSERT INTO workorder_status_history
                (work_order_id, status, previous_status, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (work_order_id, status, previous_status, updated_at),
        )

    event = {
        "event_type": "workorder_status_changed",
        "device_id": DEVICE_ID,
        "work_order_id": work_order_id,
        "status": status,
        "previous_status": previous_status,
        "timestamp": updated_at,
    }
    if emit:
        emit_status_event(event)
    return event


def emit_status_event(event: dict) -> bool:
    try:
        from rocketmq.client import Message, Producer
    except Exception as exc:
        print(f"[workorder-status] rocketmq client unavailable: {exc}", file=sys.stderr)
        return False

    producer = Producer(EVENT_PRODUCER_GROUP)
    producer.set_name_server_address(ROCKETMQ_NAMESRV)
    try:
        producer.start()
        message = Message(EVENT_TOPIC)
        message.set_tags(DEVICE_ID)
        message.set_keys(str(event.get("work_order_id", "")))
        message.set_body(json.dumps(event, ensure_ascii=False))
        result = producer.send_sync(message)
        print(
            "[workorder-status] event sent "
            f"topic={EVENT_TOPIC} tag={DEVICE_ID} status={event.get('status')} "
            f"msg_id={result.msg_id}"
        )
        return True
    except Exception as exc:
        print(f"[workorder-status] failed to send event: {exc}", file=sys.stderr)
        return False
    finally:
        try:
            producer.shutdown()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Set or query device work-order status.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("work_order_id")
    set_parser.add_argument("status", choices=sorted(VALID_STATUSES))
    set_parser.add_argument("--details-json", default="{}")
    set_parser.add_argument("--no-emit", action="store_true")

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("work_order_id")

    args = parser.parse_args()

    if args.command == "set":
        details = json.loads(args.details_json)
        event = set_status(args.work_order_id, args.status, details, emit=not args.no_emit)
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return 0

    status = get_status(args.work_order_id)
    print(json.dumps(status or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
