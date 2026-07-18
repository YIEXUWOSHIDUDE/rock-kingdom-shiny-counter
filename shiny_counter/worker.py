from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

from .capture import CaptureError, Win32Capture
from .detection import PresenceGate
from .ocr import EasyOCREngine, OCRError, OCRKeywordMatcher, crop_notification_banner
from .storage import AppSettings


class RecognitionWorker(QThread):
    detected = Signal(float)
    status_changed = Signal(str, float)
    ocr_text_changed = Signal(str)
    stopped_with_error = Signal(str)

    def __init__(self, settings: AppSettings, data_root) -> None:
        super().__init__()
        self.settings = settings
        self.data_root = data_root
        self._paused = threading.Event()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def run(self) -> None:
        if not self.settings.window_title or self.settings.client_size is None:
            self.stopped_with_error.emit("尚未选择游戏窗口")
            return
        self._run_ocr()

    def _run_ocr(self) -> None:
        self.status_changed.emit("正在检查 NVIDIA GPU 并准备中文 OCR 模型", -1.0)
        capture = None
        try:
            capture = Win32Capture(self.settings.window_title)
            engine = EasyOCREngine(self.data_root / "ocr-models")
            matcher = OCRKeywordMatcher(
                self.settings.ocr_keywords,
                min_confidence=self.settings.ocr_min_confidence,
            )
            gate = PresenceGate(
                enter_frames=self.settings.ocr_enter_frames,
                exit_frames=self.settings.ocr_exit_frames,
            )
        except (RuntimeError, OCRError, ValueError) as error:
            if capture is not None:
                capture.close()
            self.stopped_with_error.emit(str(error))
            return

        try:
            while not self.isInterruptionRequested():
                if self._paused.is_set():
                    self.status_changed.emit("已暂停", -1.0)
                    self.msleep(150)
                    continue
                scan_started = time.monotonic()
                try:
                    frame, _ = capture.capture_client(self.settings.client_size)
                    texts = engine.read(crop_notification_banner(frame))
                    joined = " | ".join(item.text for item in texts)
                    self.ocr_text_changed.emit(joined)
                    match = matcher.match(texts)
                    if gate.observe(match is not None):
                        self.detected.emit(match.confidence if match is not None else 1.0)
                    if match is None:
                        preview = joined[:36] if joined else "未识别到文字"
                        self.status_changed.emit(f"OCR {engine.device_label}：{preview}", -1.0)
                    else:
                        self.status_changed.emit(
                            f"匹配“{match.keyword}”",
                            match.confidence,
                        )
                except CaptureError as error:
                    gate.reset()
                    self.status_changed.emit(str(error), -1.0)
                    self.msleep(500)
                    continue
                except OCRError as error:
                    self.stopped_with_error.emit(str(error))
                    return
                elapsed_ms = int((time.monotonic() - scan_started) * 1000)
                remaining_ms = max(0, self.settings.ocr_interval_ms - elapsed_ms)
                if remaining_ms:
                    self.msleep(remaining_ms)
        finally:
            capture.close()
