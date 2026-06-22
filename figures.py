# figures.py
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from regime import REGIME_COLORS

DISPLAY_NAMES = {
    "^FVX": "^FVX 5-year",
    "^TNX": "^TNX 10-year",
    "^TYX": "^TYX 30-year",
}


def display_name(name) -> str:
    return DISPLAY_NAMES.get(str(name), str(name))


def _trim_empty_edges(s: pd.Series) -> pd.Series:
    first = s.first_valid_index()
    last = s.last_valid_index()
    if first is None or last is None:
        return s.iloc[0:0]
    return s.loc[first:last]


def _line_trace_xy(s: pd.Series):
    """
    Plot native observations while preserving real large gaps.
    Keeping every daily NaN makes weekly/monthly line charts disappear.
    """
    values = _trim_empty_edges(pd.to_numeric(s, errors="coerce")).dropna()
    if values.empty:
        return values.index, values.values

    if len(values) < 3:
        return values.index, values.values

    deltas = values.index.to_series().diff().dropna()
    if deltas.empty:
        return values.index, values.values

    median_delta = deltas.median()
    if pd.isna(median_delta) or median_delta <= pd.Timedelta(0):
        return values.index, values.values

    gap_threshold = max(median_delta * 3, pd.Timedelta(days=10))
    x = []
    y = []
    prev_idx = None
    for idx, value in values.items():
        if prev_idx is not None and idx - prev_idx > gap_threshold:
            x.append(prev_idx + (idx - prev_idx) / 2)
            y.append(np.nan)
        x.append(idx)
        y.append(value)
        prev_idx = idx

    return x, y


def make_timeseries_panel(df, title, yaxis_title=None):
    """
    Generic multi-line time series panel.
    Robust to empty dfs and non-numeric columns.
    Keeps sparse mixed-frequency data without over-dropping rows.
    """
    fig = go.Figure()

    if df is None or df.empty:
        fig.update_layout(
            title=f"{title} (no data)",
            template="plotly_dark",
            height=480,
            margin=dict(l=40, r=40, t=60, b=40),
        )
        return fig

    numeric_df = df.select_dtypes(include="number")
    if numeric_df.empty:
        fig.update_layout(
            title=f"{title} (no numeric data)",
            template="plotly_dark",
            height=480,
            margin=dict(l=40, r=40, t=60, b=40),
        )
        return fig

    for col in numeric_df.columns:
        x, y = _line_trace_xy(numeric_df[col])
        if len(y) == 0:
            continue
        fig.add_trace(go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name=display_name(col),
            connectgaps=False,
        ))

    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.3),
        hovermode="x unified",
    )

    if yaxis_title:
        fig.update_yaxes(title_text=yaxis_title)

    return fig

# to enable opaque display by changing the hex_color to hexadecimal 
# it returns rgba(R, G, B, A) - four digits including alpha at the end
def hex_to_rgba(hex_color: str, alpha: float = 0.14) -> str:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"rgba(128,128,128,{alpha})"

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

