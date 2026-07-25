from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shiny_counter.diagnostics import DiagnosticLog


class DiagnosticLogTests(unittest.TestCase):
    def test_runtime_error_is_recorded_with_stage_code_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = DiagnosticLog(Path(directory))

            path = diagnostics.record(
                stage="window_selection",
                code="CAPTURE_FAILED",
                message="首次截图失败",
                error=ModuleNotFoundError("mss"),
                context={"hwnd": 100, "title": "洛克王国：世界"},
            )

            entry = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual("window_selection", entry["stage"])
            self.assertEqual("CAPTURE_FAILED", entry["code"])
            self.assertEqual("ModuleNotFoundError", entry["error_type"])
            self.assertEqual(100, entry["context"]["hwnd"])
            self.assertIn("mss", entry["traceback"])


if __name__ == "__main__":
    unittest.main()
