from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from shiny_counter.probe_asset import OCR_PROBE_TEXT


def create_probe_image(destination: Path, font_path: Path) -> None:
    if not font_path.is_file():
        raise FileNotFoundError(f"中文字体不存在：{font_path}")
    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 82)
    box = draw.textbbox((0, 0), OCR_PROBE_TEXT, font=font)
    left = (image.width - (box[2] - box[0])) // 2
    top = (image.height - (box[3] - box[1])) // 2 - box[1]
    draw.text((left, top), OCR_PROBE_TEXT, fill="black", font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_probe_image(args.output, args.font)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
