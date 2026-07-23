import unittest

from shiny_counter.model import CounterState


class CounterStateTests(unittest.TestCase):
    def test_new_counter_defaults_to_eighty_attempt_pity(self) -> None:
        state = CounterState()

        self.assertEqual(state.pity_limit, 80)
        self.assertEqual(state.remaining, 80)

    def test_increment_records_source_score_and_reaches_pity_once(self) -> None:
        state = CounterState(target_name="测试宠物", pity_limit=2)

        self.assertFalse(state.increment(source="manual"))
        self.assertTrue(state.increment(source="auto", score=0.96))
        self.assertFalse(state.increment(source="auto", score=0.97))

        self.assertEqual(state.count, 3)
        self.assertEqual([event.type for event in state.history], [
            "increment",
            "increment",
            "pity_reached",
            "increment",
        ])
        self.assertEqual(state.history[1].score, 0.96)

    def test_undo_and_reset_are_auditable_and_reset_pity_status(self) -> None:
        state = CounterState(target_name="测试宠物", pity_limit=2)
        state.increment(source="auto", score=0.95)
        state.increment(source="auto", score=0.96)

        self.assertTrue(state.undo())
        self.assertEqual(state.count, 1)
        self.assertFalse(state.pity_reached)
        self.assertEqual(state.history[-1].type, "undo")

        state.reset()
        self.assertEqual(state.count, 0)
        self.assertFalse(state.pity_reached)
        self.assertEqual(state.history[-1].type, "reset")

        self.assertFalse(state.undo())

    def test_manual_reset_records_the_completed_round_attempt_count(self) -> None:
        state = CounterState(target_name="测试宠物", pity_limit=3)
        state.increment(source="auto", score=0.95)
        state.increment(source="auto", score=0.96)

        completed = state.reset(source="manual")

        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertEqual(completed.attempts, 2)
        self.assertEqual(completed.pity_limit, 3)
        self.assertFalse(completed.reached_pity)
        self.assertEqual(completed.source, "manual")
        self.assertEqual(state.rounds, [completed])
        self.assertEqual(state.count, 0)


if __name__ == "__main__":
    unittest.main()
