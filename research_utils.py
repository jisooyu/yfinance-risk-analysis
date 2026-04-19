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
    )

    if df.empty:
        return pd.DataFrame()

    if "Close" in df.columns:
        out = df[["Close"]].copy()
    else:
        out = df[["Adj Close"]].copy()
        out.columns = ["Close"]

    out = out.rename(columns={"Close": "close"})
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

    return s.join(p[["close"]], how="inner")