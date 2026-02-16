# indicators.py
import pandas as pd

# ---------------------------
# Basics
# ---------------------------
def compute_zscore(df: pd.DataFrame) -> pd.DataFrame:
    return (df - df.mean()) / df.std()

def add_credit_ratio(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "HYG" in df.columns and "LQD" in df.columns:
        df["HYG/LQD"] = df["HYG"] / df["LQD"]
    return df

# ---------------------------
# Macro indicators builder
# ---------------------------
def build_indicators(macro_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Build indicator dataframe for macro tabs.
    Always tries to produce: US2Y, JP2Y
    Optionally produces: 3M if present
    """
    df = macro_raw.copy()
    out = pd.DataFrame(index=df.index)

    # US 10Y
    if "US10Y" in df.columns:
        out["US10Y"] = df["US10Y"]
    elif "DGS10" in df.columns:
        out["US10Y"] = df["DGS10"]
    else:
        raise KeyError("build_indicators() missing US2Y (expected 'US10Y' or 'DGS10').")
    
    # US 2Y
    if "US2Y" in df.columns:
        out["US2Y"] = df["US2Y"]
    elif "DGS2" in df.columns:
        out["US2Y"] = df["DGS2"]
    else:
        raise KeyError("build_indicators() missing US2Y (expected 'US2Y' or 'DGS2').")

    # JP 2Y
    if "JP2Y" in df.columns:
        out["JP2Y"] = df["JP2Y"]
    elif "2yjpy.b" in df.columns:
        out["JP2Y"] = df["2yjpy.b"]
    else:
        raise KeyError("build_indicators() missing JP2Y (expected 'JP2Y' or '2yjpy.b').")

    # 3M (optional)
    if "3M" in df.columns:
        out["3M"] = df["3M"]
    elif "US3M" in df.columns:
        out["3M"] = df["US3M"]
    elif "DGS3MO" in df.columns:
        out["3M"] = df["DGS3MO"]
    elif "^IRX" in df.columns:
        out["3M"] = df["^IRX"]

    return out.dropna(subset=["US2Y", "JP2Y"])

# ---------------------------
# Spread add-on
# ---------------------------
def add_spreads(ind: pd.DataFrame) -> pd.DataFrame:
    """
    Expects columns: 3M, US10y, US2Y, JP2Y (all in % units)
    Adds:
      - spread_3m_10y: US10Y - 3M
      - spread_3m_2y: US2Y - 3M
      - spread_us2y_jp2y: US2Y - JP2Y
    """
    out = ind.copy()

    for c in ["3M", "US10Y","US2Y", "JP2Y"]:
        if c not in out.columns:
            raise KeyError(f"add_spreads() requires '{c}' in ind dataframe")

    out["spread_3m_10y"] = out["US10Y"] - out["3M"]
    out["spread_3m_2y"] = out["US2Y"] - out["3M"]
    out["spread_us2y_jp2y"] = out["US2Y"] - out["JP2Y"]

    return out

# ---------------------------
# Stress score (robust)
# ---------------------------
def compute_stress_score(z: pd.DataFrame) -> pd.DataFrame:
    """
    Robust weighted stress score.
    Only uses available columns and renormalizes weights to sum to 1.
    """
    z = z.copy()

    # weights (+ means risk up, - means risk down)
    weights = {
        "^VIX": 0.30,
        "^VIX3M": 0.15,
        "^VIX6M": 0.10,
        "HYG/LQD": 0.25,
        "^TNX": 0.15,
        "UUP": 0.05,
        "EEM": -0.10,
    }

    available = [c for c in weights.keys() if c in z.columns]
    if not available:
        # return empty but safe dataframe
        return pd.DataFrame(columns=["Stress Score"])

    z2 = z[available].dropna()
    if z2.empty:
        return pd.DataFrame(columns=["Stress Score"])

    # Renormalize weights over available columns
    w = pd.Series({k: weights[k] for k in available}, dtype=float)
    w = w / w.abs().sum()

    MSS_raw = (z2 * w).sum(axis=1)

    # Scale to a 0-100-ish index
    MSS = 50 + 10 * MSS_raw
    return MSS.to_frame("Stress Score")