from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import Qt

from shiny_counter.capture import WindowBinding
from shiny_counter.storage import AppSettings
from shiny_counter.worker import RecognitionWorker, ocr_result_status_code


class RecognitionWorkerTests(unittest.TestCase):
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
