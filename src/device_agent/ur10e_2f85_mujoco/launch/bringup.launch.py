#!/usr/bin/env python3

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler, Shutdown
from launch.event_handlers import OnProcessExit
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile, ParameterValue
from launch_ros.substitutions import FindPackageShare

PRIME_OFFLOAD_ENV = {
    "__NV_PRIME_RENDER_OFFLOAD": "1",
    "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
}


def get_prime_offload_env(context):
    return PRIME_OFFLOAD_ENV if LaunchConfiguration("prime_offload").perform(context) == "true" else {}


def launch_setup(context, *args, **kwargs):
    pkg_share = FindPackageShare("ur10e_2f85_mujoco")
    prime_offload_env = get_prime_offload_env(context)

    robot_description_content = Command(
        [
            PathJoinSubstitution([FindExecutable(name="xacro")]),
            " ",
            PathJoinSubstitution([pkg_share, "description", "urdf", "ur5e_2f85.urdf.xacro"]),
            " headless:=",
            LaunchConfiguration("headless"),
        ]
    )

    robot_description = {
        "robot_description": ParameterValue(
            value=robot_description_content.perform(context),
            value_type=str,
        )
    }

    controllers_file = PathJoinSubstitution([pkg_share, "config", "controllers.yaml"])
    plugins_file = PathJoinSubstitution([pkg_share, "config", "mujoco_ros2_control_plugins.yaml"])
    rviz_file = PathJoinSubstitution([pkg_share, "rviz", "ur10e_2f85.rviz"])

    joint_state_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster", "--param-file", controllers_file],
        output="both",
    )

    nodes = [
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            output="both",
            parameters=[robot_description, {"use_sim_time": True}],
        ),
        Node(
            package="mujoco_ros2_control",
            executable="ros2_control_node",
            emulate_tty=True,
            output="both",
            additional_env=prime_offload_env,
            parameters=[
                {"use_sim_time": True},
                ParameterFile(controllers_file),
                ParameterFile(plugins_file),
            ],
            remappings=(
                [("~/robot_description", "/robot_description")] if os.environ.get("ROS_DISTRO") == "humble" else []
            ),
            on_exit=Shutdown(),
        ),
        joint_state_spawner,
    ]

    if LaunchConfiguration("use_trajectory_controllers").perform(context) == "true":
        arm_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["arm_trajectory_controller", "--param-file", controllers_file],
            output="both",
        )
        gripper_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["gripper_trajectory_controller", "--param-file", controllers_file],
            output="both",
        )
        nodes.extend(
            [
                RegisterEventHandler(
                    OnProcessExit(target_action=joint_state_spawner, on_exit=[arm_spawner])
                ),
                RegisterEventHandler(
                    OnProcessExit(target_action=arm_spawner, on_exit=[gripper_spawner])
                ),
            ]
        )
    else:
        position_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["position_controller", "--param-file", controllers_file],
            output="both",
        )
        gripper_spawner = Node(
            package="controller_manager",
            executable="spawner",
            arguments=["gripper_controller", "--param-file", controllers_file],
            output="both",
        )
        nodes.extend(
            [
                RegisterEventHandler(
                    OnProcessExit(target_action=joint_state_spawner, on_exit=[position_spawner])
                ),
                RegisterEventHandler(
                    OnProcessExit(target_action=position_spawner, on_exit=[gripper_spawner])
                ),
            ]
        )

    if LaunchConfiguration("rviz").perform(context) == "true":
        nodes.append(
            Node(
                package="rviz2",
                executable="rviz2",
                arguments=["-d", rviz_file],
                parameters=[{"use_sim_time": True}],
                output="both",
                additional_env=prime_offload_env,
            )
        )

    return nodes


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("headless", default_value="false", description="Run without MuJoCo GUI"),
            DeclareLaunchArgument("use_pid", default_value="false", description="Enable ROS-side PID settings"),
            DeclareLaunchArgument("prime_offload", default_value="true", description="Force NVIDIA PRIME offload"),
            DeclareLaunchArgument("rviz", default_value="false", description="Launch RViz with a saved config"),
            DeclareLaunchArgument(
                "use_trajectory_controllers",
                default_value="false",
                description="Spawn trajectory controllers for MoveIt instead of topic command controllers",
            ),
            OpaqueFunction(function=launch_setup),
        ]
    )
