from __future__ import annotations

import numpy as np
import pandas as pd


REGIME_ORDER = ["crisis", "risk_off", "caution", "neutral", "risk_on"]
STRESS_BINS = [-np.inf, -1, 0, 1, 2, np.inf]
STRESS_LABELS = ["Very Easy", "Easy", "Normal", "Stress", "Crisis"]


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
        out["expected_up"].isna() | out[fwd_col].isna(),
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
        out["expected_up"].isna() | out[fwd_col].isna(),
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
        bins=STRESS_BINS,
        labels=STRESS_LABELS,
    )

    table = (
        valid.groupby("stress_bucket", observed=False)[fwd_col]
        .agg(
            observations="count",
            hit_rate=lambda s: (s > 0).mean(),
            avg_forward_return="mean",
            median_forward_return="median",
            vol_forward_return="std",
            worst_forward_return="min",
        )
    )
    return table


def build_crisis_episode_table(
    df: pd.DataFrame,
    stress_col: str = "stress_score",
    horizon: int = 21,
    threshold: float = 2.0,
    regime: str = "crisis",
) -> pd.DataFrame:
    """
    Build non-overlapping crisis episodes.

    Signals within ``horizon`` trading observations of the previous signal are
    treated as one episode. The highest-stress signal is the representative
    entry date, so the resulting forward-return windows do not overlap.
    """
    out = df.copy().sort_index()
    fwd_col = f"fwd_{horizon}d"
    if fwd_col not in out.columns:
        out = add_forward_returns(out, horizons=(horizon,))

    required = [stress_col, "regime_label", "close", fwd_col]
    if any(col not in out.columns for col in required):
        return pd.DataFrame()

    out["_row_number"] = np.arange(len(out))
    signals = out.loc[
        (out[stress_col] >= threshold)
        & (out["regime_label"] == regime)
        & out[fwd_col].notna()
    ].copy()
    if signals.empty:
        return pd.DataFrame()

    row_gap = signals["_row_number"].diff()
    new_episode = row_gap.gt(horizon)
    new_episode.iloc[0] = True
    signals["_episode_id"] = new_episode.cumsum()

    rows = []
    for episode_id, episode in signals.groupby("_episode_id"):
        representative_date = episode[stress_col].idxmax()
        representative = out.loc[representative_date]
        representative_pos = int(representative["_row_number"])
        forward_path = out.iloc[
            representative_pos : representative_pos + horizon + 1
        ]["close"].dropna()

        if len(forward_path) <= horizon:
            continue

        entry_close = float(forward_path.iloc[0])
        path_returns = forward_path / entry_close - 1.0
        forward_return = float(representative[fwd_col])

        rows.append(
            {
                "episode": int(episode_id),
                "start_date": episode.index.min(),
                "end_date": episode.index.max(),
                "signal_date": representative_date,
                "signal_observations": int(len(episode)),
                "peak_stress": float(representative[stress_col]),
                "forward_return": forward_return,
                "max_drawdown": float(path_returns.min()),
                "up": forward_return > 0,
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index("episode")


def build_crisis_condition_summary(
    df: pd.DataFrame,
    episode_df: pd.DataFrame,
    stress_col: str = "stress_score",
    horizon: int = 21,
    threshold: float = 2.0,
    regime: str = "crisis",
) -> dict[str, float | int]:
    fwd_col = f"fwd_{horizon}d"
    valid = df.dropna(subset=[stress_col, "regime_label", fwd_col]).copy()
    target = (valid[stress_col] >= threshold) & (valid["regime_label"] == regime)

    target_returns = valid.loc[target, fwd_col]
    other_returns = valid.loc[~target, fwd_col]

    return {
        "daily_observations": int(len(target_returns)),
        "daily_hit_rate": float((target_returns > 0).mean()) if len(target_returns) else np.nan,
        "daily_avg_return": float(target_returns.mean()) if len(target_returns) else np.nan,
        "other_hit_rate": float((other_returns > 0).mean()) if len(other_returns) else np.nan,
        "episode_count": int(len(episode_df)),
        "episode_hit_rate": float(episode_df["up"].mean()) if not episode_df.empty else np.nan,
        "episode_avg_return": (
            float(episode_df["forward_return"].mean()) if not episode_df.empty else np.nan
        ),
        "episode_worst_return": (
            float(episode_df["forward_return"].min()) if not episode_df.empty else np.nan
        ),
        "episode_worst_drawdown": (
            float(episode_df["max_drawdown"].min()) if not episode_df.empty else np.nan
        ),
    }


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
