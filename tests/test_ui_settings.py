import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
)

from shiny_counter.storage import AppData, DataStore
from shiny_counter.ui import OverlayWindow, SettingsDialog


class SettingsBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_global_hotkeys_are_opt_in_and_only_recover_click_through(self) -> None:
        dialog = SettingsDialog(AppData())
        try:
            advanced_groups = [
                group
                for group in dialog.findChildren(QGroupBox)
                if group.title() == "高级设置"
            ]
            self.assertEqual(len(advanced_groups), 1)
            advanced = advanced_groups[0]
            checkboxes = {
                checkbox.text(): checkbox
                for checkbox in advanced.findChildren(QCheckBox)
            }
            self.assertFalse(checkboxes["启用全局快捷键"].isChecked())
            self.assertFalse(dialog.disable_click_through_hotkey.isEnabled())

            visible_text = {
                label.text()
                for label in advanced.findChildren(QLabel)
            }
            self.assertIn("关闭点击穿透", visible_text)
            self.assertNotIn("手动补一", visible_text)
            self.assertNotIn("撤销", visible_text)
            self.assertNotIn("暂停或继续", visible_text)
        finally:
            dialog.close()

    def test_click_through_requires_a_recovery_path_when_tray_is_unavailable(self) -> None:
        dialog = SettingsDialog(AppData(), system_tray_available=False)
        try:
            dialog.click_through.setChecked(True)
            dialog.hotkeys_enabled.setChecked(False)
            save_button = dialog.button_box.button(
                QDialogButtonBox.StandardButton.Save
            )

            save_button.click()

            self.assertNotEqual(
                dialog.result(),
                QDialog.DialogCode.Accepted,
            )
            self.assertIn("关闭穿透", dialog.advanced_status.text())
        finally:
            dialog.close()

    def test_system_tray_is_a_valid_click_through_recovery_path(self) -> None:
        data = AppData()
        dialog = SettingsDialog(data, system_tray_available=True)
        try:
            dialog.click_through.setChecked(True)
            dialog.hotkeys_enabled.setChecked(False)
            dialog.button_box.button(
                QDialogButtonBox.StandardButton.Save
            ).click()

            self.assertEqual(
                dialog.result(),
                QDialog.DialogCode.Accepted,
            )
            dialog.apply()
            self.assertTrue(data.settings.click_through)
            self.assertFalse(data.settings.hotkeys_enabled)
        finally:
            dialog.close()

    def test_tray_recovery_turns_click_through_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = OverlayWindow(
                DataStore(Path(directory)),
                system_tray_available=False,
            )
            try:
                window.set_click_through(True)

                window.tray_restore_action.trigger()

                self.assertFalse(window.data.settings.click_through)
                self.assertFalse(
                    bool(
                        window.windowFlags()
                        & window.windowFlags().WindowTransparentForInput
                    )
                )
            finally:
                window.close()

    def test_overlay_starts_without_registering_global_hotkeys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = OverlayWindow(
                DataStore(Path(directory)),
                system_tray_available=False,
            )
            try:
                self.assertIsNone(window.hotkey_worker)
            finally:
                window.close()

    def test_hotkey_registration_failure_only_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            data.settings.hotkeys_enabled = True
            store.save(data)
            window = OverlayWindow(
                store,
                system_tray_available=False,
            )
            try:
                self.assertIsNotNone(window.hotkey_worker)
                with patch("shiny_counter.ui.QMessageBox.warning") as warning:
                    window.hotkey_worker.registration_error.emit(
                        "快捷键被占用：Ctrl+Alt+T"
                    )
                    self.app.processEvents()

                self.assertEqual(
                    window.status_label.text(),
                    "快捷键被占用：Ctrl+Alt+T",
                )
                warning.assert_not_called()
            finally:
                window.close()

    def test_accepted_settings_enable_click_through_when_tray_can_restore_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = OverlayWindow(
                DataStore(Path(directory)),
                system_tray_available=True,
            )
            dialog = SettingsDialog(
                window.data,
                system_tray_available=True,
            )
            try:
                dialog.click_through.setChecked(True)
                dialog.hotkeys_enabled.setChecked(False)
                dialog.button_box.button(
                    QDialogButtonBox.StandardButton.Save
                ).click()

                window.apply_settings(dialog)

                self.assertTrue(window.data.settings.click_through)
                self.assertTrue(
                    bool(
                        window.windowFlags()
                        & window.windowFlags().WindowTransparentForInput
                    )
                )
            finally:
                dialog.close()
                window.close()

    def test_without_tray_click_through_waits_for_recovery_hotkey_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = OverlayWindow(
                DataStore(Path(directory)),
                system_tray_available=False,
            )
            dialog = SettingsDialog(
                window.data,
                system_tray_available=False,
            )
            try:
                dialog.click_through.setChecked(True)
                dialog.hotkeys_enabled.setChecked(True)
                dialog.disable_click_through_hotkey.setText("Ctrl+Alt+T")
                dialog.button_box.button(
                    QDialogButtonBox.StandardButton.Save
                ).click()

                window.apply_settings(dialog)
                self.assertFalse(window.data.settings.click_through)

                window.hotkey_registration_succeeded(
                    "disable_click_through"
                )
                self.assertTrue(window.data.settings.click_through)
            finally:
                dialog.close()
                window.close()

    def test_failed_recovery_hotkey_keeps_the_overlay_clickable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = OverlayWindow(
                DataStore(Path(directory)),
                system_tray_available=False,
            )
            dialog = SettingsDialog(
                window.data,
                system_tray_available=False,
            )
            try:
                dialog.click_through.setChecked(True)
                dialog.hotkeys_enabled.setChecked(True)
                dialog.disable_click_through_hotkey.setText("Ctrl+Alt+T")
                dialog.button_box.button(
                    QDialogButtonBox.StandardButton.Save
                ).click()
                window.apply_settings(dialog)

                window.hotkey_registration_failed(
                    "快捷键被占用：Ctrl+Alt+T"
                )

                self.assertFalse(window.data.settings.click_through)
                self.assertIn("未开启点击穿透", window.status_label.text())
            finally:
                dialog.close()
                window.close()


if __name__ == "__main__":
    unittest.main()
