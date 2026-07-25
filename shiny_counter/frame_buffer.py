from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class FrameSample:
    frame: Any
    captured_at: float
    activity: float


class NotificationFrameBuffer:
    """Keep short-lived changed frames available while GPU OCR is busy."""

    def __init__(
        self,
        *,
        candidate_capacity: int = 96,
        candidate_retention_seconds: float = 4.0,
        active_threshold: float = 2.5,
        comparison_size: tuple[int, int] = (160, 48),
    ) -> None:
        if candidate_capacity < 1:
            raise ValueError("candidate capacity must be positive")
        if candidate_retention_seconds < 0.75:
            raise ValueError("candidate retention must cover the 750 ms banner")
        if active_threshold < 0:
            raise ValueError("active threshold cannot be negative")
        self._candidates: deque[FrameSample] = deque()
        self._candidate_capacity = candidate_capacity
        self._candidate_retention_seconds = candidate_retention_seconds
        self._quiet: FrameSample | None = None
        self._reference: np.ndarray | None = None
        self._active_threshold = active_threshold
        self._comparison_size = comparison_size
        self._closed = False
        self._condition = threading.Condition()

    @property
    def pending_candidates(self) -> int:
        with self._condition:
            return len(self._candidates)

    def _comparison_frame(self, frame: Any) -> np.ndarray:
        pixels = np.asarray(frame)
        if pixels.ndim == 3:
            if pixels.shape[2] == 4:
                pixels = cv2.cvtColor(pixels, cv2.COLOR_BGRA2GRAY)
            else:
                pixels = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
        return cv2.resize(
            pixels,
            self._comparison_size,
            interpolation=cv2.INTER_AREA,
        )

    def offer(self, frame: Any, *, captured_at: float | None = None) -> None:
        captured_at = time.monotonic() if captured_at is None else captured_at
        comparison = self._comparison_frame(frame)
        with self._condition:
            if self._closed:
                return
            if self._reference is None:
                activity = 0.0
                self._reference = comparison
            else:
                activity = float(
                    cv2.absdiff(comparison, self._reference).mean()
                )
                if activity < self._active_threshold:
                    self._reference = comparison

            sample = FrameSample(
                frame=np.ascontiguousarray(frame),
                captured_at=captured_at,
                activity=activity,
            )
            if activity >= self._active_threshold:
                self._candidates.append(sample)
                cutoff = captured_at - self._candidate_retention_seconds
                while (
                    len(self._candidates) > 1
                    and self._candidates[0].captured_at < cutoff
                ):
                    self._candidates.popleft()
                while len(self._candidates) > self._candidate_capacity:
                    self._candidates.popleft()
            else:
                self._quiet = sample
            self._condition.notify()

    def take(self, *, timeout: float | None = None) -> FrameSample | None:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._closed and not self._candidates and self._quiet is None:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

            if self._candidates:
                sample = max(
                    self._candidates,
                    key=lambda item: (item.activity, item.captured_at),
                )
                self._candidates.clear()
                return sample
            sample = self._quiet
            self._quiet = None
            return sample

    def clear(self) -> None:
        with self._condition:
            self._candidates.clear()
            self._quiet = None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
