import unittest

import numpy as np

from shiny_counter.detection import PresenceGate
from shiny_counter.frame_buffer import NotificationFrameBuffer


class NotificationFrameBufferTests(unittest.TestCase):
    def test_short_notification_survives_until_slow_ocr_is_ready(self) -> None:
        buffer = NotificationFrameBuffer(candidate_capacity=8, active_threshold=2.5)
        quiet = np.zeros((80, 240, 3), dtype=np.uint8)
        notification = quiet.copy()
        notification[20:60, 30:210] = (120, 170, 240)

        buffer.offer(quiet, captured_at=0.00)
        for index in range(15):
            buffer.offer(notification, captured_at=0.05 * (index + 1))
        for index in range(30):
            buffer.offer(quiet, captured_at=0.80 + 0.05 * index)

        sample = buffer.take(timeout=0)

        self.assertIsNotNone(sample)
        self.assertGreaterEqual(sample.activity, 2.5)
        np.testing.assert_array_equal(sample.frame, notification)

    def test_quiet_frame_follows_notification_so_presence_gate_can_rearm(self) -> None:
        buffer = NotificationFrameBuffer(candidate_capacity=4, active_threshold=2.5)
        quiet = np.zeros((50, 150, 3), dtype=np.uint8)
        notification = np.full_like(quiet, 180)

        buffer.offer(quiet, captured_at=0.0)
        buffer.offer(notification, captured_at=0.1)
        buffer.offer(quiet, captured_at=0.9)

        active = buffer.take(timeout=0)
        inactive = buffer.take(timeout=0)

        self.assertGreaterEqual(active.activity, 2.5)
        self.assertLess(inactive.activity, 2.5)
        np.testing.assert_array_equal(inactive.frame, quiet)

    def test_banner_survives_continuously_changing_background_for_three_seconds(
        self,
    ) -> None:
        buffer = NotificationFrameBuffer(active_threshold=2.5)
        quiet = np.zeros((80, 240, 3), dtype=np.uint8)
        notification = quiet.copy()
        notification[20:60, 30:210] = 220

        buffer.offer(quiet, captured_at=0.0)
        for index in range(15):
            buffer.offer(notification, captured_at=0.05 * (index + 1))
        for index in range(60):
            animated_background = np.full_like(
                quiet,
                3 + (index % 3),
            )
            buffer.offer(
                animated_background,
                captured_at=0.80 + 0.05 * index,
            )

        sample = buffer.take(timeout=0)

        self.assertIsNotNone(sample)
        np.testing.assert_array_equal(sample.frame, notification)

    def test_two_short_banners_rearm_after_two_quiet_samples(self) -> None:
        buffer = NotificationFrameBuffer(active_threshold=2.5)
        gate = PresenceGate(enter_frames=1, exit_frames=2)
        quiet = np.zeros((80, 240, 3), dtype=np.uint8)
        notification = quiet.copy()
        notification[20:60, 30:210] = 220
        detections = 0

        buffer.offer(quiet, captured_at=0.0)
        for index in range(15):
            buffer.offer(notification, captured_at=0.05 * (index + 1))
        first = buffer.take(timeout=0)
        detections += int(gate.observe(first.activity >= 2.5))

        first_quiet = buffer.take(timeout=0)
        self.assertFalse(gate.observe(first_quiet.activity >= 2.5))
        buffer.offer(quiet, captured_at=1.0)
        second_quiet = buffer.take(timeout=0)
        self.assertFalse(gate.observe(second_quiet.activity >= 2.5))

        for index in range(15):
            buffer.offer(notification, captured_at=1.05 + 0.05 * index)
        second = buffer.take(timeout=0)
        detections += int(gate.observe(second.activity >= 2.5))

        self.assertEqual(detections, 2)

    def test_candidate_queue_is_bounded(self) -> None:
        buffer = NotificationFrameBuffer(candidate_capacity=3, active_threshold=1.0)
        quiet = np.zeros((40, 120, 3), dtype=np.uint8)
        buffer.offer(quiet, captured_at=0.0)

        for index in range(20):
            changed = np.full_like(quiet, 20 + index)
            buffer.offer(changed, captured_at=float(index + 1))

        self.assertLessEqual(buffer.pending_candidates, 3)


if __name__ == "__main__":
    unittest.main()
