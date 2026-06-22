import yfinance as yf
from dash import Dash, dcc, html


df = yf.download(["^VIX", "^VXN"], period="1y", progress=False)["Close"]

app = Dash(__name__)
app.layout = html.Div(
    [
        html.H2("VIX / VXN Dashboard"),
        dcc.Graph(
            figure={
                "data": [
                    {"x": df.index, "y": df["^VIX"], "type": "line", "name": "VIX"},
                    {"x": df.index, "y": df["^VXN"], "type": "line", "name": "VXN"},
                ],
                "layout": {"title": "Market Volatility", "yaxis": {"title": "Index level"}},
            }
        ),
    ]
)


if __name__ == "__main__":
    app.run(debug=True)
