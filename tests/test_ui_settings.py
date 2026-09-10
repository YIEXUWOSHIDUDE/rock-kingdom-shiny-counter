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
from shiny_counter.recognition_profile import CURRENT_RECOGNITION_PROFILE
from shiny_counter.ui import OverlayWindow, SettingsDialog, compact_recognition_status


class SettingsBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_show_s4_profile_and_current_default_keyword(self):
        dialog = SettingsDialog(AppData())
        try:
            self.assertEqual(dialog.ocr_keywords.text(), CURRENT_RECOGNITION_PROFILE.keywords[0])
            self.assertIn(CURRENT_RECOGNITION_PROFILE.keywords[0], dialog.ocr_keywords.placeholderText())
            self.assertIn(CURRENT_RECOGNITION_PROFILE.name, [label.text() for label in dialog.findChildren(QLabel)])
        finally:
            dialog.close()

    def test_matching_a_still_visible_banner_does_not_claim_another_count(self):
        self.assertNotIn("+1", compact_recognition_status("[OCR_MATCH] 匹配横幅"))
        self.assertIn("+1", compact_recognition_status("[COUNTED] 计数已触发"))

    def test_recognition_status_hides_diagnostics_but_keeps_useful_outcome(self) -> None:
        self.assertEqual(
            "已找到并截图游戏窗口，正在启动 GPU OCR…",
            compact_recognition_status("[CAPTURE_READY] 游戏窗口首帧捕获成功"),
        )
        self.assertEqual(
            "识别正常，等待结算横幅",
            compact_recognition_status(
                "[OCR_NO_TEXT] OCR CUDA · RTX 4070 · 84 ms · 缓冲 5 ms：未识别到文字"
            ),
        )
        self.assertEqual(
            "已读到文字但未匹配：获得经验值",
            compact_recognition_status(
                "[OCR_TEXT_NO_MATCH] OCR CUDA · RTX 4070 · 91 ms：获得经验值"
            ),
        )
        self.assertEqual(
            "识别未启动：RTX 4070 驱动 566.36 过旧，请升级。",
            compact_recognition_status(
                "[CUDA_DRIVER_TOO_OLD] 识别未启动：RTX 4070 驱动 566.36 过旧，请升级。"
            ),
        )

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

    def test_timed_out_gpu_worker_is_not_force_terminated_or_discarded(self) -> None:
        class SlowGpuWorker:
            def __init__(self) -> None:
                self.interruption_requested = False

            def requestInterruption(self) -> None:
                self.interruption_requested = True

            def wait(self, timeout_ms: int) -> bool:
                return False

        with tempfile.TemporaryDirectory() as directory:
            window = OverlayWindow(
                DataStore(Path(directory)),
                system_tray_available=False,
            )
            slow_worker = SlowGpuWorker()
            window.recognition_worker = slow_worker
            try:
                stopped = window._stop_recognition(timeout_ms=1)

                self.assertFalse(stopped)
                self.assertTrue(slow_worker.interruption_requested)
                self.assertIs(window.recognition_worker, slow_worker)
                self.assertIn("仍在结束", window.status_label.text())
            finally:
                window.recognition_worker = None
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
