import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from shiny_counter.storage import AppSettings, DataCorruptError, DataStore


class DataStoreTests(unittest.TestCase):
    def test_global_hotkeys_are_disabled_by_default(self) -> None:
        settings = AppSettings()

        self.assertFalse(settings.hotkeys_enabled)
        self.assertEqual(settings.active_hotkeys(), {})

    def test_legacy_hotkeys_are_disabled_and_reduced_to_click_through_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            payload = data.to_dict()
            payload["settings"]["hotkeys"] = {
                "toggle_click_through": "Ctrl+Alt+T",
                "increment": "Ctrl+Alt+Up",
                "undo": "Ctrl+Alt+Down",
                "pause": "Ctrl+Alt+P",
            }
            payload["settings"].pop("hotkeys_enabled", None)
            store.root.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            restored = store.load().settings

            self.assertFalse(restored.hotkeys_enabled)
            self.assertEqual(
                restored.hotkeys,
                {"disable_click_through": "Ctrl+Alt+T"},
            )
            self.assertEqual(restored.active_hotkeys(), {})

    def test_overlay_position_is_locked_by_default_and_unlock_choice_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()

            self.assertTrue(data.settings.position_locked)

            data.settings.position_locked = False
            store.save(data)

            self.assertFalse(store.load().settings.position_locked)

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

    def test_completed_pity_rounds_survive_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            data.counter.pity_limit = 2
            data.counter.increment(source="auto", score=0.96)
            data.counter.increment(source="auto", score=0.97)
            data.counter.reset(source="manual")
            store.save(data)

            restored = store.load().counter.rounds

            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].attempts, 2)
            self.assertEqual(restored[0].pity_limit, 2)
            self.assertTrue(restored[0].reached_pity)
            self.assertEqual(restored[0].source, "manual")

    def test_old_reset_history_is_backfilled_as_an_explicit_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            for _ in range(61):
                data.counter.increment(source="auto", score=0.96)
            data.counter.reset(source="manual")
            legacy_payload = data.to_dict()
            legacy_payload["counter"].pop("rounds")
            store.root.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps(legacy_payload, ensure_ascii=False),
                encoding="utf-8",
            )

            restored_data = store.load()
            restored = restored_data.counter.rounds

            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].attempts, 61)
            self.assertIsNone(restored[0].pity_limit)
            self.assertEqual(restored[0].summary, "61次出（旧记录）")

            store.save(restored_data)
            self.assertEqual(len(store.load().counter.rounds), 1)

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
