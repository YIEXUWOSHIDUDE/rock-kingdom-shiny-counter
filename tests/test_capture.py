from __future__ import annotations

import unittest

from shiny_counter.capture import WindowBinding, WindowInfo, resolve_window


class WindowBindingTests(unittest.TestCase):
    def test_selected_hwnd_survives_title_change(self) -> None:
        binding = WindowBinding(
            hwnd=100,
            pid=42,
            class_name="NRCGameWindow",
            process_path=r"C:\Games\NRC-Win64-Shipping.exe",
            title="洛克王国：世界",
            width=1920,
            height=1080,
        )
        renamed = WindowInfo(
            hwnd=100,
            pid=42,
            class_name="NRCGameWindow",
            process_path=r"C:\Games\NRC-Win64-Shipping.exe",
            title="NRC-Win64-Shipping",
            width=1920,
            height=1080,
        )

        resolved = resolve_window(binding, [renamed])

        self.assertEqual(100, resolved.hwnd)
        self.assertEqual("NRC-Win64-Shipping", resolved.title)

    def test_invalid_hwnd_recovers_by_process_and_window_class(self) -> None:
        binding = WindowBinding(
            hwnd=100,
            pid=42,
            class_name="NRCGameWindow",
            process_path=r"C:\Games\NRC-Win64-Shipping.exe",
            title="洛克王国：世界",
            width=1920,
            height=1080,
        )
        restarted = WindowInfo(
            hwnd=900,
            pid=77,
            class_name="NRCGameWindow",
            process_path=r"C:\Games\NRC-Win64-Shipping.exe",
            title="新标题",
            width=1920,
            height=1080,
        )
        unrelated = WindowInfo(
            hwnd=901,
            pid=88,
            class_name="OtherWindow",
            process_path=r"C:\Other\launcher.exe",
            title="洛克王国：世界启动器",
            width=1280,
            height=720,
        )

        resolved = resolve_window(binding, [unrelated, restarted])

        self.assertEqual(900, resolved.hwnd)

    def test_reused_hwnd_is_rejected_when_process_identity_changed(self) -> None:
        binding = WindowBinding(
            hwnd=222,
            pid=42,
            class_name="NRCGameWindow",
            process_path=r"C:\Games\NRC-Win64-Shipping.exe",
            title="洛克王国：世界",
            width=1920,
            height=1080,
        )
        recycled = WindowInfo(
            hwnd=222,
            pid=900,
            class_name="Chrome_WidgetWin_1",
            process_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            title="洛克王国攻略",
            width=1920,
            height=1080,
        )
        restarted_game = WindowInfo(
            hwnd=444,
            pid=88,
            class_name="NRCGameWindow",
            process_path=r"C:\Games\NRC-Win64-Shipping.exe",
            title="NRC-Win64-Shipping",
            width=1920,
            height=1080,
        )

        resolved = resolve_window(binding, [recycled, restarted_game])

        self.assertEqual(restarted_game.hwnd, resolved.hwnd)


if __name__ == "__main__":
    unittest.main()
