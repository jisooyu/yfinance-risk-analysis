import unittest

import pandas as pd

from callbacks import (
    build_recent_change_table,
    build_recent_regime_table,
    build_recent_stress_table,
    build_recent_volatility_table,
)


class VolatilityTableTests(unittest.TestCase):
    def test_table_contains_recent_values_and_daily_changes(self):
        index = pd.to_datetime(["2024-01-02", "2025-01-02", "2025-01-03"])
        raw = pd.DataFrame(
            {
                "^VIX": [10.0, 20.0, 18.0],
                "^VXN": [15.0, 30.0, 33.0],
            },
            index=index,
        )

        component = build_recent_volatility_table(raw, months=3)
        rendered = str(component.to_plotly_json())

        self.assertNotIn("2024-01-02", rendered)
        self.assertIn("2025-01-02", rendered)
        self.assertIn("2025-01-03", rendered)
        self.assertIn("-2.00", rendered)
        self.assertIn("+3.00", rendered)
        self.assertIn("VIX Δ%", rendered)
        self.assertIn("VXN Δ%", rendered)

    def test_stress_table_contains_recent_changes_and_buckets(self):
        index = pd.to_datetime(
            ["2024-01-02", "2025-01-02", "2025-01-03", "2025-01-06"]
        )
        stress = pd.DataFrame(
            {"Stress Score": [-1.5, -0.5, 0.5, 2.5]},
            index=index,
        )

        component = build_recent_stress_table(stress, months=3)
        rendered = str(component.to_plotly_json())

        self.assertNotIn("2024-01-02", rendered)
        self.assertIn("2025-01-02", rendered)
        self.assertIn("+1.000", rendered)
        self.assertIn("Easy", rendered)
        self.assertIn("Normal", rendered)
        self.assertIn("Crisis", rendered)
        self.assertIn("Stress Score", rendered)

    def test_generic_recent_change_table_uses_three_month_window(self):
        index = pd.to_datetime(["2024-09-30", "2025-01-01", "2025-01-02"])
        df = pd.DataFrame({"A": [1.0, 2.0, 2.5]}, index=index)

        component = build_recent_change_table(
            df,
            "Recent 3-Month Example",
            months=3,
        )
        rendered = str(component.to_plotly_json())

        self.assertNotIn("2024-09-30", rendered)
        self.assertIn("2025-01-01", rendered)
        self.assertIn("2025-01-02", rendered)
        self.assertIn("+0.50", rendered)

    def test_regime_table_contains_recent_regime_metrics(self):
        index = pd.to_datetime(["2024-09-30", "2025-01-01", "2025-01-02"])
        regime = pd.DataFrame(
            {
                "regime_label": ["risk_on", "neutral", "crisis"],
                "regime_score": [1.0, 0.5, -2.0],
                "regime_confidence": [0.7, 0.8, 0.9],
                "size_mult": [1.0, 0.7, 0.0],
                "trade_allowed": [True, True, False],
                "transition_alert": [False, False, True],
            },
            index=index,
        )

        component = build_recent_regime_table(regime, months=3)
        rendered = str(component.to_plotly_json())

        self.assertNotIn("2024-09-30", rendered)
        self.assertIn("2025-01-01", rendered)
        self.assertIn("2025-01-02", rendered)
        self.assertIn("Crisis", rendered)
        self.assertIn("Score Δ", rendered)
        self.assertIn("Trade Allowed", rendered)


if __name__ == "__main__":
    unittest.main()
