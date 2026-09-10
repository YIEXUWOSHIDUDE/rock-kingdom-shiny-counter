import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path

from shiny_counter.capture import WindowBinding
from shiny_counter.storage import AppData, AppSettings, DataCorruptError, DataStore


class DataStoreTests(unittest.TestCase):
    def test_loading_an_unknown_profile_reports_it_without_altering_saved_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            payload = AppData().to_dict()
            payload["settings"]["recognition_profile_id"] = "future-season"
            encoded = json.dumps(payload, ensure_ascii=False)
            store.path.write_text(encoded, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown recognition profile.*future-season"):
                store.load()

            self.assertEqual(store.path.read_text(encoding="utf-8"), encoded)
            self.assertEqual(list(store.root.glob("data.corrupt-*")), [])

    def test_migrated_profile_is_tagged_and_stable_across_repeated_serialization(self) -> None:
        payload = AppData().to_dict()
        payload["settings"].pop("recognition_profile_id")
        payload["settings"]["ocr_keywords"] = ["写进了童话里"]

        first = AppData.from_dict(payload).to_dict()
        second = AppData.from_dict(json.loads(json.dumps(first))).to_dict()

        self.assertEqual(first, second)
        self.assertEqual(first["settings"]["recognition_profile_id"], AppSettings().recognition_profile_id)
        self.assertEqual(second["settings"]["ocr_keywords"], ["划破天幕坠落"])

    def test_custom_keywords_are_preserved_in_legacy_and_tagged_settings(self) -> None:
        cases = [
            (False, ["我的关键词"]),
            (False, ["写进了童话里", "我的关键词"]),
            (False, [" 写进了童话里 "]),
            (True, ["写进了童话里"]),
        ]
        for tagged, keywords in cases:
            with self.subTest(tagged=tagged, keywords=keywords):
                payload = AppData().to_dict()
                if not tagged:
                    payload["settings"].pop("recognition_profile_id")
                payload["settings"].update(
                    ocr_keywords=keywords,
                    ocr_min_confidence=0.63,
                    ocr_interval_ms=1200,
                    ocr_enter_frames=2,
                    ocr_exit_frames=3,
                )

                restored = AppData.from_dict(payload).settings

                self.assertEqual(restored.ocr_keywords, keywords)
                self.assertEqual(restored.recognition_profile().keywords, tuple(keywords))
                self.assertEqual(restored.ocr_min_confidence, 0.63)
                self.assertEqual(restored.ocr_interval_ms, 1200)
                self.assertEqual(restored.ocr_enter_frames, 2)
                self.assertEqual(restored.ocr_exit_frames, 3)

    def test_unknown_recognition_profile_is_rejected_without_rewriting_input(self) -> None:
        for profile_id in ("future-season", "", None):
            with self.subTest(profile_id=profile_id):
                payload = AppData().to_dict()
                payload["settings"]["recognition_profile_id"] = profile_id
                payload["settings"]["ocr_keywords"] = ["我的关键词"]
                original = deepcopy(payload)

                with self.assertRaisesRegex(ValueError, "unknown recognition profile"):
                    AppData.from_dict(payload)

                self.assertEqual(payload, original)

    def test_missing_recognition_fields_use_the_same_defaults_as_new_settings(self) -> None:
        payload = AppData().to_dict()
        payload["settings"] = {}

        restored = AppData.from_dict(payload).settings

        self.assertEqual(restored.ocr_keywords, ["划破天幕坠落"])
        self.assertEqual(restored.recognition_profile(), AppSettings().recognition_profile())

    def test_legacy_default_keyword_migrates_without_changing_other_data(self) -> None:
        data = AppData()
        data.counter.increment(source="manual")
        data.counter.reset()
        data.counter.increment(source="auto", score=0.91)
        payload = data.to_dict()
        payload["settings"].pop("recognition_profile_id", None)
        payload["settings"].update(
            ocr_keywords=["写进了童话里"],
            ocr_min_confidence=0.79,
            ocr_interval_ms=800,
            ocr_enter_frames=3,
            ocr_exit_frames=4,
            opacity=0.70,
        )
        original = deepcopy(payload)

        migrated = AppData.from_dict(payload)

        self.assertEqual(migrated.settings.ocr_keywords, ["划破天幕坠落"])
        self.assertEqual(migrated.settings.ocr_min_confidence, 0.79)
        self.assertEqual(migrated.settings.ocr_interval_ms, 800)
        self.assertEqual(migrated.settings.ocr_enter_frames, 3)
        self.assertEqual(migrated.settings.ocr_exit_frames, 4)
        self.assertEqual(migrated.settings.opacity, 0.70)
        self.assertEqual(migrated.to_dict()["counter"], original["counter"])
        self.assertEqual(payload, original)

    def test_window_binding_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DataStore(Path(directory))
            data = store.load()
            data.settings.set_window_binding(
                WindowBinding(
                    hwnd=100,
                    pid=42,
                    class_name="NRCGameWindow",
                    process_path=r"C:\Games\NRC-Win64-Shipping.exe",
                    title="洛克王国：世界",
                    width=1920,
                    height=1080,
                )
            )

            store.save(data)
            loaded = store.load()
            binding = loaded.settings.window_binding()

            self.assertIsNotNone(binding)
            self.assertEqual(100, binding.hwnd)
            self.assertEqual(42, binding.pid)
            self.assertEqual("NRCGameWindow", binding.class_name)

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
