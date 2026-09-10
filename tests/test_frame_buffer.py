import unittest

import numpy as np

from shiny_counter.detection import PresenceGate
from shiny_counter.frame_buffer import NotificationFrameBuffer
from shiny_counter.ocr import OCRKeywordMatcher, OCRText


class CaptureTimeline:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def offer(self, buffer, frame, captured_at):
        self.now = captured_at
        buffer.offer(frame, captured_at=captured_at)


def drain(buffer):
    samples = []
    while (sample := buffer.take(timeout=0)) is not None:
        samples.append(sample)
    return samples


class NotificationFrameBufferTests(unittest.TestCase):
    def test_short_notification_survives_until_slow_ocr_is_ready(self) -> None:
        timeline = CaptureTimeline()
        buffer = NotificationFrameBuffer(candidate_capacity=8, clock=timeline)
        quiet = np.zeros((80, 240, 3), dtype=np.uint8)
        notification = quiet.copy()
        notification[20:60, 30:210] = (120, 170, 240)

        timeline.offer(buffer, quiet, 0.0)
        for index in range(15):
            timeline.offer(buffer, notification, 0.05 * (index + 1))
        for index in range(30):
            timeline.offer(buffer, quiet, 0.80 + 0.05 * index)

        samples = drain(buffer)

        self.assertTrue(any(np.array_equal(item.frame, notification) for item in samples))
        self.assertEqual(
            sorted(item.captured_at for item in samples),
            [item.captured_at for item in samples],
        )

    def test_quiet_frame_follows_notification_in_capture_order(self) -> None:
        timeline = CaptureTimeline()
        buffer = NotificationFrameBuffer(candidate_capacity=4, clock=timeline)
        quiet = np.zeros((50, 150, 3), dtype=np.uint8)
        notification = np.full_like(quiet, 180)

        timeline.offer(buffer, quiet, 0.0)
        timeline.offer(buffer, notification, 0.1)
        timeline.offer(buffer, quiet, 0.9)

        samples = drain(buffer)
        self.assertEqual([0.0, 0.1, 0.9], [item.captured_at for item in samples])
        np.testing.assert_array_equal(samples[1].frame, notification)
        np.testing.assert_array_equal(samples[2].frame, quiet)

    def test_banner_survives_continuously_changing_background_for_three_seconds(
        self,
    ) -> None:
        timeline = CaptureTimeline()
        buffer = NotificationFrameBuffer(clock=timeline)
        quiet = np.zeros((80, 240, 3), dtype=np.uint8)
        notification = quiet.copy()
        notification[20:60, 30:210] = 220

        timeline.offer(buffer, quiet, 0.0)
        for index in range(15):
            timeline.offer(buffer, notification, 0.05 * (index + 1))
        for index in range(60):
            animated_background = np.full_like(
                quiet,
                3 + (index % 3),
            )
            timeline.offer(buffer, animated_background, 0.80 + 0.05 * index)

        samples = drain(buffer)
        self.assertTrue(any(np.array_equal(item.frame, notification) for item in samples))

    def test_two_short_banners_rearm_after_two_real_quiet_samples(self) -> None:
        timeline = CaptureTimeline()
        buffer = NotificationFrameBuffer(clock=timeline)
        gate = PresenceGate(enter_frames=1, exit_frames=2)
        matcher = OCRKeywordMatcher(["精灵藏进星星"])
        quiet = np.zeros((80, 240, 3), dtype=np.uint8)
        notification = quiet.copy()
        notification[20:60, 30:210] = 220
        def count_pending():
            detections = 0
            for sample in drain(buffer):
                texts = [OCRText("精灵藏进星星", 0.99)] if np.array_equal(
                    sample.frame, notification
                ) else []
                detections += int(gate.observe(matcher.match(texts) is not None))
            return detections

        timeline.offer(buffer, quiet, 0.0)
        for index in range(15):
            timeline.offer(buffer, notification, 0.05 * (index + 1))
        detections = count_pending()
        timeline.offer(buffer, quiet, 0.9)
        timeline.offer(buffer, quiet, 1.0)
        self.assertEqual(0, count_pending())

        for index in range(15):
            timeline.offer(buffer, notification, 1.05 + 0.05 * index)
        detections += count_pending()

        self.assertEqual(detections, 2)

    def test_candidate_queue_is_bounded(self) -> None:
        timeline = CaptureTimeline()
        buffer = NotificationFrameBuffer(candidate_capacity=3, active_threshold=1.0, clock=timeline)
        quiet = np.zeros((40, 120, 3), dtype=np.uint8)
        timeline.offer(buffer, quiet, 0.0)

        for index in range(20):
            changed = np.full_like(quiet, 20 + index)
            timeline.offer(buffer, changed, float(index + 1))
            self.assertLessEqual(buffer.pending_candidates, 3)

        samples = drain(buffer)
        self.assertLessEqual(len(samples), 3)
        self.assertEqual(20.0, samples[-1].captured_at)


if __name__ == "__main__":
    unittest.main()
