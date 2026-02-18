# callbacks.py
import pandas as pd
from dash import html, dcc, Output, Input
from data_fetching import fetch_data, fetch_macro
from indicators import (
    compute_zscore,
    add_credit_ratio,
    compute_stress_score,
    build_indicators,
    add_spreads,
)
from figures import (
    make_timeseries_panel,
    make_stress_gauge,
    fig_us2y_jp2y_with_lines,
    fig_volatility,
    fig_credit_risk_levels,
    fig_credit_risk_zscore,
    fig_spread_3m_2y_with_lines,  
    fig_spread_3m_10y_with_lines,  
    fig_global_liquidity, 
    fig_global_risk
)
from signal_guide import SIGNAL_GUIDE_TEXT

# callbacks.py (add these helpers near the top, below TAB_* constants)

TREASURY_TITLE = {
    ("DGS3MO", "DGS2"):  "Treasury Yields — 3M vs 2Y (%, FRED)",
    ("DGS3MO", "DGS10"): "Treasury Yields — 3M vs 10Y (%, FRED)",
    ("DGS2", "DGS10"):   "Treasury Yields — 2Y vs 10Y (%, FRED)",
}

def _missing_cols(df, cols):
    return [c for c in cols if c not in df.columns]

def render_treasury_spread_panel(
    raw: pd.DataFrame,
    *,
    left: str,
    right: str,
    spread_name: str,
    spread_fig_fn,
    levels_title: str | None = None,
):
    """
    right - left spread panel with:
      - yields chart for [left, right]
      - spread chart via spread_fig_fn(spread_df)
    """
    needed = [left, right]
    missing = _missing_cols(raw, needed)
    if missing:
        return html.Div([
            html.H3("Data unavailable"),
            html.P(f"Missing columns: {missing}. raw has: {list(raw.columns)[:25]} ...",
                   style={"color": "orange"}),
        ])

    y = raw[needed].dropna()
    spread = (y[right] - y[left]).to_frame(spread_name)

    if levels_title is None:
        levels_title = TREASURY_TITLE.get((left, right), "Treasury Yields (%, FRED)")

    return html.Div([
        dcc.Graph(figure=make_timeseries_panel(y, levels_title)),
        dcc.Graph(figure=spread_fig_fn(spread)),
    ])


TAB_3M2Y = "3mo–2y Spread"
TAB_3M10Y = "3mo–10y Spread"
TAB_US_JP = "US 2y - JP 2y Spread"
TAB_2Y10Y = "2y–10y Spread"

