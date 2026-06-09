#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml
from geometry_msgs.msg import PoseStamped
from moveit.planning import MoveItPy, PlanRequestParameters
from moveit.utils import create_params_file_from_dict


WS_ROOT = Path("/home/lx/dev_ws")
MOVEIT_CONFIG_DIR = WS_ROOT / "src" / "device_agent" / "ur5e_2f85_moveit_config" / "config"
ROBOT_XACRO = WS_ROOT / "src" / "device_agent" / "ur10e_2f85_mujoco" / "description" / "urdf" / "ur5e_2f85.urdf.xacro"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simple MoveItPy test script for the ur5e_2f85 setup."
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Keep one MoveItPy instance alive and accept repeated commands.",
    )
    parser.add_argument(
        "--group",
        default="arm",
        help="Planning group name, e.g. arm or gripper.",
    )
    parser.add_argument(
        "--goal",
        choices=["home", "pose"],
        default="home",
        help="Goal type to test.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the planned trajectory after planning succeeds.",
    )
    parser.add_argument(
        "--planning-time",
        type=float,
        default=2.0,
        help="Allowed planning time in seconds. Lower is faster but less robust.",
    )
    parser.add_argument(
        "--startup-wait",
        type=float,
        default=0.2,
        help="Extra wait time before reading current state.",
    )
    parser.add_argument(
        "--x",
        type=float,
        default=0.15,
        help="Pose goal x in world_frame.",
    )
    parser.add_argument(
        "--y",
        type=float,
        default=0.45,
        help="Pose goal y in world_frame.",
    )
    parser.add_argument(
        "--z",
        type=float,
        default=1.00,
        help="Pose goal z in world_frame.",
    )
    return parser


def load_yaml(path: Path):
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def build_moveit_config() -> dict:
    robot_description = subprocess.check_output(
        ["xacro", str(ROBOT_XACRO), "headless:=false"],
        text=True,
    )

    with open(MOVEIT_CONFIG_DIR / "ur5e_2f85.srdf", "r", encoding="utf-8") as file:
        robot_description_semantic = file.read()

    config = {
        "robot_description": robot_description,
        "robot_description_semantic": robot_description_semantic,
        "robot_description_kinematics": load_yaml(MOVEIT_CONFIG_DIR / "kinematics.yaml"),
        "robot_description_planning": load_yaml(MOVEIT_CONFIG_DIR / "joint_limits.yaml"),
        "ompl": load_yaml(MOVEIT_CONFIG_DIR / "ompl_planning.yaml"),
        "trajectory_execution": load_yaml(MOVEIT_CONFIG_DIR / "moveit_controllers.yaml")["trajectory_execution"],
        "moveit_controller_manager": load_yaml(MOVEIT_CONFIG_DIR / "moveit_controllers.yaml")[
            "moveit_controller_manager"
        ],
        "moveit_manage_controllers": load_yaml(MOVEIT_CONFIG_DIR / "moveit_controllers.yaml")[
            "moveit_manage_controllers"
        ],
        "moveit_simple_controller_manager": load_yaml(MOVEIT_CONFIG_DIR / "moveit_controllers.yaml")[
            "moveit_simple_controller_manager"
        ],
        "planning_pipelines": {
            "pipeline_names": ["ompl"],
            "namespace": "",
        },
        "default_planning_pipeline": "ompl",
        "use_sim_time": True,
        "qos_overrides": {
            "/clock": {
                "subscription": {
                    "history": "keep_last",
                    "depth": 1,
                    "reliability": "best_effort",
                    "durability": "volatile",
                }
            }
        },
    }
    return config


def build_pose_goal(x: float, y: float, z: float) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = "world_frame"
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = z
    pose.pose.orientation.x = 0.0
    pose.pose.orientation.y = 1.0
    pose.pose.orientation.z = 0.0
    pose.pose.orientation.w = 0.0
    return pose


