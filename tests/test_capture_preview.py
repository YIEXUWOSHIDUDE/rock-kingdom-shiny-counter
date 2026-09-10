import os
import unittest
from dataclasses import replace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from shiny_counter.capture import WindowBinding
from shiny_counter.recognition_profile import CURRENT_RECOGNITION_PROFILE
from shiny_counter.ui import CapturePreviewDialog


class CapturePreviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_uses_the_selected_profile_region(self) -> None:
        profile = replace(CURRENT_RECOGNITION_PROFILE, region=(0.1, 0.2, 0.5, 0.6))
        frame = np.zeros((500, 860, 3), dtype=np.uint8)
        binding = WindowBinding(hwnd=42, title="test", width=860, height=500)
        dialog = CapturePreviewDialog(frame, binding, profile=profile)
        try:
            pixels = dialog.findChild(QLabel, "capturePreview").pixmap().toImage()
            border = pixels.pixelColor(86, 150)
            self.assertEqual((border.red(), border.green(), border.blue()), (255, 0, 0))
            self.assertEqual(pixels.pixelColor(240, 50).red(), 0)
            self.assertIn(profile.name, dialog.hint_label.text())
        finally:
            dialog.close()

    def test_preview_draws_the_ocr_region_over_the_captured_client(self) -> None:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        binding = WindowBinding(
            hwnd=42,
            title="NRC-Win64-Shipping",
            width=640,
            height=360,
        )
        dialog = CapturePreviewDialog(frame, binding)
        try:
            preview = dialog.findChild(QLabel, "capturePreview")

            self.assertIsNotNone(preview)
            self.assertFalse(preview.pixmap().isNull())
            self.assertIn("红框", dialog.hint_label.text())
            self.assertIn("640×360", dialog.hint_label.text())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
