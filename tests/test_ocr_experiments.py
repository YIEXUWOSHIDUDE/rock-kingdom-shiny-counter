import unittest
from unittest.mock import Mock

from shiny_counter.ocr import EasyOCREngine


class OCRExperimentTests(unittest.TestCase):
    def test_default_keeps_original_options_and_batch_only_applies_to_one_image(self):
        for batch in (None, 1, 4, 8):
            engine = EasyOCREngine.__new__(EasyOCREngine)
            engine._experimental_batch_size = batch
            engine.reader = Mock()
            engine.reader.readtext.return_value = [(None, "text", .99)]
            frame = object()
            results = engine.read(frame)
            options = {} if batch is None else {"batch_size": batch}
            engine.reader.readtext.assert_called_once_with(frame, detail=1, paragraph=False, **options)
            self.assertEqual(results[0].text, "text")
