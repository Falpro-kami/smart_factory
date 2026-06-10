#!/usr/bin/env python3
"""Natural-language terminal for the robot agent."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from device_workorder_status import set_status


PROJECT_DIR = Path(__file__).resolve().parents[1]
ONLINE_POLL_INTERVAL_SEC = 1.0
ADAPTER_URL = os.getenv("DEVICE_AGENT_ADAPTER_URL", "http://127.0.0.1:8765")
INPUT_SOURCE = os.getenv("DEVICE_AGENT_INPUT_SOURCE", "production")
VALID_INPUT_SOURCES = {"production", "debug"}
ROCKETMQ_NAMESRV = os.getenv("ROCKETMQ_NAMESRV", "192.168.1.10:9876")
DEVICE_ID = os.getenv("DEVICE_AGENT_TAG", "DEV002")
REPLY_TOPIC = os.getenv("DEVICE_AGENT_REPLY_TOPIC", "DeviceAgentReply")
REPLY_TAG = os.getenv("MANUFACTURING_AGENT_REPLY_TAG", "manufacturing_agent")
REPLY_PRODUCER_GROUP = os.getenv("DEVICE_AGENT_REPLY_PRODUCER_GROUP", "device-agent-reply-producer")


def build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        tools={"type": "preset", "preset": "claude_code"},
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": (
                "You are the natural-language entrypoint for a ROS 2 MuJoCo "
                "robot simulation workspace. First use the top-level "
                "device-agent skill for upper-message routing, then use "
                "robot-control, vision-realize, task-generator, or "
                "task-executor as needed. Before commands that move the robot, "
                "state what command you are about to run and why. Device startup "
                "is controlled by src/device_agent/main.py. In production input mode, wait for "
                "upper-system messages; in debug input mode, accept terminal user input."
            ),
        },
        cwd=PROJECT_DIR,
        setting_sources=["user", "project", "local"],
        skills="all",
        include_partial_messages=True,
    )


def stream_text_from_event(event: dict) -> str:
    if event.get("type") == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            return delta.get("text", "")
    return ""


def print_assistant_text(message) -> bool:
    printed = False
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            print(block.text, end="" if block.text.endswith("\n") else "\n")
            printed = True

    result = getattr(message, "result", None)
    if result:
        print(result)
        printed = True

    return printed


def assistant_text_from_message(message) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(str(block.text))

    result = getattr(message, "result", None)
    if result:
        parts.append(str(result))

    return "".join(parts)


def print_help() -> None:
    print("调试输入模式下，可直接输入自然语言与设备智能体交互。")
    print("本地命令: /source 查看输入源, /help 帮助, exit 退出。")


def read_prompt() -> str:
    return input("用户: ").strip()


def handle_cli_command(command: str) -> bool:
    if command == "/source":
        print(f"当前输入源: {INPUT_SOURCE}")
        return True

    if command == "/help":
        print_help()
        return True

    return False


def pop_online_message_from_adapter() -> dict | None:
    try:
        with urlopen(f"{ADAPTER_URL}/messages/next", timeout=2.0) as response:
            if response.status == 204:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 204:
            return None
        return None
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None

    message = payload.get("message")
    if isinstance(message, dict):
        work_order_id = work_order_id_from_payload(message)
        if work_order_id:
            set_status(work_order_id, "running", message)
        return {
            "prompt": json.dumps(message, ensure_ascii=False, indent=2),
            "payload": message,
        }

    instruction = payload.get("instruction")
    if isinstance(instruction, str) and instruction.strip():
        return {
            "prompt": instruction.strip(),
            "payload": {"instruction": instruction.strip()},
        }
    return None


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


async def wait_for_online_message() -> dict | None:
    print(f"生产输入已启用，等待上层消息 adapter: {ADAPTER_URL}")
    while True:
        context = pop_online_message_from_adapter()
        if context:
            print(f"上层: {context['prompt']}")
            return context
        await asyncio.sleep(ONLINE_POLL_INTERVAL_SEC)

    return None


def publish_device_agent_reply(source_payload: dict, reply: str, status: str = "completed") -> bool:
    request_id = str(source_payload.get("request_id") or "").strip()
    if not request_id:
        return False

    try:
        from rocketmq.client import Message, Producer
    except Exception as exc:
        print(f"[device-agent] rocketmq client unavailable: {exc}", file=sys.stderr)
        return False

    payload = {
        "request_id": request_id,
        "device_id": DEVICE_ID,
        "status": status,
        "reply": reply,
        "source": "device_agent",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    producer = Producer(REPLY_PRODUCER_GROUP)
    producer.set_name_server_address(ROCKETMQ_NAMESRV)
    try:
        producer.start()
        message = Message(REPLY_TOPIC)
        message.set_tags(REPLY_TAG)
        message.set_keys(request_id)
        message.set_body(json.dumps(payload, ensure_ascii=False))
        result = producer.send_sync(message)
        print(
            "[device-agent] reply sent "
            f"topic={REPLY_TOPIC} tag={REPLY_TAG} request_id={request_id} "
            f"msg_id={getattr(result, 'msg_id', '')}"
        )
        return True
    except Exception as exc:
        print(f"[device-agent] failed to send reply: {exc}", file=sys.stderr)
        return False
    finally:
        try:
            producer.shutdown()
        except Exception:
            pass


async def send_to_agent(client: ClaudeSDKClient, prompt: str) -> str:
    await client.query(prompt)
    print("Claude: ", end="", flush=True)
    saw_partial_text = False
    collected: list[str] = []
    async for message in client.receive_response():
        event = getattr(message, "event", None)
        if isinstance(event, dict):
            text = stream_text_from_event(event)
            if text:
                print(text, end="", flush=True)
                saw_partial_text = True
                collected.append(text)
            continue

        if not saw_partial_text:
            text = assistant_text_from_message(message)
            if text:
                print(text, end="" if text.endswith("\n") else "\n")
                collected.append(text)

    if saw_partial_text:
        print()
    return "".join(collected).strip()


async def main() -> int:
    if INPUT_SOURCE not in VALID_INPUT_SOURCES:
        raise SystemExit(
            f"invalid DEVICE_AGENT_INPUT_SOURCE={INPUT_SOURCE}. "
            "expected production or debug"
        )

    print(
        "设备智能体已启动，"
        f"输入源: {INPUT_SOURCE}，"
        f"设备接入状态: {'offline' if INPUT_SOURCE == 'debug' else 'online'}。"
    )
    if INPUT_SOURCE == "debug":
        print_help()

    client: ClaudeSDKClient | None = None
    try:
        while True:
            if INPUT_SOURCE == "debug":
                try:
                    prompt = read_prompt()
                except EOFError:
                    print()
                    break

                if not prompt:
                    continue
                if prompt.lower() in {"exit", "quit"} or prompt in {"退出", "结束"}:
                    break

                if handle_cli_command(prompt):
                    continue
                context = {"prompt": prompt, "payload": {}}
            else:
                context = await wait_for_online_message()
                if context is None:
                    continue
                prompt = str(context.get("prompt") or "")

            if client is None:
                client = ClaudeSDKClient(options=build_options())
                await client.connect()

            try:
                reply = await send_to_agent(client, prompt)
                publish_device_agent_reply(context.get("payload") or {}, reply, "completed")
            except Exception as exc:
                publish_device_agent_reply(context.get("payload") or {}, str(exc), "failed")
                raise
    finally:
        if client is not None:
            await client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
