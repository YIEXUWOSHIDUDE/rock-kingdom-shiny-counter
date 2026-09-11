from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .ocr import OCR_MODEL_FILES, OCR_MODEL_LOCK, OCR_MODEL_SHA256
from .runtime_probe import RuntimeProbeReport


REQUIRED_FROZEN_MODULES = (
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "cv2",
    "easyocr",
    "mss",
    "numpy",
    "torch",
    "win32gui",
    "win32process",
)


def _check_legacy_recognition_migration(profile: Any) -> dict[str, Any]:
    from .storage import AppData

    data = AppData()
    data.counter.increment(source="package_probe")
    data.counter.reset(source="package_probe")
    data.counter.increment(source="package_probe")
    data.counter.increment(source="package_probe")
    legacy = data.to_dict()
    legacy["settings"].pop("recognition_profile_id")
    legacy["settings"]["ocr_keywords"] = ["写进了童话里"]
    counter_before = json.dumps(legacy["counter"], sort_keys=True)
    migrated = AppData.from_dict(legacy)
    if (
        migrated.settings.recognition_profile_id != profile.profile_id
        or tuple(migrated.settings.ocr_keywords) != profile.keywords
    ):
        raise ValueError("旧默认关键词没有迁移到当前识别方案")
    serialized = migrated.to_dict()
    if json.dumps(serialized["counter"], sort_keys=True) != counter_before:
        raise ValueError("识别方案迁移改变了计数或历史记录")
    if AppData.from_dict(serialized).to_dict() != serialized:
        raise ValueError("识别方案迁移后重复加载结果不稳定")
    return {
        "profile_id": migrated.settings.recognition_profile_id,
        "keywords": list(migrated.settings.ocr_keywords),
        "count": migrated.counter.count,
        "history_events": len(migrated.counter.history),
        "rounds": len(migrated.counter.rounds),
        "counter_preserved": True,
        "stable_reload": True,
        "scope": "synthetic in-memory legacy data; no user data files",
    }


def _check_recognition_stream(profile: Any) -> dict[str, Any]:
    import numpy as np

    from .ocr import OCRText
    from .recognition import BannerRecognitionStream
    from .storage import AppSettings

    now = 0.0
    stream = BannerRecognitionStream(AppSettings(), clock=lambda: now)
    present_samples = profile.enter_frames + 2
    markers = (
        [160] * present_samples
        + [0] * profile.exit_frames
        + [220] * present_samples
    )
    expected_banner = [False] * (profile.enter_frames - 1) + [True, False, False]
    expected = expected_banner + [False] * profile.exit_frames + expected_banner
    counted: list[bool] = []
    keyword = next(word for word in profile.keywords if word.strip())
    crop_shape: list[int] = []
    try:
        if stream.profile != profile:
            raise ValueError("识别协调层没有使用当前识别方案")
        for marker in markers:
            now += profile.interval_ms / 1000.0
            frame = np.full((160, 320, 3), marker, dtype=np.uint8)
            stream.offer(frame, captured_at=now)
            sample = stream.take(timeout=0)
            if sample is None:
                raise ValueError("识别协调层没有交付已提供的合成样本")
            crop_shape = list(sample.frame.shape)
            texts = [OCRText(keyword, 1.0)] if marker else []
            decision = stream.observe(sample, texts)
            if not decision.accepted:
                raise ValueError("识别协调层拒绝了当前合成样本")
            counted.append(decision.counted)
        if counted != expected:
            raise ValueError(f"两段提示或持续提示去重自检失败：{counted}，预期 {expected}")
    finally:
        stream.close()
    return {
        "module": BannerRecognitionStream.__module__,
        "profile_id": profile.profile_id,
        "input": "synthetic_ocr_text",
        "gpu_inference": False,
        "user_data_accessed": False,
        "scope": "sequential synthetic frames/text; no Worker, live capture or GPU accuracy check",
        "crop_shape": crop_shape,
        "counted": counted,
        "counts_by_banner": [sum(counted[:present_samples]), sum(counted[-present_samples:])],
    }


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

    try:
        from .recognition_profile import CURRENT_RECOGNITION_PROFILE
        from .storage import AppSettings

        profile = AppSettings().recognition_profile()
        if profile != CURRENT_RECOGNITION_PROFILE:
            raise ValueError("新建设置与当前识别方案不一致")
        details["recognition_profile"] = asdict(profile)
    except Exception as error:
        details["error_type"] = type(error).__name__
        return RuntimeProbeReport(
            ok=False,
            stage="recognition_profile",
            message=f"冻结包识别方案验证失败：{error}",
            details=details,
        )

    try:
        details["recognition_migration"] = _check_legacy_recognition_migration(profile)
    except Exception as error:
        details["error_type"] = type(error).__name__
        return RuntimeProbeReport(
            ok=False,
            stage="recognition_migration",
            message=f"冻结包识别方案迁移自检失败：{error}",
            details=details,
        )

    try:
        details["recognition_stream"] = _check_recognition_stream(profile)
    except Exception as error:
        details["error_type"] = type(error).__name__
        return RuntimeProbeReport(
            ok=False,
            stage="recognition_stream",
            message=f"冻结包识别协调层自检失败：{error}",
            details=details,
        )

    return RuntimeProbeReport(
        ok=True,
        stage="complete",
        message="冻结包依赖、离线资源与识别协调层自检通过；GPU OCR 准确率需单独验证。",
        details=details,
    )
