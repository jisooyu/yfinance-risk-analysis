from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
DB_PATH = Path("data") / "risk_snapshots.sqlite"
DEFAULT_PRICE_COL = "close"


# ------------------------------------------------------------
# Data structures
# ------------------------------------------------------------
@dataclass
class BacktestResult:
    summary: pd.DataFrame
    history: pd.DataFrame
    trades: pd.DataFrame


# ------------------------------------------------------------
# SQLite readers
# ------------------------------------------------------------
def load_daily_snapshots(db_path: str | Path = DB_PATH) -> pd.DataFrame:
    """
    Load the daily_snapshots table created from your Render logging step.

    Expected columns include fields such as:
    - snapshot_date
    - regime_label
    - regime_score
    - regime_confidence
    - trade_allowed
    - size_mult
    - transition_alert
    - stress_score
    - liquidity_score
    - hyg_lqd_z
    - hy_oas_z
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT * FROM daily_snapshots ORDER BY snapshot_date",
            conn,
        )

    if df.empty:
        return df

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df = df.sort_values("snapshot_date").set_index("snapshot_date")

    # Normalize booleans that may be stored as 0/1 or strings.
    for col in ["trade_allowed", "transition_alert"]:
        if col in df.columns:
            df[col] = _normalize_bool_series(df[col])

    return df


# ------------------------------------------------------------
# Optional price loader
# ------------------------------------------------------------
def load_price_csv(
    csv_path: str | Path,
    date_col: str = "Date",
    price_col: str = DEFAULT_PRICE_COL,
) -> pd.DataFrame:
    """
    Load a price CSV for the asset you want to test against.

    Example expected columns:
    Date, close
    2024-01-02, 476.32
    ...
    """
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.rename(columns={date_col: "date", price_col: "close"})
    df = df[["date", "close"]].dropna().sort_values("date").set_index("date")
    return df


# ------------------------------------------------------------
# Signal rules
# ------------------------------------------------------------
def default_long_risk_on_rule(df: pd.DataFrame) -> pd.Series:
    """
    A sensible first rule using your logged fields.

    Long when:
    - trade_allowed is True
    - stress_score < 1.0
    - liquidity_score > 0.0
    - hy_oas_z < 1.0
    - hyg_lqd_z < 1.0

    Position size = size_mult clipped to [0, 1].
    """
    required = [
        "trade_allowed",
        "size_mult",
        "stress_score",
        "liquidity_score",
        "hy_oas_z",
        "hyg_lqd_z",
    ]
    _require_columns(df, required)

    cond = (
        df["trade_allowed"].fillna(False)
        & (df["stress_score"] < 1.0)
        & (df["liquidity_score"] > 0.0)
        & (df["hy_oas_z"] < 1.0)
        & (df["hyg_lqd_z"] < 1.0)
    )

    size = df["size_mult"].clip(lower=0.0, upper=1.0).fillna(0.0)
    signal = np.where(cond, size, 0.0)
    return pd.Series(signal, index=df.index, name="position")


# ------------------------------------------------------------
# Core backtest engine
# ------------------------------------------------------------
def backtest_from_snapshots(
    snapshots: pd.DataFrame,
    price_df: pd.DataFrame,
    signal_func: Callable[[pd.DataFrame], pd.Series] = default_long_risk_on_rule,
    *,
    price_col: str = "close",
    trading_days: int = 252,
    cost_bps: float = 5.0,
    max_leverage: float = 1.0,
    lag_signal_days: int = 1,
) -> BacktestResult:
    """
    Backtest a signal built from SQLite snapshots against an asset price series.

    Parameters
    ----------
    snapshots:
        DataFrame indexed by snapshot_date.
    price_df:
        DataFrame indexed by date with a close column.
    signal_func:
        Function returning a position series in [0, max_leverage].
    cost_bps:
        Transaction cost in basis points per unit turnover.
    lag_signal_days:
        1 means today's signal trades tomorrow.
    """
    if snapshots.empty:
        raise ValueError("snapshots is empty")
    if price_df.empty:
        raise ValueError("price_df is empty")
    if price_col not in price_df.columns:
        raise KeyError(f"Missing price column: {price_col}")

    snapshots = snapshots.copy().sort_index()
    price_df = price_df.copy().sort_index()

    merged = _merge_snapshots_with_prices(snapshots, price_df, price_col=price_col)
    merged["asset_return"] = merged[price_col].pct_change().fillna(0.0)

    raw_signal = signal_func(merged)
    merged["raw_position"] = raw_signal.clip(lower=0.0, upper=max_leverage).fillna(0.0)
    merged["position"] = merged["raw_position"].shift(lag_signal_days).fillna(0.0)

    turnover = (merged["position"] - merged["position"].shift(1).fillna(0.0)).abs()
    merged["turnover"] = turnover
    merged["cost"] = turnover * (cost_bps / 10000.0)
    merged["strategy_return"] = (merged["position"] * merged["asset_return"]) - merged["cost"]

    merged["asset_equity"] = (1.0 + merged["asset_return"]).cumprod()
    merged["strategy_equity"] = (1.0 + merged["strategy_return"]).cumprod()

    merged["strategy_peak"] = merged["strategy_equity"].cummax()
    merged["strategy_drawdown"] = (merged["strategy_equity"] / merged["strategy_peak"]) - 1.0

    summary = _build_summary(merged, trading_days=trading_days)
    trades = _extract_trade_log(merged)

    return BacktestResult(summary=summary, history=merged, trades=trades)


# ------------------------------------------------------------
# Forward-return evaluator
# ------------------------------------------------------------
def evaluate_forward_returns(
    snapshots: pd.DataFrame,
    price_df: pd.DataFrame,
    *,
    price_col: str = "close",
    horizons: Iterable[int] = (5, 10, 21, 63),
    bucket_col: str = "regime_label",
) -> dict[str, pd.DataFrame]:
    """
    Evaluate average forward returns by regime or any bucket column.

    Example use:
    - What is SPY's average 21-day forward return when regime_label == 'risk_on'?
    - What happens after transition_alert == True?
    """
    merged = _merge_snapshots_with_prices(snapshots, price_df, price_col=price_col)
    out: dict[str, pd.DataFrame] = {}

    for h in horizons:
        col = f"fwd_{h}d_return"
        merged[col] = merged[price_col].shift(-h) / merged[price_col] - 1.0

        if bucket_col in merged.columns:
            grouped = (
                merged.groupby(bucket_col)[col]
                .agg(["count", "mean", "median", "std"])
                .sort_values("mean", ascending=False)
            )
            out[col] = grouped
        else:
            out[col] = merged[[col]].describe().T

    return out


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------
def _merge_snapshots_with_prices(
    snapshots: pd.DataFrame,
    price_df: pd.DataFrame,
    *,
    price_col: str,
) -> pd.DataFrame:
    s = snapshots.copy()
    p = price_df.copy()

    s.index = pd.to_datetime(s.index).normalize()
    p.index = pd.to_datetime(p.index).normalize()

    merged = s.join(p[[price_col]], how="inner")
    if merged.empty:
        raise ValueError(
            "No overlapping dates between snapshots and price data. "
            "Make sure both indices are daily dates."
        )
    return merged



def _normalize_bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s

    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        1: True,
        0: False,
        True: True,
        False: False,
    }
    return s.map(lambda x: mapping.get(str(x).strip().lower(), False) if isinstance(x, str) else mapping.get(x, False))



def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")



def _safe_sharpe(returns: pd.Series, trading_days: int) -> float:
    vol = returns.std(ddof=0)
    if vol == 0 or pd.isna(vol):
        return np.nan
    return math.sqrt(trading_days) * returns.mean() / vol



def _safe_cagr(equity: pd.Series, trading_days: int) -> float:
    if equity.empty or len(equity) < 2:
        return np.nan
    total_return = equity.iloc[-1] / equity.iloc[0]
    years = len(equity) / trading_days
    if years <= 0 or total_return <= 0:
        return np.nan
    return total_return ** (1 / years) - 1



def _build_summary(history: pd.DataFrame, trading_days: int) -> pd.DataFrame:
    strategy_ret = history["strategy_return"]
    asset_ret = history["asset_return"]

    summary = {
        "strategy_total_return": history["strategy_equity"].iloc[-1] - 1.0,
        "strategy_cagr": _safe_cagr(history["strategy_equity"], trading_days),
        "strategy_sharpe": _safe_sharpe(strategy_ret, trading_days),
        "strategy_max_drawdown": history["strategy_drawdown"].min(),
        "strategy_avg_daily_return": strategy_ret.mean(),
        "strategy_daily_vol": strategy_ret.std(ddof=0),
        "asset_total_return": history["asset_equity"].iloc[-1] - 1.0,
        "asset_cagr": _safe_cagr(history["asset_equity"], trading_days),
        "asset_sharpe": _safe_sharpe(asset_ret, trading_days),
        "days_in_market": (history["position"] > 0).sum(),
        "avg_position": history["position"].mean(),
        "avg_turnover": history["turnover"].mean(),
        "num_position_changes": int((history["turnover"] > 0).sum()),
    }

    return pd.DataFrame([summary]).T.rename(columns={0: "value"})



def _extract_trade_log(history: pd.DataFrame) -> pd.DataFrame:
    h = history.copy()
    h["prev_pos"] = h["position"].shift(1).fillna(0.0)

    entries = h[(h["prev_pos"] == 0.0) & (h["position"] > 0.0)].copy()
    exits = h[(h["prev_pos"] > 0.0) & (h["position"] == 0.0)].copy()

    trades = []
    exit_iter = exits.iterrows()
    current_exit = next(exit_iter, None)

    for entry_dt, entry_row in entries.iterrows():
        while current_exit is not None and current_exit[0] <= entry_dt:
            current_exit = next(exit_iter, None)

        if current_exit is None:
            exit_dt = h.index[-1]
            exit_row = h.iloc[-1]
        else:
            exit_dt, exit_row = current_exit

        trades.append(
            {
                "entry_date": entry_dt,
                "exit_date": exit_dt,
                "entry_price": entry_row.get("close", np.nan),
                "exit_price": exit_row.get("close", np.nan),
                "entry_position": entry_row.get("position", np.nan),
                "holding_days": (exit_dt - entry_dt).days,
                "gross_return": (
                    exit_row.get("close", np.nan) / entry_row.get("close", np.nan) - 1.0
                    if entry_row.get("close", np.nan) not in [0, np.nan]
                    else np.nan
                ),
            }
        )

    trades_df = pd.DataFrame(trades)
    return trades_df


# ------------------------------------------------------------
# Example strategies you can swap in
# ------------------------------------------------------------
def conservative_regime_rule(df: pd.DataFrame) -> pd.Series:
    """
    More selective than the default rule.
    """
    required = [
        "trade_allowed",
        "regime_label",
        "regime_confidence",
        "stress_score",
        "liquidity_score",
        "hy_oas_z",
        "size_mult",
    ]
    _require_columns(df, required)

    cond = (
        df["trade_allowed"].fillna(False)
        & (df["regime_label"].isin(["risk_on", "neutral"]))
        & (df["regime_confidence"] >= 0.40)
        & (df["stress_score"] < 0.75)
        & (df["liquidity_score"] > 0.25)
        & (df["hy_oas_z"] < 0.75)
    )

    size = df["size_mult"].clip(0.0, 1.0).fillna(0.0)
    return pd.Series(np.where(cond, size, 0.0), index=df.index, name="position")



def transition_avoidance_rule(df: pd.DataFrame) -> pd.Series:
    """
    Stay invested only when transition risk is low.
    """
    required = [
        "trade_allowed",
        "transition_alert",
        "stress_score",
        "liquidity_score",
        "size_mult",
    ]
    _require_columns(df, required)

    cond = (
        df["trade_allowed"].fillna(False)
        & (~df["transition_alert"].fillna(False))
        & (df["stress_score"] < 1.0)
        & (df["liquidity_score"] > 0.0)
    )
    size = df["size_mult"].clip(0.0, 1.0).fillna(0.0)
    return pd.Series(np.where(cond, size, 0.0), index=df.index, name="position")


# ------------------------------------------------------------
# Example run
# ------------------------------------------------------------
def example_run() -> None:
    """
    Minimal example. Replace the CSV path with your asset file.
    Example asset choices:
    - SPY for broad market timing
    - QQQ for tech / AI regime sensitivity
    - SOXX or SMH for semiconductor sensitivity
    """
    snapshots = load_daily_snapshots("data/risk_snapshots.sqlite")
    price_df = load_price_csv("spy_daily.csv", date_col="Date", price_col="Close")

    result = backtest_from_snapshots(
        snapshots=snapshots,
        price_df=price_df,
        signal_func=default_long_risk_on_rule,
        cost_bps=5.0,
        lag_signal_days=1,
    )

    print("\n=== Summary ===")
    print(result.summary)

    print("\n=== Trade Log (head) ===")
    print(result.trades.head())

    print("\n=== History (tail) ===")
    print(result.history.tail())


if __name__ == "__main__":
    example_run()
