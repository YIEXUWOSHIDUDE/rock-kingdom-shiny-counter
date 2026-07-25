from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .gpu_policy import (
    GPUCompatibilityError,
    validate_cuda_device,
    validate_release_cuda_build,
)
from .ocr import OCR_MODEL_FILES, OCR_MODEL_SHA256, normalize_text
from .probe_asset import OCR_PROBE_EXPECTED_FRAGMENT


@dataclass(frozen=True, slots=True)
class RuntimeProbeReport:
    ok: bool
    stage: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def write_runtime_probe_report(
    destination: Path,
    report: RuntimeProbeReport,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0 if report.ok else 4


def probe_gpu_runtime(
    model_directory: Path,
    *,
    torch_module: Any,
    easyocr_module: Any,
    expected_hashes: Mapping[str, str] | None = OCR_MODEL_SHA256,
    probe_image: Any | None = None,
    probe_image_path: Path | None = None,
    driver_version: str = "",
) -> RuntimeProbeReport:
    details = {
        "torch": str(torch_module.__version__),
        "cuda_build": str(torch_module.version.cuda),
        "driver": driver_version,
    }
    if not torch_module.cuda.is_available():
        details["error_type"] = "CUDAUnavailable"
        return RuntimeProbeReport(
            ok=False,
            stage="cuda_available",
            message="CUDA 不可用；GPU-only 模式不允许 CPU 回退。",
            details=details,
        )
    stage = "cuda_inventory"
    try:
        details["device_index"] = int(
            getattr(torch_module.cuda, "current_device", lambda: 0)()
        )
        details["device"] = str(torch_module.cuda.get_device_name())
        capability = tuple(torch_module.cuda.get_device_capability())
        details["capability"] = list(capability)
        details["architectures"] = list(torch_module.cuda.get_arch_list())

        stage = "release_runtime"
        release_runtime = validate_release_cuda_build(torch_module)
        details["release_architectures"] = release_runtime["architectures"]
    except Exception as error:
        details["error_type"] = type(error).__name__
        if isinstance(error, GPUCompatibilityError):
            details["error_code"] = error.code
        return RuntimeProbeReport(
            ok=False,
            stage=stage,
            message=f"{error}；已停止安装，且不会回退到 CPU。",
            details=details,
        )

    stage = "cuda_architecture"
    try:
        details["device_label"] = validate_cuda_device(torch_module)

        stage = "cuda_kernel"
        started = time.monotonic()
        tensor = torch_module.ones((4, 4), device="cuda")
        smoke_value = (tensor @ tensor).sum().item()
        torch_module.cuda.synchronize()
        details["cuda_smoke_value"] = float(smoke_value)
        details["cuda_smoke_ms"] = round((time.monotonic() - started) * 1000, 2)

        stage = "model_validation"
        model_hashes: dict[str, str] = {}
        for name in OCR_MODEL_FILES:
            model = model_directory / name
            if not model.is_file():
                raise FileNotFoundError(f"内置 OCR 模型缺失：{name}")
            digest = hashlib.sha256(model.read_bytes()).hexdigest().lower()
            model_hashes[name] = digest
            if expected_hashes is not None and digest != expected_hashes[name].lower():
                raise ValueError(f"内置 OCR 模型校验失败：{name}")
        details["models"] = model_hashes

        stage = "easyocr_initialization"
        reader = easyocr_module.Reader(
            ["ch_sim", "en"],
            gpu="cuda",
            model_storage_directory=str(model_directory),
            download_enabled=False,
            verbose=False,
        )
        reader_device = str(getattr(reader, "device", ""))
        details["reader_device"] = reader_device
        if not reader_device.startswith("cuda"):
            raise RuntimeError(
                f"EasyOCR 实际设备为 {reader_device or 'unknown'}；不允许 CPU 回退。"
            )

        stage = "easyocr_inference"
        if probe_image is None:
            import cv2

            if probe_image_path is None or not probe_image_path.is_file():
                raise FileNotFoundError("安装包缺少固定中文 OCR 探针图片。")
            probe_hash = hashlib.sha256(probe_image_path.read_bytes()).hexdigest()
            details["probe_image_sha256"] = probe_hash
            probe_image = cv2.imread(str(probe_image_path))
            if probe_image is None:
                raise ValueError("无法读取固定中文 OCR 探针图片。")
        started = time.monotonic()
        results = reader.readtext(probe_image, detail=1, paragraph=False)
        torch_module.cuda.synchronize()
        details["easyocr_inference_ms"] = round(
            (time.monotonic() - started) * 1000,
            2,
        )
        details["easyocr_result_count"] = len(results)
        if not results:
            raise RuntimeError("EasyOCR GPU 探针未识别到固定测试文字。")
        recognized = " | ".join(
            str(item[1])
            for item in results
            if len(item) >= 2
        )
        details["easyocr_result"] = recognized[:200]
        if normalize_text(OCR_PROBE_EXPECTED_FRAGMENT) not in normalize_text(
            recognized
        ):
            raise RuntimeError(
                "EasyOCR GPU 探针没有识别出预期中文短语“"
                + OCR_PROBE_EXPECTED_FRAGMENT
                + "”。"
            )
    except Exception as error:
        details["error_type"] = type(error).__name__
        if isinstance(error, GPUCompatibilityError):
            details["error_code"] = error.code
        return RuntimeProbeReport(
            ok=False,
            stage=stage,
            message=str(error),
            details=details,
        )

    return RuntimeProbeReport(
        ok=True,
        stage="complete",
        message="CUDA 与 EasyOCR GPU 运行时验证通过。",
        details=details,
    )
