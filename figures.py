# figures.py
import plotly.graph_objects as go


def make_timeseries_panel(df, title, yaxis_title=None):
    """
    Generic multi-line time series panel.
    Robust to empty dfs and non-numeric columns.
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

    # Keep only numeric columns (avoids accidental object columns)
    numeric_df = df.select_dtypes(include="number").dropna()
    if numeric_df.empty:
        fig.update_layout(
            title=f"{title} (no numeric data)",
            template="plotly_dark",
            height=480,
            margin=dict(l=40, r=40, t=60, b=40),
        )
        return fig

    for col in numeric_df.columns:
        fig.add_trace(go.Scatter(
            x=numeric_df.index, y=numeric_df[col], mode="lines", name=str(col)
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


def make_stress_gauge(current, mean):
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=float(current),
        delta={"reference": float(mean)},
        gauge={
            "axis": {"range": [0, 100]},
            "steps": [
                {"range": [0, 40], "color": "#2ca02c"},
                {"range": [40, 55], "color": "#1f77b4"},
                {"range": [55, 70], "color": "#ff7f0e"},
                {"range": [70, 100], "color": "#d62728"},
            ],
            "bar": {"color": "white"},
        },
        title={"text": "Composite Market Stress Score"},
    ))
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=40, r=40, t=60, b=40))
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


def add_watch_danger_lines(fig, watch=None, danger=None, watch_text="Watch", danger_text="Danger"):
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
        fig.add_hline(y=30, line_dash="dot", line_color="red",
                    annotation_text="VIX Danger (30)", annotation_position="bottom left")
    # VXN thresholds
    if "^VXN" in df.columns:
        fig.add_hline(y=30, line_dash="dot", line_color="yellow",
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
    cols = [c for c in ["HYG", "JNK", "LQD", "HYG/LQD"] if c in raw.columns]
    df = raw[cols].dropna()
    fig = _base_ts_fig(df, "Credit Risk — Levels", yaxis_title="Price / ratio")
    return fig


def fig_credit_risk_zscore(z):
    """
    Expects z has 'HYG/LQD' at least.
    Adds watch/danger lines on the z-score.
    """
    if "HYG/LQD" not in z.columns:
        # fallback: plot what exists
        cols = [c for c in z.columns]
    else:
        cols = ["HYG/LQD"]

    df = z[cols].dropna()
    fig = _base_ts_fig(df, "Credit Risk — HYG/LQD Z-Score", yaxis_title="Z-score")

    # Watch/danger
    fig = add_watch_danger_lines(fig, watch=1.0, danger=2.0,
                                watch_text="Watch z", danger_text="Danger z")
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
    fig = _base_ts_fig(df, "US 2Y − JP 2Y Spread", yaxis_title="Percentage points")

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
    import plotly.graph_objects as go
    import pandas as pd

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