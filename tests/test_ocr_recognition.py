import shutil
import sys
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from shiny_counter.gpu_policy import GPUCompatibilityError
from shiny_counter.ocr import (
    EasyOCREngine,
    OCRError,
    OCRKeywordMatcher,
    OCRText,
    crop_notification_banner,
    download_ocr_model,
    ensure_ocr_models,
    notification_banner_rect,
    validate_cuda_device,
)


class OCRKeywordMatcherTests(unittest.TestCase):
    def test_notification_banner_crop_uses_relative_coordinates(self) -> None:
        frame = np.zeros((1170, 2532, 3), dtype=np.uint8)

        cropped = crop_notification_banner(frame)

        self.assertEqual(cropped.shape, (198, 1115, 3))
        self.assertEqual(
            notification_banner_rect(2532, 1170),
            (708, 117, 1115, 198),
        )

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


class OCRModelProvisioningTests(unittest.TestCase):
    def test_bundled_models_are_used_without_network_access(self) -> None:
        root = Path(__file__).parent / "_tmp_model_provisioning"
        shutil.rmtree(root, ignore_errors=True)
        bundled = root / "bundled"
        target = root / "target"
        bundled.mkdir(parents=True)
        (bundled / "craft_mlt_25k.pth").write_bytes(b"detector")
        (bundled / "zh_sim_g2.pth").write_bytes(b"recognizer")

        network_calls: list[str] = []

        def fail_if_called(url: str, destination: Path) -> None:
            network_calls.append(url)
            raise AssertionError("bundled models must not use the network")

        try:
            source = ensure_ocr_models(
                target,
                bundled_directory=bundled,
                expected_hashes=None,
                downloader=fail_if_called,
            )

            self.assertEqual(source, "bundled")
            self.assertEqual((target / "craft_mlt_25k.pth").read_bytes(), b"detector")
            self.assertEqual((target / "zh_sim_g2.pth").read_bytes(), b"recognizer")
            self.assertEqual(network_calls, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_domestic_mirror_is_tried_before_official_source(self) -> None:
        root = Path(__file__).parent / "_tmp_model_download"
        shutil.rmtree(root, ignore_errors=True)
        target = root / "target"
        calls: list[str] = []
        sources = {
            "craft_mlt_25k.pth": (
                "https://modelscope.cn/craft",
                "https://github.com/craft",
            ),
            "zh_sim_g2.pth": (
                "https://modelscope.cn/zh",
                "https://github.com/zh",
            ),
        }

        def download(url: str, destination: Path) -> None:
            calls.append(url)
            if "modelscope.cn/craft" in url:
                raise TimeoutError("mirror timeout")
            destination.write_bytes(destination.name.encode("ascii"))

        try:
            source = ensure_ocr_models(
                target,
                expected_hashes=None,
                model_sources=sources,
                downloader=download,
            )

            self.assertEqual(source, "downloaded")
            self.assertEqual(
                calls,
                [
                    "https://modelscope.cn/craft",
                    "https://github.com/craft",
                    "https://modelscope.cn/zh",
                ],
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_empty_model_sources_disable_all_downloads(self) -> None:
        root = Path(__file__).parent / "_tmp_offline_models"
        shutil.rmtree(root, ignore_errors=True)
        network_calls: list[str] = []

        def fail_if_called(url: str, destination: Path) -> None:
            network_calls.append(url)

        try:
            with self.assertRaisesRegex(OCRError, "模型缺失"):
                ensure_ocr_models(
                    root,
                    expected_hashes=None,
                    model_sources={},
                    downloader=fail_if_called,
                )
            self.assertEqual(network_calls, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_default_sources_use_verified_domestic_mirrors_before_github(self) -> None:
        root = Path(__file__).parent / "_tmp_default_model_sources"
        shutil.rmtree(root, ignore_errors=True)
        calls: list[str] = []

        def download(url: str, destination: Path) -> None:
            calls.append(url)
            destination.write_bytes(destination.name.encode("ascii"))

        try:
            ensure_ocr_models(
                root,
                expected_hashes=None,
                downloader=download,
            )

            self.assertEqual(len(calls), 2)
            self.assertIn("modelscope.cn", calls[0])
            self.assertIn("api.gitcode.com", calls[1])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_official_zip_download_extracts_the_requested_model(self) -> None:
        root = Path(__file__).parent / "_tmp_zip_model_download"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        archive = root / "model.zip"
        destination = root / "craft_mlt_25k.pth"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("craft_mlt_25k.pth", b"official-model")

        try:
            download_ocr_model(archive.as_uri(), destination)

            self.assertEqual(destination.read_bytes(), b"official-model")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class CUDACompatibilityTests(unittest.TestCase):
    def test_cuda_is_required_and_cpu_fallback_is_not_allowed(self) -> None:
        class UnavailableCuda:
            @staticmethod
            def is_available() -> bool:
                return False

        class FakeTorch:
            cuda = UnavailableCuda()

        with self.assertRaisesRegex(
            GPUCompatibilityError,
            "RTX 20.*580\\.88.*不支持 CPU",
        ) as raised:
            validate_cuda_device(FakeTorch())
        self.assertEqual("CUDA_UNAVAILABLE", raised.exception.code)

    def test_pre_rtx_gpu_is_rejected_by_compute_capability(self) -> None:
        class LegacyCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def get_device_capability() -> tuple[int, int]:
                return (6, 1)

            @staticmethod
            def get_device_name() -> str:
                return "NVIDIA GeForce GTX 1080"

        class FakeTorch:
            cuda = LegacyCuda()

        with self.assertRaisesRegex(
            GPUCompatibilityError,
            "计算能力 6\\.1.*最低要求 7\\.5",
        ) as raised:
            validate_cuda_device(FakeTorch())
        self.assertEqual("CUDA_ARCH_UNSUPPORTED", raised.exception.code)

    def test_runtime_must_include_the_detected_gpu_architecture(self) -> None:
        class BlackwellCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def get_device_capability() -> tuple[int, int]:
                return (12, 0)

            @staticmethod
            def get_device_name() -> str:
                return "NVIDIA GeForce RTX 5070"

            @staticmethod
            def get_arch_list() -> list[str]:
                return ["sm_75", "sm_86", "sm_89", "sm_90"]

        class FakeTorch:
            cuda = BlackwellCuda()

        with self.assertRaisesRegex(RuntimeError, "不包含 sm_120.*CUDA 13\\.0"):
            validate_cuda_device(FakeTorch())

    def test_same_major_cuda_binary_supports_a_newer_minor_gpu(self) -> None:
        class AdaCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def get_device_capability() -> tuple[int, int]:
                return (8, 9)

            @staticmethod
            def get_device_name() -> str:
                return "NVIDIA GeForce RTX 4070"

            @staticmethod
            def get_arch_list() -> list[str]:
                return ["sm_75", "sm_80", "sm_86", "sm_90", "sm_120"]

        class FakeTorch:
            cuda = AdaCuda()

        self.assertIn("sm_89", validate_cuda_device(FakeTorch()))

    def test_easyocr_starts_on_gpu_with_network_download_disabled(self) -> None:
        root = Path(__file__).parent / "_tmp_gpu_engine"
        shutil.rmtree(root, ignore_errors=True)
        bundled = root / "ocr-models"
        target = root / "target"
        bundled.mkdir(parents=True)
        (bundled / "craft_mlt_25k.pth").write_bytes(b"detector")
        (bundled / "zh_sim_g2.pth").write_bytes(b"recognizer")
        reader_arguments: dict[str, object] = {}

        class SupportedCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def get_device_capability() -> tuple[int, int]:
                return (8, 6)

            @staticmethod
            def get_device_name() -> str:
                return "NVIDIA GeForce RTX 3070"

            @staticmethod
            def get_arch_list() -> list[str]:
                return ["sm_75", "sm_86", "sm_89", "sm_120"]

        fake_torch = types.SimpleNamespace(cuda=SupportedCuda())

        def reader_factory(*languages: object, **options: object) -> object:
            reader_arguments["languages"] = languages
            reader_arguments.update(options)
            return types.SimpleNamespace(readtext=lambda *args, **kwargs: [])

        fake_easyocr = types.SimpleNamespace(Reader=reader_factory)
        try:
            with patch.dict(
                sys.modules,
                {"torch": fake_torch, "easyocr": fake_easyocr},
            ), patch.object(
                sys,
                "_MEIPASS",
                str(root),
                create=True,
            ), patch(
                "shiny_counter.ocr.ensure_ocr_models",
                wraps=ensure_ocr_models,
            ) as provision:
                engine = EasyOCREngine(
                    target,
                    expected_hashes=None,
                )

            self.assertEqual("cuda", reader_arguments["gpu"])
            self.assertFalse(reader_arguments["download_enabled"])
            self.assertIn("RTX 3070", engine.device_label)
            self.assertEqual({}, provision.call_args.kwargs["model_sources"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
