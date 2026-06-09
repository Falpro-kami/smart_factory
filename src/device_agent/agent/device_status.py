#!/usr/bin/env python3
"""Device status persistence and event reporting."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sqlite3
import sys
from pathlib import Path


AGENT_DIR = Path("/home/lx/dev_ws/src/device_agent/agent")
STATUS_DB_FILE = AGENT_DIR / "device_status.sqlite3"
ROCKETMQ_NAMESRV = os.getenv("ROCKETMQ_NAMESRV", "192.168.1.10:9876")
DEVICE_ID = os.getenv("DEVICE_AGENT_TAG", "DEV002")
EVENT_TOPIC = os.getenv("DEVICE_EVENT_TOPIC", "DeviceEventReport")
EVENT_PRODUCER_GROUP = os.getenv("DEVICE_EVENT_PRODUCER_GROUP", "device-agent-event-producer")
VALID_CONNECTION_STATES = {"offline", "online"}
VALID_STATUSES = {"offline", "idle", "busy", "paused", "error", "maintenance"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_db() -> None:
    STATUS_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATUS_DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_status (
                device_id TEXT PRIMARY KEY,
                connection_state TEXT NOT NULL,
                status TEXT NOT NULL,
                previous_status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                connection_state TEXT NOT NULL,
                status TEXT NOT NULL,
                previous_status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        migrate_mode_to_connection_state(connection, "device_status")
        migrate_mode_to_connection_state(connection, "device_status_history")


def migrate_mode_to_connection_state(connection: sqlite3.Connection, table_name: str) -> None:
    columns = [
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]
    if "mode" not in columns or "connection_state" in columns:
        return

    connection.execute(f"ALTER TABLE {table_name} RENAME COLUMN mode TO connection_state")


def get_status() -> dict | None:
    init_db()
    with sqlite3.connect(STATUS_DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT device_id, connection_state, status, previous_status, updated_at
            FROM device_status
            WHERE device_id = ?
            """,
            (DEVICE_ID,),
        ).fetchone()

    if row is None:
        return None

    return {
        "device_id": row[0],
        "connection_state": row[1],
        "status": row[2],
        "previous_status": row[3],
        "updated_at": row[4],
    }


def set_status(connection_state: str, status: str, emit: bool = True) -> dict:
    if connection_state not in VALID_CONNECTION_STATES:
        raise ValueError(f"invalid device connection_state: {connection_state}")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid device status: {status}")

    init_db()
    updated_at = now_iso()
    current = get_status()
    previous_status = current["status"] if current else None

    with sqlite3.connect(STATUS_DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO device_status
                (device_id, connection_state, status, previous_status, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                connection_state = excluded.connection_state,
                status = excluded.status,
                previous_status = excluded.previous_status,
                updated_at = excluded.updated_at
            """,
            (DEVICE_ID, connection_state, status, previous_status, updated_at),
        )
        connection.execute(
            """
            INSERT INTO device_status_history
                (device_id, connection_state, status, previous_status, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (DEVICE_ID, connection_state, status, previous_status, updated_at),
        )

    event = {
        "event_type": "device_status_changed",
        "device_id": DEVICE_ID,
        "connection_state": connection_state,
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
        print(f"[device-status] rocketmq client unavailable: {exc}", file=sys.stderr)
        return False

    producer = Producer(EVENT_PRODUCER_GROUP)
    producer.set_name_server_address(ROCKETMQ_NAMESRV)
    try:
        producer.start()
        message = Message(EVENT_TOPIC)
        message.set_tags(DEVICE_ID)
        message.set_keys(DEVICE_ID)
        message.set_body(json.dumps(event, ensure_ascii=False))
        result = producer.send_sync(message)
        print(
            "[device-status] event sent "
            f"topic={EVENT_TOPIC} tag={DEVICE_ID} status={event.get('status')} "
            f"msg_id={result.msg_id}"
        )
        return True
    except Exception as exc:
        print(f"[device-status] failed to send event: {exc}", file=sys.stderr)
        return False
    finally:
        try:
            producer.shutdown()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Set or query device status.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("connection_state", choices=sorted(VALID_CONNECTION_STATES))
    set_parser.add_argument("status", choices=sorted(VALID_STATUSES))
    set_parser.add_argument("--no-emit", action="store_true")

    subparsers.add_parser("get")

    args = parser.parse_args()

    if args.command == "set":
        event = set_status(args.connection_state, args.status, emit=not args.no_emit)
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return 0

    status = get_status()
    print(json.dumps(status or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
