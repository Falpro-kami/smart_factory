#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import rclpy
import yaml
from control_msgs.action import FollowJointTrajectory
from geometry_msgs.msg import Pose, PoseStamped
from moveit.core.robot_state import RobotState
from moveit_msgs.msg import MoveItErrorCodes, RobotState as RobotStateMsg
from moveit_msgs.srv import GetCartesianPath
from moveit.planning import MoveItPy, PlanRequestParameters
from moveit.utils import create_params_file_from_dict
from rclpy.action import ActionClient
from builtin_interfaces.msg import Duration
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint


WS_ROOT = Path("/home/lx/dev_ws")
MOVEIT_CONFIG_DIR = WS_ROOT / "src" / "device_agent" / "ur5e_2f85_moveit_config" / "config"
ROBOT_XACRO = WS_ROOT / "src" / "device_agent" / "ur10e_2f85_mujoco" / "description" / "urdf" / "ur5e_2f85.urdf.xacro"
DEFAULT_SOCKET_PATH = "/tmp/moveitpy_server.sock"
DEFAULT_PLAN_RETRIES = 4
ARM_JOINT_NAMES = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
]


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

    controllers = load_yaml(MOVEIT_CONFIG_DIR / "moveit_controllers.yaml")

    return {
        "robot_description": robot_description,
        "robot_description_semantic": robot_description_semantic,
        "robot_description_kinematics": load_yaml(MOVEIT_CONFIG_DIR / "kinematics.yaml"),
        "robot_description_planning": load_yaml(MOVEIT_CONFIG_DIR / "joint_limits.yaml"),
        "ompl": load_yaml(MOVEIT_CONFIG_DIR / "ompl_planning.yaml"),
        "trajectory_execution": controllers["trajectory_execution"],
        "moveit_controller_manager": controllers["moveit_controller_manager"],
        "moveit_manage_controllers": controllers["moveit_manage_controllers"],
        "moveit_simple_controller_manager": controllers["moveit_simple_controller_manager"],
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


def rpy_to_quaternion(roll: float, pitch: float, yaw: float):
    cr = np.cos(roll * 0.5)
    sr = np.sin(roll * 0.5)
    cp = np.cos(pitch * 0.5)
    sp = np.sin(pitch * 0.5)
    cy = np.cos(yaw * 0.5)
    sy = np.sin(yaw * 0.5)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return float(qx), float(qy), float(qz), float(qw)


def build_pose_goal(x: float, y: float, z: float, roll: float | None = None,
                    pitch: float | None = None, yaw: float | None = None) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = "world_frame"
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = z
    if roll is None or pitch is None or yaw is None:
        pose.pose.orientation.x = 0.0
        pose.pose.orientation.y = 1.0
        pose.pose.orientation.z = 0.0
        pose.pose.orientation.w = 0.0
    else:
        qx, qy, qz, qw = rpy_to_quaternion(roll, pitch, yaw)
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
    return pose


def rotation_matrix_to_quaternion(rotation: np.ndarray):
    trace = np.trace(rotation)
    if trace > 0.0:
        s = 2.0 * np.sqrt(trace + 1.0)
        w = 0.25 * s
        x = (rotation[2, 1] - rotation[1, 2]) / s
        y = (rotation[0, 2] - rotation[2, 0]) / s
        z = (rotation[1, 0] - rotation[0, 1]) / s
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2])
        w = (rotation[2, 1] - rotation[1, 2]) / s
        x = 0.25 * s
        y = (rotation[0, 1] + rotation[1, 0]) / s
        z = (rotation[0, 2] + rotation[2, 0]) / s
    elif rotation[1, 1] > rotation[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2])
        w = (rotation[0, 2] - rotation[2, 0]) / s
        x = (rotation[0, 1] + rotation[1, 0]) / s
        y = 0.25 * s
        z = (rotation[1, 2] + rotation[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1])
        w = (rotation[1, 0] - rotation[0, 1]) / s
        x = (rotation[0, 2] + rotation[2, 0]) / s
        y = (rotation[1, 2] + rotation[2, 1]) / s
        z = 0.25 * s
    return x, y, z, w


def rotation_matrix_to_rpy(rotation: np.ndarray):
    sy = np.sqrt(rotation[0, 0] * rotation[0, 0] + rotation[1, 0] * rotation[1, 0])
    singular = sy < 1e-6
    if not singular:
        roll = np.arctan2(rotation[2, 1], rotation[2, 2])
        pitch = np.arctan2(-rotation[2, 0], sy)
        yaw = np.arctan2(rotation[1, 0], rotation[0, 0])
    else:
        roll = np.arctan2(-rotation[1, 2], rotation[1, 1])
        pitch = np.arctan2(-rotation[2, 0], sy)
        yaw = 0.0
    return float(roll), float(pitch), float(yaw)


