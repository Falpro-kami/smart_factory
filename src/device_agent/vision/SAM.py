import argparse
from pathlib import Path
import shutil

import cv2
import numpy as np
from ultralytics.models.sam import SAM3SemanticPredictor


VISION_DIR = Path(__file__).resolve().parent
IMAGE_PATH = VISION_DIR / "output" / "table_overview.png"
OUTPUT_DIR = VISION_DIR / "output" / "sam_result"
MODEL_PATH = VISION_DIR / "sam3.pt"
BBOX_PREVIEW_PATH = OUTPUT_DIR / "bboxes_overlay.png"
MASK_OVERLAY_PATH = OUTPUT_DIR / "masks_overlay.png"
MASK_BINARY_PATH = OUTPUT_DIR / "masks_binary.png"



def reset_output_dir(output_dir: Path) -> None:
    """Clear previous outputs so each run writes into the same folder."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SAM segmentation with one or more bounding boxes.")
    parser.add_argument(
        "--bbox",
        dest="bboxes",
        action="append",
        nargs=4,
        type=int,
        metavar=("X1", "Y1", "X2", "Y2"),
        help="Add a bounding box prompt. Repeat --bbox to provide multiple boxes.",
    )
    return parser


def save_bbox_overlay(image_path: Path, bboxes: list[list[int]] | None, output_path: Path) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"无法读取输入图像: {image_path}")

    if not bboxes:
        cv2.imwrite(str(output_path), image)
        return

    colors = [
        (0, 255, 0),
        (0, 165, 255),
        (255, 0, 0),
        (255, 255, 0),
        (255, 0, 255),
    ]
    for idx, (x1, y1, x2, y2) in enumerate(bboxes):
        color = colors[idx % len(colors)]
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            image,
            f"bbox_{idx}",
            (x1, max(y1 - 8, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )

    cv2.imwrite(str(output_path), image)


def save_mask_overlay(image_path: Path, results, output_path: Path) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"无法读取输入图像: {image_path}")

    overlay = image.copy()
    colors = [
        (0, 255, 0),
        (0, 165, 255),
        (255, 0, 0),
        (255, 255, 0),
        (255, 0, 255),
    ]

    color_idx = 0
    for result in results:
        if result.masks is None or result.masks.data is None:
            continue
        for mask in result.masks.data:
            mask_array = mask.detach().cpu().numpy().astype(bool)
            color = np.array(colors[color_idx % len(colors)], dtype=np.uint8)
            overlay[mask_array] = ((0.45 * overlay[mask_array]) + (0.55 * color)).astype(np.uint8)
            color_idx += 1

    blended = cv2.addWeighted(overlay, 0.75, image, 0.25, 0.0)
    cv2.imwrite(str(output_path), blended)


def save_binary_mask(results, output_path: Path) -> None:
    combined_mask = None

    for result in results:
        if result.masks is None or result.masks.data is None:
            continue
        for mask in result.masks.data:
            mask_array = mask.detach().cpu().numpy().astype(bool)
            if combined_mask is None:
                combined_mask = np.zeros(mask_array.shape, dtype=bool)
            combined_mask |= mask_array

    if combined_mask is None:
        raise ValueError("没有可保存的 mask")

    cv2.imwrite(str(output_path), combined_mask.astype(np.uint8) * 255)


def main() -> None:
    args = build_parser().parse_args()
    bboxes = args.bboxes

    reset_output_dir(OUTPUT_DIR)
    save_bbox_overlay(IMAGE_PATH, bboxes, BBOX_PREVIEW_PATH)
    print(f"saved bbox overlay: {BBOX_PREVIEW_PATH}")

    overrides = dict(
        conf=0.25,
        task="segment",
        mode="predict",
        model=str(MODEL_PATH),
        half=True,
        project=str(OUTPUT_DIR.parent),
        name=OUTPUT_DIR.name,
        exist_ok=True,
    )

    predictor = SAM3SemanticPredictor(overrides=overrides)
    predictor.set_image(str(IMAGE_PATH))

    results = predictor(bboxes=bboxes, save=True)
    save_mask_overlay(IMAGE_PATH, results, MASK_OVERLAY_PATH)
    print(f"saved mask overlay: {MASK_OVERLAY_PATH}")
    save_binary_mask(results, MASK_BINARY_PATH)
    print(f"saved binary mask: {MASK_BINARY_PATH}")


if __name__ == "__main__":
    main()
