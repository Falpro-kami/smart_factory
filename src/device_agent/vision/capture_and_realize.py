#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from openai import OpenAI
from rclpy.node import Node
from sensor_msgs.msg import Image


WS_ROOT = Path("/home/lx/dev_ws")
TOOLS_DIR = WS_ROOT / "src" / "device_agent" / "vision"
ENV_FILE = TOOLS_DIR / ".env"
DEFAULT_TOPIC = "/table_overview/color/image_raw"
DEFAULT_DEPTH_TOPIC = "/table_overview/depth/image_raw"
DEFAULT_OUTPUT = TOOLS_DIR / "output" / "table_overview.png"
DEFAULT_DEPTH_OUTPUT = TOOLS_DIR / "output" / "table_overview_depth.png"
DEFAULT_DEPTH_COLOR_OUTPUT = TOOLS_DIR / "output" / "table_overview_depth_color.png"
DEFAULT_DEPTH_RAW_OUTPUT = TOOLS_DIR / "output" / "table_overview_depth.npy"
DEFAULT_DEPTH_VIS_NEAR_M = 0.8
DEFAULT_DEPTH_VIS_FAR_M = 1.3
DEFAULT_TIMEOUT_SEC = 5.0
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-flash"


def load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def image_path_to_data_url(image_path: Path) -> str:
    image_bytes = image_path.read_bytes()
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


class ImageCaptureNode(Node):
    def __init__(self, color_topic: str, depth_topic: str):
        super().__init__("vision_capture_and_realize_cli")
        self.bridge = CvBridge()
        self.image_bgr: np.ndarray | None = None
        self.depth_image: np.ndarray | None = None
        self.color_subscription = self.create_subscription(Image, color_topic, self._color_callback, 1)
        self.depth_subscription = self.create_subscription(Image, depth_topic, self._depth_callback, 1)

    def _color_callback(self, msg: Image) -> None:
        self.image_bgr = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

    def _depth_callback(self, msg: Image) -> None:
        self.depth_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")


def save_depth_outputs(
    depth_image: np.ndarray,
    depth_output_path: Path,
    depth_color_output_path: Path,
    depth_raw_output_path: Path,
) -> None:
    depth_raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    depth_array = np.asarray(depth_image, dtype=np.float32)
    np.save(depth_raw_output_path, depth_array)

    # 保存可用于点云重建的真实深度图：单位为毫米，PNG 使用 uint16 编码。
    depth_png = np.zeros(depth_array.shape, dtype=np.uint16)
    finite_positive_mask = np.isfinite(depth_array) & (depth_array > 0)
    if np.any(finite_positive_mask):
        depth_png[finite_positive_mask] = np.clip(
            np.round(depth_array[finite_positive_mask] * 1000.0),
            0,
            np.iinfo(np.uint16).max,
        ).astype(np.uint16)

    ok = cv2.imwrite(str(depth_output_path), depth_png)
    if not ok:
        raise SystemExit(f"Failed to write raw depth image to: {depth_output_path}")

    finite_mask = np.isfinite(depth_array)
    if not np.any(finite_mask):
        depth_vis = np.zeros(depth_array.shape, dtype=np.uint8)
    else:
        depth_vis = np.zeros(depth_array.shape, dtype=np.uint8)
        clipped_depth = np.clip(depth_array[finite_mask], DEFAULT_DEPTH_VIS_NEAR_M, DEFAULT_DEPTH_VIS_FAR_M)
        normalized = (clipped_depth - DEFAULT_DEPTH_VIS_NEAR_M) / (
            DEFAULT_DEPTH_VIS_FAR_M - DEFAULT_DEPTH_VIS_NEAR_M
        )
        depth_vis[finite_mask] = ((1.0 - normalized) * 255.0).clip(0, 255).astype(np.uint8)

    depth_color_vis = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)
    ok = cv2.imwrite(str(depth_color_output_path), depth_color_vis)
    if not ok:
        raise SystemExit(f"Failed to write colorized depth image to: {depth_color_output_path}")


def capture_image(
    color_topic: str,
    depth_topic: str,
    output_path: Path,
    depth_output_path: Path,
    depth_color_output_path: Path,
    depth_raw_output_path: Path,
    timeout_sec: float,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rclpy.init(args=None)
    node = ImageCaptureNode(color_topic, depth_topic)
    deadline = node.get_clock().now().nanoseconds + int(timeout_sec * 1e9)

    try:
        while rclpy.ok() and (node.image_bgr is None or node.depth_image is None):
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.get_clock().now().nanoseconds > deadline:
                raise SystemExit(
                    f"Timed out waiting for image on topics: {color_topic}, {depth_topic}"
                )

        ok = cv2.imwrite(str(output_path), node.image_bgr)
        if not ok:
            raise SystemExit(f"Failed to write image to: {output_path}")

        save_depth_outputs(
            node.depth_image,
            depth_output_path,
            depth_color_output_path,
            depth_raw_output_path,
        )
        return output_path
    finally:
        node.destroy_node()
        rclpy.shutdown()


def ask_qwen(image_path: Path, prompt: str, model: str, base_url: str) -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit("Environment variable DASHSCOPE_API_KEY is not set.")

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_path_to_data_url(image_path),
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one camera frame and send it to a Qwen VL model with a prompt."
    )
    parser.add_argument("prompt", help="Prompt sent to Qwen together with the captured image.")
    return parser


def main() -> int:
    load_dotenv(ENV_FILE)

    parser = build_parser()
    args = parser.parse_args()

    model = os.getenv("QWEN_MODEL", DEFAULT_MODEL)
    base_url = os.getenv("QWEN_BASE_URL", DEFAULT_BASE_URL)

    image_path = capture_image(
        DEFAULT_TOPIC,
        DEFAULT_DEPTH_TOPIC,
        DEFAULT_OUTPUT,
        DEFAULT_DEPTH_OUTPUT,
        DEFAULT_DEPTH_COLOR_OUTPUT,
        DEFAULT_DEPTH_RAW_OUTPUT,
        DEFAULT_TIMEOUT_SEC,
    )
    reply = ask_qwen(image_path, args.prompt, model, base_url)
    print(reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
