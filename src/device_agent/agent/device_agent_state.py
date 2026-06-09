#!/usr/bin/env python3
"""CLI tool for reading and switching the device-agent state."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from device_status import set_status as set_device_status


STATE_FILE = Path("/home/lx/dev_ws/src/device_agent/agent/device_agent_state.json")
VALID_MODES = {"offline", "online"}


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"mode": "offline"}

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"mode": "offline"}

    if state.get("mode") not in VALID_MODES:
        state["mode"] = "offline"
    return state


def write_state(mode: str) -> None:
    if mode not in VALID_MODES:
        raise SystemExit(f"invalid mode: {mode}. expected one of: offline, online")

    STATE_FILE.write_text(
        json.dumps({"mode": mode}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if mode == "online":
        set_device_status("online", "idle")
    else:
        set_device_status("offline", "offline")


def main() -> int:
    if len(sys.argv) == 1 or sys.argv[1] in {"get", "status"}:
        print(read_state()["mode"])
        return 0

    if sys.argv[1] == "set":
        if len(sys.argv) != 3:
            raise SystemExit("usage: device_agent_state.py set offline|online")
        write_state(sys.argv[2])
        print(f"mode={sys.argv[2]}")
        return 0

    raise SystemExit("usage: device_agent_state.py [get|status|set offline|online]")


if __name__ == "__main__":
    raise SystemExit(main())
