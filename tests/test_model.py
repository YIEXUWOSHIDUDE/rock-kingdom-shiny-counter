import unittest

from shiny_counter.model import CounterState, PityRound


class CounterStateTests(unittest.TestCase):
    def test_round_summary_says_how_many_attempts_before_an_early_result(self) -> None:
        completed = PityRound(
            attempts=37,
            pity_limit=80,
            reached_pity=False,
            source="manual",
        )

        self.assertEqual(completed.summary, "37次出（80次保底，提前43次）")

    def test_round_summary_calls_out_an_exact_pity_result(self) -> None:
        completed = PityRound(
            attempts=80,
            pity_limit=80,
            reached_pity=True,
            source="manual",
        )

        self.assertEqual(completed.summary, "80次出（正好保底）")

    def test_round_summary_explains_attempts_counted_past_pity(self) -> None:
        completed = PityRound(
            attempts=82,
            pity_limit=80,
            reached_pity=True,
            source="manual",
        )

        self.assertEqual(completed.summary, "82次出（超过80次保底2次）")

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
