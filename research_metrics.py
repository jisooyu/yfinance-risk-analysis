from __future__ import annotations

import numpy as np
import pandas as pd


REGIME_ORDER = ["crisis", "risk_off", "caution", "neutral", "risk_on"]


def add_forward_returns(df: pd.DataFrame, horizons=(5, 10, 21, 63)) -> pd.DataFrame:
    out = df.copy()
    for h in horizons:
        out[f"fwd_{h}d"] = out["close"].shift(-h) / out["close"] - 1.0
    return out


def build_regime_accuracy_table(df: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    """
    Measures whether the regime label lined up with the sign of forward returns.
    Very simple first version:

    favorable if:
      risk_on / neutral / caution -> forward return > 0
      risk_off / crisis           -> forward return <= 0
    """
    out = df.copy()
    fwd_col = f"fwd_{horizon}d"
    if fwd_col not in out.columns:
        out = add_forward_returns(out, horizons=(horizon,))

    def expected_up(label: str) -> bool | None:
        if pd.isna(label):
            return None
        if label in ["risk_on", "neutral", "caution"]:
            return True
        if label in ["risk_off", "crisis"]:
            return False
        return None

    out["expected_up"] = out["regime_label"].map(expected_up)
    out["actual_up"] = out[fwd_col] > 0
    out["correct"] = np.where(
        out["expected_up"].isna(),
        np.nan,
        out["expected_up"] == out["actual_up"],
    )

    grouped = (
        out.groupby("regime_label")
        .agg(
            observations=("correct", "count"),
            hit_rate=("correct", "mean"),
            avg_forward_return=(fwd_col, "mean"),
            median_forward_return=(fwd_col, "median"),
            avg_confidence=("regime_confidence", "mean"),
            avg_stress=("stress_score", "mean"),
            avg_liquidity=("liquidity_score", "mean"),
        )
        .reindex(REGIME_ORDER)
    )

    return grouped


def build_regime_timeline_accuracy(df: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    out = df.copy()
    fwd_col = f"fwd_{horizon}d"
    if fwd_col not in out.columns:
        out = add_forward_returns(out, horizons=(horizon,))

    def expected_up(label: str) -> bool | None:
        if pd.isna(label):
            return None
        if label in ["risk_on", "neutral", "caution"]:
            return True
        if label in ["risk_off", "crisis"]:
            return False
        return None

    out["expected_up"] = out["regime_label"].map(expected_up)
    out["actual_up"] = out[fwd_col] > 0
    out["correct"] = np.where(
        out["expected_up"].isna(),
        np.nan,
        out["expected_up"] == out["actual_up"],
    )

    out["rolling_hit_rate_60"] = out["correct"].rolling(60, min_periods=20).mean()
    return out


def build_stress_forward_table(
    df: pd.DataFrame,
    stress_col: str = "stress_score",
    horizon: int = 21,
) -> pd.DataFrame:
    out = df.copy()
    fwd_col = f"fwd_{horizon}d"
    if fwd_col not in out.columns:
        out = add_forward_returns(out, horizons=(horizon,))

    valid = out[[stress_col, fwd_col]].dropna().copy()
    if valid.empty:
        return pd.DataFrame()

    valid["stress_bucket"] = pd.cut(
        valid[stress_col],
        bins=[-999, -1, 0, 1, 2, 999],
        labels=["Very Easy", "Easy", "Normal", "Stress", "Crisis"],
    )

    table = (
        valid.groupby("stress_bucket", observed=False)[fwd_col]
        .agg(["count", "mean", "median", "std"])
        .rename(
            columns={
                "count": "observations",
                "mean": "avg_forward_return",
                "median": "median_forward_return",
                "std": "vol_forward_return",
            }
        )
    )
    return table


def build_stress_scatter_df(
    df: pd.DataFrame,
    stress_col: str = "stress_score",
    horizon: int = 21,
) -> pd.DataFrame:
    out = df.copy()
    fwd_col = f"fwd_{horizon}d"
    if fwd_col not in out.columns:
        out = add_forward_returns(out, horizons=(horizon,))

    cols = [stress_col, fwd_col, "regime_label", "regime_confidence"]
    cols = [c for c in cols if c in out.columns]
    return out[cols].dropna()