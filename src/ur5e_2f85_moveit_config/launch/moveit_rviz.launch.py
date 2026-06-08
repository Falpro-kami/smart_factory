#!/usr/bin/env python3

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

PRIME_OFFLOAD_ENV = {
    "__NV_PRIME_RENDER_OFFLOAD": "1",
    "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
}


def load_file(package_name, relative_path):
    package_path = get_package_share_directory(package_name)
    absolute_path = os.path.join(package_path, relative_path)
    with open(absolute_path, "r", encoding="utf-8") as file:
        return file.read()


def load_yaml(package_name, relative_path):
    package_path = get_package_share_directory(package_name)
    absolute_path = os.path.join(package_path, relative_path)
    with open(absolute_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def launch_setup(context, *args, **kwargs):
    moveit_pkg = FindPackageShare("ur5e_2f85_moveit_config")
    robot_pkg = FindPackageShare("ur10e_2f85_mujoco")
    rviz_config = LaunchConfiguration("rviz_config")
    headless = LaunchConfiguration("headless")
    prime_offload_env = (
        PRIME_OFFLOAD_ENV if LaunchConfiguration("prime_offload").perform(context) == "true" else {}
    )

    robot_description_content = Command(
        [
            PathJoinSubstitution([FindExecutable(name="xacro")]),
            " ",
            PathJoinSubstitution([robot_pkg, "description", "urdf", "ur5e_2f85.urdf.xacro"]),
            " headless:=",
            headless,
        ]
    )

    robot_description = {
        "robot_description": ParameterValue(robot_description_content, value_type=str),
    }
    robot_description_semantic = {
        "robot_description_semantic": load_file("ur5e_2f85_moveit_config", "config/ur5e_2f85.srdf"),
    }
    robot_description_kinematics = {
        "robot_description_kinematics": load_yaml("ur5e_2f85_moveit_config", "config/kinematics.yaml"),
    }
    robot_description_planning = {
        "robot_description_planning": load_yaml("ur5e_2f85_moveit_config", "config/joint_limits.yaml"),
    }
    ompl_planning_pipeline_config = {
        "ompl": load_yaml("ur5e_2f85_moveit_config", "config/ompl_planning.yaml")
    }
    planning_pipeline_parameters = {
        "planning_pipelines": ["ompl"],
        "default_planning_pipeline": "ompl",
    }

    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="log",
        additional_env=prime_offload_env,
        arguments=["-d", rviz_config],
        parameters=[
            robot_description,
            robot_description_semantic,
            robot_description_kinematics,
            robot_description_planning,
            ompl_planning_pipeline_config,
            planning_pipeline_parameters,
            {"use_sim_time": True},
        ],
    )

    return [rviz_node]


def generate_launch_description():
    moveit_pkg = FindPackageShare("ur5e_2f85_moveit_config")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "rviz_config",
                default_value=PathJoinSubstitution([moveit_pkg, "config", "moveit.rviz"]),
                description="RViz configuration for MoveIt",
            ),
            DeclareLaunchArgument("headless", default_value="true", description="Forwarded to the robot xacro"),
            DeclareLaunchArgument("prime_offload", default_value="true", description="Force NVIDIA PRIME offload"),
            OpaqueFunction(function=launch_setup),
        ]
    )