def transform_to_pose(transform: np.ndarray) -> Pose:
    pose = Pose()
    pose.position.x = float(transform[0, 3])
    pose.position.y = float(transform[1, 3])
    pose.position.z = float(transform[2, 3])
    qx, qy, qz, qw = rotation_matrix_to_quaternion(transform[:3, :3])
    pose.orientation.x = float(qx)
    pose.orientation.y = float(qy)
    pose.orientation.z = float(qz)
    pose.orientation.w = float(qw)
    return pose


def build_robot_state_msg_from_group(start_state: RobotState, group_name: str) -> RobotStateMsg:
    robot_state_msg = RobotStateMsg()
    joint_state = JointState()

    if group_name == "arm":
        joint_state.name = list(ARM_JOINT_NAMES)
    else:
        raise ValueError(f"Unsupported group for RobotState message conversion: {group_name}")

    joint_state.position = list(start_state.get_joint_group_positions(group_name))
    robot_state_msg.joint_state = joint_state
    robot_state_msg.is_diff = False
    return robot_state_msg


class MoveItPyServer:
    def __init__(self):
        os.environ.setdefault("ROS_LOG_DIR", "/tmp/roslog_moveitpy")
        if not rclpy.ok():
            rclpy.init(args=None)
        params_file = create_params_file_from_dict(build_moveit_config(), "moveit_py_server")
        self.moveit_py = MoveItPy(
            node_name="moveit_py_server",
            launch_params_filepaths=[params_file],
        )
        self.aux_node = Node("moveitpy_aux_client")
        self.group = "arm"
        self.planning_component = self.moveit_py.get_planning_component(self.group)
        self.plan_request_params = PlanRequestParameters(self.moveit_py, "ompl")
        self.plan_request_params.planning_pipeline = "ompl"
        self.plan_request_params.planner_id = "RRTConnectkConfigDefault"
        self.plan_request_params.planning_time = 5.0
        self.plan_request_params.planning_attempts = 5
        self.plan_request_params.max_velocity_scaling_factor = 1.0
        self.plan_request_params.max_acceleration_scaling_factor = 1.0
        self.plan_retries = DEFAULT_PLAN_RETRIES
        self.last_plan_result = None
        self.last_joint_trajectory_msg = None
        self.cartesian_client = self.aux_node.create_client(GetCartesianPath, "/compute_cartesian_path")
        self.arm_action_client = ActionClient(
            self.aux_node,
            FollowJointTrajectory,
            "/arm_trajectory_controller/follow_joint_trajectory",
        )
        self.gripper_action_client = ActionClient(
            self.aux_node,
            FollowJointTrajectory,
            "/gripper_trajectory_controller/follow_joint_trajectory",
        )
        time.sleep(0.2)

    def _set_start_state(self):
        self.planning_component.set_start_state_to_current_state()

    def _plan(self):
        total_attempts = self.plan_retries + 1
        for attempt in range(1, total_attempts + 1):
            self._set_start_state()
            result = self.planning_component.plan(self.plan_request_params)
            if result:
                self.last_plan_result = result
                self.last_joint_trajectory_msg = None
                return {
                    "ok": True,
                    "message": "Planning succeeded."
                    if attempt == 1
                    else f"Planning succeeded on attempt {attempt}/{total_attempts}.",
                    "attempts": attempt,
                    "total_attempts": total_attempts,
                }
            if attempt < total_attempts:
                time.sleep(0.05)

        self.last_plan_result = None
        self.last_joint_trajectory_msg = None
        return {
            "ok": False,
            "message": f"Planning failed after {total_attempts} attempts.",
            "attempts": total_attempts,
            "total_attempts": total_attempts,
        }

    def HOME(self):
        self.planning_component.set_goal_state(configuration_name="home")
        return self._plan()

    def PTP(self, x, y, z, roll=None, pitch=None, yaw=None):
        pose_goal = build_pose_goal(x, y, z, roll, pitch, yaw)
        self.planning_component.set_goal_state(
            pose_stamped_msg=pose_goal,
            pose_link="tool_frame",
        )
        return self._plan()

    def LIN(
        self,
        dx,
        dy,
        dz,
        max_step=0.01,
        avoid_collisions=True,
        frame="world_frame",
    ):
        if frame not in ("world_frame", "tool_frame"):
            return {
                "ok": False,
                "message": "LIN frame must be world_frame or tool_frame.",
            }

        self._set_start_state()
        planning_scene_monitor = self.moveit_py.get_planning_scene_monitor()
        planning_scene_monitor.wait_for_current_robot_state(Time(), 1.0)
        with planning_scene_monitor.read_only() as scene:
            start_state = scene.current_state
            world_transform = scene.get_frame_transform("world_frame")
            tool_transform = start_state.get_global_link_transform("tool_frame")
            tool_in_world_frame = np.linalg.inv(world_transform) @ tool_transform
            target_transform = np.array(tool_in_world_frame, copy=True)
            offset = np.array([float(dx), float(dy), float(dz)])
            if frame == "tool_frame":
                offset = tool_in_world_frame[:3, :3] @ offset
            target_transform[:3, 3] += offset
            target_pose = transform_to_pose(target_transform)

        if not self.cartesian_client.wait_for_service(timeout_sec=3.0):
            return {"ok": False, "message": "Service /compute_cartesian_path is not available."}

        request = GetCartesianPath.Request()
        request.header.frame_id = "world_frame"
        request.start_state = build_robot_state_msg_from_group(start_state, self.group)
        request.group_name = self.group
        request.link_name = "tool_frame"
        request.waypoints = [target_pose]
        request.max_step = float(max_step)
        request.jump_threshold = 0.0
        request.prismatic_jump_threshold = 0.0
        request.revolute_jump_threshold = 0.0
        request.avoid_collisions = bool(avoid_collisions)
        request.max_velocity_scaling_factor = self.plan_request_params.max_velocity_scaling_factor
        request.max_acceleration_scaling_factor = self.plan_request_params.max_acceleration_scaling_factor

        total_attempts = self.plan_retries + 1
        last_response = None
        last_message = "Cartesian planning failed."

        for attempt in range(1, total_attempts + 1):
            future = self.cartesian_client.call_async(request)
            rclpy.spin_until_future_complete(self.aux_node, future, timeout_sec=10.0)
            if not future.done() or future.result() is None:
                last_message = "Cartesian planning timed out."
            else:
                response = future.result()
                last_response = response
                if response.error_code.val == MoveItErrorCodes.SUCCESS:
                    self.last_plan_result = None
                    self.last_joint_trajectory_msg = response.solution.joint_trajectory
                    return {
                        "ok": True,
                        "message": "Cartesian planning succeeded."
                        if attempt == 1
                        else f"Cartesian planning succeeded on attempt {attempt}/{total_attempts}.",
                        "fraction": float(response.fraction),
                        "frame": frame,
                        "attempts": attempt,
                        "total_attempts": total_attempts,
                    }
                last_message = f"Cartesian planning failed with error code {response.error_code.val}."

            if attempt < total_attempts:
                time.sleep(0.05)

        self.last_plan_result = None
        self.last_joint_trajectory_msg = None
        failure = {
            "ok": False,
            "message": f"{last_message.rstrip('.')} after {total_attempts} attempts.",
            "attempts": total_attempts,
            "total_attempts": total_attempts,
        }
        if last_response is not None:
            failure["fraction"] = float(last_response.fraction)
        return failure

    def execute_last(self):
        if self.last_plan_result is not None:
            trajectory_msg = self.last_plan_result.trajectory.get_robot_trajectory_msg()
            return self._execute_arm_trajectory(trajectory_msg.joint_trajectory)
        if self.last_joint_trajectory_msg is None:
            return {"ok": False, "message": "No saved plan to execute."}
        return self._execute_arm_trajectory(self.last_joint_trajectory_msg)

    def _execute_arm_trajectory(self, joint_trajectory_msg):
        if not joint_trajectory_msg.points:
            return {"ok": False, "message": "Saved plan has no trajectory points."}
        if not self.arm_action_client.wait_for_server(timeout_sec=3.0):
            return {"ok": False, "message": "arm_trajectory_controller action server is not available."}

        goal = FollowJointTrajectory.Goal()
        goal.trajectory = joint_trajectory_msg
        send_future = self.arm_action_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self.aux_node, send_future, timeout_sec=5.0)
        if not send_future.done() or send_future.result() is None:
            return {"ok": False, "message": "Failed to send execution goal."}

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return {"ok": False, "message": "Execution goal was rejected."}

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self.aux_node, result_future, timeout_sec=60.0)
        if not result_future.done() or result_future.result() is None:
            return {"ok": False, "message": "Execution result timed out."}

        result = result_future.result().result
        if result.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            return {
                "ok": False,
                "message": f"Execution failed with error code {result.error_code}: {result.error_string}",
            }
        planning_scene_monitor = self.moveit_py.get_planning_scene_monitor()
        planning_scene_monitor.wait_for_current_robot_state(Time(), 1.0)
        return {"ok": True, "message": "Execution completed."}

    def set_planning_time(self, seconds):
        self.plan_request_params.planning_time = float(seconds)
        return {"ok": True, "message": f"planning_time set to {seconds}"}

    def grasp(self, state):
        state = int(state)
        if state not in (0, 1):
            return {"ok": False, "message": "grasp state must be 1 for close or 0 for open."}
        if not self.gripper_action_client.wait_for_server(timeout_sec=3.0):
            return {
                "ok": False,
                "message": "gripper_trajectory_controller action server is not available.",
            }

        position = 0.72 if state == 1 else 0.0
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ["left_driver_joint"]

        point = JointTrajectoryPoint()
        point.positions = [position]
        point.time_from_start = Duration(sec=1, nanosec=0)
        goal.trajectory.points = [point]

        send_future = self.gripper_action_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self.aux_node, send_future, timeout_sec=5.0)
        if not send_future.done() or send_future.result() is None:
            return {"ok": False, "message": "Failed to send gripper goal."}

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return {"ok": False, "message": "Gripper goal was rejected."}

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self.aux_node, result_future, timeout_sec=10.0)
        if not result_future.done() or result_future.result() is None:
            return {"ok": False, "message": "Gripper result timed out."}

        result = result_future.result().result
        if result.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            return {
                "ok": False,
                "message": f"Gripper failed with error code {result.error_code}: {result.error_string}",
            }

        return {
            "ok": True,
            "message": "Gripper closed." if state == 1 else "Gripper opened.",
            "state": state,
            "joint": "left_driver_joint",
            "position": position,
        }

    def get_tool_pose(self):
        planning_scene_monitor = self.moveit_py.get_planning_scene_monitor()
        planning_scene_monitor.wait_for_current_robot_state(Time(), 1.0)
        with planning_scene_monitor.read_only() as scene:
            start_state = scene.current_state
            world_transform = scene.get_frame_transform("world_frame")
            tool_transform = start_state.get_global_link_transform("tool_frame")
            tool_in_world_frame = np.linalg.inv(world_transform) @ tool_transform

        position = tool_in_world_frame[:3, 3].astype(float)
        roll, pitch, yaw = rotation_matrix_to_rpy(tool_in_world_frame[:3, :3])
        return {
            "ok": True,
            "frame": "world_frame",
            "link": "tool_frame",
            "x": float(position[0]),
            "y": float(position[1]),
            "z": float(position[2]),
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
        }

    def handle(self, request):
        command = request.get("command")
        if command == "HOME":
            return self.HOME()
        if command == "PTP":
            return self.PTP(
                request["x"],
                request["y"],
                request["z"],
                request.get("roll"),
                request.get("pitch"),
                request.get("yaw"),
            )
        if command == "LIN":
            return self.LIN(
                request.get("dx", 0.0),
                request.get("dy", 0.0),
                request.get("dz", 0.0),
                request.get("max_step", 0.01),
                request.get("avoid_collisions", True),
                request.get("frame", "world_frame"),
            )
        if command == "execute_last":
            return self.execute_last()
        if command == "set_planning_time":
            return self.set_planning_time(request["seconds"])
        if command == "grasp":
            return self.grasp(request["state"])
        if command == "get_tool_pose":
            return self.get_tool_pose()
        if command == "ping":
            return {"ok": True, "message": "pong"}
        if command == "quit":
            return {"ok": True, "message": "bye", "quit": True}
        return {"ok": False, "message": f"Unknown command: {command}"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent MoveItPy server.")
    parser.add_argument(
        "--mode",
        choices=["socket", "stdio"],
        default="socket",
        help="socket is better for one-shot CLI calls; stdio is handy for manual testing.",
    )
    parser.add_argument(
        "--socket-path",
        default=DEFAULT_SOCKET_PATH,
        help="Unix domain socket path used in socket mode.",
    )
    return parser


def handle_request(server: MoveItPyServer, raw: str) -> dict:
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "message": f"Invalid JSON: {exc}"}

    try:
        return server.handle(request)
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}


