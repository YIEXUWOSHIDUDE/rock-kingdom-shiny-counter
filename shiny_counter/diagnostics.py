from __future__ import annotations

import json
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class DiagnosticLog:
    def __init__(self, data_root: Path, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.directory = data_root / "logs"
        self.path = self.directory / "diagnostics.jsonl"
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def record(
        self,
        *,
        stage: str,
        code: str,
        message: str,
        error: BaseException | None = None,
        context: dict[str, Any] | None = None,
    ) -> Path:
        entry: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(),
            "stage": stage,
            "code": code,
            "message": message,
            "context": context or {},
        }
        if error is not None:
            entry["error_type"] = type(error).__name__
            entry["error"] = str(error)
            entry["traceback"] = "".join(
                traceback.format_exception(
                    type(error),
                    error,
                    error.__traceback__,
                )
            )

        encoded = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                previous = self.directory / "diagnostics.previous.jsonl"
                previous.unlink(missing_ok=True)
                self.path.replace(previous)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
        return self.path
