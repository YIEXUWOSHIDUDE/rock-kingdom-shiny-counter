from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Any, Iterable


class CaptureError(RuntimeError):
    pass


class WindowNotFound(CaptureError):
    pass


class WindowUnavailable(CaptureError):
    pass


class WindowSizeChanged(CaptureError):
    pass


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    title: str
    width: int
    height: int


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def list_visible_windows() -> list[WindowInfo]:
    if sys.platform != "win32":
        return []
    import win32gui

    windows: list[WindowInfo] = []

    def collect(hwnd: int, _: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width, height = right - left, bottom - top
        if width >= 160 and height >= 120:
            windows.append(WindowInfo(hwnd=hwnd, title=title, width=width, height=height))

    win32gui.EnumWindows(collect, None)
    return sorted(windows, key=lambda item: item.title.casefold())


def find_window(title: str, windows: Iterable[WindowInfo] | None = None) -> WindowInfo:
    candidates = list(windows) if windows is not None else list_visible_windows()
    exact = next((window for window in candidates if window.title == title), None)
    if exact is not None:
        return exact
    folded = title.casefold()
    partial = [window for window in candidates if folded and folded in window.title.casefold()]
    if len(partial) == 1:
        return partial[0]
    raise WindowNotFound(f"找不到游戏窗口：{title or '未选择'}")


class Win32Capture:
    def __init__(self, window_title: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("window capture is available only on Windows")
        import mss

        self.window_title = window_title
        self._mss = mss.mss()

    def close(self) -> None:
        self._mss.close()

    def _geometry(self, expected_size: tuple[int, int] | None = None) -> tuple[int, int, int, int, int]:
        import win32gui

        window = find_window(self.window_title)
        if win32gui.IsIconic(window.hwnd):
            raise WindowUnavailable("游戏窗口已最小化")
        left, top, right, bottom = win32gui.GetClientRect(window.hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            raise WindowUnavailable("游戏窗口当前不可捕获")
        if expected_size is not None and (width, height) != expected_size:
            raise WindowSizeChanged(
                f"游戏窗口尺寸已从 {expected_size[0]}×{expected_size[1]} "
                f"变为 {width}×{height}，请恢复原尺寸或重新选择窗口"
            )
        screen_left, screen_top = win32gui.ClientToScreen(window.hwnd, (0, 0))
        return window.hwnd, screen_left, screen_top, width, height

    def capture_client(
        self, expected_size: tuple[int, int] | None = None
    ) -> tuple[Any, tuple[int, int]]:
        import numpy as np

        _, left, top, width, height = self._geometry(expected_size)
        shot = self._mss.grab({"left": left, "top": top, "width": width, "height": height})
        return np.asarray(shot)[:, :, :3].copy(), (width, height)
