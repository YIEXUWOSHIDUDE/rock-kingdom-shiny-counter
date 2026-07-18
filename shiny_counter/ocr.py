from __future__ import annotations

import hashlib
import re
import shutil
import sys
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


NOTIFICATION_BANNER_REGION = (0.28, 0.10, 0.72, 0.27)
OCR_MODEL_FILES = ("craft_mlt_25k.pth", "zh_sim_g2.pth")
OCR_MODEL_SHA256 = {
    "craft_mlt_25k.pth": "4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17",
    "zh_sim_g2.pth": "cb678fdef09d651e7763ca551ad790dc89f0b2e3d2a640484330e338fb574c7a",
}
OCR_MODEL_SOURCES = {
    "craft_mlt_25k.pth": (
        "https://www.modelscope.cn/models/ms-agent/craft_mlt_25k/resolve/master/craft_mlt_25k.zip",
        "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
    ),
    "zh_sim_g2.pth": (
        "https://api.gitcode.com/api/v5/repos/open-source-toolkit/81f68/raw/EASYOCR.zip?ref=main",
        "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/zh_sim_g2.zip",
    ),
}


class OCRError(RuntimeError):
    pass


def download_ocr_model(url: str, destination: Path) -> None:
    package_path = destination.with_suffix(destination.suffix + ".package")
    package_path.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "RockKingdomShinyCounter/0.4"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            with package_path.open("wb") as package:
                shutil.copyfileobj(response, package)

        if zipfile.is_zipfile(package_path):
            with zipfile.ZipFile(package_path) as archive:
                matching = [
                    name
                    for name in archive.namelist()
                    if Path(name).name == destination.name
                ]
                if not matching:
                    raise OCRError(f"下载包中缺少 {destination.name}")
                with archive.open(matching[0]) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        else:
            package_path.replace(destination)
    finally:
        package_path.unlink(missing_ok=True)


def validate_cuda_device(torch_module: Any) -> str:
    if not torch_module.cuda.is_available():
        raise OCRError(
            "未检测到可用的 NVIDIA CUDA。最低要求：RTX 20 系显卡、"
            "Windows NVIDIA 驱动 580.88；本程序不支持 CPU 模式。"
        )
    capability = tuple(torch_module.cuda.get_device_capability())
    device_name = str(torch_module.cuda.get_device_name())
    if capability < (7, 5):
        raise OCRError(
            f"显卡 {device_name} 的 CUDA 计算能力 {capability[0]}.{capability[1]} "
            "低于最低要求 7.5（RTX 20 系）。"
        )
    architecture = f"sm_{capability[0]}{capability[1]}"
    supported_architectures = set(torch_module.cuda.get_arch_list())
    same_major_compatible = any(
        (match := re.fullmatch(r"sm_(\d+)(\d)", candidate))
        and int(match.group(1)) == capability[0]
        and int(match.group(2)) <= capability[1]
        for candidate in supported_architectures
    )
    if not same_major_compatible:
        raise OCRError(
            f"当前 PyTorch CUDA 运行库不包含 {architecture}，无法使用 {device_name}。"
            "RTX 50 系需要 CUDA 13.0 兼容版安装包。"
        )
    return f"CUDA · {device_name} · {architecture}"


def ensure_ocr_models(
    model_directory: Path,
    *,
    bundled_directory: Path | None = None,
    expected_hashes: Mapping[str, str] | None = None,
    model_sources: Mapping[str, Iterable[str]] | None = None,
    downloader: Callable[[str, Path], None] | None = None,
) -> str:
    model_directory.mkdir(parents=True, exist_ok=True)
    if model_sources is None:
        model_sources = OCR_MODEL_SOURCES
    if downloader is None:
        downloader = download_ocr_model

    def valid(path: Path, name: str) -> bool:
        if not path.is_file():
            return False
        if expected_hashes is None:
            return True
        digest = hashlib.sha256(path.read_bytes()).hexdigest().lower()
        return digest == expected_hashes[name].lower()

    if all(valid(model_directory / name, name) for name in OCR_MODEL_FILES):
        return "existing"

    if bundled_directory is not None and all(
        valid(bundled_directory / name, name) for name in OCR_MODEL_FILES
    ):
        for name in OCR_MODEL_FILES:
            shutil.copy2(bundled_directory / name, model_directory / name)
        return "bundled"

    if model_sources is not None and downloader is not None:
        for name in OCR_MODEL_FILES:
            destination = model_directory / name
            if valid(destination, name):
                continue
            errors: list[str] = []
            for url in model_sources[name]:
                temporary = destination.with_suffix(destination.suffix + ".download")
                temporary.unlink(missing_ok=True)
                try:
                    downloader(url, temporary)
                    if not valid(temporary, name):
                        raise OCRError(f"{name} 校验失败")
                    temporary.replace(destination)
                    break
                except Exception as error:
                    temporary.unlink(missing_ok=True)
                    errors.append(f"{url}: {error}")
            else:
                raise OCRError(f"{name} 下载失败：" + "；".join(errors))
        return "downloaded"

    raise OCRError("OCR 模型缺失，且安装包中没有可用的离线模型。")


