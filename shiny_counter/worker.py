from __future__ import annotations

import threading
import time
from copy import deepcopy
from dataclasses import asdict

from PySide6.QtCore import QThread, Signal

from .capture import CaptureError, Win32Capture, WindowBinding
from .diagnostics import DiagnosticLog
from .gpu_policy import GPUCompatibilityError
from .ocr import EasyOCREngine, OCRError
from .recognition import BannerRecognitionStream
from .storage import AppSettings


CAPTURE_INTERVAL_SECONDS = 0.05


def ocr_result_status_code(recognized_text: str, matched: bool) -> str:
    if matched:
        return "OCR_MATCH"
    return "OCR_TEXT_NO_MATCH" if recognized_text else "OCR_NO_TEXT"


class RecognitionWorker(QThread):
    detected = Signal(float)
    status_changed = Signal(str, float)
    ocr_text_changed = Signal(str)
    stopped_with_error = Signal(str)

    def __init__(self, settings: AppSettings, data_root) -> None:
        super().__init__()
        self.settings = deepcopy(settings)
        self.data_root = data_root
        self._paused = threading.Event()
        self._stream: BannerRecognitionStream | None = None
        self.diagnostics = DiagnosticLog(data_root)
        self._last_capture_error: str | None = None

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()
        if self._stream is not None:
            self._stream.set_paused(paused)

    def run(self) -> None:
        binding = self.settings.window_binding()
        if binding is None:
            self.stopped_with_error.emit("尚未选择游戏窗口")
            return
        try:
            self._run_ocr(binding)
        except Exception as error:
            self._report_error(
                code="WORKER_FAILED",
                stage="recognition_worker",
                message="识别线程意外停止",
                error=error,
                binding=binding,
            )

    def _report_error(
        self,
        *,
        code: str,
        stage: str,
        message: str,
        error: BaseException,
        binding: WindowBinding,
    ) -> None:
        try:
            path = self.diagnostics.record(
                stage=stage,
                code=code,
                message=message,
                error=error,
                context=asdict(binding),
            )
            log_hint = f"；日志：{path}"
        except OSError:
            log_hint = ""
        if isinstance(error, GPUCompatibilityError):
            display_message = f"[{error.code}] {error}"
        else:
            display_message = (
                f"[{code}] {message}（{type(error).__name__}）：{error}{log_hint}"
            )
        self.stopped_with_error.emit(display_message)

    def _report_capture_unavailable(
        self,
        error: BaseException,
        binding: WindowBinding,
    ) -> None:
        error_key = f"{type(error).__name__}:{error}"
        if error_key == self._last_capture_error:
            return
        self._last_capture_error = error_key
        try:
            path = self.diagnostics.record(
                stage="window_capture",
                code="CAPTURE_UNAVAILABLE",
                message="游戏窗口暂时无法捕获",
                error=error,
                context=asdict(binding),
            )
            log_hint = f"；日志：{path}"
        except OSError:
            log_hint = ""
        self.status_changed.emit(
            f"[CAPTURE_UNAVAILABLE] {error}{log_hint}",
            -1.0,
        )

    def _run_ocr(self, binding: WindowBinding) -> None:
        self.status_changed.emit(
            "[GPU_CHECKING] 正在检查 NVIDIA GPU 并准备中文 OCR 模型",
            -1.0,
        )
        frames = BannerRecognitionStream(self.settings)
        self._stream = frames
        frames.set_paused(self._paused.is_set())
        capture_stop = threading.Event()
        capture_ready = threading.Event()
        capture_init_errors: list[BaseException] = []
        producer = threading.Thread(
            target=self._capture_loop,
            args=(
                binding,
                frames,
                capture_stop,
                capture_ready,
                capture_init_errors,
            ),
            name="notification-capture",
            daemon=True,
        )
        producer.start()
        if not capture_ready.wait(timeout=5.0):
            capture_stop.set()
            frames.close()
            producer.join(timeout=2.0)
            self._report_error(
                code="CAPTURE_INIT_TIMEOUT",
                stage="capture_initialization",
                message="窗口捕获初始化超时",
                error=TimeoutError("窗口捕获线程在 5 秒内没有完成初始化"),
                binding=binding,
            )
            return
        if capture_init_errors:
            capture_stop.set()
            frames.close()
            producer.join(timeout=2.0)
            self._report_error(
                code="CAPTURE_INIT_FAILED",
                stage="capture_initialization",
                message="窗口捕获初始化失败",
                error=capture_init_errors[0],
                binding=binding,
            )
            return
        self.status_changed.emit(
            "[CAPTURE_READY] 游戏窗口首帧捕获成功",
            -1.0,
        )
        try:
            engine = EasyOCREngine(self.data_root / "ocr-models")
        except GPUCompatibilityError as error:
            capture_stop.set()
            frames.close()
            producer.join(timeout=2.0)
            self._report_error(
                code=error.code,
                stage="ocr_initialization",
                message="GPU OCR 兼容性检查失败",
                error=error,
                binding=binding,
            )
            return
        except Exception as error:
            capture_stop.set()
            frames.close()
            producer.join(timeout=2.0)
            self._report_error(
                code="OCR_INIT_FAILED",
                stage="ocr_initialization",
                message="GPU OCR 初始化失败",
                error=error,
                binding=binding,
            )
            return
        self.status_changed.emit(
            f"[OCR_READY] GPU OCR 已就绪：{engine.device_label}",
            -1.0,
        )

        try:
            while not self.isInterruptionRequested():
                if self._paused.is_set():
                    self.status_changed.emit("[PAUSED] 已暂停", -1.0)
                    self.msleep(150)
                    continue
                sample = frames.take(timeout=0.2)
                if sample is None:
                    continue
                scan_started = time.monotonic()
                try:
                    texts = engine.read(sample.frame)
                    decision = frames.observe(sample, texts)
                    if not decision.accepted or self.isInterruptionRequested():
                        continue
                    joined = decision.text
                    self.ocr_text_changed.emit(joined)
                    match = decision.match
                    if decision.counted:
                        self.detected.emit(match.confidence if match is not None else 1.0)
                except OCRError as error:
                    self._report_error(
                        code="OCR_READ_FAILED",
                        stage="ocr_inference",
                        message="GPU OCR 识别失败",
                        error=error,
                        binding=binding,
                    )
                    return
                elapsed_ms = int((time.monotonic() - scan_started) * 1000)
                queue_delay_ms = max(
                    0,
                    int((scan_started - sample.captured_at) * 1000),
                )
                if match is None:
                    preview = joined[:30] if joined else "未识别到文字"
                    status_code = ocr_result_status_code(joined, False)
                    self.status_changed.emit(
                        f"[{status_code}] OCR {engine.device_label} · {elapsed_ms} ms"
                        f" · 缓冲 {queue_delay_ms} ms：{preview}",
                        -1.0,
                    )
                else:
                    status_code = "COUNTED" if decision.counted else "OCR_MATCH"
                    self.status_changed.emit(
                        f"[{status_code}] "
                        f"匹配“{match.keyword}” · GPU OCR {elapsed_ms} ms"
                        f" · 缓冲 {queue_delay_ms} ms",
                        match.confidence,
                    )
                remaining_ms = max(0, frames.profile.interval_ms - elapsed_ms)
                if remaining_ms:
                    self.msleep(remaining_ms)
        finally:
            capture_stop.set()
            frames.close()
            producer.join(timeout=2.0)
            if producer.is_alive():
                self._report_error(
                    code="CAPTURE_STOP_TIMEOUT",
                    stage="capture_shutdown",
                    message="窗口捕获线程未在 2 秒内结束",
                    error=TimeoutError("notification capture thread is still running"),
                    binding=binding,
                )

    def _capture_loop(
        self,
        binding: WindowBinding,
        frames: BannerRecognitionStream,
        stop: threading.Event,
        ready: threading.Event,
        init_errors: list[BaseException],
    ) -> None:
        try:
            capture = Win32Capture(binding)
        except Exception as error:
            init_errors.append(error)
            ready.set()
            return
        expected_size = (binding.width, binding.height)
        try:
            try:
                frame, _ = capture.capture_client(expected_size)
                frames.offer(
                    frame,
                    captured_at=time.monotonic(),
                )
            except Exception as error:
                init_errors.append(error)
                return
            finally:
                ready.set()
            while not stop.is_set() and not self.isInterruptionRequested():
                if self._paused.is_set():
                    stop.wait(CAPTURE_INTERVAL_SECONDS)
                    continue
                started = time.monotonic()
                try:
                    frame, _ = capture.capture_client(expected_size)
                    self._last_capture_error = None
                    frames.offer(
                        frame,
                        captured_at=time.monotonic(),
                    )
                except CaptureError as error:
                    frames.invalidate()
                    self._report_capture_unavailable(error, capture.binding)
                    stop.wait(0.5)
                    continue
                except Exception as error:
                    frames.invalidate()
                    self._report_error(
                        code="CAPTURE_LOOP_FAILED",
                        stage="capture_loop",
                        message="窗口连续捕获意外停止",
                        error=error,
                        binding=capture.binding,
                    )
                    self.requestInterruption()
                    return
                remaining = CAPTURE_INTERVAL_SECONDS - (time.monotonic() - started)
                if remaining > 0:
                    stop.wait(remaining)
        finally:
            try:
                capture.close()
            except Exception as error:
                self._report_error(
                    code="CAPTURE_CLOSE_FAILED",
                    stage="capture_shutdown",
                    message="窗口捕获资源关闭失败",
                    error=error,
                    binding=capture.binding,
                )
