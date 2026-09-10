from __future__ import annotations

import types
import unittest
from pathlib import Path
import shutil
import json

from shiny_counter.runtime_probe import (
    RuntimeProbeReport,
    probe_gpu_runtime,
    write_runtime_probe_report,
)
from shiny_counter.probe_asset import OCR_PROBE_EXPECTED_FRAGMENT


class RuntimeProbeTests(unittest.TestCase):
    def test_cuda_unavailable_fails_without_starting_easyocr(self) -> None:
        class UnavailableCuda:
            @staticmethod
            def is_available() -> bool:
                return False

        reader_started = False

        def reader_factory(*args: object, **kwargs: object) -> object:
            nonlocal reader_started
            reader_started = True
            return object()

        report = probe_gpu_runtime(
            Path("unused"),
            torch_module=types.SimpleNamespace(
                __version__="test",
                version=types.SimpleNamespace(cuda="12.8"),
                cuda=UnavailableCuda(),
            ),
            easyocr_module=types.SimpleNamespace(Reader=reader_factory),
        )

        self.assertFalse(report.ok)
        self.assertEqual("cuda_available", report.stage)
        self.assertIn("不允许 CPU", report.message)
        self.assertFalse(reader_started)

    def test_cuda_130_package_is_rejected_before_any_gpu_inference(self) -> None:
        tensor_created = False

        class AvailableCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def current_device() -> int:
                return 0

            @staticmethod
            def get_device_capability() -> tuple[int, int]:
                return (8, 6)

            @staticmethod
            def get_device_name() -> str:
                return "NVIDIA GeForce RTX 3070"

            @staticmethod
            def get_arch_list() -> list[str]:
                return ["sm_75", "sm_86", "sm_120"]

        def ones(*args: object, **kwargs: object) -> object:
            nonlocal tensor_created
            tensor_created = True
            return object()

        report = probe_gpu_runtime(
            Path("unused"),
            torch_module=types.SimpleNamespace(
                __version__="2.11.0+cu130",
                version=types.SimpleNamespace(cuda="13.0"),
                cuda=AvailableCuda(),
                ones=ones,
            ),
            easyocr_module=types.SimpleNamespace(
                Reader=lambda *args, **kwargs: object()
            ),
        )

        self.assertFalse(report.ok)
        self.assertEqual("release_runtime", report.stage)
        self.assertIn("CUDA 12.8", report.message)
        self.assertEqual("NVIDIA GeForce RTX 3070", report.details["device"])
        self.assertEqual([8, 6], report.details["capability"])
        self.assertEqual(0, report.details["device_index"])
        self.assertEqual(
            "GPUCompatibilityError",
            report.details["error_type"],
        )
        self.assertFalse(tensor_created)

    def test_success_requires_cuda_kernel_and_easyocr_inference(self) -> None:
        root = Path(__file__).parent / "_tmp_runtime_probe"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir()
        (root / "craft_mlt_25k.pth").write_bytes(b"detector")
        (root / "zh_sim_g2.pth").write_bytes(b"recognizer")
        calls: list[object] = []

        class FakeTensor:
            def __matmul__(self, other: object) -> "FakeTensor":
                calls.append("matmul")
                return self

            def sum(self) -> "FakeTensor":
                calls.append("sum")
                return self

            def item(self) -> float:
                return 8.0

        class SupportedCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def current_device() -> int:
                return 0

            @staticmethod
            def get_device_capability() -> tuple[int, int]:
                return (12, 0)

            @staticmethod
            def get_device_name() -> str:
                return "NVIDIA GeForce RTX 5070"

            @staticmethod
            def get_arch_list() -> list[str]:
                return ["sm_75", "sm_86", "sm_120"]

            @staticmethod
            def synchronize() -> None:
                calls.append("synchronize")

        def ones(*shape: object, **options: object) -> FakeTensor:
            calls.append(("ones", options.get("device")))
            return FakeTensor()

        def reader_factory(*languages: object, **options: object) -> object:
            calls.append(("reader", options.get("gpu"), options.get("download_enabled")))

            def readtext(frame: object, **read_options: object) -> list[object]:
                calls.append(("readtext", frame, read_options.get("detail")))
                return [([], OCR_PROBE_EXPECTED_FRAGMENT, 0.99)]

            return types.SimpleNamespace(device="cuda", readtext=readtext)

        try:
            report = probe_gpu_runtime(
                root,
                torch_module=types.SimpleNamespace(
                    __version__="2.11.0+cu128",
                    version=types.SimpleNamespace(cuda="12.8"),
                    cuda=SupportedCuda(),
                    ones=ones,
                ),
                easyocr_module=types.SimpleNamespace(Reader=reader_factory),
                expected_hashes=None,
                probe_image="probe-frame",
            )

            self.assertTrue(report.ok, report.message)
            self.assertEqual("complete", report.stage)
            self.assertIn(("ones", "cuda"), calls)
            self.assertIn("synchronize", calls)
            self.assertIn(("reader", "cuda", False), calls)
            self.assertIn(("readtext", "probe-frame", 1), calls)
            self.assertEqual("cuda", report.details["reader_device"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_failed_probe_writes_json_and_returns_nonzero(self) -> None:
        root = Path(__file__).parent / "_tmp_runtime_report"
        shutil.rmtree(root, ignore_errors=True)
        destination = root / "runtime.json"
        report = RuntimeProbeReport(
            ok=False,
            stage="cuda_available",
            message="CUDA 不可用；不允许 CPU 回退。",
            details={"torch": "test"},
        )
        try:
            exit_code = write_runtime_probe_report(destination, report)

            self.assertNotEqual(0, exit_code)
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual("cuda_available", payload["stage"])
            self.assertIn("不允许 CPU", payload["message"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
