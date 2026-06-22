import io
import pandas as pd
from dash import html, dcc, Output, Input
from data_fetching import fetch_data
from regime import build_regime_table, latest_regime_snapshot, REGIME_COLORS
from snapshot_history import load_snapshot_history
from research_utils import load_benchmark_prices, merge_snapshots_with_prices
from research_metrics import (
    add_forward_returns,
    build_regime_accuracy_table,
    build_regime_timeline_accuracy,
    build_crisis_condition_summary,
    build_crisis_episode_table,
    build_stress_forward_table,
    build_stress_scatter_df,
)
from indicators import (
    compute_zscore,
    add_credit_ratio,
    compute_stress_score,
    rolling_zscore_obs,
)
from figures import (
    make_timeseries_panel,
    fig_regime_state,
    make_stress_gauge,
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
    fig_crisis_episode_returns,
    fig_stress_hit_rate_bar,
    fig_stress_vs_forward_scatter,
    fig_stress_forward_bar,
)
from snapshot_store import upsert_daily_snapshot, backfill_snapshots_from_regime_df
from telegram_utils import send_telegram_alert

TREASURY_TITLE = {
    ("US3M", "US2Y"): "Treasury Yields — 3M vs 2Y (%, FRED)",
    ("US3M", "US10Y"): "Treasury Yields — 3M vs 10Y (%, FRED)",
}

# tab titles
TAB_3M2Y = "3mo–2y Spread"
TAB_3M10Y = "3mo–10y Spread"
TAB_REGIME_ACCURACY = "Historical Regime Accuracy"
TAB_STRESS_FWD = "Stress vs Forward Returns"
TAB_REGIME_MONITOR = "Regime Monitor"
TAB_STRESS_SCORE = "Stress Score"
TAB_VOLATILITY = "Volatility"
TAB_LIQUIDITY = "Liquidity"

STORE_INDEX_COL = "__date__"
SENT_ALERT_KEYS = set()

def _send_telegram_once(alert_type: str, snapshot_date: str, message: str):
    alert_key = (alert_type, snapshot_date)
    if alert_key in SENT_ALERT_KEYS:
        return None
    result = send_telegram_alert(message)
    if isinstance(result, dict) and result.get("ok", False):
        SENT_ALERT_KEYS.add(alert_key)
    return result

def _pack_df(df: pd.DataFrame) -> str:
    out = df.reset_index()
    out = out.rename(columns={out.columns[0]: STORE_INDEX_COL})
    return out.to_json(date_format="iso", orient="split")

def _unpack_df(payload: str) -> pd.DataFrame:
    df = pd.read_json(io.StringIO(payload), orient="split")
    df[STORE_INDEX_COL] = pd.to_datetime(df[STORE_INDEX_COL], errors="coerce")
    return df.set_index(STORE_INDEX_COL).sort_index()

def _missing_cols(df, cols):
    return [c for c in cols if c not in df.columns]


def _require_recent_observation_density(
    s: pd.Series,
    *,
    lookback_days: int,
    min_observations: int,
) -> pd.Series:
    """
    Drop sparse historical observations before a daily-like series becomes active.
    Observation-based rolling stats can otherwise span multi-year gaps.
    """
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
    if s.empty:
        return s

    obs_count = (
        s.notna()
        .astype("int64")
        .rolling(f"{lookback_days}D", min_periods=1)
        .sum()
    )
    return s.loc[obs_count >= min_observations]


