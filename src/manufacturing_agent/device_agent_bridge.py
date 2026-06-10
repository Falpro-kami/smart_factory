"""Request/reply bridge from the manufacturing agent to device agents."""

from __future__ import annotations

import json
import os
import queue
import time
import uuid
from datetime import datetime
from typing import Any


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rocketmq_namesrv() -> str:
    return os.environ.get("ROCKETMQ_NAMESRV_ADDR") or os.environ.get("ROCKETMQ_NAMESRV") or "127.0.0.1:9876"


def send_device_agent_command_sync(
    *,
    device_id: str,
    instruction: str,
    timeout_sec: int = 60,
) -> dict[str, Any]:
    """Send a natural-language command to a device agent and wait for its reply."""
    try:
        from rocketmq.client import ConsumeStatus, Message, Producer, PushConsumer
    except Exception as exc:
        raise RuntimeError("rocketmq-client-python is not installed") from exc

    target_device_id = device_id.strip()
    command_text = instruction.strip()
    if not target_device_id:
        raise ValueError("device_id is required")
    if not command_text:
        raise ValueError("instruction is required")

    request_id = f"device-chat-{uuid.uuid4()}"
    namesrv = rocketmq_namesrv()
    command_topic = os.environ.get("DEVICE_AGENT_COMMAND_TOPIC", "DeviceAgentCommand")
    reply_topic = os.environ.get("DEVICE_AGENT_REPLY_TOPIC", "DeviceAgentReply")
    reply_tag = os.environ.get("MANUFACTURING_AGENT_REPLY_TAG", "manufacturing_agent")
    producer_group = os.environ.get("DEVICE_AGENT_COMMAND_PRODUCER_GROUP", "manufacturing-agent-device-command-producer")
    consumer_group = f"manufacturing-agent-device-reply-{request_id}"
    replies: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

    consumer = PushConsumer(consumer_group)
    consumer.set_name_server_address(namesrv)
    consumer.set_instance_name(consumer_group)

    def on_reply(message: Any):
        try:
            body = message.body.decode("utf-8")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return ConsumeStatus.CONSUME_SUCCESS
            if str(payload.get("request_id") or "") != request_id:
                return ConsumeStatus.CONSUME_SUCCESS
            try:
                replies.put_nowait(payload)
            except queue.Full:
                pass
            return ConsumeStatus.CONSUME_SUCCESS
        except Exception:
            return ConsumeStatus.RECONSUME_LATER

    producer = Producer(producer_group)
    producer.set_name_server_address(namesrv)
    consumer_started = False
    producer_started = False
    try:
        consumer.subscribe(reply_topic, on_reply, expression=reply_tag)
        consumer.start()
        consumer_started = True

        producer.start()
        producer_started = True
        payload = {
            "request_id": request_id,
            "source": "manufacturing_agent",
            "target_device_id": target_device_id,
            "instruction": command_text,
            "created_at": now_iso(),
        }
        message = Message(command_topic)
        message.set_tags(target_device_id)
        message.set_keys(request_id)
        message.set_body(json.dumps(payload, ensure_ascii=False))
        send_result = producer.send_sync(message)

        try:
            reply = replies.get(timeout=max(1, int(timeout_sec)))
        except queue.Empty:
            return {
                "success": False,
                "status": "timeout",
                "request_id": request_id,
                "device_id": target_device_id,
                "instruction": command_text,
                "sent": True,
                "send_result": str(send_result),
                "message_id": str(getattr(send_result, "msg_id", "")),
                "timeout_sec": int(timeout_sec),
                "created_at": payload["created_at"],
                "finished_at": now_iso(),
            }

        return {
            "success": reply.get("status") == "completed",
            "status": str(reply.get("status") or "completed"),
            "request_id": request_id,
            "device_id": target_device_id,
            "instruction": command_text,
            "reply": str(reply.get("reply") or ""),
            "sent": True,
            "send_result": str(send_result),
            "message_id": str(getattr(send_result, "msg_id", "")),
            "device_reply": reply,
            "created_at": payload["created_at"],
            "finished_at": now_iso(),
        }
    finally:
        if producer_started:
            try:
                producer.shutdown()
            except Exception:
                pass
        if consumer_started:
            time.sleep(0.1)
            try:
                consumer.shutdown()
            except Exception:
                pass
