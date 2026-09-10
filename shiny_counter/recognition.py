from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable, Iterable

from .detection import PresenceGate
from .frame_buffer import FrameSample, NotificationFrameBuffer
from .ocr import OCRKeywordMatcher, OCRMatch, OCRText, crop_notification_banner
from .storage import AppSettings


MAX_OCR_INFLIGHT_SECONDS = 4.0


@dataclass(frozen=True, slots=True)
class RecognitionDecision:
    text: str
    match: OCRMatch | None
    counted: bool
    accepted: bool = True


class BannerRecognitionStream:
    """Own the crop, chronological frame delivery, matching and count gate.

    The capture producer offers full client frames; the GPU consumer reads a
    returned crop and submits OCR text for that same sample. Pixel activity is
    only a buffering hint and never grants permission to count.
    """

    def __init__(self, settings: AppSettings, *, clock: Callable[[], float] | None = None):
        self.profile = settings.recognition_profile()
        self._clock = clock or time.monotonic
        self._frames = NotificationFrameBuffer(
            clock=self._clock,
            minimum_run_samples=max(self.profile.enter_frames, self.profile.exit_frames),
        )
        self._matcher = OCRKeywordMatcher(self.profile.keywords, self.profile.min_confidence)
        self._gate = PresenceGate(self.profile.enter_frames, self.profile.exit_frames)
        self._lock = threading.RLock()
        self._paused = False
        self._closed = False
        self._last_observed_at = float("-inf")
        self._issued: tuple[FrameSample, float] | None = None

    def offer(self, frame, *, captured_at: float | None = None) -> None:
        with self._lock:
            if not self._paused and not self._closed:
                self._frames.offer(crop_notification_banner(frame, self.profile), captured_at=captured_at)

    def take(self, *, timeout: float | None = None) -> FrameSample | None:
        # Never hold the stream lock while waiting for the capture producer.
        sample = self._frames.take(timeout=timeout)
        with self._lock:
            if (sample is None or self._paused or self._closed
                    or not self._frames.is_current(sample)):
                return None
            self._issued = (sample, self._clock())
            return sample

    def observe(self, sample: FrameSample, texts: Iterable[OCRText]) -> RecognitionDecision:
        with self._lock:
            issued = self._issued
            if issued is None or issued[0] is not sample:
                return RecognitionDecision("", None, False, accepted=False)
            self._issued = None
            # Queue TTL is checked at take. Re-checking capture age after GPU
            # inference would starve every result under sustained backlog.
            if (self._paused or self._closed
                    or not self._frames.is_current(sample, check_expiry=False)
                    or self._clock() - issued[1] > MAX_OCR_INFLIGHT_SECONDS
                    or sample.captured_at <= self._last_observed_at):
                self._gate.interrupt()
                return RecognitionDecision("", None, False, accepted=False)
            self._last_observed_at = sample.captured_at
            texts = list(texts)
            match = self._matcher.match(texts)
            return RecognitionDecision(
                text=" | ".join(item.text for item in texts),
                match=match,
                counted=self._gate.observe(match is not None),
            )

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            if self._paused != paused:
                self._paused = paused
                self.invalidate()

    def invalidate(self) -> None:
        """Drop pending/in-flight work without re-counting a continuing banner."""
        with self._lock:
            self._frames.clear()
            self._gate.interrupt()
            self._issued = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._issued = None
            self._frames.close()
