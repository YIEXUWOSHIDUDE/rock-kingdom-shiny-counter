import unittest
from unittest.mock import Mock, patch

import numpy as np

from shiny_counter.capture import CaptureError, Win32Capture, WindowSizeChanged, WindowUnavailable
from shiny_counter.ocr import crop_notification_banner, notification_banner_rect
from shiny_counter.recognition import BannerRecognitionStream
from shiny_counter.storage import AppSettings


class PatternBackend:
    def __init__(self):
        self.rectangles = []

    def grab(self, rect):
        self.rectangles.append(rect)
        y, x = np.ogrid[:rect["height"], :rect["width"]]
        frame = np.zeros((rect["height"], rect["width"], 4), np.uint8)
        frame[:, :, 0] = (x + rect["left"]) % 256
        frame[:, :, 1] = (y + rect["top"]) % 256
        frame[:, :, 2] = (x + rect["left"] + y + rect["top"]) % 251
        self.latest = frame
        return frame


class RegionCaptureTests(unittest.TestCase):
    def capture(self, geometry):
        capture = Win32Capture.__new__(Win32Capture)
        capture._mss = PatternBackend()
        capture.performance = None
        capture._geometry = Mock(return_value=geometry)
        return capture

    def test_same_pixels_as_full_crop_at_physical_sizes_and_moved_origins(self):
        # Physical pixels after DPI awareness: 100%, 125%, 150% representative sizes.
        for width, height in ((1920, 1080), (2560, 1600), (2400, 1350), (2880, 1620), (160, 120), (1919, 1079)):
            capture = self.capture((42, -400, 57, width, height))
            full, size = capture.capture_client((width, height))
            banner, original_size = capture.capture_banner((width, height), AppSettings().recognition_profile())
            np.testing.assert_array_equal(banner, crop_notification_banner(full))
            self.assertEqual(size, original_size)
            left, top, w, h = notification_banner_rect(width, height)
            self.assertEqual(capture._mss.rectangles[-1], dict(left=-400+left, top=57+top, width=w, height=h))
            self.assertLess(w*h, width*height)
            capture._geometry.return_value = (42, 111, -100, width, height)
            capture.capture_banner((width, height), AppSettings().recognition_profile())
            self.assertEqual(capture._mss.rectangles[-1]["left"], 111+left)
            self.assertEqual(capture._mss.rectangles[-1]["top"], -100+top)
            capture._geometry.assert_called_with((width, height))

    def test_original_window_errors_propagate_without_grabbing(self):
        for exception in (WindowUnavailable("minimized"), WindowSizeChanged("resized")):
            capture = self.capture((42, 0, 0, 1920, 1080))
            capture._geometry.side_effect = exception
            with self.assertRaises(type(exception)):
                capture.capture_banner((1920, 1080), AppSettings().recognition_profile())
            self.assertEqual(capture._mss.rectangles, [])

    def test_empty_region_rejected_before_backend(self):
        capture = self.capture((42, 0, 0, 1, 1))
        with self.assertRaises(CaptureError):
            capture.capture_banner((1, 1), AppSettings().recognition_profile())
        self.assertEqual(capture._mss.rectangles, [])

    def test_capture_and_buffer_each_own_pixels_no_double_crop(self):
        capture = self.capture((42, 0, 0, 1920, 1080))
        banner, _ = capture.capture_banner((1920, 1080), AppSettings().recognition_profile())
        expected = banner.copy()
        capture._mss.latest[:] = 0
        np.testing.assert_array_equal(banner, expected)
        stream = BannerRecognitionStream(AppSettings())
        with patch("shiny_counter.recognition.crop_notification_banner", side_effect=AssertionError("double crop")):
            stream.offer_banner(banner)
        banner[:] = 0
        sample = stream.take(timeout=0)
        np.testing.assert_array_equal(sample.frame, expected)
        self.assertTrue(sample.frame.flags.c_contiguous)
