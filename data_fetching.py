import os
import time
import io
from pathlib import Path
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
"""
재사용할 수 있는 http session 을 만들고 configure하는 메쏘드
"""
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
_FRED_SERIES_CACHE: dict[str, pd.Series] = {}
_FRED_LAST_CALL = 0.0
_STOOQ_CACHE: dict[str, pd.Series] = {}
_CACHE_DIR = Path(__file__).resolve().parent / "data" / "fred_cache"
_FRED_MIN_INTERVAL_SEC = 0.8
_FRED_RETRIES = 3


def _fred_cache_path(series_id: str) -> Path:
    safe_id = "".join(ch for ch in series_id if ch.isalnum() or ch in ("_", "-"))
    return _CACHE_DIR / f"{safe_id}.csv"


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


def _normalize_fred_series(s: pd.Series, sid: str) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").dropna()
    s.index = pd.to_datetime(s.index, errors="coerce")
    s = s[~s.index.isna()]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = sid
    return s


def _load_fred_series_cache(sid: str) -> pd.Series:
    if sid in _FRED_SERIES_CACHE:
        return _FRED_SERIES_CACHE[sid].copy()

    path = _fred_cache_path(sid)
    if not path.exists():
        return pd.Series(dtype="float64", name=sid)

    try:
        df = pd.read_csv(path, parse_dates=["Date"])
        if "Date" not in df.columns or sid not in df.columns:
            return pd.Series(dtype="float64", name=sid)
        s = df.set_index("Date")[sid]
        s = _normalize_fred_series(s, sid)
        _FRED_SERIES_CACHE[sid] = s.copy()
        return s
    except Exception as e:
        print(f"[fred] Could not read cache for {sid}: {type(e).__name__}: {e}")
        return pd.Series(dtype="float64", name=sid)


def _save_fred_series_cache(sid: str, s: pd.Series) -> None:
    if s.empty:
        return

    cached = _load_fred_series_cache(sid)
    merged = pd.concat([cached, s]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged.name = sid

    _FRED_SERIES_CACHE[sid] = merged.copy()

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        merged.rename_axis("Date").to_frame().to_csv(_fred_cache_path(sid))
    except Exception as e:
        print(f"[fred] Could not write cache for {sid}: {type(e).__name__}: {e}")


def _cached_fred_slice(sid: str, start_d: pd.Timestamp, end_d: pd.Timestamp) -> pd.Series:
    cached = _load_fred_series_cache(sid)
    if cached.empty:
        return cached
    return cached.loc[(cached.index >= start_d) & (cached.index <= end_d)]


def _get_fred_series_with_retry(sid: str, start_d: pd.Timestamp, end_d: pd.Timestamp) -> pd.Series:
    global _FRED_LAST_CALL

    last_error: Exception | None = None
    for attempt in range(_FRED_RETRIES):
        elapsed = time.monotonic() - _FRED_LAST_CALL
        if elapsed < _FRED_MIN_INTERVAL_SEC:
            time.sleep(_FRED_MIN_INTERVAL_SEC - elapsed)

        try:
            s = _FRED.get_series(
                sid,
                observation_start=start_d,
                observation_end=end_d,
            )
            _FRED_LAST_CALL = time.monotonic()
            s = _normalize_fred_series(s, sid)
            _save_fred_series_cache(sid, s)
            return s
        except Exception as e:
            _FRED_LAST_CALL = time.monotonic()
            last_error = e
            if not _is_rate_limit_error(e) or attempt == _FRED_RETRIES - 1:
                break
            time.sleep((2 ** attempt) * 5)

    cached = _cached_fred_slice(sid, start_d, end_d)
    if not cached.empty:
        print(
            f"[fred] {sid} fetch failed ({type(last_error).__name__}: {last_error}); "
            "using cached data."
        )
        return cached

    raise RuntimeError(f"FRED fetch failed for {sid}: {last_error}") from last_error

def _fetch_fred(series_list, start, end) -> pd.DataFrame:
    """
    Fetch multiple FRED series using fredapi.
    Returns a DataFrame indexed by date with columns = raw FRED series ids.
    """
    global _FRED # to prevent creating _FRED client multiple times
    if _FRED is None:
        _FRED = _fred_client()

    start_d = pd.to_datetime(start).normalize()
    end_d = pd.to_datetime(end).normalize()

    series_list = tuple(series_list)
    key = (series_list, str(start_d.date()), str(end_d.date()))

    """
    다음 조건문은 prevents repeated downloads from the Federal Reserve Economic Data
    """
    if key in _FRED_CACHE:
        return _FRED_CACHE[key].copy()

    out = pd.DataFrame()

    for sid in series_list:
        # sid (e.g., DGS10)의 데이터를 Federal Reserve Economic Data database 에서 다운로드
        s = _get_fred_series_with_retry(sid, start_d, end_d)
        out = pd.concat([out, s], axis=1)

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
                    threads=False,
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
# Macro dataset
# ------------------------------------------------------------
def fetch_macro(start="2015-01-01") -> pd.DataFrame:
    end = pd.Timestamp.today().normalize()
    us = fetch_treasury_yields(start, end)[["US3M", "US2Y", "US10Y"]]
    return us
