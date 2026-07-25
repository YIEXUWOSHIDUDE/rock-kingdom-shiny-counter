import json
import tempfile
import types
import unittest
from pathlib import Path

from shiny_counter.package_probe import probe_packaged_dependencies
from shiny_counter.ocr import OCR_MODEL_LOCK


class PackagedDependencyProbeTests(unittest.TestCase):
    def test_all_runtime_boundaries_are_imported_and_assets_are_checked(self) -> None:
        imported: list[str] = []

        def importer(name: str):
            imported.append(name)
            return types.SimpleNamespace(__version__="test", __file__=name)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text("0.4.2", encoding="ascii")
            (root / "ocr-models.lock.json").write_text(
                json.dumps(OCR_MODEL_LOCK, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "ocr-models").mkdir()
            (root / "ocr-models" / "craft_mlt_25k.pth").write_bytes(b"detector")
            (root / "ocr-models" / "zh_sim_g2.pth").write_bytes(b"recognizer")
            (root / "ocr-probe").mkdir()
            (root / "ocr-probe" / "ocr-probe.png").write_bytes(b"png")

            report = probe_packaged_dependencies(
                root,
                importer=importer,
                expected_model_hashes=None,
            )

        self.assertTrue(report.ok, report.message)
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