def fig_regime_state(regime_df: pd.DataFrame) -> go.Figure:
    regime_map = {
        "crisis": 0,
        "risk_off": 1,
        "caution": 2,
        "neutral": 3,
        "risk_on": 4,
    }
    
    state = regime_df["regime_label"].map(regime_map).rename("Regime State")

    fig = go.Figure()

    # background bands with opaque 
    zone_colors = [
        (-0.5, 0.5, hex_to_rgba(REGIME_COLORS.get("crisis", "#8b0000"), 0.50)),
        (0.5, 1.5, hex_to_rgba(REGIME_COLORS.get("risk_off", "#d62728"), 0.14)),
        (1.5, 2.5, hex_to_rgba(REGIME_COLORS.get("caution", "#ff7f0e"), 0.30)),
        (2.5, 3.5, hex_to_rgba(REGIME_COLORS.get("neutral", "#1f77b4"), 0.14)),
        (3.5, 4.5, hex_to_rgba(REGIME_COLORS.get("risk_on", "#2ca02c"), 0.30)),
    ]
    # to force the bands behind traces  
    for y0, y1, color in zone_colors:
        fig.add_hrect(
            y0=y0,
            y1=y1,
            line_width=0,
            fillcolor=color,
            layer="below",
        )

    fig.add_trace(
        go.Scatter(
            x=state.index,
            y=state.values,
            mode="lines",
            line_shape="hv",
            name="Regime State",
            hovertemplate="Date: %{x|%Y-%m-%d}<br>State: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title="Regime State",
        xaxis_title="Date",
        yaxis_title="State",
        hovermode="x unified",
        height=420,
        margin=dict(l=60, r=30, t=60, b=50),
    )

    fig.update_yaxes(
        tickmode="array",
        tickvals=[0, 1, 2, 3, 4],
        ticktext=["Crisis", "Risk Off", "Caution", "Neutral", "Risk On"],
        range=[-0.2, 4.2],
    )

    return fig

def make_stress_gauge(current, mean):
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=float(current),
        delta={"reference": float(mean)},
        gauge={
            "axis": {"range": [-2, 3]},   # 🔥 핵심 수정
            "steps": [
                {"range": [-2, -1], "color": REGIME_COLORS.get("risk_on")},   # Easy
                {"range": [-1, 0], "color":REGIME_COLORS.get("neutral")},    # Normal
                {"range": [0, 1], "color": REGIME_COLORS.get("caution")},     # Watch
                {"range": [1, 2], "color": REGIME_COLORS.get("risk_off")},     # Stress
                {"range": [2, 3], "color": REGIME_COLORS.get("crisis")},     # Crisis
            ],
            "bar": {"color": "white"},
        },
        title={"text": "Composite Market Stress Score (Z)"},
    ))

    fig.update_layout(
        template="plotly_dark",
        height=450,
        margin=dict(l=40, r=40, t=60, b=40)
    )
    return fig

