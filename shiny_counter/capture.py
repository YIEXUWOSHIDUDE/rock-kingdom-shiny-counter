from __future__ import annotations

import ctypes
import ctypes.wintypes
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
    pid: int = 0
    class_name: str = ""
    process_path: str = ""


@dataclass(frozen=True, slots=True)
class WindowBinding:
    hwnd: int
    title: str
    width: int
    height: int
    pid: int = 0
    class_name: str = ""
    process_path: str = ""

    @classmethod
    def from_window(cls, window: WindowInfo) -> "WindowBinding":
        return cls(
            hwnd=window.hwnd,
            title=window.title,
            width=window.width,
            height=window.height,
            pid=window.pid,
            class_name=window.class_name,
            process_path=window.process_path,
        )


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


def _process_path(pid: int) -> str:
    if sys.platform != "win32" or pid <= 0:
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        ctypes.wintypes.DWORD,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPWSTR,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
    process = kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return ""
    try:
        size = ctypes.wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(
            process,
            0,
            buffer,
            ctypes.byref(size),
        ):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(process)


def _read_window_info(hwnd: int) -> WindowInfo:
    import win32gui
    import win32process

    title = win32gui.GetWindowText(hwnd).strip()
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        class_name = win32gui.GetClassName(hwnd)
    except OSError:
        class_name = ""
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        width=right - left,
        height=bottom - top,
        pid=pid,
        class_name=class_name,
        process_path=_process_path(pid),
    )


def list_windows(*, include_minimized: bool = False) -> list[WindowInfo]:
    if sys.platform != "win32":
        return []
    import win32gui

    windows: list[WindowInfo] = []

    def collect(hwnd: int, _: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        if not include_minimized and win32gui.IsIconic(hwnd):
            return
        try:
            window = _read_window_info(hwnd)
        except (OSError, RuntimeError):
            return
        if not window.title:
            return
        if window.width >= 160 and window.height >= 120:
            windows.append(window)

    win32gui.EnumWindows(collect, None)
    return sorted(windows, key=lambda item: item.title.casefold())


def list_visible_windows() -> list[WindowInfo]:
    return list_windows(include_minimized=False)


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


def resolve_window(
    binding: WindowBinding,
    windows: Iterable[WindowInfo] | None = None,
) -> WindowInfo:
    candidates = list(windows) if windows is not None else list_visible_windows()
    selected = next(
        (
            window
            for window in candidates
            if binding.hwnd
            and window.hwnd == binding.hwnd
            and _matches_saved_identity(binding, window)
        ),
        None,
    )
    if selected is not None:
        return selected
    process_matches = [
        window
        for window in candidates
        if binding.process_path
        and binding.class_name
        and window.process_path.casefold() == binding.process_path.casefold()
        and window.class_name == binding.class_name
    ]
    if len(process_matches) == 1:
        return process_matches[0]
    pid_matches = [
        window
        for window in candidates
        if binding.pid
        and binding.class_name
        and window.pid == binding.pid
        and window.class_name == binding.class_name
    ]
    if len(pid_matches) == 1:
        return pid_matches[0]
    return find_window(binding.title, candidates)


def _matches_saved_identity(
    binding: WindowBinding,
    window: WindowInfo,
) -> bool:
    if binding.process_path:
        return (
            window.process_path.casefold() == binding.process_path.casefold()
            and (
                not binding.class_name
                or window.class_name == binding.class_name
            )
        )
    if binding.class_name:
        return (
            window.class_name == binding.class_name
            and (not binding.pid or window.pid == binding.pid)
        )
    if binding.pid:
        return window.pid == binding.pid
    return True


class Win32Capture:
    def __init__(self, target: WindowBinding | str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("window capture is available only on Windows")
        import mss

        if isinstance(target, WindowBinding):
            self.binding = target
        else:
            self.binding = WindowBinding(
                hwnd=0,
                title=target,
                width=0,
                height=0,
            )
        self._mss = mss.mss()

    def close(self) -> None:
        self._mss.close()

    def _geometry(self, expected_size: tuple[int, int] | None = None) -> tuple[int, int, int, int, int]:
        import win32gui

        window = None
        if self.binding.hwnd and win32gui.IsWindow(self.binding.hwnd):
            try:
                candidate = _read_window_info(self.binding.hwnd)
                if _matches_saved_identity(self.binding, candidate):
                    window = candidate
            except (OSError, RuntimeError):
                window = None
        if window is None:
            window = resolve_window(
                self.binding,
                list_windows(include_minimized=True),
            )
        self.binding = WindowBinding.from_window(window)
        if win32gui.IsIconic(window.hwnd):
            raise WindowUnavailable("游戏窗口已最小化")
        if not win32gui.IsWindowVisible(window.hwnd):
            raise WindowUnavailable("游戏窗口当前不可见")
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
        try:
            shot = self._mss.grab(
                {"left": left, "top": top, "width": width, "height": height}
            )
            return np.asarray(shot)[:, :, :3].copy(), (width, height)
        except Exception as error:
            raise CaptureError(
                f"窗口截图失败（{type(error).__name__}）：{error}"
            ) from error
