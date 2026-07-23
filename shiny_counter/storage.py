from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .model import CounterState, HistoryEvent, PityRound


DATA_VERSION = 1


def default_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "RockKingdomShinyCounter"
    return Path.home() / ".rock-kingdom-shiny-counter"


@dataclass(slots=True)
class AppSettings:
    window_title: str = ""
    client_size: tuple[int, int] | None = None
    ocr_keywords: list[str] = field(default_factory=lambda: ["写进了童话里"])
    ocr_min_confidence: float = 0.55
    ocr_interval_ms: int = 200
    ocr_enter_frames: int = 1
    ocr_exit_frames: int = 2
    opacity: float = 0.92
    click_through: bool = False
    position_locked: bool = True
    overlay_position: tuple[int, int] | None = None
    hotkeys: dict[str, str] = field(
        default_factory=lambda: {
            "toggle_click_through": "Ctrl+Alt+T",
            "increment": "Ctrl+Alt+Up",
            "undo": "Ctrl+Alt+Down",
            "pause": "Ctrl+Alt+P",
        }
    )

    def validate(self) -> None:
        if not 0.30 <= self.opacity <= 1:
            raise ValueError("opacity must be between 0.30 and 1")
        if not 0 <= self.ocr_min_confidence <= 1:
            raise ValueError("OCR confidence must be between 0 and 1")
        if not 200 <= self.ocr_interval_ms <= 5000:
            raise ValueError("OCR interval must be between 200 and 5000 ms")
        if self.ocr_enter_frames < 1 or self.ocr_exit_frames < 1:
            raise ValueError("OCR frame counts must be positive")
        if not any(keyword.strip() for keyword in self.ocr_keywords):
            raise ValueError("at least one OCR keyword is required")
        if self.client_size is not None and (
            len(self.client_size) != 2 or self.client_size[0] < 1 or self.client_size[1] < 1
        ):
            raise ValueError("client_size must contain two positive values")
        if self.overlay_position is not None and len(self.overlay_position) != 2:
            raise ValueError("overlay_position must contain two values")


@dataclass(slots=True)
class AppData:
    counter: CounterState = field(default_factory=CounterState)
    settings: AppSettings = field(default_factory=AppSettings)
    version: int = DATA_VERSION

    def validate(self) -> None:
        if self.version != DATA_VERSION:
            raise ValueError(f"unsupported data version: {self.version}")
        self.counter.__post_init__()
        self.settings.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppData":
        if not isinstance(raw, dict):
            raise ValueError("data root must be an object")
        version = int(raw.get("version", 0))
        if version != DATA_VERSION:
            raise ValueError(f"unsupported data version: {version}")

        counter_raw = raw.get("counter")
        settings_raw = raw.get("settings")
        if not isinstance(counter_raw, dict) or not isinstance(settings_raw, dict):
            raise ValueError("counter and settings objects are required")

        events = [HistoryEvent(**event) for event in counter_raw.get("history", [])]
        rounds = [PityRound(**round_data) for round_data in counter_raw.get("rounds", [])]
        counter = CounterState(
            target_name=str(counter_raw.get("target_name", "异色宠物")),
            pity_limit=int(counter_raw.get("pity_limit", 80)),
            count=int(counter_raw.get("count", 0)),
            pity_reached=bool(counter_raw.get("pity_reached", False)),
            history=events,
            rounds=rounds,
        )

        client_size_raw = settings_raw.get("client_size")
        position_raw = settings_raw.get("overlay_position")
        settings = AppSettings(
            window_title=str(settings_raw.get("window_title", "")),
            client_size=tuple(map(int, client_size_raw)) if client_size_raw is not None else None,
            ocr_keywords=[str(item) for item in settings_raw.get("ocr_keywords", ["写进了童话里"])],
            ocr_min_confidence=float(settings_raw.get("ocr_min_confidence", 0.55)),
            ocr_interval_ms=int(settings_raw.get("ocr_interval_ms", 200)),
            ocr_enter_frames=int(settings_raw.get("ocr_enter_frames", 1)),
            ocr_exit_frames=int(settings_raw.get("ocr_exit_frames", 2)),
            opacity=float(settings_raw.get("opacity", 0.92)),
            click_through=bool(settings_raw.get("click_through", False)),
            position_locked=bool(settings_raw.get("position_locked", True)),
            overlay_position=tuple(map(int, position_raw)) if position_raw is not None else None,
            hotkeys=dict(settings_raw.get("hotkeys", AppSettings().hotkeys)),
        )
        data = cls(counter=counter, settings=settings, version=version)
        data.validate()
        return data


class DataStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_data_dir()
        self.path = self.root / "data.json"

    def load(self) -> AppData:
        if not self.path.exists():
            return AppData()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return AppData.from_dict(raw)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup = self.root / f"data.corrupt-{timestamp}.json"
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                pass
            raise DataCorruptError(
                f"计数数据损坏，原文件已保留为 {backup.name}。请从有效备份导入。"
            ) from error

    def save(self, data: AppData) -> None:
        data.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / "data.json.tmp"
        encoded = json.dumps(data.to_dict(), ensure_ascii=False, indent=2) + "\n"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def export_archive(self, destination: Path) -> None:
        if not self.path.exists():
            self.save(AppData())
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.path, "data.json")

    def import_archive(self, source: Path) -> None:
        with zipfile.ZipFile(source, "r") as archive:
            names = set(archive.namelist())
            if "data.json" not in names:
                raise ValueError("archive does not contain data.json")
            if any(Path(name).name != name for name in names):
                raise ValueError("archive contains unsafe paths")
            if archive.getinfo("data.json").file_size > 20 * 1024 * 1024:
                raise ValueError("data.json is too large")
            raw = json.loads(archive.read("data.json").decode("utf-8"))
            imported = AppData.from_dict(raw)

        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            self.export_archive(self.root / f"pre-import-{timestamp}.zip")

        self.save(imported)


class DataCorruptError(RuntimeError):
    pass
