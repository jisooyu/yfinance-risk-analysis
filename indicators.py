import pandas as pd


def rolling_zscore_obs(
    s: pd.Series,
    window_obs: int,
    min_obs: int | None = None,
    ddof: int = 0,
) -> pd.Series:
    """
    Rolling z-score based on number of observations, not calendar spacing.
    Works well for sparse mixed-frequency series.
    """
    s = pd.to_numeric(s, errors="coerce")
    s_nonan = s.dropna()

    if s_nonan.empty:
        return pd.Series(index=s.index, dtype="float64", name=s.name)

    if min_obs is None:
        min_obs = max(2, window_obs // 2)

    mu = s_nonan.rolling(window=window_obs, min_periods=min_obs).mean()
    sig = s_nonan.rolling(window=window_obs, min_periods=min_obs).std(ddof=ddof)

    z = (s_nonan - mu) / sig
    z = z.replace([float("inf"), float("-inf")], pd.NA)

    return z.reindex(s.index)


def compute_zscore(
    df: pd.DataFrame,
    *,
    method: str = "full",
    window_obs: int = 252,
    min_obs: int | None = None,
    ddof: int = 0,
) -> pd.DataFrame:
    """
    Two modes:
      - method='full'    : full-sample z-score
      - method='rolling' : rolling observation-based z-score
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    for col in out.columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if method == "rolling":
        z = pd.DataFrame(index=out.index)
        for col in out.columns:
            z[col] = rolling_zscore_obs(
                out[col],
                window_obs=window_obs,
                min_obs=min_obs,
                ddof=ddof,
            )
        return z

    mu = out.mean()
    sig = out.std(ddof=ddof).replace(0, pd.NA)
    return (out - mu) / sig


def add_credit_ratio(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "HYG" in df.columns and "LQD" in df.columns:
        hyg = pd.to_numeric(df["HYG"], errors="coerce")
        lqd = pd.to_numeric(df["LQD"], errors="coerce").replace(0, pd.NA)
        df["HYG/LQD"] = hyg / lqd

    return df


def compute_stress_score(z_df: pd.DataFrame) -> pd.DataFrame:
    """
    Weighted composite stress score.
    Uses only columns that actually exist in z_df.
    """
    if z_df.empty:
        return pd.DataFrame(columns=["Stress Score"], index=z_df.index)

    weights = {
        "^VIX": 0.30,
        "^VIX3M": 0.15,
        "^VIX6M": 0.10,
        "HYG/LQD": 0.25,
        "^TNX": 0.15,
        "UUP": 0.05,
        "EEM": -0.10,
    }

    available = {k: v for k, v in weights.items() if k in z_df.columns}
    if not available:
        return pd.DataFrame(columns=["Stress Score"], index=z_df.index)

    score = pd.Series(0.0, index=z_df.index, dtype="float64")
    weight_sum = 0.0

    for col, w in available.items():
        s = pd.to_numeric(z_df[col], errors="coerce")
        score = score.add(s * w, fill_value=0.0)
        weight_sum += abs(w)

    if weight_sum > 0:
        score = score / sum(weights.values())

    return score.to_frame("Stress Score")


def build_indicators(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Basic macro indicator builder.
    Keeps only expected macro columns if present.
    """
    if raw.empty:
        return raw.copy()

    out = raw.copy()
    for col in out.columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.sort_index()
    return out


def add_spreads(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "US3M" in df.columns and "US2Y" in df.columns:
        df["spread_3m_2y"] = df["US2Y"] - df["US3M"]

    if "US3M" in df.columns and "US10Y" in df.columns:
        df["spread_3m_10y"] = df["US10Y"] - df["US3M"]

    if "US2Y" in df.columns and "US10Y" in df.columns:
        df["spread_2y_10y"] = df["US10Y"] - df["US2Y"]

    if "US2Y" in df.columns and "JP2Y" in df.columns:
        df["spread_us2y_jp2y"] = df["US2Y"] - df["JP2Y"]

    return df