@dataclass(frozen=True, slots=True)
class OCRText:
    text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class OCRMatch:
    keyword: str
    text: str
    confidence: float


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", "", normalized)


def crop_notification_banner(frame: Any) -> Any:
    """Crop the top-centre notification banner using resolution-independent ratios."""
    height, width = frame.shape[:2]
    left_ratio, top_ratio, right_ratio, bottom_ratio = NOTIFICATION_BANNER_REGION
    left = int(width * left_ratio)
    top = int(height * top_ratio)
    right = int(width * right_ratio)
    bottom = int(height * bottom_ratio)
    return frame[top:bottom, left:right]


class OCRKeywordMatcher:
    def __init__(self, keywords: Iterable[str], min_confidence: float = 0.55) -> None:
        cleaned = [keyword.strip() for keyword in keywords if keyword.strip()]
        if not cleaned:
            raise ValueError("至少需要一个 OCR 关键词")
        if not 0 <= min_confidence <= 1:
            raise ValueError("OCR 置信度必须在 0 到 1 之间")
        self.keywords = cleaned
        self.min_confidence = min_confidence

    def match(self, results: Iterable[OCRText]) -> OCRMatch | None:
        eligible = [result for result in results if result.confidence >= self.min_confidence]
        best: OCRMatch | None = None
        for result in eligible:
            normalized_result = normalize_text(result.text)
            for keyword in self.keywords:
                if normalize_text(keyword) in normalized_result:
                    candidate = OCRMatch(keyword, result.text, result.confidence)
                    if best is None or candidate.confidence > best.confidence:
                        best = candidate
        if best is not None:
            return best

        combined = "".join(normalize_text(result.text) for result in eligible)
        for keyword in self.keywords:
            if normalize_text(keyword) in combined:
                return OCRMatch(
                    keyword=keyword,
                    text=" | ".join(result.text for result in eligible),
                    confidence=min(result.confidence for result in eligible),
                )
        return None


class EasyOCREngine:
    def __init__(
        self,
        model_directory: Path,
        *,
        bundled_model_directory: Path | None = None,
        expected_hashes: Mapping[str, str] | None = OCR_MODEL_SHA256,
        model_sources: Mapping[str, Iterable[str]] | None = None,
        downloader: Callable[[str, Path], None] | None = None,
    ) -> None:
        try:
            import easyocr
            import torch
        except ImportError as error:
            raise OCRError(
                "缺少 OCR 依赖，请重新执行 python -m pip install -r requirements.txt"
            ) from error

        self.device_label = validate_cuda_device(torch)
        if bundled_model_directory is None:
            bundled_model_directory = Path(
                getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
            ) / "ocr-models"
        ensure_ocr_models(
            model_directory,
            bundled_directory=bundled_model_directory,
            expected_hashes=expected_hashes,
            model_sources=model_sources,
            downloader=downloader,
        )
        try:
            self.reader = easyocr.Reader(
                ["ch_sim", "en"],
                gpu=True,
                model_storage_directory=str(model_directory),
                download_enabled=False,
                verbose=False,
            )
        except Exception as error:
            raise OCRError(f"OCR 模型初始化失败：{error}") from error

    def read(self, frame: Any) -> list[OCRText]:
        try:
            raw_results = self.reader.readtext(frame, detail=1, paragraph=False)
        except Exception as error:
            raise OCRError(f"OCR 识别失败：{error}") from error
        results: list[OCRText] = []
        for item in raw_results:
            if len(item) < 3:
                continue
            results.append(OCRText(text=str(item[1]), confidence=float(item[2])))
        return results
