from __future__ import annotations

import tempfile
import queue
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import Qt

from shiny_counter.capture import CaptureError, WindowBinding
from shiny_counter.gpu_policy import GPUCompatibilityError
from shiny_counter.ocr import OCRText
from shiny_counter.storage import AppSettings
from shiny_counter.worker import RecognitionWorker, ocr_result_status_code


class RecognitionWorkerTests(unittest.TestCase):
    def test_capture_gap_discards_inflight_text_and_requires_real_blanks_to_rearm(self) -> None:
        commands: queue.Queue[int | Exception | None] = queue.Queue()
        inflight_started = threading.Event()
        release_inflight = threading.Event()
        capture_failed = threading.Event()
        capture_closed = threading.Event()
        matched_statuses = {
            label: threading.Event()
            for label in ("initial", "recovered", "continuing", "next")
        }
        blank_statuses = [threading.Event() for _ in range(3)]
        labels = {
            10: ("initial", 0.91),
            20: ("stale-inflight", 0.88),
            30: ("recovered", 0.92),
            50: ("continuing", 0.93),
            80: ("next", 0.99),
        }
        counts: list[float] = []
        texts: list[str] = []
        statuses: list[str] = []
        errors: list[str] = []

        class FakeCapture:
            def __init__(self, binding):
                self.binding = binding

            def capture_client(self, expected_size):
                command = commands.get(timeout=5)
                if isinstance(command, Exception):
                    raise command
                frame = np.full((100, 300, 3), command or 0, dtype=np.uint8)
                return frame, expected_size

            def close(self):
                capture_closed.set()

        class ControlledGpuEngine:
            device_label = "CUDA test double"

            def __init__(self, model_directory):
                pass

            def read(self, frame):
                marker = int(np.asarray(frame)[0, 0, 0])
                if marker == 20:
                    inflight_started.set()
                    if not release_inflight.wait(5):
                        raise AssertionError("test did not release the in-flight OCR call")
                if marker not in labels:
                    return []
                label, confidence = labels[marker]
                return [OCRText(f"{settings.ocr_keywords[0]} {label}", confidence)]

        def record_status(message: str, score: float) -> None:
            statuses.append(message)
            if message.startswith("[CAPTURE_UNAVAILABLE]"):
                capture_failed.set()
            elif message.startswith("[OCR_NO_TEXT]"):
                number = sum(item.startswith("[OCR_NO_TEXT]") for item in statuses)
                if number <= len(blank_statuses):
                    blank_statuses[number - 1].set()
            elif message.startswith(("[COUNTED]", "[OCR_MATCH]")):
                for label, observed in matched_statuses.items():
                    if texts and texts[-1].endswith(" " + label):
                        observed.set()

        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            settings.set_window_binding(WindowBinding(hwnd=42, title="test", width=300, height=100))
            worker = RecognitionWorker(settings, Path(directory))
            worker.detected.connect(counts.append, Qt.ConnectionType.DirectConnection)
            worker.ocr_text_changed.connect(texts.append, Qt.ConnectionType.DirectConnection)
            worker.status_changed.connect(record_status, Qt.ConnectionType.DirectConnection)
            worker.stopped_with_error.connect(errors.append, Qt.ConnectionType.DirectConnection)
            commands.put(10)
            with (
                patch("shiny_counter.worker.Win32Capture", FakeCapture),
                patch("shiny_counter.worker.EasyOCREngine", ControlledGpuEngine),
            ):
                worker.start()
                try:
                    self.assertTrue(matched_statuses["initial"].wait(5), errors or statuses)
                    self.assertEqual(counts, [0.91])
                    commands.put(20)
                    self.assertTrue(inflight_started.wait(5), errors or statuses)
                    commands.put(CaptureError("test capture gap during GPU OCR"))
                    self.assertTrue(capture_failed.wait(5), errors or statuses)
                    release_inflight.set()

                    commands.put(30)
                    self.assertTrue(matched_statuses["recovered"].wait(5), errors or statuses)
                    self.assertEqual(counts, [0.91])
                    self.assertFalse(any("stale-inflight" in text for text in texts))

                    commands.put(40)
                    self.assertTrue(blank_statuses[0].wait(5), errors or statuses)
                    commands.put(50)
                    self.assertTrue(matched_statuses["continuing"].wait(5), errors or statuses)
                    self.assertEqual(counts, [0.91], "one blank must not rearm the gate")

                    commands.put(60)
                    self.assertTrue(blank_statuses[1].wait(5), errors or statuses)
                    commands.put(70)
                    self.assertTrue(blank_statuses[2].wait(5), errors or statuses)
                    commands.put(80)
                    self.assertTrue(matched_statuses["next"].wait(5), errors or statuses)
                    self.assertEqual(counts, [0.91, 0.99])
                finally:
                    worker.requestInterruption()
                    release_inflight.set()
                    commands.put(None)
                    self.assertTrue(worker.wait(5000), "worker did not stop")

        self.assertEqual(errors, [])
        self.assertTrue(capture_closed.is_set())
        self.assertEqual(sum(item.startswith("[COUNTED]") for item in statuses), 2)
        self.assertEqual(sum(item.startswith("[CAPTURE_UNAVAILABLE]") for item in statuses), 1)

    def test_sustained_banner_counts_once_and_later_matches_do_not_claim_an_increment(self) -> None:
        repeated_matches_seen = threading.Event()
        capture_closed = threading.Event()
        counts: list[float] = []
        statuses: list[str] = []
        errors: list[str] = []

        class FakeCapture:
            def __init__(self, binding):
                self.binding = binding

            def capture_client(self, expected_size):
                return np.full((100, 300, 3), 180, dtype=np.uint8), expected_size

            def close(self):
                capture_closed.set()

        class MatchingGpuEngine:
            device_label = "CUDA test double"

            def __init__(self, model_directory):
                pass

            def read(self, frame):
                return [OCRText(settings.ocr_keywords[0], 0.99)]

        def record_status(message: str, score: float) -> None:
            statuses.append(message)
            if sum(item.startswith("[OCR_MATCH]") for item in statuses) >= 2:
                repeated_matches_seen.set()

        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            settings.set_window_binding(WindowBinding(hwnd=42, title="test", width=300, height=100))
            worker = RecognitionWorker(settings, Path(directory))
            worker.detected.connect(counts.append, Qt.ConnectionType.DirectConnection)
            worker.status_changed.connect(record_status, Qt.ConnectionType.DirectConnection)
            worker.stopped_with_error.connect(errors.append, Qt.ConnectionType.DirectConnection)
            with (
                patch("shiny_counter.worker.Win32Capture", FakeCapture),
                patch("shiny_counter.worker.EasyOCREngine", MatchingGpuEngine),
            ):
                worker.start()
                try:
                    self.assertTrue(repeated_matches_seen.wait(5), errors or statuses)
                finally:
                    worker.requestInterruption()
                    self.assertTrue(worker.wait(5000), "worker did not stop")

        self.assertEqual(errors, [])
        self.assertTrue(capture_closed.is_set())
        self.assertEqual(counts, [0.99])
        self.assertEqual(sum(item.startswith("[COUNTED]") for item in statuses), 1)
        later_matches = [item for item in statuses if item.startswith("[OCR_MATCH]")]
        self.assertGreaterEqual(len(later_matches), 2)
        for message in later_matches:
            self.assertNotRegex(message, r"\+\s*1")

    def test_pausing_during_gpu_read_discards_the_inflight_count(self) -> None:
        class FakeCapture:
            def __init__(self, binding):
                self.binding = binding

            def capture_client(self, expected_size):
                return np.full((100, 300, 3), 180, dtype=np.uint8), expected_size

            def close(self):
                pass

        class PausingEngine:
            device_label = "CUDA test double"

            def __init__(self, model_directory):
                self.calls = 0

            def read(self, frame):
                self.calls += 1
                if self.calls == 1:
                    worker.set_paused(True)
                    worker.set_paused(False)
                    return [OCRText(settings.ocr_keywords[0], 0.99)]
                worker.requestInterruption()
                return []

        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            settings.set_window_binding(WindowBinding(hwnd=42, title="test", width=300, height=100))
            worker = RecognitionWorker(settings, Path(directory))
            counts = []
            worker.detected.connect(counts.append, Qt.ConnectionType.DirectConnection)
            with (
                patch("shiny_counter.worker.Win32Capture", FakeCapture),
                patch("shiny_counter.worker.EasyOCREngine", PausingEngine),
            ):
                worker.start()
                finished = worker.wait(5000)
            self.assertTrue(finished)
            self.assertEqual(counts, [])

    def test_gpu_compatibility_error_is_short_and_actionable_in_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            binding = WindowBinding(
                hwnd=100,
                pid=42,
                class_name="NRCGameWindow",
                process_path=r"C:\Games\NRC-Win64-Shipping.exe",
                title="洛克王国：世界",
                width=2560,
                height=1600,
            )
            worker = RecognitionWorker(settings, Path(directory))
            messages: list[str] = []
            worker.stopped_with_error.connect(messages.append)

            worker._report_error(
                code="CUDA_DRIVER_TOO_OLD",
                stage="ocr_initialization",
                message="GPU OCR 兼容性检查失败",
                error=GPUCompatibilityError(
                    "CUDA_DRIVER_TOO_OLD",
                    "识别未启动：RTX 4070 驱动 566.36 过旧，请升级到 570.65 或更高。",
                ),
                binding=binding,
            )

            self.assertEqual(
                [
                    "[CUDA_DRIVER_TOO_OLD] 识别未启动：RTX 4070 驱动 "
                    "566.36 过旧，请升级到 570.65 或更高。"
                ],
                messages,
            )

    def test_ocr_result_status_codes_distinguish_pipeline_outcomes(self) -> None:
        self.assertEqual("OCR_NO_TEXT", ocr_result_status_code("", False))
        self.assertEqual(
            "OCR_TEXT_NO_MATCH",
            ocr_result_status_code("其他文字", False),
        )
        self.assertEqual(
            "OCR_MATCH",
            ocr_result_status_code("写进了童话里", True),
        )

    def test_unexpected_capture_initialization_error_is_reported_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            settings.set_window_binding(
                WindowBinding(
                    hwnd=100,
                    pid=42,
                    class_name="NRCGameWindow",
                    process_path=r"C:\Games\NRC-Win64-Shipping.exe",
                    title="洛克王国：世界",
                    width=1920,
                    height=1080,
                )
            )
            worker = RecognitionWorker(settings, Path(directory))
            messages: list[str] = []
            worker.stopped_with_error.connect(messages.append)

            with patch(
                "shiny_counter.worker.Win32Capture",
                side_effect=ModuleNotFoundError("mss"),
            ):
                worker.run()

            self.assertEqual(1, len(messages))
            self.assertIn("CAPTURE_INIT_FAILED", messages[0])
            log = Path(directory) / "logs" / "diagnostics.jsonl"
            self.assertTrue(log.is_file())
            self.assertIn("ModuleNotFoundError", log.read_text(encoding="utf-8"))

    def test_continuous_capture_error_has_a_stable_code_and_deduplicated_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings()
            binding = WindowBinding(
                hwnd=100,
                pid=42,
                class_name="NRCGameWindow",
                process_path=r"C:\Games\NRC-Win64-Shipping.exe",
                title="洛克王国：世界",
                width=1920,
                height=1080,
            )
            settings.set_window_binding(binding)
            worker = RecognitionWorker(settings, Path(directory))
            messages: list[str] = []
            worker.status_changed.connect(
                lambda message, score: messages.append(message)
            )

            worker._report_capture_unavailable(
                RuntimeError("窗口已最小化"),
                binding,
            )
            worker._report_capture_unavailable(
                RuntimeError("窗口已最小化"),
                binding,
            )

            self.assertEqual(1, len(messages))
            self.assertIn("CAPTURE_UNAVAILABLE", messages[0])
            log = Path(directory) / "logs" / "diagnostics.jsonl"
            self.assertEqual(
                1,
                len(log.read_text(encoding="utf-8").splitlines()),
            )

    def test_capture_keeps_buffering_while_gpu_ocr_is_busy(self) -> None:
        class FakeCapture:
            instance = None

            def __init__(self, binding) -> None:
                self.binding = binding
                self.calls = 0
                self.closed = False
                self.created_on = threading.get_ident()
                self.capture_threads = []
                FakeCapture.instance = self

            def capture_client(self, expected_size):
                self.capture_threads.append(threading.get_ident())
                self.calls += 1
                frame = np.zeros((100, 300, 3), dtype=np.uint8)
                if 2 <= self.calls <= 8:
                    frame[10:27, 84:216] = (120, 170, 240)
                return frame, expected_size

            def close(self) -> None:
                self.closed = True

        engine_created = threading.Event()
        notification_read = threading.Event()
        worker_holder = {}

        class SlowGpuEngine:
            device_label = "CUDA · test"

            def __init__(self, model_directory) -> None:
                self.calls = 0
                engine_created.set()

            def read(self, frame):
                self.calls += 1
                if self.calls == 1:
                    time.sleep(0.12)
                elif float(np.asarray(frame).mean()) > 0:
                    notification_read.set()
                    worker_holder["worker"].requestInterruption()
                return []

        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings(ocr_interval_ms=200)
            settings.set_window_binding(
                WindowBinding(
                    hwnd=100,
                    pid=42,
                    class_name="NRCGameWindow",
                    process_path=r"C:\Games\NRC-Win64-Shipping.exe",
                    title="洛克王国：世界",
                    width=300,
                    height=100,
                )
            )
            worker = RecognitionWorker(settings, Path(directory))
            worker_holder["worker"] = worker
            statuses: list[str] = []
            worker.status_changed.connect(
                lambda message, score: statuses.append(message),
                Qt.ConnectionType.DirectConnection,
            )

            with (
                patch("shiny_counter.worker.Win32Capture", FakeCapture),
                patch("shiny_counter.worker.EasyOCREngine", SlowGpuEngine),
                patch("shiny_counter.worker.CAPTURE_INTERVAL_SECONDS", 0.01),
            ):
                worker.start()
                finished = worker.wait(5000)

            self.assertTrue(finished)
            self.assertTrue(engine_created.is_set())
            self.assertTrue(notification_read.is_set())
            self.assertGreaterEqual(FakeCapture.instance.calls, 5)
            self.assertTrue(FakeCapture.instance.closed)
            self.assertEqual(
                set(FakeCapture.instance.capture_threads),
                {FakeCapture.instance.created_on},
            )
            self.assertTrue(
                any("[CAPTURE_READY]" in message for message in statuses),
                statuses,
            )
            self.assertTrue(
                any("[OCR_READY]" in message for message in statuses),
                statuses,
            )
            self.assertTrue(
                any("[OCR_NO_TEXT]" in message for message in statuses),
                statuses,
            )


if __name__ == "__main__":
    unittest.main()
