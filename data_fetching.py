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
# Constants
# ------------------------------------------------------------
TREASURY_SERIES = (
    "DGS3MO",
    "DGS2",
    "DGS10",
    "BAMLH0A0HYM2",
    "WRMFNS",
    "RRPONTSYD",
    "M2SL",
    "TOTRESNS",
    "WRESBAL",
)

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
    s.headers.update(
        {"User-Agent": "Mozilla/5.0 (compatible; RenderBot/1.0; +https://render.com)"}
    )
    return s


def _fred_client() -> Fred:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is not set. Add it in environment variables.")
    return Fred(api_key=api_key)


_HTTP = _http_session()
_FRED: Fred | None = None
_FRED_CACHE: dict[tuple, pd.DataFrame] = {}
_STOOQ_CACHE: dict[str, pd.Series] = {}


def _fetch_fred(series_list, start, end) -> pd.DataFrame:
    """
    Fetch multiple FRED series using fredapi.
    Returns a DataFrame indexed by date with columns = raw FRED series ids.
    """
    global _FRED
    if _FRED is None:
        _FRED = _fred_client()

    start_d = pd.to_datetime(start).normalize()
    end_d = pd.to_datetime(end).normalize()

    series_list = tuple(series_list)
    key = (series_list, str(start_d.date()), str(end_d.date()))
    if key in _FRED_CACHE:
        return _FRED_CACHE[key].copy()

    out = pd.DataFrame()

    for sid in series_list:
        try:
            s = _FRED.get_series(
                sid,
                observation_start=start_d,
                observation_end=end_d,
            )
            s = pd.to_numeric(s, errors="coerce").dropna()
            s.index = pd.to_datetime(s.index, errors="coerce")
            s = s[~s.index.isna()]
            s = s[~s.index.duplicated(keep="last")].sort_index()
            s.name = sid
            out = pd.concat([out, s], axis=1)
        except Exception as e:
            raise RuntimeError(f"FRED fetch failed for {sid}: {e}") from e

    out = out.sort_index()
    _FRED_CACHE[key] = out.copy()
    return out


def fetch_treasury_yields(start, end, *, ffill: bool = True) -> pd.DataFrame:
    """
    Fetch FRED treasury / liquidity series and rename them into app-friendly names.
    """
    df = _fetch_fred(TREASURY_SERIES, start, end)

    df = df.rename(
        columns={
            "DGS3MO": "US3M",
            "DGS2": "US2Y",
            "DGS10": "US10Y",
            "BAMLH0A0HYM2": "HY_OAS",
            "WRMFNS": "MMF",
            "RRPONTSYD": "RRP",
            "M2SL": "M2",
            "TOTRESNS": "RESERVES",
            "WRESBAL": "RESERVES_PROXY",
        }
    )

    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].copy()

    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)

    df = df[~df.index.duplicated(keep="last")].sort_index()

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

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
            raise ValueError(
                f"Unexpected Stooq CSV columns for {symbol}: {df.columns.tolist()}"
            )

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
# Yahoo helpers
# ------------------------------------------------------------
def _flatten_yf_prices(df_raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """
    Normalize yfinance download output to a simple Date x Ticker price DataFrame.
    Prefers Adj Close, otherwise Close.
    """
    if df_raw.empty:
        return pd.DataFrame()

    yf_data = pd.DataFrame()

    if isinstance(df_raw.columns, pd.MultiIndex):
        data = None

        for field in ("Adj Close", "Close"):
            try:
                # common case: columns = (ticker, field)
                data = df_raw.xs(field, level=1, axis=1)
                break
            except (KeyError, IndexError):
                pass

            try:
                # fallback: columns = (field, ticker)
                data = df_raw.xs(field, level=0, axis=1)
                break
            except (KeyError, IndexError):
                pass

        if data is not None:
            yf_data = data.copy()

    else:
        for field in ("Adj Close", "Close"):
            if field in df_raw.columns:
                s = df_raw[field]
                yf_data = s.to_frame() if isinstance(s, pd.Series) else s.copy()
                break

    if yf_data.empty:
        return pd.DataFrame()

    existing = [c for c in yf_data.columns if c in tickers]
    yf_data = yf_data[existing].copy()

    yf_data.index = pd.to_datetime(yf_data.index, errors="coerce")
    yf_data = yf_data[~yf_data.index.isna()].copy()

    if getattr(yf_data.index, "tz", None) is not None:
        yf_data.index = yf_data.index.tz_localize(None)

    yf_data = yf_data[~yf_data.index.duplicated(keep="last")].sort_index()

    for col in yf_data.columns:
        yf_data[col] = pd.to_numeric(yf_data[col], errors="coerce")

    return yf_data.ffill().dropna(how="all")


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
      - Yahoo Finance prices
      - optional FRED treasury/liquidity data

    Important:
      FRED end-date is NOT capped by Yahoo's last trading date.
    """
    tickers = list(dict.fromkeys(sum(ticker_groups.values(), [])))
    df_raw = pd.DataFrame()

    # 1) Yahoo
    if tickers:
        for _ in range(retries):
            try:
                df_raw = yf.download(
                    tickers=tickers,
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

    # 2) FRED
    if include_treasury:
        if not yf_data.empty:
            start = yf_data.index.min()
        else:
            start = pd.Timestamp.today().normalize() - pd.Timedelta(days=370)

        # 핵심 수정:
        # Yahoo 마지막 거래일로 FRED를 자르지 않는다.
        end = pd.Timestamp.today().normalize()

        treas = fetch_treasury_yields(start, end)

        treas = treas.copy()
        treas.index = pd.to_datetime(treas.index, errors="coerce")
        treas = treas[~treas.index.isna()].copy()

        if getattr(treas.index, "tz", None) is not None:
            treas.index = treas.index.tz_localize(None)

        treas = treas[~treas.index.duplicated(keep="last")].sort_index()

        data = yf_data.join(treas, how="outer")
    else:
        data = yf_data.copy()

    # final normalization
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[~data.index.isna()].copy()

    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)

    data = data[~data.index.duplicated(keep="last")].sort_index()

    for col in data.columns:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    return data.ffill().dropna(how="all")


# ------------------------------------------------------------
# JP proxy from FRED
# ------------------------------------------------------------
def fetch_jp_proxy(start, end):
    fred = _fred_client()
    s = fred.get_series(
        "IR3TIB01JPM156N",
        observation_start=pd.to_datetime(start),
        observation_end=pd.to_datetime(end),
    )
    s = pd.to_numeric(s, errors="coerce").dropna()
    s.name = "JP2Y"
    return s


# ------------------------------------------------------------
# Macro dataset
# ------------------------------------------------------------
def fetch_macro(start="2015-01-01") -> pd.DataFrame:
    end = pd.Timestamp.today().normalize()

    us = fetch_treasury_yields(start, end)[["US3M", "US2Y", "US10Y"]]

    try:
        jp2y = fetch_jp_proxy(start, end)
    except Exception as e:
        print(f"JP proxy fetch failed: {type(e).__name__}: {e}")
        jp2y = pd.Series(dtype="float64", name="JP2Y")

    out = pd.concat([us, jp2y], axis=1).sort_index().ffill()
    return out