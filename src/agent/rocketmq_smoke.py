#!/usr/bin/env python3
"""Minimal RocketMQ send/receive smoke test for the device agent."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from threading import Event

from rocketmq.client import ConsumeStatus, Message, Producer, PushConsumer


DEFAULT_NAMESRV = "192.168.1.10:9876"
WORKORDER_TOPIC = "WorkOrderDeliver"
EVENT_TOPIC = "DeviceEventReport"
DEFAULT_DEVICE_TAG = os.getenv("DEVICE_AGENT_TAG", "DEV002")


def namesrv_addr() -> str:
    return os.getenv("ROCKETMQ_NAMESRV", DEFAULT_NAMESRV)


def make_payload(kind: str) -> dict:
    if kind == "workorder":
        return {
            "workorder_id": f"smoke-{uuid.uuid4()}",
            "device_id": "device-192.168.1.3",
            "instruction": "测试设备智能体 RocketMQ 工单接收链路",
            "timestamp": time.time(),
        }

    return {
        "event_id": f"smoke-{uuid.uuid4()}",
        "event_type": "smoke_test",
        "device_id": "device-192.168.1.3",
        "status": "ok",
        "timestamp": time.time(),
    }


def send_message(topic: str, tag: str, payload: dict) -> None:
    producer = Producer("device-agent-smoke-producer")
    producer.set_name_server_address(namesrv_addr())
    producer.start()
    try:
        body = json.dumps(payload, ensure_ascii=False)
        message = Message(topic)
        message.set_tags(tag)
        message.set_keys(payload.get("workorder_id") or payload.get("event_id") or str(uuid.uuid4()))
        message.set_body(body)
        result = producer.send_sync(message)
        print("SEND_OK")
        print(f"namesrv={namesrv_addr()}")
        print(f"topic={topic}")
        print(f"status={result.status.name}")
        print(f"msg_id={result.msg_id}")
        print(f"offset={result.offset}")
        print(f"body={body}")
    finally:
        producer.shutdown()


def consume_once(topic: str, group: str, timeout_sec: int) -> int:
    received = Event()
    exit_code = 1

    def callback(message):
        nonlocal exit_code
        body = message.body.decode("utf-8")
        print("RECEIVE_OK")
        print(f"namesrv={namesrv_addr()}")
        print(f"topic={message.topic}")
        print(f"tags={decode_optional(message.tags)}")
        print(f"keys={decode_optional(message.keys)}")
        print(f"msg_id={message.id}")
        print(f"body={body}")
        exit_code = 0
        received.set()
        return ConsumeStatus.CONSUME_SUCCESS

    consumer = PushConsumer(group)
    consumer.set_name_server_address(namesrv_addr())
    consumer.set_instance_name(f"{group}-{uuid.uuid4()}")
    consumer.subscribe(topic, callback)
    consumer.start()
    print(f"waiting topic={topic} namesrv={namesrv_addr()} timeout={timeout_sec}s")
    try:
        if not received.wait(timeout_sec):
            print(f"TIMEOUT topic={topic}")
            return 1
        return exit_code
    finally:
        consumer.shutdown()


def decode_optional(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="RocketMQ smoke test.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_workorder = subparsers.add_parser("send-workorder")
    send_workorder.add_argument("--topic", default=WORKORDER_TOPIC)
    send_workorder.add_argument("--tag", default=DEFAULT_DEVICE_TAG)

    send_event = subparsers.add_parser("send-event")
    send_event.add_argument("--topic", default=EVENT_TOPIC)
    send_event.add_argument("--tag", default=DEFAULT_DEVICE_TAG)

    consume_workorder = subparsers.add_parser("consume-workorder-once")
    consume_workorder.add_argument("--topic", default=WORKORDER_TOPIC)
    consume_workorder.add_argument("--timeout", type=int, default=30)

    consume_event = subparsers.add_parser("consume-event-once")
    consume_event.add_argument("--topic", default=EVENT_TOPIC)
    consume_event.add_argument("--timeout", type=int, default=30)

    args = parser.parse_args()

    if args.command == "send-workorder":
        send_message(args.topic, args.tag, make_payload("workorder"))
        return 0
    if args.command == "send-event":
        send_message(args.topic, args.tag, make_payload("event"))
        return 0
    if args.command == "consume-workorder-once":
        return consume_once(args.topic, "device-agent-smoke-workorder-consumer", args.timeout)
    if args.command == "consume-event-once":
        return consume_once(args.topic, "device-agent-smoke-event-consumer", args.timeout)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
