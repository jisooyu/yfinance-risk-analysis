from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd


DB_PATH = Path(os.getenv("SQLITE_PATH", "data/risk_snapshots.sqlite"))


def load_snapshot_history(db_path: str | Path = DB_PATH) -> pd.DataFrame:
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame()

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM daily_snapshots
            ORDER BY snapshot_date
            """,
            conn,
        )

    if df.empty:
        return df

    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df = df.sort_values("snapshot_date").set_index("snapshot_date")

    for col in ["trade_allowed", "transition_alert"]:
        if col in df.columns:
            df[col] = df[col].astype("float").fillna(0).astype(int).astype(bool)

    return df