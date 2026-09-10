import unittest

import numpy as np

from shiny_counter.ocr import OCRText
from shiny_counter.recognition import BannerRecognitionStream
from shiny_counter.storage import AppSettings


class BannerRecognitionStreamTests(unittest.TestCase):
    def test_one_banner_stays_counted_across_pause_until_real_absence(self):
        now = [0.0]
        stream = BannerRecognitionStream(AppSettings(), clock=lambda: now[0])
        def observe(present):
            now[0] += 0.1
            frame = np.full((100, 300, 3), 180 if present else 0, dtype=np.uint8)
            stream.offer(frame)
            sample = stream.take(timeout=0)
            texts = [OCRText(stream.profile.keywords[0], 0.99)] if present else []
            return stream.observe(sample, texts).counted

        self.assertTrue(observe(True))
        self.assertFalse(observe(True))
        self.assertFalse(observe(False))  # Incomplete absence before pause.
        stream.set_paused(True)
        stream.set_paused(False)
        self.assertFalse(observe(False))  # Cannot combine evidence across pause.
        self.assertFalse(observe(True))
        self.assertFalse(observe(False))
        self.assertFalse(observe(False))
        self.assertTrue(observe(True))

    def test_inflight_timeout_and_duplicate_result_do_not_count(self):
        now = [0.0]
        stream = BannerRecognitionStream(AppSettings(), clock=lambda: now[0])
        frame = np.full((100, 300, 3), 180, dtype=np.uint8)
        texts = [OCRText(stream.profile.keywords[0], 0.99)]
        stream.offer(frame)
        sample = stream.take(timeout=0)
        now[0] = 4.1
        self.assertFalse(stream.observe(sample, texts).accepted)
        stream.offer(frame)
        sample = stream.take(timeout=0)
        self.assertTrue(stream.observe(sample, texts).counted)
        self.assertFalse(stream.observe(sample, texts).accepted)

    def test_capture_gap_and_close_reject_inflight_results(self):
        for action in ("invalidate", "close"):
            with self.subTest(action=action):
                stream = BannerRecognitionStream(AppSettings(), clock=lambda: 0.0)
                stream.offer(np.full((100, 300, 3), 180, dtype=np.uint8))
                sample = stream.take(timeout=0)
                getattr(stream, action)()
                result = stream.observe(sample, [OCRText(stream.profile.keywords[0], 0.99)])
                self.assertFalse(result.accepted)
                self.assertFalse(result.counted)

    def test_custom_confirmation_lengths_survive_backlog_compression(self):
        stream = BannerRecognitionStream(
            AppSettings(ocr_enter_frames=3, ocr_exit_frames=4), clock=lambda: 2.0
        )
        for index, present in enumerate([True] * 12 + [False] * 12 + [True] * 12):
            stream.offer(
                np.full((100, 300, 3), 180 if present else 0, dtype=np.uint8),
                captured_at=index * 0.05,
            )
        count = 0
        while (sample := stream.take(timeout=0)) is not None:
            texts = [OCRText(stream.profile.keywords[0], 0.99)] if sample.frame.mean() else []
            count += stream.observe(sample, texts).counted
        self.assertEqual(count, 2)

    def test_sustained_dynamic_backlog_does_not_expire_every_gpu_result(self):
        now = [0.0]
        stream = BannerRecognitionStream(AppSettings(), clock=lambda: now[0])
        captured = 0
        accepted = []
        for scan in range(60):
            started = scan * 0.2
            now[0] = started
            while captured * 0.05 <= started:
                frame = np.full((100, 300, 3), 180 * (captured % 2), dtype=np.uint8)
                stream.offer(frame, captured_at=captured * 0.05)
                captured += 1
            sample = stream.take(timeout=0)
            now[0] = started + 0.15  # GPU boundary stand-in, no CPU OCR.
            accepted.append(stream.observe(sample, []).accepted)
        self.assertTrue(all(accepted[-20:]), accepted)

    def test_inflight_result_cannot_count_after_pause_and_resume(self):
        stream = BannerRecognitionStream(AppSettings(), clock=lambda: 1.0)
        stream.offer(np.full((100, 300, 3), 180, dtype=np.uint8), captured_at=0.5)
        sample = stream.take(timeout=0)
        stream.set_paused(True)
        stream.set_paused(False)
        decision = stream.observe(sample, [OCRText(stream.profile.keywords[0], 0.99)])
        self.assertFalse(decision.accepted)
        self.assertFalse(decision.counted)

    def test_two_banners_buffered_before_ocr_count_separately(self):
        now = [1.2]
        stream = BannerRecognitionStream(AppSettings(), clock=lambda: now[0])
        quiet = np.zeros((100, 300, 3), dtype=np.uint8)
        banner = np.full_like(quiet, 180)
        for frame, timestamp in [
            (quiet, 0.0), (banner, 0.1), (quiet, 0.9),
            (quiet, 1.0), (banner, 1.1),
        ]:
            stream.offer(frame, captured_at=timestamp)
        count = 0
        timestamps = []
        while (sample := stream.take(timeout=0)) is not None:
            timestamps.append(sample.captured_at)
            # External OCR stand-in for this timing test, not an OCR accuracy claim.
            texts = [OCRText(stream.profile.keywords[0], 0.99)] if sample.frame.mean() else []
            count += stream.observe(sample, texts).counted
        self.assertEqual(count, 2)
        self.assertEqual(timestamps, sorted(timestamps))


if __name__ == "__main__":
    unittest.main()