def run_stdio_server(server: MoveItPyServer) -> int:
    print(json.dumps({"ok": True, "message": "moveitpy_server ready"}), flush=True)

    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        response = handle_request(server, raw)
        print(json.dumps(response), flush=True)
        if response.get("quit"):
            break
    return 0


def run_socket_server(server: MoveItPyServer, socket_path: str) -> int:
    socket_file = Path(socket_path)
    if socket_file.exists():
        socket_file.unlink()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    sock.listen(1)
    print(json.dumps({"ok": True, "message": f"moveitpy_server ready on {socket_path}"}), flush=True)

    try:
        while True:
            conn, _ = sock.accept()
            with conn:
                raw = conn.recv(65536).decode("utf-8").strip()
                if not raw:
                    continue
                response = handle_request(server, raw)
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                if response.get("quit"):
                    break
    finally:
        sock.close()
        if socket_file.exists():
            socket_file.unlink()
    return 0


def main() -> int:
    args = build_parser().parse_args()
    print("Make sure demo.launch.py is already running before using this server.", file=sys.stderr)
    server = MoveItPyServer()

    if args.mode == "stdio":
        exit_code = run_stdio_server(server)
    else:
        exit_code = run_socket_server(server, args.socket_path)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)


if __name__ == "__main__":
    sys.exit(main())
