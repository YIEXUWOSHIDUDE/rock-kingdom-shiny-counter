"""Exercise real image decoding at the runtime-probe boundary, not GPU speed."""
import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from shiny_counter.probe_asset import OCR_PROBE_EXPECTED_FRAGMENT
from shiny_counter.runtime_probe import probe_gpu_runtime


class ProbeImagePathTests(unittest.TestCase):
    def run_probe(self, root, image):
        torch = MagicMock()
        torch.__version__ = "2.11.0+cu128"
        torch.version.cuda = "12.8"
        torch.cuda.is_available.return_value = True
        torch.cuda.current_device.return_value = 0
        torch.cuda.get_device_name.return_value = "NVIDIA GeForce RTX 3070"
        torch.cuda.get_device_capability.return_value = (8, 6)
        torch.cuda.get_arch_list.return_value = ["sm_75", "sm_86", "sm_120"]
        torch.ones.return_value.__matmul__.return_value.sum.return_value.item.return_value = 64.0
        reader = MagicMock()
        reader.device = "cuda"
        reader.readtext.return_value = [([], OCR_PROBE_EXPECTED_FRAGMENT, .99)]
        factory = MagicMock(return_value=reader)
        for name in ("craft_mlt_25k.pth", "zh_sim_g2.pth"):
            (root / name).write_bytes(b"test-model")
        report = probe_gpu_runtime(
            root, torch_module=torch, easyocr_module=types.SimpleNamespace(Reader=factory),
            expected_hashes=None, probe_image_path=image,
        )
        return report, reader, factory

    def test_ascii_and_unicode_paths_decode_identical_pixels(self):
        pixels = np.full((16, 32, 3), (20, 90, 160), dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", pixels)
        self.assertTrue(ok)
        blob = encoded.tobytes()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            for name in ("ascii", "中文用户", "中文 空格 é"):
                with self.subTest(path=name):
                    folder = root / name
                    folder.mkdir()
                    image = folder / "probe.png"
                    image.write_bytes(blob)
                    report, reader, factory = self.run_probe(folder, image)
                    self.assertTrue(report.ok, report.message)
                    np.testing.assert_array_equal(reader.readtext.call_args.args[0], pixels)
                    self.assertEqual(hashlib.sha256(blob).hexdigest(), report.details["probe_image_sha256"])
                    self.assertEqual("cuda", factory.call_args.kwargs["gpu"])
                    self.assertFalse(factory.call_args.kwargs["download_enabled"])

    def test_missing_empty_and_corrupt_images_fail_before_ocr(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            for content in (None, b"", b"not-a-png"):
                with self.subTest(content=content):
                    image = root / "probe.png"
                    if content is not None:
                        image.write_bytes(content)
                    report, reader, _ = self.run_probe(root, image)
                    self.assertFalse(report.ok)
                    self.assertEqual("probe_image_load", report.stage)
                    reader.readtext.assert_not_called()


if __name__ == "__main__":
    unittest.main()
