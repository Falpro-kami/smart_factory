#!/usr/bin/env python3
"""Start the full simulated device-agent stack."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import argparse
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


SRC_ROOT = Path(__file__).resolve().parent
WS_ROOT = SRC_ROOT.parent.parent
VENV_PYTHON = SRC_ROOT / ".venv" / "bin" / "python"
ROS_SETUP = "/opt/ros/jazzy/setup.bash"
WS_SETUP = WS_ROOT / "install" / "setup.bash"
LOG_DIR = WS_ROOT / "log" / "device_agent_main"


@dataclass(frozen=True)
class ManagedProcess:
    name: str
    command: str
    startup_delay_sec: float = 0.0
    health_url: str | None = None
    mirror_patterns: tuple[str, ...] = ()


def ros_command(command: str) -> str:
    return (
        f"cd {WS_ROOT} && "
        f"source {ROS_SETUP} && "
        f"source {WS_SETUP} && "
        f"{command}"
    )


def python_command(script: Path, env: dict[str, str] | None = None) -> str:
    env_prefix = ""
    if env:
        env_prefix = " ".join(f"{key}={value}" for key, value in env.items()) + " "
    return f"cd {WS_ROOT} && {env_prefix}{VENV_PYTHON} {script}"


def start_process(spec: ManagedProcess) -> subprocess.Popen:
    if spec.health_url and is_http_healthy(spec.health_url):
        print(f"[main] {spec.name} already running: {spec.health_url}")
        return subprocess.Popen(["true"])

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{spec.name}.log"
    log_file = log_path.open("a", encoding="utf-8")
    print(f"[main] starting {spec.name}, log: {log_path}")
    if spec.mirror_patterns:
        process = subprocess.Popen(
            ["bash", "-lc", spec.command],
            cwd=str(WS_ROOT),
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(
            target=pump_process_output,
            args=(spec, process, log_file),
            daemon=True,
        ).start()
        if spec.startup_delay_sec > 0:
            time.sleep(spec.startup_delay_sec)
        return process

    process = subprocess.Popen(
        ["bash", "-lc", spec.command],
        cwd=str(WS_ROOT),
        start_new_session=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    if spec.startup_delay_sec > 0:
        time.sleep(spec.startup_delay_sec)
    log_file.close()
    return process


def pump_process_output(
    spec: ManagedProcess,
    process: subprocess.Popen,
    log_file,
) -> None:
    try:
        if process.stdout is None:
            return
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()
            if any(pattern in line for pattern in spec.mirror_patterns):
                print(line, end="", file=sys.stdout, flush=True)
    finally:
        log_file.close()


def is_http_healthy(url: str) -> bool:
    try:
        with urlopen(url, timeout=1.0) as response:
            return 200 <= response.status < 300
    except (URLError, TimeoutError, OSError):
        return False


def terminate_process(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    print(f"[main] stopping {name}")
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        print(f"[main] killing {name}")
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def report_device_stopped() -> None:
    command = python_command(SRC_ROOT / "agent" / "device_status.py")
    subprocess.call(
        ["bash", "-lc", f"{command} set offline offline"],
        cwd=str(WS_ROOT),
    )


def report_device_started() -> None:
    command = python_command(SRC_ROOT / "agent" / "device_status.py")
    subprocess.call(
        ["bash", "-lc", f"{command} set online idle"],
        cwd=str(WS_ROOT),
    )


def run_agent_foreground(input_source: str) -> int:
    command = python_command(
        SRC_ROOT / "agent" / "claude_agent_cli.py",
        {"DEVICE_AGENT_INPUT_SOURCE": input_source},
    )
    print("[main] starting claude_agent_cli in foreground")
    return subprocess.call(["bash", "-lc", command], cwd=str(WS_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the simulated device-agent stack.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Use terminal input for local debugging instead of upper-system messages.",
    )
    parser.add_argument(
        "--virtual-devices",
        action="store_true",
        help="Start temporary virtual devices DEV001/DEV003/DEV004/DEV005.",
    )
    args = parser.parse_args()

    input_source = "debug" if args.debug else "production"
    processes: list[tuple[str, subprocess.Popen]] = []
    specs = []
    if not args.debug:
        report_device_started()
        specs.append(
            ManagedProcess(
                "device_adapter_service",
                python_command(SRC_ROOT / "agent" / "device_adapter_service.py"),
                startup_delay_sec=1.0,
                health_url="http://127.0.0.1:8765/health",
            )
        )
        specs.append(
            ManagedProcess(
                "device_heartbeat",
                python_command(SRC_ROOT / "agent" / "device_heartbeat.py"),
                startup_delay_sec=0.0,
            )
        )
        if args.virtual_devices:
            specs.append(
                ManagedProcess(
                    "virtual_devices",
                    python_command(SRC_ROOT / "agent" / "virtual_devices.py"),
                    startup_delay_sec=1.0,
                    mirror_patterns=(
                        "已收到工单",
                        "开始执行工单",
                        "工单已完成",
                    ),
                )
            )

    specs.extend(
        [
            ManagedProcess(
                "mujoco_moveit_rviz",
                ros_command(
                    "ros2 launch ur5e_2f85_moveit_config demo.launch.py "
                    "headless:=false rviz:=true"
                ),
                startup_delay_sec=10.0,
            ),
            ManagedProcess(
                "moveitpy_server",
                ros_command(f"{VENV_PYTHON} {SRC_ROOT / 'moveitpy_tools' / 'moveitpy_server.py'}"),
                startup_delay_sec=3.0,
            ),
        ]
    )

    try:
        for spec in specs:
            process = start_process(spec)
            processes.append((spec.name, process))
            if process.poll() is not None:
                print(f"[main] {spec.name} exited early with code {process.returncode}")
                return process.returncode or 1

        return run_agent_foreground(input_source)
    except KeyboardInterrupt:
        print()
        print("[main] interrupted")
        return 130
    finally:
        for name, process in reversed(processes):
            terminate_process(name, process)
        if not args.debug:
            report_device_stopped()


if __name__ == "__main__":
    raise SystemExit(main())
