from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class FrameSample:
    """One real captured image; activity ranks pixels, not OCR confidence."""

    frame: Any
    captured_at: float
    activity: float
    generation: int = 0


@dataclass(slots=True)
class _VisualRun:
    anchor: np.ndarray
    baseline: np.ndarray
    samples: list[FrameSample]


class NotificationFrameBuffer:
    """Keep ordered, expiring snapshots while GPU OCR is busy.

    Only adjacent frames similar to a fixed run anchor may be compressed.
    A run retains real first/strongest/latest samples, including at least
    minimum_run_samples when that many remain available. This is visual
    compression, not a claim that their OCR text or event meaning is equal.
    Capacity and TTL always win: an uncompressible busy scene can lose events.
    """

    def __init__(
        self,
        *,
        candidate_capacity: int = 96,
        candidate_retention_seconds: float = 4.0,
        active_threshold: float = 2.5,
        comparison_size: tuple[int, int] = (160, 48),
        clock: Callable[[], float] = time.monotonic,
        minimum_run_samples: int = 2,
    ) -> None:
        if candidate_capacity < 1:
            raise ValueError("candidate capacity must be positive")
        if candidate_retention_seconds < 0.75:
            raise ValueError("candidate retention must be at least 750 ms")
        if active_threshold < 0:
            raise ValueError("active threshold cannot be negative")
        if minimum_run_samples < 1:
            raise ValueError("minimum run samples must be positive")
        self._runs: deque[_VisualRun] = deque()
        self._candidate_capacity = candidate_capacity
        self._candidate_retention_seconds = candidate_retention_seconds
        self._reference: np.ndarray | None = None
        self._active_threshold = active_threshold
        self._comparison_size = comparison_size
        self._clock = clock
        self._minimum_run_samples = minimum_run_samples
        self._closed = False
        self._generation = 0
        self._last_captured_at: float | None = None
        self._condition = threading.Condition()

    @property
    def pending_candidates(self) -> int:
        """Stored pending samples, including quiet frames; offer/take prune TTL."""
        with self._condition:
            return sum(len(run.samples) for run in self._runs)

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
        """Offer a snapshot with a strictly increasing time in the clock's domain.

        Equal or decreasing capture times are rejected until clear().
        Already expired arrivals and all arrivals after close() are ignored.
        """
        captured_at = self._clock() if captured_at is None else captured_at
        comparison = self._comparison_frame(frame)
        with self._condition:
            if self._closed:
                return
            if (
                self._last_captured_at is not None
                and captured_at <= self._last_captured_at
            ):
                raise ValueError("capture timestamps must be strictly increasing")
            now = self._clock()
            self._expire(now)
            if captured_at < now - self._candidate_retention_seconds:
                return
            run = self._runs[-1] if self._runs else None
            if (
                run is None
                or float(cv2.absdiff(comparison, run.anchor).mean()) > self._active_threshold
            ):
                baseline = self._reference if self._reference is not None else comparison
                run = _VisualRun(comparison, baseline, [])
                self._runs.append(run)
                self._reference = comparison
            sample = FrameSample(
                frame=np.array(frame, copy=True, order="C"),
                captured_at=captured_at,
                activity=float(cv2.absdiff(comparison, run.baseline).mean()),
                generation=self._generation,
            )
            run.samples.append(sample)
            self._last_captured_at = captured_at
            if len(run.samples) > max(3, self._minimum_run_samples + 1):
                representatives = (
                    *run.samples[: max(1, self._minimum_run_samples - 1)],
                    max(run.samples, key=lambda item: item.activity),
                    run.samples[-1],
                )
                run.samples[:] = sorted(
                    {id(item): item for item in representatives}.values(),
                    key=lambda item: item.captured_at,
                )
            while self.pending_candidates > self._candidate_capacity:
                self._runs[0].samples.pop(0)
                if not self._runs[0].samples:
                    self._runs.popleft()
            self._condition.notify()

    def _expire(self, now: float) -> None:
        cutoff = now - self._candidate_retention_seconds
        while self._runs:
            run = self._runs[0]
            run.samples[:] = [item for item in run.samples if item.captured_at >= cutoff]
            if run.samples:
                break
            self._runs.popleft()

    def take(self, *, timeout: float | None = None) -> FrameSample | None:
        """Consume the oldest unexpired sample; timeout uses real elapsed time."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            self._expire(self._clock())
            while not self._closed and not self._runs:
                if deadline is None:
                    self._condition.wait()
                    self._expire(self._clock())
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
                self._expire(self._clock())

            if self._runs:
                run = self._runs[0]
                sample = run.samples.pop(0)
                if not run.samples:
                    self._runs.popleft()
                return sample
            return None

    def clear(self) -> None:
        """Discard queued and in-flight work and reset comparison/time history."""
        with self._condition:
            self._runs.clear()
            self._reference = None
            self._last_captured_at = None
            self._generation += 1

    def is_current(self, sample: FrameSample, *, check_expiry: bool = True) -> bool:
        """Validate generation/closure and, by default, the capture-age TTL.

        An owner with a separate bounded in-flight deadline may disable the
        queue-age check after a legal take. It must enforce that deadline and
        accept the issued sample at most once; this buffer does not do either.
        """
        with self._condition:
            return (
                not self._closed
                and sample.generation == self._generation
                and (
                    not check_expiry
                    or sample.captured_at >= self._clock() - self._candidate_retention_seconds
                )
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self.clear()
            self._condition.notify_all()
