#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
AGENT_DIR = SRC_ROOT / "agent"
TASK_LIBRARY_DIR = SRC_ROOT / ".claude" / "tasks"
JOB_LOG_DIR = SRC_ROOT.parent / "log" / "device_task_jobs"
MOVEITPY_CLI = SCRIPT_DIR / "moveitpy_cli.py"
sys.path.insert(0, str(AGENT_DIR))

SUPPORTED_OPERATIONS = {
    "HOME",
    "PTP",
    "LIN",
    "grasp",
    "get_tool_pose",
    "set_planning_time",
}


def set_workorder_status(work_order_id: str, status: str, details: dict) -> None:
    from device_workorder_status import set_status

    set_status(work_order_id, status, details)


def set_device_status(mode: str, status: str) -> None:
    from device_status import set_status

    set_status(mode, status)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute a JSON task by calling moveitpy_cli.py step by step."
    )
    parser.add_argument("json_path", nargs="?", help="Path to task JSON file.")
    parser.add_argument(
        "--process-id",
        help="Process id used to find a matching task JSON in the task library.",
    )
    parser.add_argument(
        "--task-dir",
        default=str(TASK_LIBRARY_DIR),
        help="Task library directory used with --process-id. Defaults to .claude/tasks.",
    )
    parser.add_argument(
        "--task-name",
        help="Top-level task key to execute. Defaults to the first list value in the JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated commands without executing them.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Execute in the foreground. By default, the task is submitted as a background job.",
    )
    parser.add_argument(
        "--run-job",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--work-order-id",
        default=os.getenv("DEVICE_CURRENT_WORK_ORDER_ID"),
        help="Work-order id used for status reporting.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between commands. Defaults to 1.0.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to run moveitpy_cli.py.",
    )
    return parser


def load_json_object(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def find_task_by_process_id(process_id: str, task_dir: Path) -> Path:
    if not task_dir.exists():
        raise FileNotFoundError(f"Task library does not exist: {task_dir}")

    matches: list[Path] = []
    for path in sorted(task_dir.glob("*.json")):
        try:
            data = load_json_object(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("process_id") == process_id:
            matches.append(path)

    if not matches:
        raise FileNotFoundError(
            f"No task JSON with process_id '{process_id}' under {task_dir}"
        )
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        raise ValueError(f"Multiple task JSON files match process_id '{process_id}': {joined}")
    return matches[0]


def resolve_task_path(args: argparse.Namespace) -> Path:
    if args.process_id:
        return find_task_by_process_id(
            args.process_id,
            Path(args.task_dir).expanduser().resolve(),
        ).resolve()

    if args.json_path:
        return Path(args.json_path).expanduser().resolve()

    raise ValueError("Either json_path or --process-id is required.")


def now_job_id() -> str:
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d%H%M%S")
    return f"JOB-{timestamp}-{os.getpid()}"


def load_task(path: Path, task_name: str | None) -> tuple[str, list[dict]]:
    data = load_json_object(path)

    if isinstance(data, list):
        return path.stem, data

    if not isinstance(data, dict):
        raise ValueError("Task JSON must be an object or a list.")

    if task_name is not None:
        steps = data.get(task_name)
        if not isinstance(steps, list):
            raise ValueError(f"Task key '{task_name}' must exist and contain a list.")
        return task_name, steps

    for key, value in data.items():
        if isinstance(value, list):
            return key, value

    raise ValueError("Task JSON object must contain at least one list task.")


def parameter_to_args(parameters: dict) -> list[str]:
    args = []
    for key, value in parameters.items():
        option = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                args.append(option)
            continue
        args.extend([option, str(value)])
    return args


def step_to_command(step: dict, python_executable: str) -> list[str]:
    if not isinstance(step, dict):
        raise ValueError("Each step must be a JSON object.")

    operation = step.get("operation")
    if not isinstance(operation, str):
        raise ValueError("Each step must contain string key 'operation'.")
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")

    parameters = step.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError(f"Step '{operation}' parameters must be a JSON object.")

    return [
        python_executable,
        str(MOVEITPY_CLI),
        operation,
        *parameter_to_args(parameters),
    ]


def run_step(index: int, command: list[str], dry_run: bool) -> bool:
    printable = " ".join(command)
    print(f"[{index}] {printable}")
    if dry_run:
        return True

    result = subprocess.run(command, text=True)
    if result.returncode != 0:
        print(f"Step {index} failed with exit code {result.returncode}.", file=sys.stderr)
        return False
    return True


def execute_task(args: argparse.Namespace) -> int:
    try:
        task_path = resolve_task_path(args)
        task_name, steps = load_task(task_path, args.task_name)
        commands = [step_to_command(step, args.python) for step in steps]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to load task: {exc}", file=sys.stderr)
        return 1

    print(f"Executing task '{task_name}' from {task_path}")
    for index, command in enumerate(commands, start=1):
        if not run_step(index, command, args.dry_run):
            return 1
        if index < len(commands) and args.delay > 0.0:
            print(f"Waiting {args.delay:.3f}s before next command...")
            if not args.dry_run:
                time.sleep(args.delay)
    return 0


def submit_background_job(args: argparse.Namespace) -> int:
    try:
        task_path = resolve_task_path(args)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to resolve task: {exc}", file=sys.stderr)
        return 1

    job_id = now_job_id()
    work_order_id = args.work_order_id or task_path.stem
    JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = JOB_LOG_DIR / f"{job_id}.log"

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        str(task_path),
        "--run-job",
        job_id,
        "--work-order-id",
        work_order_id,
        "--delay",
        str(args.delay),
        "--python",
        args.python,
    ]
    if args.task_name:
        command.extend(["--task-name", args.task_name])

    log_file = log_path.open("a", encoding="utf-8")
    subprocess.Popen(
        command,
        cwd=str(SRC_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "async",
                "job_id": job_id,
                "work_order_id": work_order_id,
                "task_path": str(task_path),
                "log_path": str(log_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    args = build_parser().parse_args()

    if not args.sync and not args.run_job and not args.dry_run:
        return submit_background_job(args)

    try:
        task_path = resolve_task_path(args)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to resolve task: {exc}", file=sys.stderr)
        return 1

    work_order_id = args.work_order_id or task_path.stem
    if args.run_job:
        set_workorder_status(
            work_order_id,
            "running",
            {
                "job_id": args.run_job,
                "task_path": str(task_path),
                "executor": "task_execute.py",
            },
        )
        set_device_status("online", "busy")

    result = execute_task(args)

    if args.run_job:
        set_workorder_status(
            work_order_id,
            "succeeded" if result == 0 else "failed",
            {
                "job_id": args.run_job,
                "task_path": str(task_path),
                "executor": "task_execute.py",
                "exit_code": result,
            },
        )
        set_device_status("online", "idle" if result == 0 else "error")
    return result


if __name__ == "__main__":
    sys.exit(main())
