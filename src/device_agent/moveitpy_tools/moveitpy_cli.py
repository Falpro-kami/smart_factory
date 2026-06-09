#!/usr/bin/env python3
import argparse
import json
import socket
import sys


DEFAULT_SOCKET_PATH = "/tmp/moveitpy_server.sock"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-shot client for moveitpy_server. Planning commands inherit the server's automatic retries."
    )
    parser.add_argument(
        "command",
        choices=[
            "ping",
            "HOME",
            "PTP",
            "PTP_record",
            "LIN",
            "grasp",
            "get_tool_pose",
            "set_planning_time",
            "quit",
        ],
        help="Command to send to the persistent MoveItPy server.",
    )
    parser.add_argument("--socket-path", default=DEFAULT_SOCKET_PATH, help="Unix domain socket path.")
    parser.add_argument("--x", type=float, help="Pose goal x in world_frame.")
    parser.add_argument("--y", type=float, help="Pose goal y in world_frame.")
    parser.add_argument("--z", type=float, help="Pose goal z in world_frame.")
    parser.add_argument("--roll", type=float, help="Pose goal roll in radians (world_frame).")
    parser.add_argument("--pitch", type=float, help="Pose goal pitch in radians (world_frame).")
    parser.add_argument("--yaw", type=float, help="Pose goal yaw in radians (world_frame).")
    parser.add_argument("--dx", type=float, default=0.0, help="Cartesian offset x.")
    parser.add_argument("--dy", type=float, default=0.0, help="Cartesian offset y.")
    parser.add_argument("--dz", type=float, default=0.0, help="Cartesian offset z.")
    parser.add_argument(
        "--frame",
        choices=["world_frame", "tool_frame"],
        default="world_frame",
        help="Frame for --dx --dy --dz in LIN.",
    )
    parser.add_argument("--max-step", type=float, default=0.01, help="Cartesian interpolation step.")
    parser.add_argument("--state", type=int, choices=[0, 1], help="Gripper state: 1 closes, 0 opens.")
    parser.add_argument("--seconds", type=float, help="Planning time in seconds.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON responses.")
    return parser


def build_request(args: argparse.Namespace) -> dict:
    request = {"command": args.command}
    if args.command == "PTP_record":
        return {"command": "get_tool_pose"}
    if args.command == "PTP":
        if args.x is None or args.y is None or args.z is None:
            raise ValueError("PTP requires --x --y --z")
        request.update({"x": args.x, "y": args.y, "z": args.z})
        if args.roll is not None or args.pitch is not None or args.yaw is not None:
            if args.roll is None or args.pitch is None or args.yaw is None:
                raise ValueError("PTP requires --roll --pitch --yaw when specifying orientation")
            request.update({"roll": args.roll, "pitch": args.pitch, "yaw": args.yaw})
    if args.command == "LIN":
        if args.dx == 0.0 and args.dy == 0.0 and args.dz == 0.0:
            raise ValueError("LIN requires at least one of --dx --dy --dz")
        request.update(
            {
                "dx": args.dx,
                "dy": args.dy,
                "dz": args.dz,
                "frame": args.frame,
                "max_step": args.max_step,
                "avoid_collisions": True,
            }
        )
    if args.command == "grasp":
        if args.state is None:
            raise ValueError("grasp requires --state 1 or --state 0")
        request["state"] = args.state
    if args.command == "set_planning_time":
        if args.seconds is None:
            raise ValueError("set_planning_time requires --seconds")
        request["seconds"] = args.seconds
    return request


def build_ptp_record(pose_response: dict) -> dict:
    return {
        "operation": "PTP",
        "parameters": {
            "x": pose_response["x"],
            "y": pose_response["y"],
            "z": pose_response["z"],
            "roll": pose_response["roll"],
            "pitch": pose_response["pitch"],
            "yaw": pose_response["yaw"],
        },
    }


def send_request(socket_path: str, request: dict) -> str:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(socket_path)
            sock.sendall(json.dumps(request).encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            return sock.recv(65536).decode("utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "moveitpy_server is not running. Start it with: "
            "python3 src/moveitpy_tools/moveitpy_server.py"
        ) from exc
    except ConnectionRefusedError as exc:
        raise RuntimeError(f"Cannot connect to moveitpy_server at {socket_path}.") from exc
    except PermissionError as exc:
        raise RuntimeError(f"Permission denied while connecting to {socket_path}.") from exc


def main() -> int:
    args = build_parser().parse_args()
    try:
        request = build_request(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        response = send_request(args.socket_path, request)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.command == "PTP_record":
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            print(response)
            return 1
        if not parsed.get("ok"):
            print(json.dumps(parsed, ensure_ascii=False), file=sys.stderr)
            return 1
        record = build_ptp_record(parsed)
        print(json.dumps(record, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0

    if args.command in ("HOME", "PTP", "LIN"):
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            print(response)
            return 1
        if not parsed.get("ok"):
            print(response)
            return 1
        execute_response = send_request(args.socket_path, {"command": "execute_last"})
        output = {"plan": parsed, "execute": json.loads(execute_response)}
        print(json.dumps(output, indent=2 if args.pretty else None))
        return 0

    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        print(response)
        return 1
    print(json.dumps(parsed, indent=2 if args.pretty else None))
    return 0 if parsed.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
