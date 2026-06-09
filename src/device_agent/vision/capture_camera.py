#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image


WS_ROOT = Path("/home/lx/dev_ws")
TOOLS_DIR = WS_ROOT / "src" / "device_agent" / "vision"
DEFAULT_TOPIC = "/table_overview/color/image_raw"
DEFAULT_OUTPUT = TOOLS_DIR / "output" / "table_overview.png"
DEFAULT_TIMEOUT_SEC = 5.0


class ImageCaptureNode(Node):
    def __init__(self, topic: str):
        super().__init__("vision_camera_capture_cli")
        self.bridge = CvBridge()
        self.image_bgr = None
        self.subscription = self.create_subscription(Image, topic, self._callback, 1)

    def _callback(self, msg: Image) -> None:
        self.image_bgr = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")


def main() -> int:
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    rclpy.init(args=None)
    node = ImageCaptureNode(DEFAULT_TOPIC)

    deadline = node.get_clock().now().nanoseconds + int(DEFAULT_TIMEOUT_SEC * 1e9)
    try:
        while rclpy.ok() and node.image_bgr is None:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.get_clock().now().nanoseconds > deadline:
                raise SystemExit(f"Timed out waiting for image on topic: {DEFAULT_TOPIC}")

        ok = cv2.imwrite(str(DEFAULT_OUTPUT), node.image_bgr)
        if not ok:
            raise SystemExit(f"Failed to write image to: {DEFAULT_OUTPUT}")

        print(str(DEFAULT_OUTPUT))
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
