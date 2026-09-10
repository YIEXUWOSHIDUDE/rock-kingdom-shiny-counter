from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PresenceGate:
    """Emit once when an OCR phrase appears, then wait for it to disappear."""

    enter_frames: int = 2
    exit_frames: int = 2
    _armed: bool = field(default=True, init=False)
    _enter_streak: int = field(default=0, init=False)
    _exit_streak: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.enter_frames < 1 or self.exit_frames < 1:
            raise ValueError("frame counts must be positive")

    def reset(self) -> None:
        self._armed = True
        self._enter_streak = 0
        self._exit_streak = 0

    def interrupt(self) -> None:
        """Forget partial evidence across a capture gap, preserving counted state."""
        self._enter_streak = 0
        self._exit_streak = 0

    def observe(self, present: bool) -> bool:
        if self._armed:
            self._enter_streak = self._enter_streak + 1 if present else 0
            if self._enter_streak >= self.enter_frames:
                self._armed = False
                self._enter_streak = 0
                self._exit_streak = 0
                return True
            return False

        self._exit_streak = self._exit_streak + 1 if not present else 0
        if self._exit_streak >= self.exit_frames:
            self._armed = True
            self._exit_streak = 0
        return False
