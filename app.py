from dash import Dash
from layout import build_layout
from callbacks import register_callbacks

# from extensions import cache
"""
same snippet is also running on Mac but it fails to fectch data from fred
"""
# Working tickers only - 리스트 안에 있는 변수는 yfinance에서 download받는 것
RISK_TICKERS = {
    "Volatility": ["^VIX", "^VIX3M", "^VIX6M", "^VXN", "^SKEW"],
    "Liquidity":[],
    "Credit Risk": ["HYG", "JNK", "LQD"],
    "Treasury Yields": ["^FVX", "^TNX", "^TYX"],
    "3mo–2y Spread": [],
    "3mo–10y Spread": [],
    "Global Liquidity": ["UUP", "SHY", "IEI"],
    "Global Risk (EEM)": ["EEM"],
    "Regime Monitor": [],
    "Historical Regime Accuracy":[],
    "Stress vs Forward Returns": [],
    "Stress Score": [],
}

app = Dash(__name__, title="Yfinance Risk Anaysis")

app.layout = build_layout(RISK_TICKERS)

register_callbacks(app, RISK_TICKERS)

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=8050, debug=True)
