import unittest
from pathlib import Path

from shiny_counter import __version__
from shiny_counter.gpu_policy import (
    EXPECTED_CUDA_TAG,
    EXPECTED_TORCH_VERSION,
    EXPECTED_TORCHVISION_VERSION,
)
from shiny_counter.ocr import OCR_MODEL_LOCK


ROOT = Path(__file__).resolve().parents[1]


class ReleaseConfigurationTests(unittest.TestCase):
    def test_python_package_version_comes_from_the_root_version_file(self) -> None:
        expected = (ROOT / "VERSION").read_text(encoding="ascii").strip()

        self.assertEqual(__version__, expected)

    def test_cuda_requirement_files_match_runtime_release_policy(self) -> None:
        cuda_requirements = (ROOT / "requirements-cuda.txt").read_text(
            encoding="utf-8"
        )
        locked_requirements = (
            ROOT / "requirements-lock-win-py313.txt"
        ).read_text(encoding="utf-8")

        self.assertIn(
            f"torch=={EXPECTED_TORCH_VERSION}",
            cuda_requirements,
        )
        self.assertIn(
            f"torchvision=={EXPECTED_TORCHVISION_VERSION}",
            cuda_requirements,
        )
        self.assertIn(
            f"torch=={EXPECTED_TORCH_VERSION}+{EXPECTED_CUDA_TAG}",
            locked_requirements,
        )
        self.assertIn(
            f"torchvision=={EXPECTED_TORCHVISION_VERSION}+{EXPECTED_CUDA_TAG}",
            locked_requirements,
        )
        self.assertIn(
            f"easyocr=={OCR_MODEL_LOCK['easyocr_version']}",
            locked_requirements,
        )


if __name__ == "__main__":
    unittest.main()
