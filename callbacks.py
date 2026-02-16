# callbacks.py
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
        # 1) Spread tabs FIRST (avoid falling into Yahoo panels)
        # =====================================================
        # --- 3mo–2y Spread (FRED columns already merged in fetch_data) ---
        if selected_group == TAB_3M2Y:
            raw = fetch_data(RISK_TICKERS)

            needed = ["DGS3MO", "DGS2"]
            if any(c not in raw.columns for c in needed):
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P(f"Missing columns: {needed}. raw has: {list(raw.columns)[:25]} ...",
                           style={"color": "orange"}),
                ])

            y = raw[needed].dropna()
            spread = (y["DGS2"] - y["DGS3MO"]).to_frame("2Y - 3M (pp)")

            return html.Div([
                dcc.Graph(figure=make_timeseries_panel(y, "Treasury Yields — 3M vs 2Y (%, FRED)")),
                dcc.Graph(figure=fig_spread_3m_2y_with_lines(spread)),
            ])
        # --- 3mo–10y Spread (FRED columns already merged in fetch_data) ---
        if selected_group == TAB_3M10Y:
            raw = fetch_data(RISK_TICKERS)

            needed = ["DGS3MO", "DGS10"]
            if any(c not in raw.columns for c in needed):
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P(f"Missing columns: {needed}. raw has: {list(raw.columns)[:25]} ...",
                           style={"color": "orange"}),
                ])

            y = raw[needed].dropna()
            spread = (y["DGS10"] - y["DGS3MO"]).to_frame("10Y - 3M (pp)")

            return html.Div([
                dcc.Graph(figure=make_timeseries_panel(y, "Treasury Yields — 3M vs 10Y (%, FRED)")),
                dcc.Graph(figure=fig_spread_3m_10y_with_lines(spread)),
            ])

        # --- US 2y - JP 2y Spread (macro pipeline) ---
        if selected_group == TAB_US_JP:
            try:
                macro_raw = fetch_macro(start="2015-01-01")
                ind = build_indicators(macro_raw)   # must output US2Y, JP2Y (+ optional 3M)
                ind = add_spreads(ind)              # adds spread_us2y_jp2y (+ optional spread_3m_2y)
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

            return html.Div([
                dcc.Graph(figure=fig_us2y_jp2y_with_lines(ind)),
            ])

        # =====================================================
        # 2) Fetch market data for everything else
        # =====================================================
        raw = fetch_data(RISK_TICKERS)

        # =====================================================
        # Signal Guide
        # =====================================================
        if selected_group == "Signal Guide":
            return html.Div([
                dcc.Markdown(
                    SIGNAL_GUIDE_TEXT,
                    style={"whiteSpace": "pre-wrap", "overflowY": "scroll", "height": "800px"},
                ),
            ])

        # =====================================================
        # Stress Score
        # =====================================================
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
            return html.Div([
                dcc.Graph(figure=gauge), dcc.Graph(figure=line)])

        # =====================================================
        # Volatility (with watch/danger lines)
        # =====================================================
        if selected_group == "Volatility":
            # Uses fig_volatility which expects '^VIX' and/or '^VXN' columns
            return html.Div([
                dcc.Graph(figure=fig_volatility(raw)),
            ])

        # =====================================================
        # Credit Risk (levels + zscore with watch/danger lines)
        # =====================================================
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
        # =====================================================
        # Global Liquidity (with watch/danger lines)
        # =====================================================
        if selected_group == "Global Liquidity":
            return html.Div([
                dcc.Graph(figure=fig_global_liquidity(raw)),
            ])

        # =====================================================
        # Global Risk (EEM) (with watch/danger lines)
        # =====================================================
        if selected_group == "Global Risk (EEM)":
            return html.Div([
                dcc.Graph(figure=fig_global_risk(raw)),
            ])

        # =====================================================
        # 2y–10y Spread (FRED)
        # =====================================================
        if selected_group == TAB_2Y10Y:
            needed = ["DGS2", "DGS10"]
            if any(c not in raw.columns for c in needed):
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P("FRED yields (DGS2, DGS10) were not returned.", style={"color": "orange"}),
                ])

            y = raw[needed].dropna()
            spread = (y["DGS10"] - y["DGS2"]).to_frame("10Y - 2Y (pp)")
            return html.Div([
                dcc.Graph(figure=make_timeseries_panel(y, "Treasury Yields — 2Y vs 10Y (%, FRED)")),
                dcc.Graph(figure=make_timeseries_panel(spread, "Yield Spread — 10Y minus 2Y (percentage points)")),
            ])

        # =====================================================
        # Generic panels (everything else)
        # =====================================================
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