def build_recent_change_table(
    df: pd.DataFrame,
    title: str,
    *,
    months: int = 3,
    columns: list[str] | None = None,
    include_pct: bool = False,
    value_decimals: int = 2,
    change_decimals: int = 2,
    positive_color: str = "#ff6b6b",
    negative_color: str = "#55c878",
    note: str | None = None,
):
    if df is None or df.empty:
        return html.P(
            f"No recent data is available for {title}.",
            style={"color": "orange"},
        )

    if columns is None:
        columns = list(df.columns)

    cols = [c for c in columns if c in df.columns]
    if not cols:
        return html.P(
            f"No requested columns are available for {title}.",
            style={"color": "orange"},
        )

    levels = df[cols].apply(pd.to_numeric, errors="coerce").sort_index()
    changes = levels.diff()
    pct_changes = levels.pct_change(fill_method=None)

    latest_date = levels.dropna(how="all").index.max()
    if pd.isna(latest_date):
        return html.P(
            f"No usable recent data is available for {title}.",
            style={"color": "orange"},
        )

    cutoff = latest_date - pd.DateOffset(months=months)
    recent = levels.loc[levels.index >= cutoff].dropna(how="all").sort_index(ascending=False)

    def value_cell(value, decimals=2):
        return "" if pd.isna(value) else f"{value:.{decimals}f}"

    def change_cell(value, percent=False):
        if pd.isna(value):
            return html.Td("")
        color = positive_color if value > 0 else negative_color if value < 0 else "#dddddd"
        text = f"{value:+.2%}" if percent else f"{value:+.{change_decimals}f}"
        return html.Td(text, style={"color": color, "textAlign": "right"})

    header_style = {
        "position": "sticky",
        "top": "0",
        "backgroundColor": "#1e1e1e",
        "zIndex": "1",
        "padding": "8px",
        "borderBottom": "1px solid #555555",
        "textAlign": "right",
    }
    cell_style = {
        "padding": "6px 8px",
        "borderBottom": "1px solid #333333",
        "textAlign": "right",
    }

    headers = ["Date"]
    for col in cols:
        headers.extend([col, f"{col} Δ"])
        if include_pct:
            headers.append(f"{col} Δ%")

    rows = []
    for dt, row in recent.iterrows():
        cells = [
            html.Td(
                pd.Timestamp(dt).strftime("%Y-%m-%d"),
                style={**cell_style, "textAlign": "left"},
            )
        ]
        for col in cols:
            cells.append(html.Td(value_cell(row[col], value_decimals), style=cell_style))
            cells.append(change_cell(changes.loc[dt, col]))
            if include_pct:
                cells.append(change_cell(pct_changes.loc[dt, col], percent=True))
        rows.append(html.Tr(cells))

    if note is None:
        note = "Daily values and changes versus the previous trading day."

    return html.Div(
        [
            html.H3(title),
            html.P(note),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th(
                                        header,
                                        style={
                                            **header_style,
                                            "textAlign": "left" if header == "Date" else "right",
                                        },
                                    )
                                    for header in headers
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    style={
                        "width": "100%",
                        "borderCollapse": "collapse",
                        "fontVariantNumeric": "tabular-nums",
                    },
                ),
                style={
                    "maxHeight": "520px",
                    "overflowY": "auto",
                    "overflowX": "auto",
                    "border": "1px solid #444444",
                    "borderRadius": "6px",
                },
            ),
        ],
        style={"marginTop": "18px"},
    )


def build_recent_volatility_table(raw: pd.DataFrame, months: int = 3):
    return build_recent_change_table(
        raw,
        "Recent 3-Month Volatility Values",
        months=months,
        columns=["^VIX", "^VXN"],
        include_pct=True,
        note=(
            "Daily closes and changes versus the previous trading day. "
            "Red indicates rising volatility; green indicates falling volatility."
        ),
    )


