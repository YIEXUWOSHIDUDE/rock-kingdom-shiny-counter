from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys

from PySide6.QtCore import QThread, Signal


MODIFIERS = {"CTRL": 0x0002, "ALT": 0x0001, "SHIFT": 0x0004, "WIN": 0x0008}
KEYS = {
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "SPACE": 0x20,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in text.split("+") if part.strip()]
    if not parts:
        raise ValueError("快捷键不能为空")
    modifiers = 0
    key: int | None = None
    for part in parts:
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        elif part in KEYS:
            if key is not None:
                raise ValueError(f"快捷键包含多个主键：{text}")
            key = KEYS[part]
        elif len(part) == 1 and part.isalnum():
            if key is not None:
                raise ValueError(f"快捷键包含多个主键：{text}")
            key = ord(part)
        else:
            raise ValueError(f"不支持的快捷键：{part}")
    if key is None:
        raise ValueError(f"快捷键缺少主键：{text}")
    return modifiers, key


class GlobalHotkeyThread(QThread):
    activated = Signal(str)
    registration_error = Signal(str)

    def __init__(self, bindings: dict[str, str]) -> None:
        super().__init__()
        self.bindings = dict(bindings)

    def run(self) -> None:
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        registered: dict[int, str] = {}
        for identifier, (action, text) in enumerate(self.bindings.items(), start=1):
            try:
                modifiers, key = parse_hotkey(text)
            except ValueError as error:
                self.registration_error.emit(str(error))
                continue
            if not user32.RegisterHotKey(None, identifier, modifiers | 0x4000, key):
                self.registration_error.emit(f"快捷键被占用：{text}（{action}）")
                continue
            registered[identifier] = action

        message = ctypes.wintypes.MSG()
        try:
            while not self.isInterruptionRequested():
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0x0001):
                    if message.message == 0x0312 and message.wParam in registered:
                        self.activated.emit(registered[int(message.wParam)])
                self.msleep(40)
        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)