def set_goal(planning_component, args: argparse.Namespace) -> None:
    if args.goal == "home":
        planning_component.set_goal_state(configuration_name="home")
        return

    pose_goal = build_pose_goal(args.x, args.y, args.z)
    planning_component.set_goal_state(
        pose_stamped_msg=pose_goal,
        pose_link="tool_frame",
    )


def hard_exit(code: int) -> None:
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def plan_for_goal(planning_component, plan_request_params) -> object:
    plan_result = planning_component.plan(plan_request_params)
    if not plan_result:
        print("Planning failed.")
        return None

    print("Planning succeeded.")
    return plan_result


def interactive_loop(moveit_py: MoveItPy, planning_component, plan_request_params, args: argparse.Namespace) -> int:
    last_plan_result = None
    help_text = (
        "Commands:\n"
        "  home              plan to named state 'home'\n"
        "  pose x y z        plan to a pose goal in world_frame\n"
        "  execute           execute the last successful plan\n"
        "  help              show this help\n"
        "  quit              exit"
    )

    print(help_text)

    while True:
        try:
            raw = input("moveit> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        if not raw:
            continue

        parts = raw.split()
        command = parts[0].lower()

        if command in {"quit", "exit"}:
            return 0

        if command == "help":
            print(help_text)
            continue

        if command == "execute":
            if last_plan_result is None:
                print("No plan available. Run home or pose first.")
                continue

            print("Executing trajectory...")
            moveit_py.execute(last_plan_result.trajectory, controllers=[])
            print("Execution request sent.")
            continue

        planning_component.set_start_state_to_current_state()

        if command == "home":
            planning_component.set_goal_state(configuration_name="home")
        elif command == "pose":
            if len(parts) != 4:
                print("Usage: pose <x> <y> <z>")
                continue
            try:
                x, y, z = map(float, parts[1:])
            except ValueError:
                print("Pose values must be numbers.")
                continue
            pose_goal = build_pose_goal(x, y, z)
            planning_component.set_goal_state(
                pose_stamped_msg=pose_goal,
                pose_link="tool_frame",
            )
        else:
            print("Unknown command. Type 'help' to see available commands.")
            continue

        print(f"Planning group: {args.group}")
        print(f"Command: {raw}")
        last_plan_result = plan_for_goal(planning_component, plan_request_params)


def main() -> int:
    args = build_parser().parse_args()

    print("Make sure demo.launch.py is already running before using this script.")
    os.environ.setdefault("ROS_LOG_DIR", "/tmp/roslog_moveitpy")
    params_file = create_params_file_from_dict(build_moveit_config(), "moveit_py_test")
    moveit_py = MoveItPy(
        node_name="moveit_py_test",
        launch_params_filepaths=[params_file],
    )
    planning_component = moveit_py.get_planning_component(args.group)
    plan_request_params = PlanRequestParameters(moveit_py, "ompl")
    plan_request_params.planning_pipeline = "ompl"
    plan_request_params.planner_id = "RRTConnectkConfigDefault"
    plan_request_params.planning_time = args.planning_time
    plan_request_params.planning_attempts = 1
    plan_request_params.max_velocity_scaling_factor = 1.0
    plan_request_params.max_acceleration_scaling_factor = 1.0

    time.sleep(max(args.startup_wait, 0.0))
    if args.interactive:
        exit_code = interactive_loop(moveit_py, planning_component, plan_request_params, args)
        hard_exit(exit_code)

    planning_component.set_start_state_to_current_state()
    set_goal(planning_component, args)

    print(f"Planning group: {args.group}")
    print(f"Goal type: {args.goal}")
    plan_result = plan_for_goal(planning_component, plan_request_params)

    if not plan_result:
        hard_exit(1)

    if args.execute:
        print("Executing trajectory...")
        moveit_py.execute(plan_result.trajectory, controllers=[])
        print("Execution request sent.")

    hard_exit(0)


if __name__ == "__main__":
    sys.exit(main())
