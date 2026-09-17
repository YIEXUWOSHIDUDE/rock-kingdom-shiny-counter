import unittest

import numpy as np

from shiny_counter.frame_buffer import NotificationFrameBuffer
from shiny_counter.performance import PerformanceStats


class PerformanceTests(unittest.TestCase):
    def test_cpu_time_is_not_elapsed_time_and_reports_reset(self):
        wall, cpu = [0.0], [0.0]
        stats = PerformanceStats(clock=lambda: wall[0], cpu_clock=lambda: cpu[0])
        for value in range(1, 101):
            stats.timing("ocr", value / 1000)
        stats.event("captures", 20)
        wall[0], cpu[0] = 2.0, 0.1
        report = stats.report()
        self.assertAlmostEqual(report["cpu_one_core_percent"], 5)
        self.assertEqual(report["captures_per_second"], 10)
        self.assertAlmostEqual(report["stages"]["ocr"]["p95_ms"], 95)
        self.assertAlmostEqual(report["stages"]["ocr"]["mean_ms"], 50.5)
        self.assertEqual(stats.report()["stages"], {})

    def test_capacity_and_expiration_are_separate_from_compression(self):
        now = [0.0]
        stats = PerformanceStats()
        buffer = NotificationFrameBuffer(clock=lambda: now[0], candidate_capacity=2, performance=stats)
        for i in range(3):
            now[0] += .1
            buffer.offer(np.full((10, 10, 3), i * 100, np.uint8))
        now[0] = 6
        self.assertIsNone(buffer.take(timeout=0))
        events = stats.report()["events"]
        self.assertEqual(events["capacity_drops"], 1)
        self.assertEqual(events["expired_frames"], 2)
        self.assertNotIn("compressed_frames", events)
