#!/usr/bin/env python3
"""Local adapter service between the device agent and RocketMQ."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from rocketmq.client import ConsumeStatus, PushConsumer

from device_workorder_status import set_status


HOST = "127.0.0.1"
PORT = 8765
AGENT_DIR = Path("/home/lx/dev_ws/src/device_agent/agent")
EVENT_OUTBOX_FILE = AGENT_DIR / "device_events.jsonl"
PENDING_DB_FILE = AGENT_DIR / "device_adapter_pending.sqlite3"
ROCKETMQ_NAMESRV = os.getenv("ROCKETMQ_NAMESRV", "192.168.1.10:9876")
MESSAGE_TOPICS = [
    topic.strip()
    for topic in os.getenv(
        "DEVICE_AGENT_TOPICS",
        os.getenv("DEVICE_WORKORDER_TOPIC", "WorkOrderDeliver"),
    ).split(",")
    if topic.strip()
]
DEVICE_TAG = os.getenv("DEVICE_AGENT_TAG", "DEV002")
MESSAGE_CONSUMER_GROUP = os.getenv(
    "DEVICE_AGENT_CONSUMER_GROUP",
    f"device-agent-{DEVICE_TAG}-message-consumer",
)
DB_LOCK = threading.Lock()
ROCKETMQ_CONSUMERS: list[PushConsumer] = []


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def init_pending_db() -> None:
    PENDING_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PENDING_DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )


def enqueue_message(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    with DB_LOCK:
        with sqlite3.connect(PENDING_DB_FILE) as connection:
            connection.execute(
                "INSERT INTO pending_messages (payload, created_at) VALUES (?, ?)",
                (data, time.time()),
            )


def pop_message() -> dict | None:
    with DB_LOCK:
        with sqlite3.connect(PENDING_DB_FILE) as connection:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id, payload FROM pending_messages ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None

            connection.execute("DELETE FROM pending_messages WHERE id = ?", (row[0],))
            connection.execute("COMMIT")

    try:
        payload = json.loads(row[1])
    except json.JSONDecodeError:
        return {"instruction": row[1], "source": "adapter-sqlite"}

    if isinstance(payload, dict):
        return payload
    return {"instruction": json.dumps(payload, ensure_ascii=False), "source": "adapter-sqlite"}


def pending_message_count() -> int:
    with DB_LOCK:
        with sqlite3.connect(PENDING_DB_FILE) as connection:
            row = connection.execute("SELECT COUNT(*) FROM pending_messages").fetchone()
    return int(row[0])


def instruction_from_payload(payload: dict) -> str:
    for key in ("instruction", "task", "prompt", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(payload, ensure_ascii=False)


def decode_optional(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def payload_from_message(message) -> dict:
    body = message.body.decode("utf-8")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"instruction": body}

    if not isinstance(payload, dict):
        payload = {"instruction": body, "payload": payload}

    return payload


def metadata_from_message(message) -> dict:
    return {
        "source": "rocketmq",
        "received_timestamp": time.time(),
        "rocketmq": {
            "topic": message.topic,
            "tags": decode_optional(message.tags),
            "keys": decode_optional(message.keys),
            "msg_id": message.id,
        },
    }


def work_order_id_from_payload(payload: dict) -> str | None:
    for key in ("work_order_id", "workorder_id", "order_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    rocketmq = payload.get("rocketmq")
    if isinstance(rocketmq, dict):
        key = rocketmq.get("keys")
        if isinstance(key, str) and key.strip():
            return key.strip()

    return None


def report_workorder_status(payload: dict, status: str, details: dict | None = None) -> None:
    work_order_id = work_order_id_from_payload(payload)
    if not work_order_id:
        print(f"[adapter] skip status={status}: missing work_order_id")
        return
    set_status(work_order_id, status, details or payload)


def start_message_consumer(topic: str) -> PushConsumer:
    group = f"{MESSAGE_CONSUMER_GROUP}-{topic}"
    consumer = PushConsumer(group)
    consumer.set_name_server_address(ROCKETMQ_NAMESRV)
    consumer.set_instance_name(f"{group}-{os.getpid()}")

    def on_message(message):
        try:
            payload = payload_from_message(message)
            details = {
                "workorder": payload,
                **metadata_from_message(message),
            }
            report_workorder_status(payload, "received", details)
            enqueue_message(payload)
            print(
                "[adapter] cached device message "
                f"topic={message.topic} tag={decode_optional(message.tags)} "
                f"key={decode_optional(message.keys)} msg_id={message.id}"
            )
            return ConsumeStatus.CONSUME_SUCCESS
        except Exception as exc:
            print(f"[adapter] failed to handle RocketMQ message: {exc}")
            return ConsumeStatus.RECONSUME_LATER

    consumer.subscribe(topic, on_message, expression=DEVICE_TAG)
    consumer.start()
    print(
        "[adapter] RocketMQ consumer started: "
        f"namesrv={ROCKETMQ_NAMESRV}, topic={topic}, "
        f"tag={DEVICE_TAG}, group={group}"
    )
    return consumer


def start_message_consumers() -> list[PushConsumer]:
    return [start_message_consumer(topic) for topic in MESSAGE_TOPICS]


class AdapterHandler(BaseHTTPRequestHandler):
    server_version = "DeviceAgentAdapter/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[adapter] {self.address_string()} - {fmt % args}")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_empty(self, status: int) -> None:
        self.send_response(status)
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "device-agent-adapter",
                    "backend": "rocketmq",
                    "namesrv": ROCKETMQ_NAMESRV,
                    "topics": MESSAGE_TOPICS,
                    "device_tag": DEVICE_TAG,
                    "pending_messages": pending_message_count(),
                },
            )
            return

        if path == "/messages/next":
            payload = pop_message()
            if payload is None:
                self.send_empty(204)
                return
            self.send_json(
                200,
                {
                    "ok": True,
                    "message": payload,
                    "instruction": instruction_from_payload(payload),
                },
            )
            return

        self.send_json(404, {"ok": False, "error": f"unknown endpoint: {path}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
        except json.JSONDecodeError as exc:
            self.send_json(400, {"ok": False, "error": f"invalid json: {exc}"})
            return

        if path == "/workorders":
            if not isinstance(payload, dict):
                self.send_json(400, {"ok": False, "error": "payload must be an object"})
                return
            payload.setdefault("source", "adapter-http")
            payload.setdefault("timestamp", time.time())
            enqueue_message(payload)
            self.send_json(202, {"ok": True, "cached": instruction_from_payload(payload)})
            return

        if path == "/events":
            if not isinstance(payload, dict):
                self.send_json(400, {"ok": False, "error": "payload must be an object"})
                return
            payload.setdefault("source", "device-agent")
            payload.setdefault("timestamp", time.time())
            append_jsonl(EVENT_OUTBOX_FILE, payload)
            self.send_json(202, {"ok": True})
            return

        self.send_json(404, {"ok": False, "error": f"unknown endpoint: {path}"})


def main() -> int:
    global ROCKETMQ_CONSUMERS
    init_pending_db()
    server = ThreadingHTTPServer((HOST, PORT), AdapterHandler)
    ROCKETMQ_CONSUMERS = start_message_consumers()
    print(f"device-agent adapter listening on http://{HOST}:{PORT}")

    def stop(_signum=None, _frame=None) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
        return 0
    finally:
        for consumer in ROCKETMQ_CONSUMERS:
            consumer.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
