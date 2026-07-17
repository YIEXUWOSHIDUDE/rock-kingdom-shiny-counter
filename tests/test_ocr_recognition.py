import unittest

from shiny_counter.ocr import OCRKeywordMatcher, OCRText


class OCRKeywordMatcherTests(unittest.TestCase):
    def test_keyword_match_tolerates_spaces_and_ignores_low_confidence_text(self) -> None:
        matcher = OCRKeywordMatcher(["污染解除", "噩梦枷锁"], min_confidence=0.55)

        low_confidence = matcher.match([OCRText("污染 解除", 0.40)])
        matched = matcher.match(
            [OCRText("战斗结束", 0.98), OCRText("污染 解除", 0.82)]
        )

        self.assertIsNone(low_confidence)
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.keyword, "污染解除")
        self.assertEqual(matched.confidence, 0.82)

    def test_keyword_can_span_multiple_ocr_text_boxes(self) -> None:
        matcher = OCRKeywordMatcher(["污染解除"], min_confidence=0.55)

        matched = matcher.match([OCRText("污染", 0.91), OCRText("解除", 0.87)])

        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.keyword, "污染解除")
        self.assertEqual(matched.confidence, 0.87)


if __name__ == "__main__":
    unittest.main()
