#!/usr/bin/env python3
"""Manage the MuJoCo cubes as MoveIt planning scene collision objects."""

import argparse
import sys
from dataclasses import dataclass

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.msg import (
    AllowedCollisionEntry,
    AllowedCollisionMatrix,
    AttachedCollisionObject,
    CollisionObject,
    ObjectColor,
    PlanningScene,
    PlanningSceneComponents,
)
from moveit_msgs.srv import ApplyPlanningScene, GetPlanningScene
from rclpy.node import Node
from shape_msgs.msg import SolidPrimitive


WORLD_FRAME = "world"
DEFAULT_ATTACH_LINK = "tool_frame"
CUBE_SIZE = 0.05

TABLE_LINKS = ("table_1", "table_2", "table_3", "table_4")
GRIPPER_TOUCH_LINKS = (
    "gripper_base_mount",
    "gripper_base",
    "gripper_left_driver",
    "gripper_right_driver",
    "gripper_left_coupler",
    "gripper_right_coupler",
    "gripper_left_spring_link",
    "gripper_right_spring_link",
    "gripper_left_follower",
    "gripper_right_follower",
    "gripper_left_pad",
    "gripper_right_pad",
    "gripper_left_silicone_pad",
    "gripper_right_silicone_pad",
)


@dataclass(frozen=True)
class CubeSpec:
    name: str
    xyz: tuple[float, float, float]


CUBES = {
    "Cube1": CubeSpec("Cube1", (0.0, -0.8, 0.765)),
    "Cube2": CubeSpec("Cube2", (-0.2, -0.8, 0.765)),
    "Cube3": CubeSpec("Cube3", (0.2, -0.8, 0.765)),
}

CUBE_COLORS = {
    "Cube1": (0.8, 0.2, 0.2, 1.0),
    "Cube2": (0.0, 1.0, 0.0, 1.0),
    "Cube3": (0.0, 0.0, 1.0, 1.0),
}


def make_pose(xyz: tuple[float, float, float]) -> Pose:
    pose = Pose()
    pose.position.x = xyz[0]
    pose.position.y = xyz[1]
    pose.position.z = xyz[2]
    pose.orientation.w = 1.0
    return pose


def make_cube_object(name: str, xyz: tuple[float, float, float]) -> CollisionObject:
    primitive = SolidPrimitive()
    primitive.type = SolidPrimitive.BOX
    primitive.dimensions = [CUBE_SIZE, CUBE_SIZE, CUBE_SIZE]

    obj = CollisionObject()
    obj.id = name
    obj.header.frame_id = WORLD_FRAME
    obj.primitives.append(primitive)
    obj.primitive_poses.append(make_pose(xyz))
    obj.operation = CollisionObject.ADD
    return obj


def make_remove_object(name: str) -> CollisionObject:
    obj = CollisionObject()
    obj.id = name
    obj.header.frame_id = WORLD_FRAME
    obj.operation = CollisionObject.REMOVE
    return obj


def make_object_color(name: str) -> ObjectColor:
    rgba = CUBE_COLORS[name]
    color = ObjectColor()
    color.id = name
    color.color.r = rgba[0]
    color.color.g = rgba[1]
    color.color.b = rgba[2]
    color.color.a = rgba[3]
    return color


def make_attached_object(
    name: str, link_name: str, offset_xyz: tuple[float, float, float]
) -> AttachedCollisionObject:
    attached = AttachedCollisionObject()
    attached.link_name = link_name
    attached.touch_links = list(GRIPPER_TOUCH_LINKS)
    attached.object = make_cube_object(name, offset_xyz)
    attached.object.header.frame_id = link_name
    attached.object.operation = CollisionObject.ADD
    return attached


def make_detach_object(name: str, link_name: str) -> AttachedCollisionObject:
    attached = AttachedCollisionObject()
    attached.link_name = link_name
    attached.object.id = name
    attached.object.operation = CollisionObject.REMOVE
    return attached


