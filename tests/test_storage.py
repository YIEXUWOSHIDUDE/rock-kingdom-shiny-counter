import tempfile
import unittest
import zipfile
from pathlib import Path

from shiny_counter.storage import DataCorruptError, DataStore


class DataStoreTests(unittest.TestCase):
    def test_counter_and_settings_survive_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            data.counter.target_name = "幽灵系异色"
            data.counter.pity_limit = 30
            data.counter.increment(source="auto", score=0.97)
            data.settings.window_title = "洛克王国：世界"
            data.settings.client_size = (1920, 1080)
            store.save(data)

            restored = DataStore(Path(directory)).load()

            self.assertEqual(restored.counter.target_name, "幽灵系异色")
            self.assertEqual(restored.counter.count, 1)
            self.assertEqual(restored.counter.history[0].score, 0.97)
            self.assertEqual(restored.settings.window_title, "洛克王国：世界")
            self.assertEqual(restored.settings.client_size, (1920, 1080))
            self.assertFalse((Path(directory) / "data.json.tmp").exists())

    def test_ocr_settings_survive_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            data.settings.ocr_keywords = ["污染解除", "噩梦枷锁"]
            data.settings.ocr_min_confidence = 0.61
            data.settings.ocr_interval_ms = 900
            store.save(data)

            restored = store.load().settings
            self.assertEqual(restored.ocr_keywords, ["污染解除", "噩梦枷锁"])
            self.assertEqual(restored.ocr_min_confidence, 0.61)
            self.assertEqual(restored.ocr_interval_ms, 900)

    def test_export_and_import_restore_data_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "app-data"
            store = DataStore(root)
            data = store.load()
            data.counter.increment(source="manual")
            store.save(data)

            archive = Path(directory) / "counter-backup.zip"
            store.export_archive(archive)

            data.counter.increment(source="manual")
            store.save(data)
            store.import_archive(archive)

            restored = store.load()
            self.assertEqual(restored.counter.count, 1)
            self.assertTrue(list(root.glob("pre-import-*.zip")))

    def test_corrupt_data_is_preserved_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("data.json").write_text("not-json", encoding="utf-8")

            with self.assertRaises(DataCorruptError):
                DataStore(root).load()

            backups = list(root.glob("data.corrupt-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "not-json")

    def test_invalid_import_does_not_replace_current_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "app-data"
            store = DataStore(root)
            data = store.load()
            data.counter.increment(source="manual")
            store.save(data)

            archive = Path(directory) / "incomplete.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("readme.txt", "missing data")

            with self.assertRaises(ValueError):
                store.import_archive(archive)
            self.assertEqual(store.load().counter.count, 1)


if __name__ == "__main__":
    unittest.main()
