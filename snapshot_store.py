from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
import pandas as pd


DB_PATH = Path("data") / "risk_snapshots.sqlite"


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                snapshot_date TEXT PRIMARY KEY,
                regime_label TEXT,
                regime_score REAL,
                regime_confidence REAL,
                trade_allowed INTEGER,
                size_mult REAL,
                transition_alert INTEGER,
                stress_score REAL,
                liquidity_score REAL,
                hyg_lqd_z REAL,
                hy_oas_z REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _to_int_bool(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(bool(value))
    except Exception:
        return None


def upsert_daily_snapshot(
    *,
    snapshot_date: str,
    regime_label: str | None,
    regime_score: Any,
    regime_confidence: Any,
    trade_allowed: Any,
    size_mult: Any,
    transition_alert: Any,
    stress_score: Any = None,
    liquidity_score: Any = None,
    hyg_lqd_z: Any = None,
    hy_oas_z: Any = None,
) -> None:
    ensure_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO daily_snapshots (
                snapshot_date,
                regime_label,
                regime_score,
                regime_confidence,
                trade_allowed,
                size_mult,
                transition_alert,
                stress_score,
                liquidity_score,
                hyg_lqd_z,
                hy_oas_z
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                regime_label = excluded.regime_label,
                regime_score = excluded.regime_score,
                regime_confidence = excluded.regime_confidence,
                trade_allowed = excluded.trade_allowed,
                size_mult = excluded.size_mult,
                transition_alert = excluded.transition_alert,
                stress_score = excluded.stress_score,
                liquidity_score = excluded.liquidity_score,
                hyg_lqd_z = excluded.hyg_lqd_z,
                hy_oas_z = excluded.hy_oas_z
            """,
            (
                snapshot_date,
                regime_label,
                _to_float(regime_score),
                _to_float(regime_confidence),
                _to_int_bool(trade_allowed),
                _to_float(size_mult),
                _to_int_bool(transition_alert),
                _to_float(stress_score),
                _to_float(liquidity_score),
                _to_float(hyg_lqd_z),
                _to_float(hy_oas_z),
            ),
        )
        conn.commit()


def load_snapshot_history() -> pd.DataFrame:
    ensure_db()

    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            """
            SELECT
                snapshot_date,
                regime_label,
                regime_score,
                regime_confidence,
                trade_allowed,
                size_mult,
                transition_alert,
                stress_score,
                liquidity_score,
                hyg_lqd_z,
                hy_oas_z,
                created_at
            FROM daily_snapshots
            ORDER BY snapshot_date
            """,
            conn,
        )

    if not df.empty:
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])

    return df

def backfill_snapshots_from_regime_df(regime_df: pd.DataFrame) -> None:
    if regime_df is None or regime_df.empty:
        return

    hist = regime_df.dropna(how="all").copy()

    for dt, row in hist.iterrows():
        upsert_daily_snapshot(
            snapshot_date=pd.Timestamp(dt).strftime("%Y-%m-%d"),
            regime_label=row.get("regime_label"),
            regime_score=row.get("regime_score"),
            regime_confidence=row.get("regime_confidence"),
            trade_allowed=row.get("trade_allowed"),
            size_mult=row.get("size_mult"),
            transition_alert=row.get("transition_alert"),
            stress_score=row.get("StressScore_z"),
            liquidity_score=row.get("LiquidityScore_z"),
            hyg_lqd_z=row.get("HYG_LQD_z"),
            hy_oas_z=row.get("HY_OAS_z"),
        )