def fig_spread_3m_2y(ind):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ind.index, y=ind["spread_3m_2y"], mode="lines", name="US (2Y - 3M)"
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_hline(y=-0.25, line_dash="dot", line_color="yellow",
                  annotation_text="Watch (-0.25)", annotation_position="bottom left")
    fig.add_hline(y=-0.50, line_dash="dot", line_color="red",
                  annotation_text="Danger (-0.50)", annotation_position="bottom left")

    fig.update_layout(
        title="US 3M–2Y Spread (2Y − 3M)",
        yaxis_title="Percentage points",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

def fig_spread_3m_10y(ind):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ind.index, y=ind["spread_3m_10y"], mode="lines", name="US (10Y - 3M)"
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_hline(y=-0.25, line_dash="dot", line_color="yellow",
                  annotation_text="Watch (-0.25)", annotation_position="bottom left")
    fig.add_hline(y=-0.50, line_dash="dot", line_color="red",
                  annotation_text="Danger (-0.50)", annotation_position="bottom left")

    fig.update_layout(
        title="US 3M–10Y Spread (10Y − 3M)",
        yaxis_title="Percentage points",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )

    return fig

def fig_spread_us2y_jp2y(ind):
    """
    US 2Y - JP 2Y differential.
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=ind.index,
        y=ind["spread_us2y_jp2y"],
        mode="lines",
        name="US2Y - JP2Y"
    ))

    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title="US 2Y − JP 2Y Spread",
        yaxis_title="Percentage points",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

def _base_ts_fig(series_df, title, yaxis_title=""):
    fig = go.Figure()
    for col in series_df.columns:
        fig.add_trace(go.Scatter(
            x=series_df.index, y=series_df[col], mode="lines", name=str(col)
        ))
    fig.update_layout(
        title=title,
        yaxis_title=yaxis_title,
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

def _single_series_fig(df: pd.DataFrame, col: str, title: str, yaxis_title: str) -> go.Figure:
    fig = go.Figure()

    if df is None or df.empty or col not in df.columns:
        fig.update_layout(
            title=f"{title} (no data)",
            template="plotly_dark",
            height=480,
            margin=dict(l=40, r=40, t=60, b=40),
        )
        return fig

    x, y = _line_trace_xy(df[col])
    if len(y) == 0:
        fig.update_layout(
            title=f"{title} (no data)",
            template="plotly_dark",
            height=480,
            margin=dict(l=40, r=40, t=60, b=40),
        )
        return fig

    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode="lines",
        name=col,
        connectgaps=False,
    ))

    fig.update_layout(
        title=title,
        yaxis_title=yaxis_title,
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

def add_watch_danger_lines(fig, watch=None, danger=None, crisis=None, watch_text="Watch", danger_text="Danger"):
    """
    Adds horizontal lines if thresholds are provided.
    """
    if watch is not None:
        fig.add_hline(
            y=watch, line_dash="dot", line_color="yellow",
            annotation_text=f"{watch_text} ({watch})",
            annotation_position="bottom left",
        )
    if danger is not None:
        fig.add_hline(
            y=danger, line_dash="dot", line_color="red",
            annotation_text=f"{danger_text} ({danger})",
            annotation_position="bottom left",
        )

    return fig

def add_credit_risk_zones(
    fig,
    y_min=-3.5,
    y_max=3.5,
    hyoas_watch=1.0,
    hyoas_danger=2.0,
    hyglqd_watch=-1.0,
    hyglqd_danger=-2.0,
):
    # HY OAS upper zones
    fig.add_hrect(
        y0=hyoas_watch, y1=hyoas_danger,
        fillcolor="yellow", opacity=0.10,
        line_width=0, layer="below",
        annotation_text="HY OAS Watch",
        annotation_position="top left",
    )
    fig.add_hrect(
        y0=hyoas_danger, y1=y_max,
        fillcolor="red", opacity=0.10,
        line_width=0, layer="below",
        annotation_text="HY OAS Danger",
        annotation_position="top left",
    )

    # HYG/LQD lower zones
    fig.add_hrect(
        y0=hyglqd_danger, y1=hyglqd_watch,
        fillcolor="yellow", opacity=0.10,
        line_width=0, layer="below",
        annotation_text="HYG/LQD Watch",
        annotation_position="bottom left",
    )
    fig.add_hrect(
        y0=y_min, y1=hyglqd_danger,
        fillcolor="red", opacity=0.10,
        line_width=0, layer="below",
        annotation_text="HYG/LQD Danger",
        annotation_position="bottom left",
    )

    # guide lines
    for y, color in [
        (hyoas_watch, "yellow"),
        (hyoas_danger, "red"),
        (hyglqd_watch, "yellow"),
        (hyglqd_danger, "red"),
    ]:
        fig.add_hline(y=y, line_dash="dot", line_color=color, opacity=0.7)

    return fig
# -------------------------
# Volatility (VIX / VXN)
# Defaults: VIX 20/30, VXN 30/40
# -------------------------
def fig_volatility(ind_or_raw):
    """
    Expects columns: '^VIX', '^VXN' (either raw or z doesn't matter; usually raw levels).
    """
    cols = [c for c in ["^VIX", "^VXN"] if c in ind_or_raw.columns]
    df = ind_or_raw[cols].dropna()

    fig = _base_ts_fig(df, "Volatility — VIX / VXN", yaxis_title="Index level")

    # Add lines separately (two y-series share one axis; thresholds still helpful)
    # VIX thresholds
    if "^VIX" in df.columns:
        fig.add_hline(y=20, line_dash="dot", line_color="yellow",
                    annotation_text="VIX Watch (20)", annotation_position="bottom left")
        fig.add_hline(y=29, line_dash="dot", line_color="red",
                    annotation_text="VIX Danger (30)", annotation_position="bottom left")
    # VXN thresholds
    if "^VXN" in df.columns:
        fig.add_hline(y=31, line_dash="dot", line_color="yellow",
                    annotation_text="VXN Watch (30)", annotation_position="bottom left")
        fig.add_hline(y=40, line_dash="dot", line_color="red",
                    annotation_text="VXN Danger (40)", annotation_position="bottom left")

    return fig


# -------------------------
# Credit Risk (HYG/LQD ratio + optional HYG/JNK/LQD)
# Defaults: use Z-score thresholds on HYG/LQD: +1 (watch), +2 (danger)
# -------------------------
def fig_credit_risk_levels(raw):
    """
    Expects raw has: HYG, JNK, LQD, and HYG/LQD already added.
    Shows ratio + ETFs.
    """
    cols = [c for c in ["HYG", "JNK", "LQD"] if c in raw.columns]
    df = raw[cols].dropna()
    fig = _base_ts_fig(df, "Credit Risk — Levels", yaxis_title="Price / ratio")
    return fig

def fig_credit_risk_zscore(z):
    cols = [c for c in ["HY_OAS", "HYG/LQD"] if c in z.columns]
    if not cols:
        return _base_ts_fig(pd.DataFrame(), "Credit Risk — No Data", yaxis_title="Z-score")

    df = z[cols].dropna()
    fig = _base_ts_fig(df, "Credit Risk — HY OAS & HYG/LQD Z-Score", yaxis_title="Z-score")

    y_min = min(-3.5, df.min().min() - 0.3)
    y_max = max(3.5, df.max().max() + 0.3)

    fig = add_credit_risk_zones(
        fig,
        y_min=y_min,
        y_max=y_max,
        hyoas_watch=1.0,
        hyoas_danger=2.0,
        hyglqd_watch=-1.0,
        hyglqd_danger=-2.0,
    )
    return fig
    # ---------------------------
    # HYG/LQD (negative = risk)
    # ---------------------------
    if "HYG/LQD" in df.columns:
        fig.add_hrect(
            y0=-2.0, y1=-1.0,
            fillcolor="orange", opacity=0.12,
            layer="below", line_width=0,
            annotation_text="HYG/LQD Watch",
            annotation_position="bottom left"
        )
        fig.add_hrect(
            y0=-5.0, y1=-2.0,
            fillcolor="red", opacity=0.12,
            layer="below", line_width=0,
            annotation_text="HYG/LQD Danger",
            annotation_position="bottom left"
        )

    return fig
# -------------------------
# 3mo–10y Spread (10Y - 3M)
# Defaults: Watch -0.25, Danger -0.50 (in percentage points)
# -------------------------
def fig_spread_3m_10y_with_lines(spread_df):
    """
    Expects a dataframe with one column: '10Y - 3M (pp)' or similar.
    Adds inversion thresholds.
    """
    col = spread_df.columns[0]
    df = spread_df[[col]].dropna()

    fig = _base_ts_fig(df, "US 3M–10Y Spread (10Y − 3M)", yaxis_title="Percentage points")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig = add_watch_danger_lines(fig, watch=-0.25, danger=-0.50,
                                watch_text="Watch", danger_text="Danger")
    return fig

# -------------------------
# 3mo–2y Spread (2Y - 3M)
# Defaults: Watch -0.25, Danger -0.50 (in percentage points)
# -------------------------
def fig_spread_3m_2y_with_lines(spread_df):
    """
    Expects a dataframe with one column: '2Y - 3M (pp)' or similar.
    Adds inversion thresholds.
    """
    col = spread_df.columns[0]
    df = spread_df[[col]].dropna()

    fig = _base_ts_fig(df, "US 3M–2Y Spread (2Y − 3M)", yaxis_title="Percentage points")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig = add_watch_danger_lines(fig, watch=-0.25, danger=-0.50,
                                watch_text="Watch", danger_text="Danger")
    return fig

# -------------------------
# US2Y - JP2Y Spread
# Defaults: Watch 4.0, Danger 5.0 (pct points)  <-- tune to your preference
# -------------------------
def fig_us2y_jp2y_with_lines(ind):
    """
    Expects 'spread_us2y_jp2y' in ind.
    """
    df = ind[["spread_us2y_jp2y"]].dropna()
    fig = _base_ts_fig(df, "US 2Y − JP 2Y Proxy (JP 10Y) Spread", yaxis_title="Percentage points")

    # These are NOT universal "risk" levels; they are policy-differential levels.
    # Still useful as watch/danger markers if you want to monitor carry pressure.
    fig = add_watch_danger_lines(fig, watch=4.0, danger=5.0,
                                watch_text="Wide (watch)", danger_text="Very wide (danger)")
    return fig


# --- Global Liquidity / Global Risk figures (with watch & danger lines) ---

def fig_global_liquidity(raw):
    """
    Global Liquidity (Z-score view)
    Primary signal: Z(UUP)

    Interpretation:
      Z(UUP) > +1 → USD tightening (watch)
      Z(UUP) > +2 → Severe liquidity stress (danger)
    """

    if "UUP" not in raw.columns:
        return go.Figure().update_layout(
            title="Global Liquidity — UUP (missing)",
            template="plotly_dark",
            height=480,
        )

    # Compute Z-score
    uup = raw[["UUP"]].dropna()
    z_uup = (uup - uup.mean()) / uup.std()
    z_uup.columns = ["UUP_Z"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=z_uup.index,
        y=z_uup["UUP_Z"],
        mode="lines",
        name="UUP Z-score",
        line=dict(color="#00ccff")
    ))

    # Regime bands
    fig.add_hline(
        y=1.0, line_dash="dot", line_color="yellow",
        annotation_text="Watch (+1σ)", annotation_position="bottom left"
    )
    fig.add_hline(
        y=2.0, line_dash="dot", line_color="red",
        annotation_text="Danger (+2σ)", annotation_position="bottom left"
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title="Global Liquidity — USD Strength (UUP Z-score)",
        yaxis_title="Z-score",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )

    return fig

def fig_global_risk(raw):
    """
    Global risk proxy:
      - EEM (EM equities). Falling EEM often aligns with risk-off.

    Thresholds:
      - Watch: -7% drawdown from 6M high
      - Danger: -15% drawdown from 6M high
    """
    if "EEM" not in raw.columns:
        # fallback empty fig
        return go.Figure().update_layout(
            title="Global Risk — EEM (missing)",
            template="plotly_dark",
            height=480,
        )

    eem = raw[["EEM"]].dropna()
    dd = (eem["EEM"] / eem["EEM"].rolling(126).max() - 1) * 100
    df = dd.to_frame("EEM_drawdown_%")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["EEM_drawdown_%"], mode="lines", name="EEM Drawdown (%)"))

    fig.add_hline(y=-7, line_dash="dot", line_color="yellow",
                  annotation_text="Watch (-7%)", annotation_position="bottom left")
    fig.add_hline(y=-15, line_dash="dot", line_color="red",
                  annotation_text="Danger (-15%)", annotation_position="bottom left")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title="Global Risk — EEM Drawdown (% from 6M high)",
        yaxis_title="Percent",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig

"""
==========================
Liquidity Risk
==========================
"""
def fig_liquidity(df: pd.DataFrame) -> go.Figure:
    fig = _single_series_fig(
        df,
        "LiquidityScore",
        "Liquidity Score (Z)",
        "Liquidity Score (z)",
    )

    fig.add_hline(y=-1.5, line_dash="dot", line_color="yellow",
                  annotation_text="Watch", annotation_position="bottom left")
    fig.add_hline(y=-2.0, line_dash="dot", line_color="red",
                  annotation_text="Danger", annotation_position="bottom left")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    return fig


def fig_rrpz(df: pd.DataFrame) -> go.Figure:
    fig = _single_series_fig(
        df,
        "RRP (z)",
        "Fed's Reverse Repo (RRPONTSYD) Weekly (Z)",
        "Fed RRP Weekly (z)",
    )

    fig.add_hline(
        y=1.0,
        line_dash="dot",
        line_color="yellow",
        annotation_text="+1",
        annotation_position="bottom left",
    )
    fig.add_hline(
        y=-1.0,
        line_dash="dot",
        line_color="yellow",
        annotation_text="-1",
        annotation_position="bottom left",
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    return fig


def fig_m2slz(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    s = df["M2 (z)"].dropna() if "M2 (z)" in df.columns else pd.Series(dtype=float)
    fig.add_trace(go.Scatter(
        x=s.index,
        y=s.values,
        mode="lines+markers",
        name="M2 Money Supply (M2SL) (Z)",
        connectgaps=False,
    ))

    fig.add_hline(y=-1.0, line_dash="dot", line_color="yellow",
                  annotation_text="Watch", annotation_position="bottom left")
    fig.add_hline(y=-2.0, line_dash="dot", line_color="red",
                  annotation_text="Danger", annotation_position="bottom left")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title="M2 Money Supply (M2SL) (Z)",
        yaxis_title="M2 Money Supply (z)",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig


def fig_wrmfnsz(df: pd.DataFrame) -> go.Figure:
    fig = _single_series_fig(
        df,
        "MMF (z)",
        "Money Market Funds (WRMFNS) (Z) (Z)",
        "MMF (z)",
    )

    fig.add_hline(y=-1.0, line_dash="dot", line_color="yellow",
                  annotation_text="Watch", annotation_position="bottom left")
    fig.add_hline(y=-2.0, line_dash="dot", line_color="red",
                  annotation_text="Danger", annotation_position="bottom left")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    return fig


def fig_totresnsz(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    s = df["RESERVES Monthly (z)"].dropna() if "RESERVES Monthly (z)" in df.columns else pd.Series(dtype=float)
    fig.add_trace(go.Scatter(
        x=s.index,
        y=s.values,
        mode="lines+markers",
        name="Total Reserves (TOTRESNS) (Z)",
        connectgaps=False,
    ))

    fig.add_hline(y=-1.0, line_dash="dot", line_color="yellow",
                  annotation_text="Watch", annotation_position="bottom left")
    fig.add_hline(y=-2.0, line_dash="dot", line_color="red",
                  annotation_text="Danger", annotation_position="bottom left")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title="Bank Reserves (TOTRESNS) (Z)",
        yaxis_title="Bank Reserves Monthly (z)",
        template="plotly_dark",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    return fig


def fig_wresbal(df: pd.DataFrame) -> go.Figure:
    fig = _single_series_fig(
        df,
        "RESERVES_PROXY Weekly (z)",
        "Bank Reserve Proxy (WRESBAL) (Z)",
        "Bank Reserve Proxy (z)",
    )

    fig.add_hline(y=-1.0, line_dash="dot", line_color="yellow",
                  annotation_text="Watch", annotation_position="bottom left")
    fig.add_hline(y=-2.0, line_dash="dot", line_color="red",
                  annotation_text="Danger", annotation_position="bottom left")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    return fig

def fig_regime_accuracy_bar(acc_df):
    fig = go.Figure()

    if acc_df.empty:
        fig.update_layout(
            template="plotly_dark",
            title="Historical Regime Accuracy",
            height=420,
        )
        return fig

    y = acc_df["hit_rate"].fillna(0.0)

    fig.add_bar(
        x=acc_df.index.tolist(),
        y=y,
        text=[f"{x:.1%}" if pd.notna(x) else "" for x in y],
        textposition="outside",
        cliponaxis=False,
        name="Hit Rate",
    )

    ymax = max(1.0, float(y.max()) + 0.12)

    fig.update_layout(
        template="plotly_dark",
        title="Historical Regime Accuracy by Regime",
        yaxis_title="Hit Rate",
        xaxis_title="Regime",
        height=420,
        margin=dict(l=60, r=30, t=90, b=60),
    )
    fig.update_yaxes(
        tickformat=".0%",
        range=[0, ymax],
    )
    return fig


def fig_regime_accuracy_timeline(timeline_df):
    fig = go.Figure()

    if timeline_df.empty:
        fig.update_layout(
            template="plotly_dark",
            title="Rolling Regime Accuracy",
            height=420,
        )
        return fig

    fig.add_scatter(
        x=timeline_df.index,
        y=timeline_df["rolling_hit_rate_60"],
        mode="lines",
        name="60D Rolling Hit Rate",
    )

    fig.update_layout(
        template="plotly_dark",
        title="Rolling Regime Accuracy (60 observations)",
        yaxis_title="Hit Rate",
        xaxis_title="Date",
        hovermode="x unified",
        height=420,
    )
    fig.update_yaxes(tickformat=".0%")
    return fig


def fig_stress_vs_forward_scatter(scatter_df, stress_col="stress_score", horizon=21):
    fwd_col = f"fwd_{horizon}d"

    if scatter_df.empty:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            title="Stress vs Forward Returns",
            height=460,
        )
        return fig

    fig = px.scatter(
        scatter_df,
        x=stress_col,
        y=fwd_col,
        color="regime_label" if "regime_label" in scatter_df.columns else None,
        hover_data=["regime_confidence"] if "regime_confidence" in scatter_df.columns else None,
        title=f"Stress vs {horizon}D Forward Returns",
    )
    fig.update_layout(
        template="plotly_dark",
        xaxis_title="Stress Score",
        yaxis_title=f"{horizon}D Forward Return",
        hovermode="closest",
        height=460,
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def fig_stress_forward_bar(table_df):
    fig = go.Figure()

    if table_df.empty:
        fig.update_layout(
            template="plotly_dark",
            title="Forward Returns by Stress Bucket",
            height=420,
        )
        return fig

    fig.add_bar(
        x=table_df.index.astype(str).tolist(),
        y=table_df["avg_forward_return"],
        text=[f"{x:.1%}" if pd.notna(x) else "" for x in table_df["avg_forward_return"]],
        textposition="outside",
        name="Avg Fwd Return",
    )

    fig.update_layout(
        template="plotly_dark",
        title="Average Forward Returns by Stress Bucket",
        xaxis_title="Stress Bucket",
        yaxis_title="Average Forward Return",
        height=420,
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def fig_stress_hit_rate_bar(table_df):
    fig = go.Figure()

    if table_df.empty:
        fig.update_layout(
            template="plotly_dark",
            title="21D Up Probability by Stress Bucket",
            height=420,
        )
        return fig

    labels = table_df.index.astype(str).tolist()
    hit_rates = table_df["hit_rate"]
    observations = table_df["observations"]

    fig.add_bar(
        x=labels,
        y=hit_rates,
        text=[
            f"{hit:.1%}<br>n={int(obs)}" if pd.notna(hit) and pd.notna(obs) else ""
            for hit, obs in zip(hit_rates, observations)
        ],
        textposition="outside",
        marker_color="#4c9be8",
        name="21D Up Probability",
    )
    fig.add_hline(
        y=0.5,
        line_dash="dash",
        line_color="#aaaaaa",
        annotation_text="50%",
    )
    fig.update_layout(
        template="plotly_dark",
        title="SPY 21D Up Probability by Stress Bucket",
        xaxis_title="Stress Bucket",
        yaxis_title="Up Probability",
        yaxis_range=[0, 1.08],
        height=420,
    )
    fig.update_yaxes(tickformat=".0%")
    return fig


def fig_crisis_episode_returns(episode_df, horizon=21):
    fig = go.Figure()

    if episode_df.empty:
        fig.update_layout(
            template="plotly_dark",
            title="Independent Crisis Episodes",
            height=420,
        )
        return fig

    returns = episode_df["forward_return"]
    colors = ["#2ca02c" if value > 0 else "#d62728" for value in returns]
    labels = pd.to_datetime(episode_df["signal_date"]).dt.strftime("%Y-%m-%d")

    fig.add_bar(
        x=labels,
        y=returns,
        marker_color=colors,
        text=[f"{value:.1%}" for value in returns],
        textposition="outside",
        customdata=np.column_stack(
            [
                pd.to_datetime(episode_df["start_date"]).dt.strftime("%Y-%m-%d"),
                pd.to_datetime(episode_df["end_date"]).dt.strftime("%Y-%m-%d"),
                episode_df["peak_stress"],
                episode_df["max_drawdown"],
            ]
        ),
        hovertemplate=(
            "Signal: %{x}<br>"
            "Episode: %{customdata[0]} to %{customdata[1]}<br>"
            "Peak stress: %{customdata[2]:.2f}<br>"
            f"{horizon}D return: %{{y:.1%}}<br>"
            "Forward max drawdown: %{customdata[3]:.1%}<extra></extra>"
        ),
        name=f"{horizon}D Return",
    )
    fig.add_hline(y=0, line_color="#aaaaaa")
    fig.update_layout(
        template="plotly_dark",
        title=f"Independent Crisis Episodes: SPY {horizon}D Returns",
        xaxis_title="Peak Stress Signal Date",
        yaxis_title=f"{horizon}D Forward Return",
        height=460,
    )
    fig.update_yaxes(tickformat=".1%")
    return fig
