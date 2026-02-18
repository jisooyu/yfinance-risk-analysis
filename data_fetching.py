# data_fetching.py
import os
import time
import io
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import yfinance as yf
from fredapi import Fred

# ------------------------------------------------------------
# Constants (single source of truth)
# ------------------------------------------------------------
TREASURY_SERIES = ("DGS3MO", "DGS2", "DGS10")  # 3M, 2Y, 10Y

# ------------------------------------------------------------
# HTTP + FRED client
# ------------------------------------------------------------
def _http_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; RenderBot/1.0; +https://render.com)"})
    return s


def _fred_client() -> Fred:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is not set. Add it in Render environment variables.")
    return Fred(api_key=api_key)


_HTTP = _http_session()
_FRED: Fred | None = None
_FRED_CACHE: dict[tuple, pd.DataFrame] = {}
_STOOQ_CACHE: dict[str, pd.Series] = {}


def _fetch_fred(series_list, start, end) -> pd.DataFrame:
    """
    Fetch multiple FRED series using fredapi.
    Returns DataFrame indexed by date with columns=series ids.
    Caches results to avoid repeated API calls.
    """
    global _FRED
    if _FRED is None:
        _FRED = _fred_client()

    start_d = pd.to_datetime(start)
    end_d = pd.to_datetime(end)

    series_list = tuple(series_list)
    key = (series_list, str(start_d.date()), str(end_d.date()))
    if key in _FRED_CACHE:
        return _FRED_CACHE[key].copy()

    out = pd.DataFrame()
    for sid in series_list:
        try:
            s = _FRED.get_series(sid, observation_start=start_d, observation_end=end_d)
            s = pd.to_numeric(s, errors="coerce").dropna()
            s.name = sid
            out = pd.concat([out, s], axis=1)
        except Exception as e:
            raise RuntimeError(f"FRED fetch failed for {sid}: {e}") from e

    out = out.sort_index().ffill()
    _FRED_CACHE[key] = out.copy()
    return out


def fetch_fred_series(series: str, start="2010-01-01", end=None) -> pd.Series:
    if end is None:
        end = pd.Timestamp.today().normalize()
    df = _fetch_fred([series], start, end)
    s = df[series].dropna()
    s.name = series
    return s


def fetch_treasury_yields(start, end, *, ffill: bool = True) -> pd.DataFrame:
    """
    Fetch US Treasury yields from FRED.
    Columns: DGS3MO, DGS2, DGS10
    """
    df = _fetch_fred(TREASURY_SERIES, start, end)
    return df.ffill() if ffill else df


# ------------------------------------------------------------
# Stooq
# ------------------------------------------------------------
def fetch_stooq_daily(symbol: str) -> pd.Series:
    url = "https://stooq.com/q/d/l/"
    params = {"s": symbol, "i": "d"}

    try:
        r = _HTTP.get(url, params=params, timeout=(5, 12))
        r.raise_for_status()
        text = (r.text or "").strip()

        if text.lower().startswith("<!doctype html") or "<html" in text.lower():
            raise RuntimeError("Stooq returned HTML (possible block/rate-limit)")

        df = pd.read_csv(io.StringIO(text))
        if "Date" not in df.columns or "Close" not in df.columns:
            raise ValueError(f"Unexpected Stooq CSV columns for {symbol}: {df.columns.tolist()}")

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")

        s = pd.to_numeric(df["Close"], errors="coerce").dropna()
        s.name = symbol
        _STOOQ_CACHE[symbol] = s
        return s

    except Exception as e:
        print(f"[stooq] {symbol} fetch failed: {type(e).__name__}: {e}")
        if symbol in _STOOQ_CACHE and not _STOOQ_CACHE[symbol].empty:
            return _STOOQ_CACHE[symbol]
        raise RuntimeError(f"Stooq fetch failed for {symbol}: {e}") from e


# ------------------------------------------------------------
# Macro dataset (uses same Treasury fetch)
# ------------------------------------------------------------
def fetch_macro(start="2015-01-01") -> pd.DataFrame:
    """
    Macro-only dataset for spread tabs:
      - US3M/US2Y/US10Y from FRED
      - JP2Y from Stooq (best-effort)
    Returns columns: US3M, US2Y, US10Y, JP2Y
    """
    end = pd.Timestamp.today().normalize()

    us = fetch_treasury_yields(start, end)[list(TREASURY_SERIES)]  # DGS3MO, DGS2, DGS10

    # JP2Y: best-effort
    try:
        jp2y = fetch_stooq_daily("2yjpy.b").loc[pd.Timestamp.today() - pd.Timedelta(days=1100):]
    except Exception:
        jp2y = pd.Series(dtype="float64", name="JP2Y")

    out = pd.concat([us, jp2y], axis=1).rename(columns={
        "DGS3MO": "US3M",
        "DGS2": "US2Y",
        "DGS10": "US10Y",
        "2yjpy.b": "JP2Y",
    }).sort_index().ffill()

    if "JP2Y" not in out.columns:
        out["JP2Y"] = pd.NA

    return out


# ------------------------------------------------------------
# Yahoo fetch helpers
# ------------------------------------------------------------
def _flatten_yf_prices(df_raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """
    Normalize yfinance download output to a simple DataFrame of prices.
    Picks Adj Close first, otherwise Close.
    """
    if df_raw.empty:
        return pd.DataFrame()

    yf_data = pd.DataFrame()

    if isinstance(df_raw.columns, pd.MultiIndex):
        data = None
        for field in ("Adj Close", "Close"):
            for level in (0, 1):
                try:
                    data = df_raw.xs(field, level=level, axis=1)
                    break
                except (KeyError, IndexError):
                    continue
            if data is not None:
                break
        if data is not None:
            yf_data = data
    else:
        for field in ("Adj Close", "Close"):
            if field in df_raw.columns:
                s = df_raw[field]
                yf_data = s.to_frame() if isinstance(s, pd.Series) else s
                break

    if yf_data.empty:
        return pd.DataFrame()

    yf_data = yf_data.ffill().dropna(how="all")
    yf_data = yf_data[[c for c in yf_data.columns if c in tickers]]
    return yf_data


def fetch_data(
    ticker_groups: dict[str, list[str]],
    *,
    retries: int = 2,
    delay: int = 2,
    period: str = "1y",
    include_treasury: bool = True,
) -> pd.DataFrame:
    """
    Main merged dataset:
      - yfinance tickers from ticker_groups
      - optional FRED Treasury yields (DGS3MO, DGS2, DGS10)
    """
    tickers = sum(ticker_groups.values(), [])
    df_raw = pd.DataFrame()

    # 1) Yahoo
    if tickers:
        for _ in range(retries):
            try:
                df_raw = yf.download(
                    tickers,
                    period=period,
                    interval="1d",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                    auto_adjust=False,
                )
                if not df_raw.empty:
                    break
            except Exception:
                pass
            time.sleep(delay)

    yf_data = _flatten_yf_prices(df_raw, tickers)

    # 2) Choose date range for treasury fetch
    if include_treasury:
        if not yf_data.empty:
            start = yf_data.index.min()
            end = yf_data.index.max()
        else:
            end = pd.Timestamp.today().normalize()
            start = end - pd.Timedelta(days=370)

        treas = fetch_treasury_yields(start, end)  # uses TREASURY_SERIES

        # 3) Merge
        data = yf_data.join(treas, how="outer").sort_index()
    else:
        data = yf_data.sort_index()

    data = data.ffill().dropna(how="all")
    return data
