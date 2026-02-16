# layout.py
from dash import html, dcc

def build_layout(RISK_TICKERS):
    
    tabs = [dcc.Tab(label=k, value=k) for k in RISK_TICKERS.keys()]

    return html.Div(
        [
            html.H1("Market Risk Dashboard", style={"textAlign": "center"}),

            dcc.Interval(id="refresh", interval=15 * 60 * 1000, n_intervals=0),

            dcc.Tabs(
                id="tabs",
                value="Stress Score",   # safer default
                children=tabs,
                colors={"border": "#444", "primary": "#00ccff", "background": "#222"},
            ),

            html.Div(id="panel-output"),
        ],
        style={"backgroundColor": "#111111", "color": "white", "padding": "20px"},
    )
