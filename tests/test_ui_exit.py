import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OverlayExitTests(unittest.TestCase):
    def run_exit_probe(self, action: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "tests.test_ui_exit", "--probe", action, directory],
                cwd=ROOT,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

    def test_close_button_exits_the_event_loop_and_saves_data(self):
        result = self.run_exit_probe("button")
        self.assertEqual(result["exit_code"], 0, result)
        self.assertFalse(result["visible"], result)
        self.assertTrue(result["counter_preserved"], result)
        self.assertTrue(result["position_saved"], result)

    def test_tray_exit_stops_workers_and_saves_data(self):
        result = self.run_exit_probe("tray")
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue(result["recognition_stopped"], result)
        self.assertTrue(result["hotkeys_stopped"], result)
        self.assertTrue(result["counter_preserved"], result)
        self.assertTrue(result["position_saved"], result)

    def test_busy_ocr_keeps_window_open_until_safe_to_exit(self):
        for action in ("button-busy", "tray-busy"):
            with self.subTest(action=action):
                result = self.run_exit_probe(action)
                self.assertTrue(result["busy_close_rejected"], result)
                self.assertEqual(result["exit_code"], 0, result)
                self.assertTrue(result["recognition_stopped"], result)
                self.assertTrue(result["hotkeys_stopped"], result)


def probe(action: str, directory: str) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
    from shiny_counter.storage import DataStore
    from shiny_counter.ui import OverlayWindow

    app = QApplication([])
    store = DataStore(Path(directory))
    data = store.load()
    data.counter.increment(source="manual")
    store.save(data)
    before = data.to_dict()["counter"]
    window = OverlayWindow(store, system_tray_available=False)
    window.move(31, 47)
    button = next(b for b in window.findChildren(QPushButton) if b.text() == "×")

    class Worker:
        def __init__(self, busy=False):
            self.busy = busy
            self.interrupted = False
            self.stopped = False

        def requestInterruption(self):
            self.interrupted = True

        def wait(self, timeout_ms):
            self.stopped = not self.busy
            return self.stopped

    busy = action.endswith("-busy")
    recognition = Worker(busy)
    hotkeys = Worker()
    if action != "button":
        window.recognition_worker = recognition
        window.hotkey_worker = hotkeys
    trigger = button.click
    if action.startswith("tray"):
        trigger = next(a for a in window.tray_menu.actions() if a.text() == "退出").trigger
    result = {"busy_close_rejected": False}

    def request_close():
        trigger()
        if busy:
            result["busy_close_rejected"] = (
                window.isVisible()
                and window.recognition_worker is recognition
                and recognition.interrupted
                and not hotkeys.interrupted
            )
            QTimer.singleShot(20, retry_close)

    def retry_close():
        recognition.busy = False
        trigger()

    window.show()
    QTimer.singleShot(20, request_close)
    QTimer.singleShot(1000, lambda: app.exit(99))
    exit_code = app.exec()
    after = store.load()
    print(json.dumps({**result,
        "exit_code": exit_code,
        "visible": window.isVisible(),
        "counter_preserved": after.to_dict()["counter"] == before,
        "position_saved": after.settings.overlay_position == (31, 47),
        "recognition_stopped": recognition.interrupted and recognition.stopped,
        "hotkeys_stopped": hotkeys.interrupted and hotkeys.stopped,
    }))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--probe":
        probe(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
