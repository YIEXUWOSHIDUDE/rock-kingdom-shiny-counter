import unittest
from dataclasses import FrozenInstanceError, replace

from shiny_counter.recognition_profile import CURRENT_RECOGNITION_PROFILE
from shiny_counter.storage import AppSettings


class RecognitionProfileTests(unittest.TestCase):
    def test_profile_rejects_empty_or_out_of_frame_regions(self) -> None:
        for region in (
            (0.0, 0.0, 0.0, 0.5),
            (0.0, 0.5, 0.5, 0.2),
            (-0.1, 0.0, 0.5, 0.5),
            (0.0, 0.0, 1.1, 0.5),
            (0.0, 0.0, 0.5),
        ):
            with self.subTest(region=region):
                with self.assertRaisesRegex(ValueError, "region"):
                    replace(CURRENT_RECOGNITION_PROFILE, region=region)

    def test_invalid_recognition_parameters_are_rejected_when_resolved(self) -> None:
        invalid = [
            {"ocr_keywords": []},
            {"ocr_min_confidence": -0.1},
            {"ocr_min_confidence": float("nan")},
            {"ocr_interval_ms": 199},
            {"ocr_enter_frames": 0},
            {"ocr_exit_frames": 0},
        ]
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    AppSettings(**values).recognition_profile()

    def test_profile_detaches_keywords_and_region_from_mutable_inputs(self) -> None:
        keywords = ["独立目标"]
        region = [0.1, 0.2, 0.6, 0.8]

        profile = replace(CURRENT_RECOGNITION_PROFILE, keywords=keywords, region=region)
        keywords.append("外部修改")
        region[0] = 0.5

        self.assertEqual(profile.keywords, ("独立目标",))
        self.assertEqual(profile.region, (0.1, 0.2, 0.6, 0.8))

    def test_unknown_profile_cannot_be_resolved_or_saved_as_current(self) -> None:
        settings = AppSettings(recognition_profile_id="future-season")

        with self.assertRaisesRegex(ValueError, "unknown recognition profile"):
            settings.recognition_profile()
        with self.assertRaisesRegex(ValueError, "unknown recognition profile"):
            settings.validate()

    def test_new_settings_resolve_the_current_s4_recognition_target(self) -> None:
        settings = AppSettings()

        profile = settings.recognition_profile()

        self.assertEqual(profile.profile_id, settings.recognition_profile_id)
        self.assertEqual(profile.name, "S4 星星横幅")
        self.assertEqual(profile.keywords, ("划破天幕坠落",))
        self.assertEqual(profile.region, (0.28, 0.10, 0.72, 0.27))
        self.assertEqual(profile.min_confidence, 0.55)
        self.assertEqual(profile.interval_ms, 200)
        self.assertEqual(profile.enter_frames, 1)
        self.assertEqual(profile.exit_frames, 2)
        self.assertEqual(settings.ocr_keywords, list(profile.keywords))

    def test_resolved_profile_is_an_immutable_snapshot_of_custom_settings(self) -> None:
        settings = AppSettings(
            ocr_keywords=["用户事件"],
            ocr_min_confidence=0.71,
            ocr_interval_ms=900,
            ocr_enter_frames=3,
            ocr_exit_frames=4,
        )

        profile = settings.recognition_profile()
        settings.ocr_keywords.append("后来加入")

        self.assertEqual(profile.keywords, ("用户事件",))
        self.assertEqual(profile.min_confidence, 0.71)
        self.assertEqual(profile.interval_ms, 900)
        self.assertEqual(profile.enter_frames, 3)
        self.assertEqual(profile.exit_frames, 4)
        with self.assertRaises(FrozenInstanceError):
            profile.interval_ms = 200
        self.assertEqual(AppSettings().ocr_keywords, ["划破天幕坠落"])


if __name__ == "__main__":
    unittest.main()