def build_recent_stress_table(stress_df: pd.DataFrame, months: int = 3):
    if "Stress Score" not in stress_df.columns:
        return html.P(
            "No Stress Score history is available.",
            style={"color": "orange"},
        )

    scores = pd.to_numeric(
        stress_df["Stress Score"],
        errors="coerce",
    ).sort_index()
    changes = scores.diff()
    buckets = pd.cut(
        scores,
        bins=[float("-inf"), -1, 0, 1, 2, float("inf")],
        labels=["Very Easy", "Easy", "Normal", "Stress", "Crisis"],
    )

    latest_date = scores.dropna().index.max()
    cutoff = latest_date - pd.DateOffset(months=months)
    recent = scores.loc[scores.index >= cutoff].dropna().sort_index(ascending=False)

    header_style = {
        "position": "sticky",
        "top": "0",
        "backgroundColor": "#1e1e1e",
        "zIndex": "1",
        "padding": "8px",
        "borderBottom": "1px solid #555555",
    }
    cell_style = {
        "padding": "6px 8px",
        "borderBottom": "1px solid #333333",
    }

    rows = []
    for dt, value in recent.items():
        change = changes.loc[dt]
        change_color = (
            "#ff6b6b" if change > 0 else "#55c878" if change < 0 else "#dddddd"
        )
        rows.append(
            html.Tr(
                [
                    html.Td(
                        pd.Timestamp(dt).strftime("%Y-%m-%d"),
                        style={**cell_style, "textAlign": "left"},
                    ),
                    html.Td(f"{value:.3f}", style={**cell_style, "textAlign": "right"}),
                    html.Td(
                        "" if pd.isna(change) else f"{change:+.3f}",
                        style={
                            **cell_style,
                            "textAlign": "right",
                            "color": change_color,
                        },
                    ),
                    html.Td(
                        str(buckets.loc[dt]),
                        style={**cell_style, "textAlign": "left"},
                    ),
                ]
            )
        )

    headers = ["Date", "Stress Score", "Daily Δ", "Stress Bucket"]
    return html.Div(
        [
            html.H3("Recent 3-Month Stress Score Values"),
            html.P(
                "Daily Stress Score and change versus the previous trading day. "
                "Red indicates rising stress; green indicates falling stress. "
                "Buckets are based on Stress Score: Very Easy <= -1; Easy (-1, 0]; "
                "Normal (0, 1]; Stress (1, 2]; Crisis > 2."
            ),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th(
                                        header,
                                        style={
                                            **header_style,
                                            "textAlign": (
                                                "right"
                                                if header in ["Stress Score", "Daily Δ"]
                                                else "left"
                                            ),
                                        },
                                    )
                                    for header in headers
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    style={
                        "width": "100%",
                        "borderCollapse": "collapse",
                        "fontVariantNumeric": "tabular-nums",
                    },
                ),
                style={
                    "maxHeight": "520px",
                    "overflowY": "auto",
                    "overflowX": "auto",
                    "border": "1px solid #444444",
                    "borderRadius": "6px",
                },
            ),
        ],
        style={"marginTop": "18px"},
    )


def build_recent_regime_table(regime_df: pd.DataFrame, months: int = 3):
    if regime_df is None or regime_df.empty:
        return html.P(
            "No regime history is available.",
            style={"color": "orange"},
        )

    df = regime_df.copy().sort_index()
    latest_date = df.dropna(how="all").index.max()
    if pd.isna(latest_date):
        return html.P(
            "No usable regime history is available.",
            style={"color": "orange"},
        )

    cutoff = latest_date - pd.DateOffset(months=months)
    recent = df.loc[df.index >= cutoff].dropna(how="all").sort_index(ascending=False)
    score_changes = pd.to_numeric(df.get("regime_score"), errors="coerce").diff()

    header_style = {
        "position": "sticky",
        "top": "0",
        "backgroundColor": "#1e1e1e",
        "zIndex": "1",
        "padding": "8px",
        "borderBottom": "1px solid #555555",
    }
    cell_style = {
        "padding": "6px 8px",
        "borderBottom": "1px solid #333333",
    }

    def fmt_num(value, decimals=2):
        return "" if pd.isna(value) else f"{value:.{decimals}f}"

    def fmt_bool(value):
        if pd.isna(value):
            return ""
        return "Yes" if bool(value) else "No"

    rows = []
    for dt, row in recent.iterrows():
        label = row.get("regime_label", "")
        label_color = REGIME_COLORS.get(label, "#dddddd")
        change = score_changes.loc[dt] if dt in score_changes.index else pd.NA
        change_color = "#55c878" if change > 0 else "#ff6b6b" if change < 0 else "#dddddd"
        rows.append(
            html.Tr(
                [
                    html.Td(
                        pd.Timestamp(dt).strftime("%Y-%m-%d"),
                        style={**cell_style, "textAlign": "left"},
                    ),
                    html.Td(
                        str(label).replace("_", " ").title(),
                        style={**cell_style, "textAlign": "left", "color": label_color},
                    ),
                    html.Td(
                        fmt_num(row.get("regime_score")),
                        style={**cell_style, "textAlign": "right"},
                    ),
                    html.Td(
                        "" if pd.isna(change) else f"{change:+.2f}",
                        style={
                            **cell_style,
                            "textAlign": "right",
                            "color": change_color,
                        },
                    ),
                    html.Td(
                        fmt_num(row.get("regime_confidence")),
                        style={**cell_style, "textAlign": "right"},
                    ),
                    html.Td(
                        fmt_num(row.get("size_mult")),
                        style={**cell_style, "textAlign": "right"},
                    ),
                    html.Td(
                        fmt_bool(row.get("trade_allowed")),
                        style={**cell_style, "textAlign": "center"},
                    ),
                    html.Td(
                        fmt_bool(row.get("transition_alert")),
                        style={**cell_style, "textAlign": "center"},
                    ),
                ]
            )
        )

    headers = [
        "Date",
        "Regime",
        "Regime Score",
        "Score Δ",
        "Confidence",
        "Size Mult",
        "Trade Allowed",
        "Transition",
    ]
    right_headers = {"Regime Score", "Score Δ", "Confidence", "Size Mult"}
    center_headers = {"Trade Allowed", "Transition"}

    return html.Div(
        [
            html.H3("Recent 3-Month Regime Monitor Values"),
            html.P(
                "Daily regime classification and key regime metrics. "
                "Green Score Δ indicates regime improvement; red indicates deterioration."
            ),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th(
                                        header,
                                        style={
                                            **header_style,
                                            "textAlign": (
                                                "right"
                                                if header in right_headers
                                                else "center"
                                                if header in center_headers
                                                else "left"
                                            ),
                                        },
                                    )
                                    for header in headers
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    style={
                        "width": "100%",
                        "borderCollapse": "collapse",
                        "fontVariantNumeric": "tabular-nums",
                    },
                ),
                style={
                    "maxHeight": "520px",
                    "overflowY": "auto",
                    "overflowX": "auto",
                    "border": "1px solid #444444",
                    "borderRadius": "6px",
                },
            ),
        ],
        style={"marginTop": "18px"},
    )


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
        build_recent_change_table(
            y.join(spread, how="outer"),
            f"Recent 3-Month {spread_name} Values",
            months=3,
            value_decimals=3,
            change_decimals=3,
        ),
    ])


