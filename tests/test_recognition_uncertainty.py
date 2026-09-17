import unittest

import numpy as np

from shiny_counter.ocr import OCRText
from shiny_counter.recognition import BannerRecognitionStream
from shiny_counter.storage import AppSettings


class RecognitionUncertaintyTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.stream = BannerRecognitionStream(AppSettings(), clock=lambda: self.now)

    def observe(self, texts):
        self.now += .2
        self.stream.offer_banner(np.zeros((30, 120, 3), np.uint8))
        sample = self.stream.take(timeout=0)
        return self.stream.observe(sample, texts)

    def target(self, confidence=.9):
        return [OCRText(self.stream.profile.keywords[0], confidence)]

    def test_weak_keyword_cannot_turn_one_banner_into_two_counts(self):
        now = [0.0]
        stream = BannerRecognitionStream(AppSettings(), clock=lambda: now[0])
        counted = []
        for confidence in (.8, .5139803657, .5202381079, .8):
            now[0] += .2
            stream.offer_banner(np.zeros((30, 120, 3), np.uint8))
            sample = stream.take(timeout=0)
            decision = stream.observe(sample, [OCRText(stream.profile.keywords[0], confidence)])
            counted.append(decision.counted)
        self.assertEqual(counted, [True, False, False, False])

    def test_weak_keyword_never_starts_a_count(self):
        for confidence in (0, .1, .52, .54999):
            decision = self.observe(self.target(confidence))
            self.assertTrue(decision.uncertain)
            self.assertFalse(decision.counted)
            self.assertIsNone(decision.match)
        self.assertTrue(self.observe(self.target(.55)).counted)

    def test_weak_keyword_breaks_absence_but_real_blanks_allow_next_event(self):
        self.assertTrue(self.observe(self.target()).counted)
        self.observe([])
        self.assertTrue(self.observe(self.target(.51)).uncertain)
        self.observe([])
        self.assertFalse(self.observe(self.target()).counted)
        self.observe([])
        self.observe([])
        self.assertTrue(self.observe(self.target()).counted)

    def test_weak_keyword_cannot_join_partial_enter_evidence(self):
        self.stream = BannerRecognitionStream(AppSettings(ocr_enter_frames=2), clock=lambda: self.now)
        self.assertFalse(self.observe(self.target()).counted)
        self.assertTrue(self.observe(self.target(.51)).uncertain)
        self.assertFalse(self.observe(self.target()).counted)
        self.assertTrue(self.observe(self.target()).counted)

    def test_custom_split_keyword_uses_same_matcher_without_lowering_threshold(self):
        self.stream = BannerRecognitionStream(
            AppSettings(ocr_keywords=["自定义关键词"], ocr_min_confidence=.9), clock=lambda: self.now)
        self.assertTrue(self.observe(self.target(.99)).counted)
        weak = [OCRText("自定义", .99), OCRText("关键词", .89)]
        self.assertTrue(self.observe(weak).uncertain)
        self.assertTrue(self.observe(weak).uncertain)
        self.assertFalse(self.observe(self.target(.99)).counted)
        for _ in range(2):
            decision = self.observe([OCRText("其他文字", .2)])
            self.assertFalse(decision.uncertain)
        self.assertTrue(self.observe(self.target(.99)).counted)

    def test_weak_target_across_pause_or_capture_gap_does_not_recount(self):
        for action in ("pause", "invalidate"):
            self.setUp()
            self.assertTrue(self.observe(self.target()).counted)
            self.observe([])
            if action == "pause":
                self.stream.set_paused(True)
                self.stream.set_paused(False)
            else:
                self.stream.invalidate()
            self.observe(self.target(.51))
            self.observe(self.target(.52))
            self.assertFalse(self.observe(self.target()).counted)
