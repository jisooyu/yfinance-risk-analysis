import unittest

import numpy as np
import pandas as pd

from research_metrics import (
    add_forward_returns,
    build_crisis_condition_summary,
    build_crisis_episode_table,
    build_regime_accuracy_table,
    build_regime_timeline_accuracy,
    build_stress_forward_table,
)


class StressResearchMetricsTests(unittest.TestCase):
    def setUp(self):
        index = pd.bdate_range("2020-01-01", periods=80)
        close = pd.Series(np.linspace(100, 140, len(index)), index=index)
        df = pd.DataFrame(
            {
                "close": close,
                "stress_score": 0.5,
                "regime_label": "neutral",
                "regime_confidence": 0.8,
                "liquidity_score": 0.0,
            },
            index=index,
        )

        # Two clusters separated by more than 21 trading observations.
        df.iloc[5:9, df.columns.get_loc("stress_score")] = [2.1, 2.8, 2.4, 2.2]
        df.iloc[5:9, df.columns.get_loc("regime_label")] = "crisis"
        df.iloc[40:43, df.columns.get_loc("stress_score")] = [2.2, 3.1, 2.7]
        df.iloc[40:43, df.columns.get_loc("regime_label")] = "crisis"
        self.df = add_forward_returns(df, horizons=(21,))

    def test_stress_table_includes_hit_rate_and_worst_return(self):
        table = build_stress_forward_table(self.df, horizon=21)

        self.assertIn("hit_rate", table.columns)
        self.assertIn("worst_forward_return", table.columns)
        self.assertGreater(table.loc["Crisis", "observations"], 0)
        self.assertEqual(table.loc["Crisis", "hit_rate"], 1.0)

    def test_crisis_signals_are_grouped_into_non_overlapping_episodes(self):
        episodes = build_crisis_episode_table(self.df, horizon=21)

        self.assertEqual(len(episodes), 2)
        self.assertEqual(
            episodes.iloc[0]["signal_date"],
            self.df.index[6],
        )
        self.assertEqual(
            episodes.iloc[1]["signal_date"],
            self.df.index[41],
        )
        signal_positions = [
            self.df.index.get_loc(date) for date in episodes["signal_date"]
        ]
        self.assertGreater(signal_positions[1] - signal_positions[0], 21)

    def test_condition_summary_separates_daily_and_episode_statistics(self):
        episodes = build_crisis_episode_table(self.df, horizon=21)
        summary = build_crisis_condition_summary(
            self.df,
            episodes,
            horizon=21,
        )

        self.assertEqual(summary["daily_observations"], 7)
        self.assertEqual(summary["episode_count"], 2)
        self.assertEqual(summary["episode_hit_rate"], 1.0)

    def test_regime_accuracy_excludes_unresolved_forward_returns(self):
        table = build_regime_accuracy_table(self.df, horizon=21)
        timeline = build_regime_timeline_accuracy(self.df, horizon=21)

        expected_valid = (
            self.df.loc[self.df["regime_label"] == "neutral", "fwd_21d"]
            .notna()
            .sum()
        )
        self.assertEqual(table.loc["neutral", "observations"], expected_valid)
        self.assertTrue(pd.isna(timeline.loc[self.df.index[-1], "correct"]))


if __name__ == "__main__":
    unittest.main()
