from __future__ import annotations

import pandas as pd
import yfinance as yf


def load_benchmark_prices(ticker: str = "SPY", period: str = "10y") -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="column",
    )

    if df.empty:
        return pd.DataFrame()

    # -----------------------------------
    # Flatten MultiIndex columns if needed
    # -----------------------------------
    if isinstance(df.columns, pd.MultiIndex):
        # try level 0 = OHLCV structure
        if "Close" in df.columns.get_level_values(0):
            out = df.xs("Close", level=0, axis=1).copy()
        elif "Adj Close" in df.columns.get_level_values(0):
            out = df.xs("Adj Close", level=0, axis=1).copy()
        # fallback: try level 1 = OHLCV structure
        elif "Close" in df.columns.get_level_values(1):
            out = df.xs("Close", level=1, axis=1).copy()
        elif "Adj Close" in df.columns.get_level_values(1):
            out = df.xs("Adj Close", level=1, axis=1).copy()
        else:
            raise KeyError(f"Could not find Close/Adj Close in columns: {df.columns}")

        # if still a DataFrame with one ticker column, reduce to Series
        if isinstance(out, pd.DataFrame):
            if out.shape[1] == 1:
                out = out.iloc[:, 0]
            else:
                # if multiple columns somehow remain, take the first one
                out = out.iloc[:, 0]

        out = out.to_frame("close")

    else:
        # normal single-level columns
        if "Close" in df.columns:
            out = df[["Close"]].copy()
        elif "Adj Close" in df.columns:
            out = df[["Adj Close"]].copy()
        else:
            raise KeyError(f"Could not find Close/Adj Close in columns: {df.columns}")

        out.columns = ["close"]

    out.index = pd.to_datetime(out.index).normalize()
    return out.sort_index()


def merge_snapshots_with_prices(
    snapshots: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    if snapshots.empty or prices.empty:
        return pd.DataFrame()

    s = snapshots.copy()
    p = prices.copy()

    s.index = pd.to_datetime(s.index).normalize()
    p.index = pd.to_datetime(p.index).normalize()

    # safety: flatten price columns if they somehow remain MultiIndex
    if isinstance(p.columns, pd.MultiIndex):
        p.columns = [
            "_".join([str(x) for x in col if str(x) != ""]).strip("_")
            for col in p.columns
        ]

    # find close column robustly
    if "close" not in p.columns:
        close_candidates = [c for c in p.columns if str(c).lower().endswith("close") or str(c).lower() == "close"]
        if close_candidates:
            p = p[[close_candidates[0]]].copy()
            p.columns = ["close"]
        else:
            raise KeyError(f"No usable close column found in prices: {list(p.columns)}")

    merged = s.join(p[["close"]], how="inner")
    return merged