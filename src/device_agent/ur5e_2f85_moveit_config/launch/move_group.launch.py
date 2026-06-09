#!/usr/bin/env python3

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


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


def generate_launch_description():
    moveit_pkg = FindPackageShare("ur5e_2f85_moveit_config")
    robot_pkg = FindPackageShare("ur10e_2f85_mujoco")

    headless = LaunchConfiguration("headless")
    moveit_log_level = LaunchConfiguration("moveit_log_level")

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
    moveit_controllers = load_yaml("ur5e_2f85_moveit_config", "config/moveit_controllers.yaml")
    planning_pipeline_parameters = {
        "planning_pipelines": ["ompl"],
        "default_planning_pipeline": "ompl",
    }

    move_group_capabilities = {
        "capabilities": "move_group/ExecuteTaskSolutionCapability",
        "disable_capabilities": "",
    }

    planning_scene_monitor_parameters = {
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
        "publish_robot_description": True,
        "publish_robot_description_semantic": True,
    }

    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        arguments=[
            "--ros-args",
            "--log-level",
            "warn",
            "--log-level",
            ["move_group.moveit:=", moveit_log_level],
        ],
        parameters=[
            robot_description,
            robot_description_semantic,
            robot_description_kinematics,
            robot_description_planning,
            ompl_planning_pipeline_config,
            planning_pipeline_parameters,
            moveit_controllers,
            planning_scene_monitor_parameters,
            move_group_capabilities,
            {"allow_trajectory_execution": True},
            {"use_sim_time": True},
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("headless", default_value="true", description="Forwarded to the robot xacro"),
            DeclareLaunchArgument(
                "moveit_log_level",
                default_value="debug",
                description="ROS log level for move_group",
            ),
            move_group,
        ]
    )