def register_callbacks(app, RISK_TICKERS):

    @app.callback(
        Output("panel-output", "children"),
        Input("tabs", "value"),
        Input("refresh", "n_intervals"),
    )
    def update_panel(selected_group, n):

        # =====================================================
        # 0) Fetch once (includes Treasury by default)
        # =====================================================
        # Note: fetch_data already merges DGS3MO/DGS2/DGS10
        raw = fetch_data(RISK_TICKERS)

        # =====================================================
        # 1) Spread tabs
        # =====================================================
        if selected_group == TAB_3M2Y:
            return render_treasury_spread_panel(
                raw,
                left="DGS3MO",
                right="DGS2",
                spread_name="2Y - 3M (pp)",
                spread_fig_fn=fig_spread_3m_2y_with_lines,
                levels_title="Treasury Yields — 3M vs 2Y (%, FRED)",
            )

        if selected_group == TAB_3M10Y:
            return render_treasury_spread_panel(
                raw,
                left="DGS3MO",
                right="DGS10",
                spread_name="10Y - 3M (pp)",
                spread_fig_fn=fig_spread_3m_10y_with_lines,
                levels_title="Treasury Yields — 3M vs 10Y (%, FRED)",
            )

        if selected_group == TAB_2Y10Y:
            # keep your existing style (two timeseries panels) but still dedupe data-checking
            needed = ["DGS2", "DGS10"]
            missing = _missing_cols(raw, needed)
            if missing:
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P(f"Missing columns: {missing}", style={"color": "orange"}),
                ])

            y = raw[needed].dropna()
            spread = (y["DGS10"] - y["DGS2"]).to_frame("10Y - 2Y (pp)")
            return html.Div([
                dcc.Graph(figure=make_timeseries_panel(y, "Treasury Yields — 2Y vs 10Y (%, FRED)")),
                dcc.Graph(figure=make_timeseries_panel(spread, "Yield Spread — 10Y minus 2Y (percentage points)")),]
            )

        # --- US 2y - JP 2y Spread (macro pipeline) ---
        if selected_group == TAB_US_JP:
            try:
                macro_raw = fetch_macro(start="2015-01-01")
                ind = build_indicators(macro_raw)
                ind = add_spreads(ind)
            except Exception as e:
                return html.Div([
                    html.H3("Indicator build failed"),
                    html.P(str(e), style={"color": "orange"}),
                ])

            if ind.empty or "spread_us2y_jp2y" not in ind.columns:
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P(f"ind columns: {list(ind.columns)}", style={"color": "orange"}),
                ])

            return html.Div([dcc.Graph(figure=fig_us2y_jp2y_with_lines(ind))])

        # =====================================================
        # 2) Everything else (unchanged logic)
        # =====================================================
        if selected_group == "Signal Guide":
            return html.Div([
                dcc.Markdown(
                    SIGNAL_GUIDE_TEXT,
                    style={"whiteSpace": "pre-wrap", "overflowY": "scroll", "height": "800px"},
                ),
            ])

        if selected_group == "Stress Score":
            raw2 = add_credit_ratio(raw)
            z = compute_zscore(raw2)
            MSS = compute_stress_score(z)
            if MSS.empty:
                return html.Div([
                    html.H3("Stress Score unavailable"),
                    html.P("Refresh in a few seconds.", style={"color": "orange"}),
                ])
            gauge = make_stress_gauge(MSS.iloc[-1]["Stress Score"], MSS["Stress Score"].mean())
            line = make_timeseries_panel(MSS, "Stress Score Trend")
            return html.Div([dcc.Graph(figure=gauge), dcc.Graph(figure=line)])

        if selected_group == "Volatility":
            return html.Div([dcc.Graph(figure=fig_volatility(raw))])

        if selected_group == "Credit Risk":
            raw2 = add_credit_ratio(raw)
            cols = ["HYG", "JNK", "LQD", "HYG/LQD"]
            existing = [c for c in cols if c in raw2.columns]
            if not existing:
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P("HYG/JNK/LQD were not returned by Yahoo Finance.", style={"color": "orange"}),
                ])
            df = raw2[existing].dropna()
            z = compute_zscore(df)
            return html.Div([
                dcc.Graph(figure=fig_credit_risk_levels(raw2)),
                dcc.Graph(figure=fig_credit_risk_zscore(z)),
            ])

        if selected_group == "Global Liquidity":
            return html.Div([dcc.Graph(figure=fig_global_liquidity(raw))])

        if selected_group == "Global Risk (EEM)":
            return html.Div([dcc.Graph(figure=fig_global_risk(raw))])

        # Generic panels
        raw2 = add_credit_ratio(raw)
        cols = RISK_TICKERS.get(selected_group, [])
        existing_cols = [c for c in cols if c in raw2.columns]
        if not existing_cols:
            return html.Div([
                html.H3("Data unavailable"),
                html.P("Required tickers were not returned by Yahoo Finance.", style={"color": "orange"}),
            ])
        df2 = raw2[existing_cols].dropna()
        z2 = compute_zscore(df2)
        return html.Div([
            dcc.Graph(figure=make_timeseries_panel(df2, f"{selected_group} — Levels")),
            dcc.Graph(figure=make_timeseries_panel(z2, f"{selected_group} — Z-Scores")),
        ])
