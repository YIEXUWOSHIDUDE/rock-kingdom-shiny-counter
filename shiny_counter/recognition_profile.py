"""Season-specific recognition defaults, independent of UI and OCR runtimes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RecognitionProfile:
    profile_id: str
    name: str
    keywords: tuple[str, ...]
    region: tuple[float, float, float, float]
    min_confidence: float
    interval_ms: int
    enter_frames: int
    exit_frames: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "region", tuple(self.region))
        if len(self.region) != 4:
            raise ValueError("recognition region must contain four ratios")
        left, top, right, bottom = self.region
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("recognition region must be a nonempty rectangle within the frame")
        if not any(keyword.strip() for keyword in self.keywords):
            raise ValueError("at least one OCR keyword is required")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("OCR confidence must be between 0 and 1")
        if not 200 <= self.interval_ms <= 5000:
            raise ValueError("OCR interval must be between 200 and 5000 ms")
        if self.enter_frames < 1 or self.exit_frames < 1:
            raise ValueError("OCR frame counts must be positive")


CURRENT_RECOGNITION_PROFILE = RecognitionProfile(
    profile_id="s4_meteor",
    name="S4 星星横幅",
    keywords=("划破天幕坠落",),
    region=(0.28, 0.10, 0.72, 0.27),
    min_confidence=0.55,
    interval_ms=200,
    enter_frames=1,
    exit_frames=2,
)


class UnknownRecognitionProfileError(ValueError):
    """A saved profile requires support from a different application version."""


def get_recognition_profile(profile_id: str) -> RecognitionProfile:
    if profile_id != CURRENT_RECOGNITION_PROFILE.profile_id:
        raise UnknownRecognitionProfileError(
            f"unknown recognition profile: {profile_id!r}；请使用支持此识别配置的版本。"
        )
    return CURRENT_RECOGNITION_PROFILE


def migrate_recognition_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate only the exact untagged legacy default, without mutating input.

    Legacy files have no provenance for keywords: manually entering that exact
    old default is indistinguishable from accepting it. Other values are kept.
    """
    settings = dict(raw)
    profile = get_recognition_profile(
        settings.get("recognition_profile_id", CURRENT_RECOGNITION_PROFILE.profile_id)
    )
    if (
        "recognition_profile_id" not in settings
        and settings.get("ocr_keywords") == ["写进了童话里"]
    ):
        settings["ocr_keywords"] = list(profile.keywords)
    settings.setdefault("recognition_profile_id", profile.profile_id)
    settings.setdefault("ocr_keywords", list(profile.keywords))
    settings.setdefault("ocr_min_confidence", profile.min_confidence)
    settings.setdefault("ocr_interval_ms", profile.interval_ms)
    settings.setdefault("ocr_enter_frames", profile.enter_frames)
    settings.setdefault("ocr_exit_frames", profile.exit_frames)
    return settings