class PlanningSceneCubes(Node):
    def __init__(self) -> None:
        super().__init__("planning_scene_cubes")
        self.apply_client = self.create_client(ApplyPlanningScene, "/apply_planning_scene")
        self.get_client = self.create_client(GetPlanningScene, "/get_planning_scene")

    def apply(self, scene: PlanningScene) -> bool:
        if not self.apply_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("Service /apply_planning_scene is not available")
            return False

        request = ApplyPlanningScene.Request()
        request.scene = scene
        future = self.apply_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)

        if not future.done():
            self.get_logger().error("Timed out while applying planning scene")
            return False

        response = future.result()
        if response is None or not response.success:
            self.get_logger().error("MoveIt rejected the planning scene update")
            return False

        return True

    def get_allowed_collision_matrix(self) -> AllowedCollisionMatrix | None:
        if not self.get_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("Service /get_planning_scene is not available")
            return None

        request = GetPlanningScene.Request()
        request.components.components = PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
        future = self.get_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)

        if not future.done():
            self.get_logger().error("Timed out while reading the planning scene")
            return None

        response = future.result()
        if response is None:
            self.get_logger().error("MoveIt returned an empty planning scene response")
            return None

        return response.scene.allowed_collision_matrix

    def merge_allowed_collisions(self, cube_names: list[str]) -> AllowedCollisionMatrix | None:
        matrix = self.get_allowed_collision_matrix()
        if matrix is None:
            return None

        names = list(matrix.entry_names)
        rows = [list(entry.enabled) for entry in matrix.entry_values]

        for row in rows:
            row.extend([False] * (len(names) - len(row)))

        required_names = list(cube_names) + list(TABLE_LINKS) + list(GRIPPER_TOUCH_LINKS)
        for name in required_names:
            if name not in names:
                names.append(name)
                for row in rows:
                    row.append(False)
                rows.append([False] * len(names))

        name_to_index = {name: index for index, name in enumerate(names)}
        allowed_targets = list(TABLE_LINKS) + list(GRIPPER_TOUCH_LINKS)
        for cube_name in cube_names:
            cube_index = name_to_index[cube_name]
            for target_name in allowed_targets:
                target_index = name_to_index[target_name]
                rows[cube_index][target_index] = True
                rows[target_index][cube_index] = True

        merged = AllowedCollisionMatrix()
        merged.entry_names = names
        for row in rows:
            entry = AllowedCollisionEntry()
            entry.enabled = row
            merged.entry_values.append(entry)
        merged.default_entry_names = list(matrix.default_entry_names)
        merged.default_entry_values = list(matrix.default_entry_values)
        return merged

    def add(self, cube_names: list[str]) -> bool:
        matrix = self.merge_allowed_collisions(cube_names)
        if matrix is None:
            return False

        scene = PlanningScene()
        scene.is_diff = True
        scene.world.collision_objects = [
            make_cube_object(name, CUBES[name].xyz) for name in cube_names
        ]
        scene.object_colors = [make_object_color(name) for name in cube_names]
        scene.allowed_collision_matrix = matrix
        return self.apply(scene)

    def remove(self, cube_names: list[str]) -> bool:
        scene = PlanningScene()
        scene.is_diff = True
        scene.world.collision_objects = [make_remove_object(name) for name in cube_names]
        return self.apply(scene)

    def attach(
        self, name: str, link_name: str, offset_xyz: tuple[float, float, float]
    ) -> bool:
        matrix = self.merge_allowed_collisions([name])
        if matrix is None:
            return False

        scene = PlanningScene()
        scene.is_diff = True
        scene.world.collision_objects = [make_remove_object(name)]
        scene.robot_state.is_diff = True
        scene.robot_state.attached_collision_objects = [
            make_attached_object(name, link_name, offset_xyz)
        ]
        scene.object_colors = [make_object_color(name)]
        scene.allowed_collision_matrix = matrix
        return self.apply(scene)

    def detach(self, name: str, link_name: str, xyz: tuple[float, float, float]) -> bool:
        matrix = self.merge_allowed_collisions([name])
        if matrix is None:
            return False

        scene = PlanningScene()
        scene.is_diff = True
        scene.robot_state.is_diff = True
        scene.robot_state.attached_collision_objects = [
            make_detach_object(name, link_name)
        ]
        scene.world.collision_objects = [make_cube_object(name, xyz)]
        scene.object_colors = [make_object_color(name)]
        scene.allowed_collision_matrix = matrix
        return self.apply(scene)


def parse_cube_names(values: list[str]) -> list[str]:
    if not values or values == ["all"]:
        return list(CUBES.keys())

    unknown = [name for name in values if name not in CUBES]
    if unknown:
        raise ValueError(f"Unknown cube name(s): {', '.join(unknown)}")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add, remove, attach, or detach Cube1/Cube2/Cube3 in MoveIt."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add cubes to the planning scene")
    add_parser.add_argument("cubes", nargs="*", help="Cube names, or all")

    remove_parser = subparsers.add_parser("remove", help="Remove cubes from the scene")
    remove_parser.add_argument("cubes", nargs="*", help="Cube names, or all")

    attach_parser = subparsers.add_parser("attach", help="Attach one cube to a link")
    attach_parser.add_argument("cube", choices=sorted(CUBES))
    attach_parser.add_argument("--link", default=DEFAULT_ATTACH_LINK)
    attach_parser.add_argument(
        "--offset",
        nargs=3,
        type=float,
        default=(0.0, 0.0, 0.0),
        metavar=("X", "Y", "Z"),
        help="Cube pose relative to the attach link. Defaults to the link origin.",
    )

    detach_parser = subparsers.add_parser("detach", help="Detach one cube back to world")
    detach_parser.add_argument("cube", choices=sorted(CUBES))
    detach_parser.add_argument("--link", default=DEFAULT_ATTACH_LINK)
    detach_parser.add_argument(
        "--xyz",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help="World pose for the detached cube. Defaults to its MuJoCo start pose.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    rclpy.init()
    node = PlanningSceneCubes()

    try:
        if args.command == "add":
            ok = node.add(parse_cube_names(args.cubes))
        elif args.command == "remove":
            ok = node.remove(parse_cube_names(args.cubes))
        elif args.command == "attach":
            ok = node.attach(args.cube, args.link, tuple(args.offset))
        elif args.command == "detach":
            xyz = tuple(args.xyz) if args.xyz else CUBES[args.cube].xyz
            ok = node.detach(args.cube, args.link, xyz)
        else:
            parser.error(f"Unsupported command: {args.command}")
            ok = False
    except ValueError as exc:
        node.get_logger().error(str(exc))
        ok = False
    finally:
        node.destroy_node()
        rclpy.shutdown()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
