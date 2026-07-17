from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class OCRError(RuntimeError):
    pass


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
    def __init__(self, model_directory: Path) -> None:
        try:
            import easyocr
            import torch
        except ImportError as error:
            raise OCRError(
                "缺少 OCR 依赖，请重新执行 python -m pip install -r requirements.txt"
            ) from error

        if not torch.cuda.is_available():
            raise OCRError(
                "PyTorch 未检测到 CUDA。请按 README 安装与显卡驱动匹配的 CUDA 版 PyTorch。"
            )
        model_directory.mkdir(parents=True, exist_ok=True)
        try:
            self.reader = easyocr.Reader(
                ["ch_sim", "en"],
                gpu=True,
                model_storage_directory=str(model_directory),
                download_enabled=True,
                verbose=False,
            )
        except Exception as error:
            raise OCRError(f"OCR 模型初始化失败：{error}") from error
        self.device_label = "CUDA"

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
