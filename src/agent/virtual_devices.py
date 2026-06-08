#!/usr/bin/env python3
"""Temporary virtual devices for production-flow testing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time


ROCKETMQ_NAMESRV = os.getenv("ROCKETMQ_NAMESRV", "192.168.1.10:9876")
WORKORDER_TOPIC = os.getenv("DEVICE_WORKORDER_TOPIC", "WorkOrderDeliver")
EVENT_TOPIC = os.getenv("DEVICE_EVENT_TOPIC", "DeviceEventReport")
DEFAULT_DEVICES = ["DEV001", "DEV003", "DEV004", "DEV005"]
DEVICE_NAMES = {
    "DEV001": "立体库",
    "DEV002": "装配工作站",
    "DEV003": "质检工作站",
    "DEV004": "贴标工作站",
    "DEV005": "AGV小车",
}
HEARTBEAT_INTERVAL_SEC = float(os.getenv("VIRTUAL_DEVICE_HEARTBEAT_INTERVAL_SEC", "10"))
RUNNING_SECONDS = float(os.getenv("VIRTUAL_DEVICE_RUNNING_SECONDS", "10"))
STOP = False
SEND_LOCK = threading.Lock()
ConsumeStatus = None
Message = None
Producer = None
PushConsumer = None


def load_rocketmq_client() -> None:
    global ConsumeStatus, Message, Producer, PushConsumer
    if Producer is not None:
        return
    from rocketmq.client import (
        ConsumeStatus as RocketConsumeStatus,
        Message as RocketMessage,
        Producer as RocketProducer,
        PushConsumer as RocketPushConsumer,
    )

    ConsumeStatus = RocketConsumeStatus
    Message = RocketMessage
    Producer = RocketProducer
    PushConsumer = RocketPushConsumer


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stop(_signum=None, _frame=None) -> None:
    global STOP
    STOP = True


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

    if isinstance(payload, dict):
        return payload
    return {"instruction": body, "payload": payload}


def work_order_id_from_payload(payload: dict, message) -> str:
    for key in ("work_order_id", "workorder_id", "order_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    key = decode_optional(message.keys)
    if key:
        return key
    return f"WO-{message.id}"


def send_event(device_id: str, event: dict, key: str) -> bool:
    load_rocketmq_client()
    with SEND_LOCK:
        producer_group = f"vd-{device_id}-{os.getpid()}-{time.time_ns()}"
        producer = Producer(producer_group)
        producer.set_name_server_address(ROCKETMQ_NAMESRV)
        try:
            producer.start()
            message = Message(EVENT_TOPIC)
            message.set_tags(device_id)
            message.set_keys(key)
            message.set_body(json.dumps(event, ensure_ascii=False))
            result = producer.send_sync(message)
            print(
                f"[virtual-device:{device_id}] sent {event['event_type']} "
                f"status={event.get('status')} msg_id={result.msg_id}",
                flush=True,
            )
            return True
        except Exception as exc:
            print(f"[virtual-device:{device_id}] failed to send event: {exc}", flush=True)
            return False
        finally:
            try:
                producer.shutdown()
            except Exception:
                pass


def send_device_status(device_id: str, connection_state: str, status: str) -> None:
    event = {
        "event_type": "device_status_changed",
        "device_id": device_id,
        "connection_state": connection_state,
        "status": status,
        "previous_status": None,
        "timestamp": now_iso(),
    }
    send_event(device_id, event, device_id)


def send_heartbeat(device_id: str, status: str) -> None:
    event = {
        "event_type": "device_heartbeat",
        "device_id": device_id,
        "connection_state": "online",
        "status": status,
        "timestamp": now_iso(),
    }
    send_event(device_id, event, device_id)


def send_workorder_status(
    device_id: str,
    work_order_id: str,
    status: str,
    previous_status: str | None,
) -> None:
    event = {
        "event_type": "workorder_status_changed",
        "device_id": device_id,
        "work_order_id": work_order_id,
        "status": status,
        "previous_status": previous_status,
        "timestamp": now_iso(),
    }
    send_event(device_id, event, work_order_id)


class VirtualDevice:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.device_name = DEVICE_NAMES.get(device_id, device_id)
        self.status = "idle"
        self.lock = threading.Lock()
        self.consumer: object | None = None
        self.workorders: queue.Queue[str] = queue.Queue()

    def set_device_status(self, connection_state: str, status: str) -> None:
        with self.lock:
            self.status = status
        send_device_status(self.device_id, connection_state, status)

    def start(self) -> None:
        load_rocketmq_client()
        with self.lock:
            self.status = "idle"
        self.consumer = PushConsumer(
            f"virtual-device-{self.device_id}-message-consumer-{WORKORDER_TOPIC}"
        )
        self.consumer.set_name_server_address(ROCKETMQ_NAMESRV)
        self.consumer.set_instance_name(f"virtual-device-{self.device_id}-{os.getpid()}")
        self.consumer.subscribe(WORKORDER_TOPIC, self.on_message, expression=self.device_id)
        self.consumer.start()
        print(
            f"[virtual-device:{self.device_id}] consumer started "
            f"topic={WORKORDER_TOPIC} tag={self.device_id}",
            flush=True,
        )
        send_device_status(self.device_id, "online", "idle")

    def shutdown(self) -> None:
        if self.consumer is not None:
            self.consumer.shutdown()
        self.set_device_status("offline", "offline")

    def on_message(self, message):
        try:
            payload = payload_from_message(message)
            work_order_id = work_order_id_from_payload(payload, message)
            print(
                f"[virtual-device:{self.device_id}:{self.device_name}] 已收到工单，等待执行 "
                f"work_order_id={work_order_id} msg_id={message.id}",
                flush=True,
            )
            self.workorders.put(work_order_id)
            return ConsumeStatus.CONSUME_SUCCESS
        except Exception as exc:
            print(f"[virtual-device:{self.device_id}] failed to handle message: {exc}")
            return ConsumeStatus.RECONSUME_LATER

    def process_workorder(self, work_order_id: str) -> None:
        print(
            f"[virtual-device:{self.device_id}:{self.device_name}] 开始执行工单 "
            f"work_order_id={work_order_id}",
            flush=True,
        )
        send_workorder_status(self.device_id, work_order_id, "received", None)
        send_workorder_status(self.device_id, work_order_id, "running", "received")
        self.set_device_status("online", "busy")
        time.sleep(RUNNING_SECONDS)
        send_workorder_status(self.device_id, work_order_id, "succeeded", "running")
        self.set_device_status("online", "idle")
        print(
            f"[virtual-device:{self.device_id}:{self.device_name}] 工单已完成 "
            f"work_order_id={work_order_id}",
            flush=True,
        )

    def heartbeat_loop(self) -> None:
        while not STOP:
            with self.lock:
                status = self.status
            if status != "offline":
                send_heartbeat(self.device_id, status)
            time.sleep(HEARTBEAT_INTERVAL_SEC)

    def workorder_loop(self) -> None:
        while not STOP:
            try:
                work_order_id = self.workorders.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process_workorder(work_order_id)
            finally:
                self.workorders.task_done()


def parse_devices(value: str) -> list[str]:
    return [device.strip() for device in value.split(",") if device.strip()]


def run_parent_process(device_ids: list[str]) -> int:
    children: list[subprocess.Popen] = []
    try:
        for device_id in device_ids:
            child = subprocess.Popen(
                [sys.executable, __file__, "--devices", device_id],
                cwd=os.getcwd(),
            )
            children.append(child)
            print(f"[virtual-devices] started {device_id} pid={child.pid}", flush=True)

        while not STOP:
            for child in children:
                if child.poll() is not None:
                    print(
                        f"[virtual-devices] child pid={child.pid} exited "
                        f"code={child.returncode}",
                        flush=True,
                    )
                    return child.returncode or 1
            time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 8
        for child in children:
            remaining = max(0, deadline - time.monotonic())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
    return 0


def run_single_device(device_id: str) -> int:
    device = VirtualDevice(device_id)
    device.start()
    threading.Thread(target=device.workorder_loop, daemon=True).start()
    threading.Thread(target=device.heartbeat_loop, daemon=True).start()

    try:
        while not STOP:
            time.sleep(0.5)
    finally:
        device.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run temporary virtual devices.")
    parser.add_argument(
        "--devices",
        default=",".join(DEFAULT_DEVICES),
        help="Comma-separated virtual device ids.",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    device_ids = parse_devices(args.devices)
    if len(device_ids) > 1:
        return run_parent_process(device_ids)
    if len(device_ids) == 1:
        return run_single_device(device_ids[0])

    print("[virtual-devices] no devices configured", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
