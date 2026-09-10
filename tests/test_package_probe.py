import builtins
import json
import tempfile
import types
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from shiny_counter.package_probe import probe_packaged_dependencies
from shiny_counter.ocr import OCR_MODEL_LOCK
from shiny_counter.recognition_profile import CURRENT_RECOGNITION_PROFILE


class PackagedDependencyProbeTests(unittest.TestCase):
    @staticmethod
    def _write_assets(root: Path) -> None:
        (root / "VERSION").write_text("0.4.2", encoding="ascii")
        (root / "ocr-models.lock.json").write_text(
            json.dumps(OCR_MODEL_LOCK, ensure_ascii=False), encoding="utf-8",
        )
        (root / "ocr-models").mkdir()
        (root / "ocr-models" / "craft_mlt_25k.pth").write_bytes(b"detector")
        (root / "ocr-models" / "zh_sim_g2.pth").write_bytes(b"recognizer")
        (root / "ocr-probe").mkdir()
        (root / "ocr-probe" / "ocr-probe.png").write_bytes(b"png")

    def test_recognition_self_check_failures_report_their_specific_stage(self) -> None:
        actual_import = builtins.__import__

        def missing_packaged_profile(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "recognition_profile" and level == 1:
                raise ModuleNotFoundError("recognition profile is absent from the frozen package")
            return actual_import(name, globals, locals, fromlist, level)

        failures = [
            (
                "recognition_profile",
                patch("builtins.__import__", side_effect=missing_packaged_profile),
                "ModuleNotFoundError",
            ),
            (
                "recognition_migration",
                patch("json.dumps", side_effect=TypeError("counter serialization failed")),
                "TypeError",
            ),
            (
                "recognition_stream",
                patch("numpy.full", side_effect=MemoryError("synthetic image allocation failed")),
                "MemoryError",
            ),
        ]
        for stage, failure, error_type in failures:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_assets(root)
                with failure:
                    report = probe_packaged_dependencies(
                        root,
                        importer=lambda name: types.SimpleNamespace(__file__=name),
                        expected_model_hashes=None,
                    )

                self.assertFalse(report.ok)
                self.assertEqual(report.stage, stage)
                self.assertEqual(report.details["error_type"], error_type)
                self.assertIn("失败", report.message)

    def test_probe_exercises_two_banners_and_deduplication_with_synthetic_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_assets(root)
            report = probe_packaged_dependencies(
                root,
                importer=lambda name: types.SimpleNamespace(__file__=name),
                expected_model_hashes=None,
            )

        self.assertTrue(report.ok, report.message)
        stream = report.details["recognition_stream"]
        self.assertEqual(stream["module"], "shiny_counter.recognition")
        self.assertEqual(stream["profile_id"], CURRENT_RECOGNITION_PROFILE.profile_id)
        self.assertEqual(stream["counts_by_banner"], [1, 1])
        self.assertEqual(sum(stream["counted"]), 2)
        self.assertGreater(len(stream["counted"]), 2)
        self.assertEqual(stream["input"], "synthetic_ocr_text")
        self.assertFalse(stream["gpu_inference"])
        self.assertFalse(stream["user_data_accessed"])

    def test_probe_checks_legacy_migration_without_changing_counter_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_assets(root)
            report = probe_packaged_dependencies(
                root,
                importer=lambda name: types.SimpleNamespace(__file__=name),
                expected_model_hashes=None,
            )

        self.assertTrue(report.ok, report.message)
        migration = report.details["recognition_migration"]
        self.assertEqual(migration["profile_id"], CURRENT_RECOGNITION_PROFILE.profile_id)
        self.assertEqual(migration["keywords"], list(CURRENT_RECOGNITION_PROFILE.keywords))
        self.assertEqual(migration["count"], 2)
        self.assertEqual(migration["history_events"], 4)
        self.assertEqual(migration["rounds"], 1)
        self.assertTrue(migration["counter_preserved"])
        self.assertTrue(migration["stable_reload"])

    def test_all_runtime_boundaries_are_imported_and_assets_are_checked(self) -> None:
        imported: list[str] = []

        def importer(name: str):
            imported.append(name)
            return types.SimpleNamespace(__version__="test", __file__=name)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_assets(root)

            report = probe_packaged_dependencies(
                root,
                importer=importer,
                expected_model_hashes=None,
            )

        self.assertTrue(report.ok, report.message)
        self.assertEqual(
            report.details["recognition_profile"],
            asdict(CURRENT_RECOGNITION_PROFILE),
        )
        self.assertEqual(
            set(imported),
            {
                "PySide6",
                "cv2",
                "easyocr",
                "mss",
                "numpy",
                "torch",
                "win32gui",
                "win32process",
            },
        )

    def test_missing_frozen_module_fails_with_its_name(self) -> None:
        def importer(name: str):
            if name == "mss":
                raise ModuleNotFoundError(name)
            return types.SimpleNamespace(__version__="test", __file__=name)

        report = probe_packaged_dependencies(
            Path("unused"),
            importer=importer,
            expected_model_hashes=None,
        )

        self.assertFalse(report.ok)
        self.assertEqual("dependency_import", report.stage)
        self.assertIn("mss", report.message)


if __name__ == "__main__":
    unittest.main()
