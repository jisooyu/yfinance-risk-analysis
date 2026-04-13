# regime.py
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import (
    add_credit_ratio,
    compute_zscore,
    compute_stress_score,
    rolling_zscore_obs,
)

# used by callbacks.py and feature.py
REGIME_COLORS = {
    "risk_on": "#2ca02c",
    "neutral": "#1f77b4",
    "caution": "#ff7f0e",
    "risk_off": "#d62728",
    "crisis": "#8b0000",
}

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _safe_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(index=df.index, dtype="float64", name=col)


def _obs_z(s: pd.Series, window_obs: int, min_obs: int) -> pd.Series:
    return rolling_zscore_obs(
        pd.to_numeric(s, errors="coerce"),
        window_obs=window_obs,
        min_obs=min_obs,
    )


def _first_existing(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for col in candidates:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(index=df.index, dtype="float64")


def _ffill_limited(df: pd.DataFrame, fill_limits: dict[str, int]) -> pd.DataFrame:
    out = df.copy()
    for col, lim in fill_limits.items():
        if col in out.columns:
            out[col] = out[col].ffill(limit=lim)
    return out


def _row_valid_ratio(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    existing = [c for c in cols if c in df.columns]
    if not existing:
        return pd.Series(index=df.index, dtype="float64")
    return df[existing].notna().mean(axis=1)


# ------------------------------------------------------------
# 1) Build regime features from your merged raw dataset
# ------------------------------------------------------------
def build_regime_features(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the merged dataset from fetch_data(...)
    and returns a feature table for regime classification.

    Expected raw inputs may include:
      Yahoo: ^VIX, ^VIX3M, ^VIX6M, ^VXN, ^SKEW, HYG, JNK, LQD, UUP, SHY, IEI, EEM
      FRED : US3M, US2Y, US10Y, HY_OAS, MMF, RRP, M2, RESERVES, RESERVES_PROXY
    """
    raw2 = add_credit_ratio(raw).copy()

    feat = pd.DataFrame(index=raw2.index)

    # -------------------------
    # Credit / liquidity inputs
    # -------------------------
    hy_oas = _safe_series(raw2, "HY_OAS")
    hyglqd = _safe_series(raw2, "HYG/LQD")

    mmf = _safe_series(raw2, "MMF").dropna().resample("W-FRI").last()
    rrp = _safe_series(raw2, "RRP")
    m2 = _safe_series(raw2, "M2").dropna().resample("MS").last()
    reserves = _safe_series(raw2, "RESERVES").dropna().resample("MS").last()
    reserves_proxy = _safe_series(raw2, "RESERVES_PROXY").dropna()

    feat["HY_OAS_z"] = _obs_z(hy_oas, window_obs=60, min_obs=30)
    feat["HYG_LQD_z"] = _obs_z(hyglqd, window_obs=126, min_obs=63)

    feat["MMF_z"] = _obs_z(mmf, window_obs=104, min_obs=26).reindex(feat.index)
    feat["RRP_z"] = _obs_z(rrp, window_obs=60, min_obs=30)
    feat["M2_z"] = _obs_z(m2, window_obs=24, min_obs=12).reindex(feat.index)
    feat["RESERVES_z"] = _obs_z(reserves, window_obs=24, min_obs=12).reindex(feat.index)
    feat["RESERVES_PROXY_z"] = _obs_z(reserves_proxy, window_obs=52, min_obs=26).reindex(feat.index)

    # -------------------------
    # Volatility inputs
    # -------------------------
    vix = _safe_series(raw2, "^VIX")
    vix3m = _safe_series(raw2, "^VIX3M")
    skew = _safe_series(raw2, "^SKEW")
    eem = _safe_series(raw2, "EEM")
    uup = _safe_series(raw2, "UUP")

    feat["VIX_z"] = _obs_z(vix, window_obs=252, min_obs=126)
    feat["VIX3M_z"] = _obs_z(vix3m, window_obs=252, min_obs=126)
    feat["SKEW_z"] = _obs_z(skew, window_obs=252, min_obs=126)
    feat["EEM_z"] = _obs_z(eem, window_obs=252, min_obs=126)
    feat["UUP_z"] = _obs_z(uup, window_obs=252, min_obs=126)

    # term structure: positive usually easier than inversion
    if "^VIX" in raw2.columns and "^VIX3M" in raw2.columns:
        feat["VIX_term"] = raw2["^VIX3M"] - raw2["^VIX"]
        feat["VIX_term_z"] = _obs_z(feat["VIX_term"], window_obs=252, min_obs=126)

    # -------------------------
    # Treasury / macro spreads
    # -------------------------
    if {"US3M", "US2Y"}.issubset(raw2.columns):
        feat["spread_2y_3m"] = raw2["US2Y"] - raw2["US3M"]
        feat["spread_2y_3m_z"] = _obs_z(feat["spread_2y_3m"], window_obs=252, min_obs=126)

    if {"US3M", "US10Y"}.issubset(raw2.columns):
        feat["spread_10y_3m"] = raw2["US10Y"] - raw2["US3M"]
        feat["spread_10y_3m_z"] = _obs_z(feat["spread_10y_3m"], window_obs=252, min_obs=126)

    if {"US2Y", "US10Y"}.issubset(raw2.columns):
        feat["spread_10y_2y"] = raw2["US10Y"] - raw2["US2Y"]
        feat["spread_10y_2y_z"] = _obs_z(feat["spread_10y_2y"], window_obs=252, min_obs=126)

    # -------------------------
    # Liquidity score (same philosophy as your liquidity app)
    # -------------------------
    score_inputs = feat[
        [
            c for c in [
                "MMF_z",
                "RRP_z",
                "M2_z",
                "RESERVES_z",
                "RESERVES_PROXY_z",
                "HY_OAS_z",
                "HYG_LQD_z",
            ]
            if c in feat.columns
        ]
    ].copy()

    fill_limits = {
        "RRP_z": 10,
        "HY_OAS_z": 10,
        "RESERVES_PROXY_z": 10,
        "MMF_z": 15,
        "RESERVES_z": 45,
        "M2_z": 45,
        "HYG_LQD_z": 5,
    }
    score_inputs = _ffill_limited(score_inputs, fill_limits)

    feat["LiquidityScore_raw"] = (
        score_inputs.get("MMF_z", 0)
        + score_inputs.get("RRP_z", 0)
        + score_inputs.get("M2_z", 0)
        + score_inputs.get("RESERVES_z", 0) * 0.3
        + score_inputs.get("RESERVES_PROXY_z", 0) * 0.7
        - score_inputs.get("HY_OAS_z", 0)
        + score_inputs.get("HYG_LQD_z", 0) * 0.5
    )

    feat["LiquidityScore_z"] = _obs_z(
        feat["LiquidityScore_raw"],
        window_obs=60,
        min_obs=30,
    )

    # -------------------------
    # Stress Score
    # -------------------------
    # Reuse your existing stress logic. This expects a z-score frame.
    z_for_stress_cols = [c for c in [
        "^VIX", "^VIX3M", "^VIX6M", "HYG/LQD", "^TNX", "UUP", "EEM"
    ] if c in raw2.columns]

    if z_for_stress_cols:
        z_for_stress = compute_zscore(raw2[z_for_stress_cols].dropna(how="all"), method="rolling", window_obs=252)
        mss = compute_stress_score(z_for_stress)
        if not mss.empty and "Stress Score" in mss.columns:
            feat["StressScore"] = mss["Stress Score"].reindex(feat.index)
            feat["StressScore_z"] = _obs_z(feat["StressScore"], window_obs=252, min_obs=126)

    # -------------------------
    # Feature coverage / freshness
    # -------------------------
    core_cols = [
        "LiquidityScore_z",
        "HY_OAS_z",
        "HYG_LQD_z",
        "VIX_z",
        "StressScore_z",
        "EEM_z",
        "UUP_z",
    ]
    feat["core_valid_ratio"] = _row_valid_ratio(feat, core_cols)

    return feat.sort_index()


# ------------------------------------------------------------
# 2) Regime classification
# ------------------------------------------------------------
def classify_regime(features: pd.DataFrame) -> pd.DataFrame:
    """
    Convert feature table into:
      regime_score
      regime_label
      regime_confidence
      trade_allowed
      size_mult
      regime_change
    """
    out = features.copy()

    # Higher score = easier / more risk-on
    regime_score = (
        + 1.20 * out.get("LiquidityScore_z", 0)
        - 1.00 * out.get("HY_OAS_z", 0)
        + 0.90 * out.get("HYG_LQD_z", 0)
        - 0.80 * out.get("VIX_z", 0)
        - 0.70 * out.get("StressScore_z", 0)
        + 0.45 * out.get("EEM_z", 0)
        - 0.35 * out.get("UUP_z", 0)
        + 0.20 * out.get("spread_10y_2y_z", 0)
        + 0.20 * out.get("spread_10y_3m_z", 0)
        + 0.15 * out.get("VIX_term_z", 0)
    )

    out["regime_score_raw"] = regime_score
    out["regime_score"] = regime_score.rolling(5, min_periods=1).mean()

    # Five-state regime map
    conditions = [
        regime_score >= 1.25,
        (regime_score >= 0.25) & (regime_score < 1.25),
        (regime_score >= -0.75) & (regime_score < 0.25),
        (regime_score >= -1.75) & (regime_score < -0.75),
        regime_score < -1.75,
    ]
    labels = [
        "risk_on",
        "neutral",
        "caution",
        "risk_off",
        "crisis",
    ]
    out["regime_label"] = np.select(conditions, labels, default="neutral")

    # Agreement / disagreement across the main features
    agreement_cols = [
        c for c in [
            "LiquidityScore_z",
            "HY_OAS_z",
            "HYG_LQD_z",
            "VIX_z",
            "StressScore_z",
            "EEM_z",
            "UUP_z",
        ]
        if c in out.columns
    ]

    if agreement_cols:
        # lower std after sign-normalization = stronger agreement
        signed = pd.DataFrame(index=out.index)
        signed["liq"] = out.get("LiquidityScore_z", np.nan)
        signed["hy_oas"] = -out.get("HY_OAS_z", np.nan)
        signed["hyglqd"] = out.get("HYG_LQD_z", np.nan)
        signed["vix"] = -out.get("VIX_z", np.nan)
        signed["stress"] = -out.get("StressScore_z", np.nan)
        signed["eem"] = out.get("EEM_z", np.nan)
        signed["uup"] = -out.get("UUP_z", np.nan)

        dispersion = signed.std(axis=1, skipna=True)
        confidence = (1.0 - (dispersion / 3.0)).clip(lower=0.05, upper=1.0)
    else:
        confidence = pd.Series(0.25, index=out.index)

    # penalize low feature coverage
    coverage = out.get("core_valid_ratio", pd.Series(1.0, index=out.index)).fillna(0)
    confidence = (confidence * coverage.clip(lower=0.25, upper=1.0)).clip(0.05, 1.0)

    out["regime_confidence"] = confidence

    # Trade permissions
    out["trade_allowed"] = out["regime_label"].isin(["risk_on", "neutral", "caution"])

    out["size_mult"] = out["regime_label"].map(
        {
            "risk_on": 1.00,
            "neutral": 0.70,
            "caution": 0.35,
            "risk_off": 0.10,
            "crisis": 0.00,
        }
    ).astype("float64")

    # transition flags
    out["prev_regime"] = out["regime_label"].shift(1)
    out["regime_change"] = out["regime_label"] != out["prev_regime"]

    # stronger warning if confidence drops while regime deteriorates
    deterioration = {
        "risk_on": 4,
        "neutral": 3,
        "caution": 2,
        "risk_off": 1,
        "crisis": 0,
    }
    out["regime_rank"] = out["regime_label"].map(deterioration)
    out["prev_regime_rank"] = out["prev_regime"].map(deterioration)

    out["risk_deteriorating"] = out["regime_rank"] < out["prev_regime_rank"]
    out["transition_alert"] = out["regime_change"] & out["risk_deteriorating"]
    out.to_excel("./excel_file/out_classify_regime.xlsx")
    return out

# ------------------------------------------------------------
# 3) Convenience wrapper
# ------------------------------------------------------------
def build_regime_table(raw: pd.DataFrame) -> pd.DataFrame:
    features = build_regime_features(raw)
    regime = classify_regime(features)
    return regime


# ------------------------------------------------------------
# 4) Latest snapshot helper
# ------------------------------------------------------------
def latest_regime_snapshot(regime_df: pd.DataFrame) -> dict:
    if regime_df.empty:
        return {
            "regime_label": "unknown",
            "regime_score": np.nan,
            "regime_confidence": np.nan,
            "trade_allowed": False,
            "size_mult": 0.0,
            "transition_alert": False,
        }

    last = regime_df.dropna(how="all").iloc[-1]
    return {
        "regime_label": last.get("regime_label", "unknown"),
        "regime_score": float(last.get("regime_score", np.nan)),
        "regime_confidence": float(last.get("regime_confidence", np.nan)),
        "trade_allowed": bool(last.get("trade_allowed", False)),
        "size_mult": float(last.get("size_mult", 0.0)),
        "transition_alert": bool(last.get("transition_alert", False)),
    }