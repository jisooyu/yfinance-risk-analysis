import dash
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from dash import Input, Output, dcc, html


TICKERS = {
    "^VIX": "VIX - S&P 500 volatility",
    "^VXN": "VXN - Nasdaq 100 volatility",
}


def download_volatility_data(period="1y"):
    df = yf.download(
        tickers=list(TICKERS),
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )

    if df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        close = df.xs("Close", level=1, axis=1)
    else:
        close = df[["Close"]].rename(columns={"Close": list(TICKERS)[0]})

    close.index = pd.to_datetime(close.index)
    close = close[[ticker for ticker in TICKERS if ticker in close.columns]]
    return close.dropna(how="all")


def make_volatility_figure(df):
    fig = go.Figure()

    for ticker, label in TICKERS.items():
        if ticker in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[ticker],
                    mode="lines",
                    name=label,
                )
            )

    fig.add_hline(y=20, line_dash="dot", line_color="orange", annotation_text="VIX Watch 20")
    fig.add_hline(y=30, line_dash="dot", line_color="red", annotation_text="VIX Danger 30")
    fig.add_hline(y=40, line_dash="dot", line_color="purple", annotation_text="VXN Danger 40")

    fig.update_layout(
        title="VIX and VXN Dashboard",
        template="plotly_white",
        hovermode="x unified",
        xaxis_title="Date",
        yaxis_title="Index level",
        legend_title="Indicator",
        margin={"l": 40, "r": 30, "t": 70, "b": 40},
    )
    return fig


app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H1("VIX / VXN Dashboard"),
        html.Div(
            [
                html.Label("Period"),
                dcc.Dropdown(
                    id="period",
                    options=[
                        {"label": "6 months", "value": "6mo"},
                        {"label": "1 year", "value": "1y"},
                        {"label": "3 years", "value": "3y"},
                        {"label": "5 years", "value": "5y"},
                    ],
                    value="1y",
                    clearable=False,
                ),
            ],
            style={"width": "220px", "marginBottom": "16px"},
        ),
        dcc.Graph(id="volatility-chart"),
        html.Div(id="latest-values", style={"fontSize": "18px", "marginTop": "12px"}),
    ],
    style={"maxWidth": "1000px", "margin": "0 auto", "padding": "24px", "fontFamily": "Arial"},
)


@app.callback(
    Output("volatility-chart", "figure"),
    Output("latest-values", "children"),
    Input("period", "value"),
)
def update_dashboard(period):
    df = download_volatility_data(period)

    if df.empty:
        return go.Figure(), "No data was downloaded."

    latest = df.dropna().iloc[-1]
    latest_text = " | ".join(
        f"{ticker}: {latest[ticker]:.2f}"
        for ticker in TICKERS
        if ticker in latest.index
    )

    return make_volatility_figure(df), f"Latest values - {latest_text}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8051, debug=True)
