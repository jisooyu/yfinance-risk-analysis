# data_fetching.py
import os
import time
import io
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import yfinance as yf
from pandas_datareader import data as web
from pandas_datareader._utils import RemoteDataError


def _http_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.7,                 # 0.7s, 1.4s, 2.8s...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; RenderBot/1.0; +https://render.com)"
    })
    return s

def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """
    FRED sometimes returns '.' strings for missing.
    Convert everything to numeric.
    """
    return df.replace(".", pd.NA).apply(pd.to_numeric, errors="coerce")

def _fetch_fred_api(series_list, start, end) -> pd.DataFrame:
    """
    Fetch FRED series via official API (requires FRED_API_KEY env var).
    Returns DataFrame indexed by date with columns=series ids.
    pandas_datareader가 block당할 경우에 사용함
    """
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY is not set. Add it in Render environment variables.")

    base = "https://api.stlouisfed.org/fred/series/observations"
    out = pd.DataFrame()

    for sid in series_list:
        params = {
            "series_id": sid,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": str(pd.to_datetime(start).date()),
            "observation_end": str(pd.to_datetime(end).date()),
        }
        r = requests.get(base, params=params, timeout=20)
        r.raise_for_status()
        js = r.json()
        obs = js.get("observations", [])

        s = pd.Series({o["date"]: o["value"] for o in obs}, name=sid, dtype="object")
        s.index = pd.to_datetime(s.index)
        s = pd.to_numeric(s.replace(".", pd.NA), errors="coerce")
        out = pd.concat([out, s], axis=1)

    return out.sort_index()

_FRED_CACHE: dict = {}
def _fetch_fred(series, start, end) -> pd.DataFrame:
    """
    Try pandas_datareader (fredgraph.csv). If blocked (Render), fall back to FRED API.
    Caches results.
    """
    start_d = str(pd.to_datetime(start).date())
    end_d = str(pd.to_datetime(end).date())
    key = (tuple(series), start_d, end_d)

    if key in _FRED_CACHE:
        return _FRED_CACHE[key].copy()

    try:
        df = web.DataReader(series, "fred", start, end)
        df = _coerce_numeric(df).ffill()
        _FRED_CACHE[key] = df.copy()
        return df
    except (RemoteDataError, Exception) as e:
        msg = str(e).lower()
        if "access denied" in msg or "unable to read url" in msg or "errors.edgesuite.net" in msg:
            df = _fetch_fred_api(series, start, end)
            df = _coerce_numeric(df).ffill()
            _FRED_CACHE[key] = df.copy()
            return df
        raise

def fetch_fred_series(series: str, start="2010-01-01", end=None) -> pd.Series:
    """
    Fetch single series as numeric pd.Series.
    Uses _fetch_fred() so it benefits from Render-safe fallback + caching.
    """
    if end is None:
        end = pd.Timestamp.today().normalize()

    df = _fetch_fred([series], start, end)
    s = df[series].dropna()
    s.name = series
    return s

_HTTP = _http_session()
_STOOQ_CACHE: dict = {}  # (symbol) -> Series (last good)

def fetch_stooq_daily(symbol: str) -> pd.Series:
    """
    Stooq CSV endpoint (Render-safe):
      https://stooq.com/q/d/l/?s=<symbol>&i=d
    """
    url = "https://stooq.com/q/d/l/"
    params = {"s": symbol, "i": "d"}

    try:
        r = _HTTP.get(url, params=params, timeout=(5, 12))  # (connect, read)
        r.raise_for_status()

        text = (r.text or "").strip()

        # ✅ Critical: Stooq/CDN can return HTML with HTTP 200 on Render
        if text.lower().startswith("<!doctype html") or "<html" in text.lower():
            raise RuntimeError("Stooq returned HTML (possible block/rate-limit)")

        df = pd.read_csv(io.StringIO(text))
        if "Date" not in df.columns or "Close" not in df.columns:
            raise ValueError(f"Unexpected Stooq CSV columns for {symbol}: {df.columns.tolist()}")

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")

        s = pd.to_numeric(df["Close"], errors="coerce").dropna()
        s.name = symbol

        _STOOQ_CACHE[symbol] = s  # last-good
        return s

    except Exception as e:
        # Helpful log for Render (shows up in Render logs)
        print(f"[stooq] {symbol} fetch failed: {type(e).__name__}: {e}")

        if symbol in _STOOQ_CACHE and not _STOOQ_CACHE[symbol].empty:
            return _STOOQ_CACHE[symbol]

        raise RuntimeError(f"Stooq fetch failed for {symbol}: {e}") from e

def fetch_macro(start="2015-01-01") -> pd.DataFrame:
    """
    Macro-only dataset for spread tabs:+
      - US3M from FRED (DGS3MO)
      - US2Y from FRED (DGS2)
      - JP2Y from Stooq (fallback symbols)
    Returns columns: US3M, US2Y, JP2Y
    """
    end = pd.Timestamp.today().normalize()

    us3m = fetch_fred_series("DGS3MO", start=start, end=end)
    us2y = fetch_fred_series("DGS2", start=start, end=end)

    # JP2Y: best-effort (don’t crash the whole panel)
    try:
        # jp2y = fetch_stooq_daily("2yjpy.b")
        t0 = time.perf_counter()
        # stoop에서 fetch하는 시간을 줄이기 위해 지난 1100일간의 데이터만 fetch
        jp2y = fetch_stooq_daily("2yjpy.b").loc[pd.Timestamp.today() - pd.Timedelta(days=1100):]
        # print(f"[stooq] fetched {len(jp2y)} rows in {time.perf_counter()-t0:.2f}s")
    except Exception:
        jp2y = pd.Series(dtype="float64", name="JP2Y")

    out = pd.concat([us3m, us2y, jp2y], axis=1).rename(columns={
        "DGS3MO": "US3M",
        "DGS2": "US2Y",
        "2yjpy.b": "JP2Y",
    }).sort_index().ffill()

    # If JP2Y missing, still return US columns (so charts render)
    if "JP2Y" not in out.columns:
        out["JP2Y"] = pd.NA

    return out.sort_index()

def fetch_data(ticker_groups, retries=2, delay=2, period="1y") -> pd.DataFrame:
    """
    Main merged dataset:
      - yfinance tickers from ticker_groups
      - FRED yields: DGS3MO, DGS2, DGS10 (Render-safe)
    """
    # 1) Yahoo tickers
    tickers = sum(ticker_groups.values(), [])
    df_raw = pd.DataFrame()

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

    # Normalize Yahoo output to "Adj Close" / "Close"
    yf_data = pd.DataFrame()
    if not df_raw.empty:
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

        yf_data = yf_data.ffill().dropna(how="all")
        yf_data = yf_data[[c for c in yf_data.columns if c in tickers]]

    # 2) FRED yields aligned to yf date range if possible
    if not yf_data.empty:
        start = yf_data.index.min()
        end = yf_data.index.max()
    else:
        end = pd.Timestamp.today().normalize()
        start = end - pd.Timedelta(days=370)

    fred = _fetch_fred(["DGS3MO", "DGS2", "DGS10"], start, end).ffill()

    # 3) Merge
    data = yf_data.join(fred, how="outer").sort_index()
    data = data.ffill().dropna(how="all")
    return data