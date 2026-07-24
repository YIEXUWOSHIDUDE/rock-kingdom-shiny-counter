import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from shiny_counter.storage import AppData
from shiny_counter.ui import (
    APP_STYLE,
    HistoryDialog,
    OCRTextDialog,
    SettingsDialog,
    WindowPickerDialog,
)


class DialogContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_labels_stay_dark_when_opened_from_the_overlay(self) -> None:
        parent = QWidget()
        parent.setObjectName("overlay")
        parent.setStyleSheet(APP_STYLE)
        dialog = SettingsDialog(AppData(), parent)
        dialog.show()
        self.app.processEvents()
        try:
            target_label = next(
                label
                for label in dialog.findChildren(QLabel)
                if label.text() == "目标名称"
            )
            color = target_label.palette().color(QPalette.ColorRole.WindowText)
            self.assertEqual(color.name(), "#172033")
        finally:
            dialog.close()
            parent.close()

    def test_other_light_dialogs_also_use_dark_labels(self) -> None:
        parent = QWidget()
        parent.setObjectName("overlay")
        parent.setStyleSheet(APP_STYLE)
        dialogs = [
            WindowPickerDialog([], parent),
            HistoryDialog([], [], parent),
            OCRTextDialog("", parent),
        ]
        try:
            for dialog in dialogs:
                with self.subTest(dialog=dialog.windowTitle()):
                    dialog.show()
                    self.app.processEvents()
                    colors = {
                        label.palette().color(QPalette.ColorRole.WindowText).name()
                        for label in dialog.findChildren(QLabel)
                    }
                    self.assertEqual(colors, {"#172033"})
        finally:
            for dialog in dialogs:
                dialog.close()
            parent.close()


if __name__ == "__main__":
    unittest.main()