def register_callbacks(app, RISK_TICKERS):

    @app.callback(
        Output("store-raw", "data"),
        Output("store-regime", "data"),
        Output("store-snapshot", "data"),
        Input("refresh", "n_intervals"),
    )
    def refresh_data(n):
        raw = fetch_data(RISK_TICKERS, period="max")
        regime_df = build_regime_table(raw)
        regime_df = regime_df.loc["2011-01-01":]
        snapshot = latest_regime_snapshot(regime_df)
        latest_snapshot_date = None

        backfill_snapshots_from_regime_df(regime_df)

        if regime_df is not None and not regime_df.empty:
            latest_row = regime_df.dropna(how="all").iloc[-1]
            snapshot_date = pd.Timestamp(latest_row.name).strftime("%Y-%m-%d")
            latest_snapshot_date = snapshot_date

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
            if bool(latest_row["transition_alert"]):
                _send_telegram_once(
                    "transition_alert",
                    snapshot_date,
                    f"Transition alert detected\n"
                    f"Date: {snapshot_date}\n"
                    f"Regime: {latest_row['regime_label']}\n"
                    f"Stress Score: {latest_row['StressScore_z']:.2f}\n"
                    f"Liquidity Score: {latest_row['LiquidityScore_z']:.2f}"
                )

        if not snapshot["trade_allowed"]:
            message = "No new risk."
            print(message)
            _send_telegram_once(
                "trade_blocked",
                latest_snapshot_date or "latest",
                message,
            )

        elif snapshot["regime_confidence"] < 0.45:
            message = "Reduce exposure. Signals disagree."
            print(message)
            _send_telegram_once(
                "low_confidence",
                latest_snapshot_date or "latest",
                message,
            )
        else:
            base_size = 1.0
            actual_size = base_size * snapshot["size_mult"]
            message = f"Trading allowed. Size multiplier = {actual_size:.2f}"
            print(message)
            _send_telegram_once(
                "trading_allowed",
                latest_snapshot_date or "latest",
                message,
            )

        return (
            _pack_df(raw),
            _pack_df(regime_df),
            pd.DataFrame([snapshot]).to_json(date_format="iso", orient="split"),
        )

    @app.callback(
        Output("panel-output", "children"),
        Input("tabs", "value"),
        Input("store-raw", "data"),
        Input("store-regime", "data"),
        Input("store-snapshot", "data"),
    )
    def update_panel(selected_group, raw_json, regime_json, snapshot_json):
        if not raw_json or not regime_json or not snapshot_json:
            return html.Div([
                html.H3("Loading"),
                html.P("Data is being prepared...", style={"color": "orange"}),
            ])
        raw = _unpack_df(raw_json)
        regime_df = _unpack_df(regime_json)

        raw.index = pd.to_datetime(raw.index)
        regime_df.index = pd.to_datetime(regime_df.index)

    # keep your existing tab logic here
        # =====================================================
        # 1) Regime tabs
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
            valid_21d = merged["fwd_21d"].dropna()
            if len(valid_21d) < 10:
                return html.Div([
                    html.H3("Historical Regime Accuracy"),
                    html.P(
                        f"Not enough snapshot history yet. Need more than 21 daily rows for 21-day forward returns. "
                        f"Currently usable rows: {len(valid_21d)}",
                        style={"color": "orange"},
                    ),
                ])
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
                html.P(
                    "Hit Rate measures whether each regime's expected direction matched "
                    "the subsequent SPY return. Risk On, Neutral, and Caution count as hits "
                    "when SPY rises; Risk Off and Crisis count as hits when SPY is flat or "
                    "falls. This regime-direction accuracy is different from the stress_score-"
                    "based rebound analysis in Stress vs Forward Returns, where a rise after "
                    "high stress counts as a positive outcome."
                ),
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

            prices = load_benchmark_prices("SPY", period="max")
            prices = prices.loc["2011-01-01":]
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
            episode_df = build_crisis_episode_table(
                merged,
                stress_col="stress_score",
                horizon=21,
                threshold=2.0,
                regime="crisis",
            )
            condition_summary = build_crisis_condition_summary(
                merged,
                episode_df,
                stress_col="stress_score",
                horizon=21,
                threshold=2.0,
                regime="crisis",
            )
            scatter_df = build_stress_scatter_df(
                merged,
                stress_col="stress_score",
                horizon=21,
            )

            def metric_card(title, value, note):
                return html.Div(
                    [
                        html.Div(title, style={"color": "#aaaaaa", "fontSize": "13px"}),
                        html.Div(value, style={"fontSize": "25px", "fontWeight": "600"}),
                        html.Div(note, style={"color": "#aaaaaa", "fontSize": "12px"}),
                    ],
                    style={
                        "padding": "14px",
                        "border": "1px solid #444444",
                        "borderRadius": "8px",
                        "backgroundColor": "rgba(255,255,255,0.03)",
                        "minWidth": "170px",
                        "flex": "1",
                    },
                )

            def format_pct(value):
                return "N/A" if pd.isna(value) else f"{value:.1%}"

            metric_cards = html.Div(
                [
                    metric_card(
                        "Daily signal hit rate",
                        format_pct(condition_summary["daily_hit_rate"]),
                        f"{condition_summary['daily_observations']} overlapping daily observations",
                    ),
                    metric_card(
                        "Other days hit rate",
                        format_pct(condition_summary["other_hit_rate"]),
                        "All other valid observations",
                    ),
                    metric_card(
                        "Independent episodes",
                        str(condition_summary["episode_count"]),
                        "Signals within 21 trading days are grouped",
                    ),
                    metric_card(
                        "Episode hit rate",
                        format_pct(condition_summary["episode_hit_rate"]),
                        f"Average return {format_pct(condition_summary['episode_avg_return'])}",
                    ),
                    metric_card(
                        "Worst forward drawdown",
                        format_pct(condition_summary["episode_worst_drawdown"]),
                        "Lowest point during the following 21 trading days",
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "10px",
                    "flexWrap": "wrap",
                    "margin": "14px 0 18px",
                },
            )

            summary_table = html.Table([
                html.Thead(
                    html.Tr([
                        html.Th("Stress Bucket"),
                        html.Th("Obs"),
                        html.Th("Up Probability"),
                        html.Th("Avg 21D Fwd"),
                        html.Th("Median 21D Fwd"),
                        html.Th("Worst 21D Fwd"),
                        html.Th("Vol"),
                    ])
                ),
                html.Tbody([
                    html.Tr([
                        html.Td(str(idx)),
                        html.Td("" if pd.isna(row["observations"]) else int(row["observations"])),
                        html.Td("" if pd.isna(row["hit_rate"]) else f"{row['hit_rate']:.1%}"),
                        html.Td("" if pd.isna(row["avg_forward_return"]) else f"{row['avg_forward_return']:.1%}"),
                        html.Td("" if pd.isna(row["median_forward_return"]) else f"{row['median_forward_return']:.1%}"),
                        html.Td("" if pd.isna(row["worst_forward_return"]) else f"{row['worst_forward_return']:.1%}"),
                        html.Td("" if pd.isna(row["vol_forward_return"]) else f"{row['vol_forward_return']:.1%}"),
                    ])
                    for idx, row in stress_table.iterrows()
                ])
            ], style={"width": "100%", "marginTop": "16px"})

            episode_table = html.Table([
                html.Thead(
                    html.Tr([
                        html.Th("Episode"),
                        html.Th("Start"),
                        html.Th("End"),
                        html.Th("Peak Signal"),
                        html.Th("Signal Days"),
                        html.Th("Peak Stress"),
                        html.Th("21D Return"),
                        html.Th("Forward Max Drawdown"),
                    ])
                ),
                html.Tbody([
                    html.Tr([
                        html.Td(int(idx)),
                        html.Td(pd.Timestamp(row["start_date"]).strftime("%Y-%m-%d")),
                        html.Td(pd.Timestamp(row["end_date"]).strftime("%Y-%m-%d")),
                        html.Td(pd.Timestamp(row["signal_date"]).strftime("%Y-%m-%d")),
                        html.Td(int(row["signal_observations"])),
                        html.Td(f"{row['peak_stress']:.2f}"),
                        html.Td(f"{row['forward_return']:.1%}"),
                        html.Td(f"{row['max_drawdown']:.1%}"),
                    ])
                    for idx, row in episode_df.iterrows()
                ])
            ], style={"width": "100%", "marginTop": "16px"})

            return html.Div([
                html.H3("Stress vs Forward Returns"),
                html.P(
                    "Benchmark: SPY, horizon: 21 trading days. "
                    "Primary crisis condition: Stress Score >= 2 and regime = crisis."
                ),
                html.P(
                    "These labels are based on stress_score, not regime_score or "
                    "regime_label: Very Easy <= -1; Easy (-1, 0]; Normal (0, 1]; "
                    "Stress (1, 2]; Crisis > 2."
                ),
                metric_cards,
                dcc.Graph(figure=fig_stress_hit_rate_bar(stress_table)),
                dcc.Graph(figure=fig_stress_forward_bar(stress_table)),
                summary_table,
                html.H3("Independent Crisis Episodes", style={"marginTop": "28px"}),
                html.P(
                    "Signals occurring within 21 trading days are treated as one episode. "
                    "The highest-stress date is used as the representative signal, preventing "
                    "the displayed 21-day return windows from overlapping."
                ),
                dcc.Graph(figure=fig_crisis_episode_returns(episode_df, horizon=21)),
                episode_table,
                html.Details(
                    [
                        html.Summary(
                            "Exploratory scatter plot (overlapping daily observations)",
                            style={"cursor": "pointer", "fontWeight": "600"},
                        ),
                        html.P(
                            "Use this chart for exploration only. Nearby points often share "
                            "most of the same 21-day return window."
                        ),
                        dcc.Graph(
                            figure=fig_stress_vs_forward_scatter(
                                scatter_df,
                                stress_col="stress_score",
                                horizon=21,
                            )
                        ),
                    ],
                    style={"marginTop": "28px"},
                ),
            ])
        
        if selected_group == TAB_REGIME_MONITOR:
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

            regime_line = regime_df[["regime_score"]]
            conf_line = regime_df[["regime_confidence"]]

            return html.Div([
                latest_card,
                dcc.Graph(figure=make_timeseries_panel(regime_line, "Regime Score")),
                dcc.Graph(figure=make_timeseries_panel(conf_line, "Regime Confidence")),
                dcc.Graph(figure=fig_regime_state(regime_df)),
                build_recent_regime_table(regime_df, months=3),
            ])
        # =====================================================
        # 2) Spread tabs
        # =====================================================
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

        # =====================================================
        # 3) Other tabs
        # =====================================================
        if selected_group == TAB_STRESS_SCORE:
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
                dcc.Graph(figure=line),
                build_recent_stress_table(MSS, months=3),
            ])

        if selected_group == TAB_VOLATILITY:
            return html.Div([
                dcc.Graph(figure=fig_volatility(raw)),
                build_recent_volatility_table(raw, months=3),
            ])

        if selected_group == TAB_LIQUIDITY:
            raw3 = add_credit_ratio(raw).copy()

            # -----------------------------
            # (1) Native-frequency display series
            # -----------------------------
            rrp_s = _require_recent_observation_density(
                raw3["RRP"],
                lookback_days=180,
                min_observations=30,
            ).loc["2014-01-01":].resample("W-FRI").median().dropna()

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
   
            display["RRP (z)"] = rolling_zscore_obs(rrp_s, window_obs=52, min_obs=26)
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
            # (2) Composite score inputs
            # -----------------------------
            score_inputs = display[
                [
                    "RRP (z)",
                    "RESERVES_PROXY Weekly (z)",
                    "MMF (z)",
                    "RESERVES Monthly (z)",
                    "M2 (z)",
                ]
            ].copy()

            fill_limits = {
                "RRP (z)": 10,
                "RESERVES_PROXY Weekly (z)": 10,
                "MMF (z)": 15,
                "RESERVES Monthly (z)": 45,
                "M2 (z)": 45,
            }

            for col, lim in fill_limits.items():
                score_inputs[col] = score_inputs[col].ffill(limit=lim)

            liquidity_score = (
                score_inputs["MMF (z)"]
                + score_inputs["RRP (z)"]
                + score_inputs["M2 (z)"]
                + score_inputs["RESERVES Monthly (z)"] * 0.3
                + score_inputs["RESERVES_PROXY Weekly (z)"] * 0.7
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
                build_recent_change_table(
                    liquidity_panel_df,
                    "Recent 3-Month Liquidity Values",
                    months=3,
                    value_decimals=3,
                    change_decimals=3,
                    positive_color="#55c878",
                    negative_color="#ff6b6b",
                    note=(
                        "Daily liquidity z-scores and changes versus the previous "
                        "available observation. Green indicates improving liquidity; "
                        "red indicates deterioration."
                    ),
                ),
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
            if "HY_OAS" in df.columns:
                z["HY_OAS"] = rolling_zscore_obs(df["HY_OAS"], window_obs=60, min_obs=30)
            if "HYG/LQD" in df.columns:
                z["HYG/LQD"] = rolling_zscore_obs(df["HYG/LQD"], window_obs=126, min_obs=63)

            return html.Div([
                dcc.Graph(figure=fig_credit_risk_levels(raw2)),
                dcc.Graph(figure=fig_credit_risk_zscore(z)),
                build_recent_change_table(
                    raw2[existing],
                    "Recent 3-Month Credit Risk Levels",
                    months=3,
                    value_decimals=3,
                    change_decimals=3,
                    note="Daily credit-risk levels and changes versus the previous trading day.",
                ),
                build_recent_change_table(
                    z,
                    "Recent 3-Month Credit Risk Z-Scores",
                    months=3,
                    value_decimals=3,
                    change_decimals=3,
                    note="Daily credit-risk z-scores and changes versus the previous trading day.",
                ),
            ])

        if selected_group == "Global Liquidity":
            if "UUP" in raw.columns:
                uup = raw[["UUP"]].dropna()
                uup_z = ((uup - uup.mean()) / uup.std()).rename(columns={"UUP": "UUP_Z"})
            else:
                uup_z = pd.DataFrame()

            return html.Div([
                dcc.Graph(figure=fig_global_liquidity(raw)),
                build_recent_change_table(
                    uup_z,
                    "Recent 3-Month Global Liquidity Values",
                    months=3,
                    value_decimals=3,
                    change_decimals=3,
                    note=(
                        "Daily UUP z-score and changes versus the previous trading day. "
                        "Higher UUP z-score indicates stronger USD / tighter global liquidity."
                    ),
                ),
            ])

        if selected_group == "Global Risk (EEM)":
            if "EEM" in raw.columns:
                eem = raw[["EEM"]].dropna()
                eem_dd = ((eem["EEM"] / eem["EEM"].rolling(126).max() - 1) * 100).to_frame(
                    "EEM_drawdown_%"
                )
            else:
                eem_dd = pd.DataFrame()

            return html.Div([
                dcc.Graph(figure=fig_global_risk(raw)),
                build_recent_change_table(
                    eem_dd,
                    "Recent 3-Month Global Risk Values",
                    months=3,
                    value_decimals=2,
                    change_decimals=2,
                    positive_color="#55c878",
                    negative_color="#ff6b6b",
                    note=(
                        "Daily EEM drawdown from its 6-month high. Green indicates "
                        "drawdown improvement; red indicates deeper drawdown."
                    ),
                ),
            ])

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
            build_recent_change_table(
                df2,
                f"Recent 3-Month {selected_group} Levels",
                months=3,
                value_decimals=3,
                change_decimals=3,
            ),
            build_recent_change_table(
                z2,
                f"Recent 3-Month {selected_group} Z-Scores",
                months=3,
                value_decimals=3,
                change_decimals=3,
            ),
        ])
