from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any

from shiny_counter.gpu_policy import (
    EXPECTED_TORCHVISION_VERSION,
    validate_release_cuda_build,
)
from shiny_counter.ocr import OCR_MODEL_MD5, OCR_MODEL_SHA256


def validate_cuda_release(torch_module: Any) -> dict[str, Any]:
    return validate_release_cuda_build(torch_module)


def validate_models(model_directory: Path) -> dict[str, dict[str, str]]:
    hashes: dict[str, dict[str, str]] = {}
    for name, expected in OCR_MODEL_SHA256.items():
        path = model_directory / name
        if not path.is_file():
            raise RuntimeError(f"OCR 模型缺失：{path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"OCR 模型 SHA-256 不匹配：{name}")
        md5 = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
        if md5 != OCR_MODEL_MD5[name]:
            raise RuntimeError(f"OCR 模型官方 MD5 不匹配：{name}")
        hashes[name] = {
            "sha256": actual,
            "official_md5": md5,
        }
    return hashes


def build_report(model_directory: Path) -> dict[str, Any]:
    import torch

    report = validate_cuda_release(torch)
    torchvision_version = importlib.metadata.version("torchvision")
    if (
        torchvision_version.split("+", 1)[0]
        != EXPECTED_TORCHVISION_VERSION
    ):
        raise RuntimeError(
            f"发布环境必须使用 torchvision {EXPECTED_TORCHVISION_VERSION}，"
            f"当前为 {torchvision_version}"
        )
    report.update(
        {
            "torchvision": torchvision_version,
            "python": sys.version,
            "platform": platform.platform(),
            "models": validate_models(model_directory),
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "easyocr",
                    "mss",
                    "numpy",
                    "opencv-python-headless",
                    "PySide6",
                    "pywin32",
                    "pyinstaller",
                )
            },
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.model_dir)
    except Exception as error:
        print(f"发布环境验证失败：{error}", file=sys.stderr)
        return 4
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
