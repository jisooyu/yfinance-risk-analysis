import pandas as pd
from dash import html, dcc, Output, Input
from data_fetching import fetch_data, fetch_macro
from regime import build_regime_table, latest_regime_snapshot, REGIME_COLORS
from snapshot_history import load_snapshot_history
from research_utils import load_benchmark_prices, merge_snapshots_with_prices
from research_metrics import (
    add_forward_returns,
    build_regime_accuracy_table,
    build_regime_timeline_accuracy,
    build_stress_forward_table,
    build_stress_scatter_df,
)
from indicators import (
    compute_zscore,
    add_credit_ratio,
    compute_stress_score,
    rolling_zscore_obs,
    build_indicators,
    add_spreads,
)
from figures import (
    make_timeseries_panel,
    fig_regime_state,
    make_stress_gauge,
    fig_us2y_jp2y_with_lines,
    fig_volatility,
    fig_liquidity,
    fig_rrpz,
    fig_m2slz,
    fig_wrmfnsz,
    fig_totresnsz,
    fig_wresbal,
    fig_credit_risk_levels,
    fig_credit_risk_zscore,
    fig_spread_3m_2y_with_lines,
    fig_spread_3m_10y_with_lines,
    fig_global_liquidity,
    fig_global_risk,
    fig_regime_accuracy_bar,
    fig_regime_accuracy_timeline,
    fig_stress_vs_forward_scatter,
    fig_stress_forward_bar,
)
from signal_guide import SIGNAL_GUIDE_TEXT
from snapshot_store import upsert_daily_snapshot

