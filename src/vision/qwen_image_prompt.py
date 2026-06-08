#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

from openai import OpenAI


WS_ROOT = Path("/home/lx/dev_ws")
TOOLS_DIR = WS_ROOT / "src" / "vision"
ENV_FILE = TOOLS_DIR / ".env"
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


def resolve_image_input(image_input: str) -> str:
    if image_input.startswith(("http://", "https://", "data:")):
        return image_input

    image_path = Path(image_input).expanduser()
    if not image_path.is_absolute():
        image_path = Path.cwd() / image_path
    if not image_path.exists():
        raise SystemExit(f"Image file does not exist: {image_path}")
    return image_path_to_data_url(image_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send one image plus one prompt to a Qwen VL model.")
    parser.add_argument("image", help="Image URL, data URL, or local image path.")
    parser.add_argument("prompt", help="Prompt sent together with the image.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Qwen model name.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="DashScope compatible API base URL.")
    return parser


def main() -> int:
    load_dotenv(ENV_FILE)
    parser = build_parser()
    parser.set_defaults(
        model=os.getenv("QWEN_MODEL", DEFAULT_MODEL),
        base_url=os.getenv("QWEN_BASE_URL", DEFAULT_BASE_URL),
    )
    args = parser.parse_args()

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit("Environment variable DASHSCOPE_API_KEY is not set.")

    client = OpenAI(api_key=api_key, base_url=args.base_url)
    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": resolve_image_input(args.image),
                        },
                    },
                    {
                        "type": "text",
                        "text": args.prompt,
                    },
                ],
            }
        ],
    )
    print(response.choices[0].message.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
