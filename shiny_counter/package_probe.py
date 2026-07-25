from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .ocr import OCR_MODEL_FILES, OCR_MODEL_LOCK, OCR_MODEL_SHA256
from .runtime_probe import RuntimeProbeReport


REQUIRED_FROZEN_MODULES = (
    "PySide6",
    "cv2",
    "easyocr",
    "mss",
    "numpy",
    "torch",
    "win32gui",
    "win32process",
)


def probe_packaged_dependencies(
    bundle_root: Path,
    *,
    importer: Callable[[str], Any] = importlib.import_module,
    expected_model_hashes: Mapping[str, str] | None = OCR_MODEL_SHA256,
) -> RuntimeProbeReport:
    details: dict[str, Any] = {"modules": {}}
    for name in REQUIRED_FROZEN_MODULES:
        try:
            module = importer(name)
        except Exception as error:
            details["error_type"] = type(error).__name__
            return RuntimeProbeReport(
                ok=False,
                stage="dependency_import",
                message=f"冻结包缺少或无法导入 {name}：{error}",
                details=details,
            )
        details["modules"][name] = {
            "version": str(getattr(module, "__version__", "")),
            "path": str(getattr(module, "__file__", "")),
        }

    try:
        version = (bundle_root / "VERSION").read_text(encoding="ascii").strip()
        if not version:
            raise ValueError("VERSION 为空")
        details["version"] = version
        model_hashes: dict[str, str] = {}
        for name in OCR_MODEL_FILES:
            path = bundle_root / "ocr-models" / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if (
                expected_model_hashes is not None
                and digest != expected_model_hashes[name]
            ):
                raise ValueError(f"OCR 模型哈希不匹配：{name}")
            model_hashes[name] = digest
        details["models"] = model_hashes
        model_lock_path = bundle_root / "ocr-models.lock.json"
        packaged_model_lock = json.loads(
            model_lock_path.read_text(encoding="utf-8")
        )
        if packaged_model_lock != OCR_MODEL_LOCK:
            raise ValueError("OCR 模型来源锁与运行时策略不一致")
        details["model_lock_sha256"] = hashlib.sha256(
            model_lock_path.read_bytes()
        ).hexdigest()
        details["easyocr_model_policy_version"] = packaged_model_lock[
            "easyocr_version"
        ]
        probe_path = bundle_root / "ocr-probe" / "ocr-probe.png"
        details["probe_image_sha256"] = hashlib.sha256(
            probe_path.read_bytes()
        ).hexdigest()
    except Exception as error:
        details["error_type"] = type(error).__name__
        return RuntimeProbeReport(
            ok=False,
            stage="packaged_assets",
            message=f"冻结包资源验证失败：{error}",
            details=details,
        )

    return RuntimeProbeReport(
        ok=True,
        stage="complete",
        message="冻结包依赖与离线资源验证通过。",
        details=details,
    )
