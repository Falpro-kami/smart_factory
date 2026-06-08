#!/usr/bin/env python3
"""Periodic device heartbeat reporter."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

from device_status import DEVICE_ID, emit_status_event, get_status, now_iso


DEFAULT_INTERVAL_SEC = float(os.getenv("DEVICE_HEARTBEAT_INTERVAL_SEC", "10"))
STOP = False


def stop(_signum=None, _frame=None) -> None:
    global STOP
    STOP = True


def heartbeat_event() -> dict:
    status = get_status() or {
        "device_id": DEVICE_ID,
        "connection_state": "online",
        "status": "idle",
    }
    return {
        "event_type": "device_heartbeat",
        "device_id": DEVICE_ID,
        "connection_state": status.get("connection_state", "online"),
        "status": status.get("status", "idle"),
        "timestamp": now_iso(),
    }


def run_loop(interval_sec: float, once: bool = False) -> int:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not STOP:
        event = heartbeat_event()
        emit_status_event(event)
        print(json.dumps(event, ensure_ascii=False), flush=True)
        if once:
            return 0
        time.sleep(interval_sec)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Report periodic device heartbeat events.")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help="Heartbeat interval in seconds.",
    )
    parser.add_argument("--once", action="store_true", help="Send one heartbeat and exit.")
    args = parser.parse_args()

    if args.interval <= 0:
        print("interval must be greater than 0", file=sys.stderr)
        return 1

    return run_loop(args.interval, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
