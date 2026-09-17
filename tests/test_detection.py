import unittest

from shiny_counter.detection import PresenceGate


class PresenceGateTests(unittest.TestCase):
    def test_uncertain_evidence_neither_counts_nor_rearms(self):
        gate = PresenceGate(enter_frames=1, exit_frames=2)
        self.assertEqual(
            [gate.observe(present) for present in [None, True, None, None, True, False, False, True]],
            [False, True, False, False, False, False, False, True],
        )

    def test_ocr_phrase_counts_once_until_phrase_disappears(self) -> None:
        gate = PresenceGate(enter_frames=2, exit_frames=2)

        self.assertEqual(
            [gate.observe(present) for present in [True, True, True, False, False, True, True]],
            [False, True, False, False, False, False, True],
        )


if __name__ == "__main__":
    unittest.main()
