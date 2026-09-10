import unittest

import numpy as np

from shiny_counter.detection import PresenceGate
from shiny_counter.frame_buffer import NotificationFrameBuffer
from shiny_counter.ocr import OCRKeywordMatcher, OCRText


def drain(buffer):
    samples = []
    while (sample := buffer.take(timeout=0)) is not None:
        samples.append(sample)
    return samples


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class NotificationFrameOrderTests(unittest.TestCase):
    def test_similar_run_keeps_first_strongest_and_latest_in_time_order(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock)
        for index, value in enumerate((0, 51, 50, 52, 51)):
            clock.now = index * 0.1
            buffer.offer(np.full((20, 60, 3), value, dtype=np.uint8))

        samples = drain(buffer)
        self.assertEqual([0, 51, 52, 51], [int(item.frame[0, 0, 0]) for item in samples])
        self.assertEqual([0.0, 0.1, 0.3, 0.4], [round(item.captured_at, 1) for item in samples])

    def test_four_real_quiet_samples_survive_between_two_confirmation_runs(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock, minimum_run_samples=4)
        quiet = np.zeros((20, 60, 3), dtype=np.uint8)
        banner = np.full_like(quiet, 180)
        for index in range(90):
            clock.now = index * 0.01
            buffer.offer(quiet if 30 <= index < 60 else banner)

        gate = PresenceGate(enter_frames=4, exit_frames=4)
        matcher = OCRKeywordMatcher(["精灵藏进星星"])
        detections = 0
        for sample in drain(buffer):
            texts = [] if np.array_equal(sample.frame, quiet) else [
                OCRText("精灵藏进星星", 0.99)
            ]
            detections += int(gate.observe(matcher.match(texts) is not None))
        self.assertEqual(2, detections)

    def test_capture_times_must_increase_and_clear_starts_a_new_timeline(self):
        pixels = np.zeros((20, 60, 3), dtype=np.uint8)
        for invalid_time in (0.9, 1.0):
            with self.subTest(captured_at=invalid_time):
                clock = FakeClock(1.0)
                buffer = NotificationFrameBuffer(clock=clock)
                buffer.offer(pixels, captured_at=1.0)
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    buffer.offer(pixels, captured_at=invalid_time)
                buffer.clear()
                buffer.offer(pixels, captured_at=1.0)
                self.assertEqual([1.0], [item.captured_at for item in drain(buffer)])

    def test_compression_preserves_requested_real_confirmation_samples(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock, minimum_run_samples=4)
        pixels = np.full((20, 60, 3), 180, dtype=np.uint8)
        for index in range(30):
            clock.now = index * 0.05
            buffer.offer(pixels)

        samples = drain(buffer)
        matcher = OCRKeywordMatcher(["精灵藏进星星"])
        gate = PresenceGate(enter_frames=4, exit_frames=4)
        detections = 0
        for sample in samples:
            self.assertTrue(np.array_equal(sample.frame, pixels))
            match = matcher.match([OCRText("精灵藏进星星", 0.99)])
            detections += int(gate.observe(match is not None))
        self.assertEqual(1, detections)
        self.assertGreaterEqual(len(samples), 4)
        self.assertLessEqual(len(samples), 5)
        self.assertEqual(len(samples), len({sample.captured_at for sample in samples}))

    def test_issued_sample_can_skip_queue_expiry_but_not_generation_or_close(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock, candidate_retention_seconds=4)
        pixels = np.zeros((20, 60, 3), dtype=np.uint8)
        buffer.offer(pixels)
        sample = buffer.take(timeout=0)
        clock.now = 4.1

        self.assertFalse(buffer.is_current(sample))
        self.assertTrue(buffer.is_current(sample, check_expiry=False))
        buffer.clear()
        self.assertFalse(buffer.is_current(sample, check_expiry=False))
        buffer.offer(pixels)
        new_sample = buffer.take(timeout=0)
        buffer.close()
        self.assertFalse(buffer.is_current(new_sample, check_expiry=False))

    def test_offered_pixels_are_a_snapshot_not_the_callers_mutable_array(self):
        buffer = NotificationFrameBuffer(clock=FakeClock())
        pixels = np.full((20, 60, 3), 180, dtype=np.uint8)
        buffer.offer(pixels)
        pixels[:] = 0

        sample = buffer.take(timeout=0)
        self.assertTrue(np.all(sample.frame == 180))

    def test_in_flight_result_is_invalid_after_its_capture_expires(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock, candidate_retention_seconds=4)
        buffer.offer(np.zeros((20, 60, 3), dtype=np.uint8))
        sample = buffer.take(timeout=0)
        clock.now = 4.0
        self.assertTrue(buffer.is_current(sample))
        clock.now = 4.001
        self.assertFalse(buffer.is_current(sample))

    def test_close_invalidates_in_flight_and_pending_samples(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock)
        frame = np.zeros((20, 60, 3), dtype=np.uint8)
        buffer.offer(frame)
        sample = buffer.take(timeout=0)
        clock.now = 0.1
        buffer.offer(frame)

        buffer.close()
        buffer.offer(frame)

        self.assertFalse(buffer.is_current(sample))
        self.assertIsNone(buffer.take(timeout=0))
        self.assertEqual(0, buffer.pending_candidates)

    def test_clear_invalidates_in_flight_samples_and_starts_a_new_generation(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock)
        frame = np.zeros((20, 60, 3), dtype=np.uint8)
        buffer.offer(frame)
        previous = buffer.take(timeout=0)
        self.assertTrue(buffer.is_current(previous))

        buffer.clear()
        buffer.offer(np.full_like(frame, 180))
        current = buffer.take(timeout=0)

        self.assertFalse(buffer.is_current(previous))
        self.assertTrue(buffer.is_current(current))
        self.assertGreater(current.generation, previous.generation)
        self.assertEqual(0.0, current.activity)

    def test_take_expires_a_banner_even_when_no_more_frames_arrive(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock, candidate_retention_seconds=4)
        buffer.offer(np.zeros((20, 60, 3), dtype=np.uint8))
        clock.now = 4.001

        self.assertIsNone(buffer.take(timeout=0))
        self.assertEqual(0, buffer.pending_candidates)

    def test_new_quiet_frame_expires_an_old_banner_on_offer(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock, candidate_retention_seconds=4)
        quiet = np.zeros((20, 60, 3), dtype=np.uint8)
        buffer.offer(quiet)
        clock.now = 0.1
        buffer.offer(np.full_like(quiet, 180))
        clock.now = 20
        buffer.offer(quiet)

        self.assertEqual(1, buffer.pending_candidates)
        self.assertEqual([20], [sample.captured_at for sample in drain(buffer)])

    def test_two_pending_banners_keep_real_disappearance_frames_between_them(self):
        clock = FakeClock()
        buffer = NotificationFrameBuffer(clock=clock)
        quiet = np.zeros((50, 150, 3), dtype=np.uint8)
        banner_a = np.full_like(quiet, 100)
        banner_b = np.full_like(quiet, 180)
        started = 0.0
        for offset, frame in [
            (0.0, quiet), (0.1, banner_a), (0.9, quiet),
            (1.0, quiet), (1.1, banner_b),
        ]:
            clock.now = started + offset
            buffer.offer(frame, captured_at=started + offset)

        samples = drain(buffer)
        matcher = OCRKeywordMatcher(["精灵藏进星星"])
        gate = PresenceGate(enter_frames=1, exit_frames=2)
        detections = 0
        for sample in samples:
            # Scripted recognition at the external OCR seam, not an activity test.
            texts = [] if np.array_equal(sample.frame, quiet) else [
                OCRText("精灵藏进星星，划破天幕坠落！", 0.99)
            ]
            detections += int(gate.observe(matcher.match(texts) is not None))

        self.assertEqual(2, detections)
        self.assertEqual(
            [started + offset for offset in (0.0, 0.1, 0.9, 1.0, 1.1)],
            [sample.captured_at for sample in samples],
        )


if __name__ == "__main__":
    unittest.main()