TREASURY_TITLE = {
    ("US3M", "US2Y"): "Treasury Yields — 3M vs 2Y (%, FRED)",
    ("US3M", "US10Y"): "Treasury Yields — 3M vs 10Y (%, FRED)",
    ("US2Y", "US10Y"): "Treasury Yields — 2Y vs 10Y (%, FRED)",
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
    needed = [left, right]
    missing = _missing_cols(raw, needed)
    if missing:
        return html.Div([
            html.H3("Data unavailable"),
            html.P(
                f"Missing columns: {missing}. raw has: {list(raw.columns)[:25]} ...",
                style={"color": "orange"},
            ),
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
TAB_REGIME_ACCURACY = "Historical Regime Accuracy"
TAB_STRESS_FWD = "Stress vs Forward Returns"

def register_callbacks(app, RISK_TICKERS):

    @app.callback(
        Output("panel-output", "children"),
        Input("tabs", "value"),
        Input("refresh", "n_intervals"),
    )
    def update_panel(selected_group, n):

        # =====================================================
        # 0) Fetch once
        # =====================================================
        raw = fetch_data(RISK_TICKERS, period="5y")
        regime_df = build_regime_table(raw)
        # regime_df.to_excel("./excel_file/regime_df.xlsx")
        snapshot = latest_regime_snapshot(regime_df)
                # =====================================================
        # 0.5) Persist latest daily snapshot to SQLite
        # =====================================================
        if regime_df is not None and not regime_df.empty:
            latest_row = regime_df.dropna(how="all").iloc[-1]
            snapshot_date = pd.Timestamp(latest_row.name).strftime("%Y-%m-%d")

            upsert_daily_snapshot(
                snapshot_date=snapshot_date,
                regime_label=latest_row["regime_label"],
                regime_score=latest_row["regime_score"],
                regime_confidence=latest_row["regime_confidence"],
                trade_allowed=latest_row["trade_allowed"],
                size_mult=latest_row["size_mult"],
                transition_alert=latest_row["transition_alert"],
                stress_score=latest_row["StressScore_z"],
                liquidity_score=latest_row["LiquidityScore_z"],
                hyg_lqd_z=latest_row["HYG_LQD_z"],
                hy_oas_z=latest_row["HY_OAS_z"],
            )
        # Example policy
        if not snapshot["trade_allowed"]:
            print("No new risk.")
        elif snapshot["regime_confidence"] < 0.45:
            print("Reduce exposure. Signals disagree.")
        else:
            base_size = 1.0
            actual_size = base_size * snapshot["size_mult"]
            print(f"Trading allowed. Size multiplier = {actual_size:.2f}")

        # =====================================================
        # 1) Spread tabs
        # =====================================================
        if selected_group == TAB_REGIME_ACCURACY:
            hist = load_snapshot_history()
            if hist.empty:
                return html.Div([
                    html.H3("Historical Regime Accuracy"),
                    html.P("No snapshot history found in SQLite.", style={"color": "orange"}),
                ])

            prices = load_benchmark_prices("SPY", period="10y")
            merged = merge_snapshots_with_prices(hist, prices)

            if merged.empty:
                return html.Div([
                    html.H3("Historical Regime Accuracy"),
                    html.P("Could not align snapshot history with benchmark prices.", style={"color": "orange"}),
                ])

            merged = add_forward_returns(merged, horizons=(21,))
            acc_df = build_regime_accuracy_table(merged, horizon=21)
            timeline_df = build_regime_timeline_accuracy(merged, horizon=21)

            acc_table = html.Table([
                html.Thead(
                    html.Tr([html.Th("Regime"), html.Th("Obs"), html.Th("Hit Rate"), html.Th("Avg 21D Fwd"), html.Th("Avg Confidence")])
                ),
                html.Tbody([
                    html.Tr([
                        html.Td(idx),
                        html.Td("" if pd.isna(row["observations"]) else int(row["observations"])),
                        html.Td("" if pd.isna(row["hit_rate"]) else f"{row['hit_rate']:.1%}"),
                        html.Td("" if pd.isna(row["avg_forward_return"]) else f"{row['avg_forward_return']:.1%}"),
                        html.Td("" if pd.isna(row["avg_confidence"]) else f"{row['avg_confidence']:.2f}"),
                    ])
                    for idx, row in acc_df.iterrows()
                ])
            ], style={"width": "100%", "marginTop": "16px"})

            return html.Div([
                html.H3("Historical Regime Accuracy"),
                html.P("Benchmark: SPY, horizon: 21 trading days"),
                dcc.Graph(figure=fig_regime_accuracy_bar(acc_df)),
                dcc.Graph(figure=fig_regime_accuracy_timeline(timeline_df)),
                acc_table,
            ])

        if selected_group == TAB_STRESS_FWD:
            hist = load_snapshot_history()
            if hist.empty:
                return html.Div([
                    html.H3("Stress vs Forward Returns"),
                    html.P("No snapshot history found in SQLite.", style={"color": "orange"}),
                ])

            prices = load_benchmark_prices("SPY", period="10y")
            merged = merge_snapshots_with_prices(hist, prices)

            if merged.empty:
                return html.Div([
                    html.H3("Stress vs Forward Returns"),
                    html.P("Could not align snapshot history with benchmark prices.", style={"color": "orange"}),
                ])

            merged = add_forward_returns(merged, horizons=(21,))
            stress_table = build_stress_forward_table(
                merged,
                stress_col="stress_score",
                horizon=21,
            )
            scatter_df = build_stress_scatter_df(
                merged,
                stress_col="stress_score",
                horizon=21,
            )

            summary_table = html.Table([
                html.Thead(
                    html.Tr([html.Th("Stress Bucket"), html.Th("Obs"), html.Th("Avg 21D Fwd"), html.Th("Median 21D Fwd"), html.Th("Vol")])
                ),
                html.Tbody([
                    html.Tr([
                        html.Td(str(idx)),
                        html.Td("" if pd.isna(row["observations"]) else int(row["observations"])),
                        html.Td("" if pd.isna(row["avg_forward_return"]) else f"{row['avg_forward_return']:.1%}"),
                        html.Td("" if pd.isna(row["median_forward_return"]) else f"{row['median_forward_return']:.1%}"),
                        html.Td("" if pd.isna(row["vol_forward_return"]) else f"{row['vol_forward_return']:.1%}"),
                    ])
                    for idx, row in stress_table.iterrows()
                ])
            ], style={"width": "100%", "marginTop": "16px"})

            return html.Div([
                html.H3("Stress vs Forward Returns"),
                html.P("Benchmark: SPY, horizon: 21 trading days"),
                dcc.Graph(figure=fig_stress_vs_forward_scatter(scatter_df, stress_col="stress_score", horizon=21)),
                dcc.Graph(figure=fig_stress_forward_bar(stress_table)),
                summary_table,
            ])
        if selected_group == "Regime Monitor":
            if regime_df.empty:
                return html.Div([
                    html.H3("Regime unavailable"),
                    html.P("No regime data could be built.", style={"color": "orange"}),
                ])

            latest = regime_df.dropna(how="all").iloc[-1]
            status_color = {
                # "risk_on": "#2ca02c",
                "risk_on": REGIME_COLORS.get("risk_on"),
                "neutral": REGIME_COLORS.get("neutral"),
                "caution": REGIME_COLORS.get("caution"),
                "risk_off": REGIME_COLORS.get("risk_off"),
                "crisis": REGIME_COLORS.get("crisis"),
            }.get(latest["regime_label"], "#aaaaaa")

            latest_card = html.Div(
                style={
                    "padding": "16px",
                    "border": f"2px solid {status_color}",
                    "borderRadius": "12px",
                    "marginBottom": "18px",
                    "backgroundColor": "rgba(255,255,255,0.03)",
                },
                children=[
                    html.H3("Current Regime"),
                    html.H2(
                        latest["regime_label"].replace("_", " ").title(),
                        style={"color": status_color},
                    ),
                    html.P(f"Regime Score: {latest['regime_score']:.2f}"),
                    html.P(f"Confidence: {latest['regime_confidence']:.2f}"),
                    html.P(f"Trade Allowed: {bool(latest['trade_allowed'])}"),
                    html.P(f"Size Multiplier: {latest['size_mult']:.2f}"),
                    html.P(f"Transition Alert: {bool(latest['transition_alert'])}"),
                ],
            )

            regime_line = regime_df[["regime_score"]].copy()
            conf_line = regime_df[["regime_confidence"]].copy()

            return html.Div([
                latest_card,
                dcc.Graph(figure=make_timeseries_panel(regime_line, "Regime Score")),
                dcc.Graph(figure=make_timeseries_panel(conf_line, "Regime Confidence")),
                dcc.Graph(figure=fig_regime_state(regime_df)),
            ])
        if selected_group == TAB_3M2Y:
            return render_treasury_spread_panel(
                raw,
                left="US3M",
                right="US2Y",
                spread_name="2Y - 3M (pp)",
                spread_fig_fn=fig_spread_3m_2y_with_lines,
                levels_title="Treasury Yields — 3M vs 2Y (%, FRED)",
            )

        if selected_group == TAB_3M10Y:
            return render_treasury_spread_panel(
                raw,
                left="US3M",
                right="US10Y",
                spread_name="10Y - 3M (pp)",
                spread_fig_fn=fig_spread_3m_10y_with_lines,
                levels_title="Treasury Yields — 3M vs 10Y (%, FRED)",
            )

        if selected_group == TAB_2Y10Y:
            needed = ["US2Y", "US10Y"]
            missing = _missing_cols(raw, needed)
            if missing:
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P(f"Missing columns: {missing}", style={"color": "orange"}),
                ])

            y = raw[needed].dropna()
            spread = (y["US10Y"] - y["US2Y"]).to_frame("10Y - 2Y (pp)")
            return html.Div([
                dcc.Graph(
                    figure=make_timeseries_panel(
                        y, "Treasury Yields — 2Y vs 10Y (%, FRED)"
                    )
                ),
                dcc.Graph(
                    figure=make_timeseries_panel(
                        spread,
                        "Yield Spread — 10Y minus 2Y (percentage points)",
                    )
                ),
            ])

        if selected_group == TAB_US_JP:
            try:
                macro_raw = fetch_macro(start="2015-01-01")
                ind_build = build_indicators(macro_raw)
                ind = add_spreads(ind_build)
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
        # 2) Other tabs
        # =====================================================
        if selected_group == "Signal Guide":
            return html.Div([
                dcc.Markdown(
                    SIGNAL_GUIDE_TEXT,
                    style={
                        "whiteSpace": "pre-wrap",
                        "overflowY": "scroll",
                        "height": "800px",
                    },
                ),
            ])

        if selected_group == "Stress Score":
            raw2 = add_credit_ratio(raw)

            # 🔥 핵심 변경
            z = compute_zscore(raw2, method="rolling", window_obs=252)
            MSS = compute_stress_score(z)
            if MSS.empty:
                return html.Div([
                    html.H3("Stress Score unavailable"),
                    html.P("Refresh in a few seconds.", style={"color": "orange"}),
                ])

            gauge = make_stress_gauge(
                MSS.iloc[-1]["Stress Score"],
                MSS["Stress Score"].mean()
            )

            line = make_timeseries_panel(MSS, "Stress Score Trend")

            return html.Div([
                dcc.Graph(figure=gauge),
                dcc.Graph(figure=line)
            ])

        if selected_group == "Volatility":
            return html.Div([dcc.Graph(figure=fig_volatility(raw))])

        if selected_group == "Liquidity":
            raw3 = add_credit_ratio(raw).copy()

            # -----------------------------
            # 1) Native-frequency display series
            # -----------------------------
            rrp_s = raw3["RRP"].dropna().copy()
            hy_s = raw3["HY_OAS"].dropna().copy()
            ratio_s = raw3["HYG/LQD"].dropna().copy()

            mmf_s = raw3["MMF"].dropna().resample("W-FRI").last()
            # wres_s = raw3["RESERVES_PROXY"].dropna().resample("W-FRI").last()
            wres_s = raw3["RESERVES_PROXY"].dropna()
            m2_s = raw3["M2"].dropna().resample("MS").last()
            totres_s = raw3["RESERVES"].dropna().resample("MS").last()

            # FRED 최신 날짜까지 포함되는 전체 index 유지
            display = pd.DataFrame(index=raw3.index)
            display["RESERVES_PROXY Weekly (z)"] = rolling_zscore_obs(
                wres_s,
                window_obs=52,   # 약 1년 (weekly)
                min_obs=26       # 최소 6개월
            )
            display = display.sort_index()
   
            display["RRP (z)"] = rolling_zscore_obs(rrp_s, window_obs=60, min_obs=30)
            display["HY_OAS (z)"] = rolling_zscore_obs(hy_s, window_obs=60, min_obs=30)
            display["HYG/LQD (z)"] = rolling_zscore_obs(ratio_s, window_obs=126, min_obs=63)
            display["MMF (z)"] = rolling_zscore_obs(mmf_s, window_obs=104, min_obs=26)
            display["RESERVES_PROXY Weekly (z)"] = rolling_zscore_obs(
                wres_s, window_obs=52, min_obs=26
            )
            display["M2 (z)"] = rolling_zscore_obs(m2_s, window_obs=24, min_obs=12)
            display["RESERVES Monthly (z)"] = rolling_zscore_obs(
                totres_s, window_obs=24, min_obs=12
            )

            display = display.sort_index()

            # -----------------------------
            # 2) Composite score inputs
            # -----------------------------
            score_inputs = display[
                [
                    "RRP (z)",
                    "HY_OAS (z)",
                    "RESERVES_PROXY Weekly (z)",
                    "MMF (z)",
                    "RESERVES Monthly (z)",
                    "M2 (z)",
                    "HYG/LQD (z)",
                ]
            ].copy()

            fill_limits = {
                "RRP (z)": 10,
                "HY_OAS (z)": 10,
                "RESERVES_PROXY Weekly (z)": 10,
                "MMF (z)": 15,
                "RESERVES Monthly (z)": 45,
                "M2 (z)": 45,
                "HYG/LQD (z)": 5,
            }

            for col, lim in fill_limits.items():
                score_inputs[col] = score_inputs[col].ffill(limit=lim)

            liquidity_score = (
                score_inputs["MMF (z)"]
                + score_inputs["RRP (z)"]
                + score_inputs["M2 (z)"]
                + score_inputs["RESERVES Monthly (z)"] * 0.3
                + score_inputs["RESERVES_PROXY Weekly (z)"] * 0.7
                - score_inputs["HY_OAS (z)"]
                + score_inputs["HYG/LQD (z)"] * 0.5
            ).rename("LiquidityScore")

            liquidity_score_z = rolling_zscore_obs(
                liquidity_score,
                window_obs=60,
                min_obs=30,
            ).rename("LiquidityScore")

            liquidity_panel_df = pd.concat(
                [display, liquidity_score_z],
                axis=1,
            ).sort_index()

            return html.Div([
                dcc.Graph(figure=fig_liquidity(liquidity_panel_df)),
                dcc.Graph(figure=fig_wrmfnsz(liquidity_panel_df)),
                dcc.Graph(figure=fig_rrpz(liquidity_panel_df)),
                dcc.Graph(figure=fig_m2slz(liquidity_panel_df)),
                dcc.Graph(figure=fig_totresnsz(liquidity_panel_df)),
                dcc.Graph(figure=fig_wresbal(liquidity_panel_df)),
            ])

        if selected_group == "Credit Risk":
            raw2 = add_credit_ratio(raw)
            cols = ["HYG", "JNK", "LQD", "HY_OAS", "HYG/LQD"]
            existing = [c for c in cols if c in raw2.columns]

            if not existing:
                return html.Div([
                    html.H3("Data unavailable"),
                    html.P(
                        "HYG/JNK/LQD were not returned by Yahoo Finance.",
                        style={"color": "orange"},
                    ),
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
                html.P(
                    "Required tickers were not returned by Yahoo Finance.",
                    style={"color": "orange"},
                ),
            ])

        df2 = raw2[existing_cols].dropna()
        z2 = compute_zscore(df2)

        return html.Div([
            dcc.Graph(figure=make_timeseries_panel(df2, f"{selected_group} — Levels")),
            dcc.Graph(figure=make_timeseries_panel(z2, f"{selected_group} — Z-Scores")),
        ])