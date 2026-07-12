import sys

import dash as dash_package
from dash import Dash
from layout import build_layout
from callbacks import register_callbacks


def _normalize_dash_windows_paths() -> None:
    """Remove the extended-path prefix that breaks Dash resource lookups."""
    if sys.platform != "win32":
        return

    for module_name, module in tuple(sys.modules.items()):
        if module_name != "dash" and not module_name.startswith("dash."):
            continue
        module_file = getattr(module, "__file__", None)
        if isinstance(module_file, str) and module_file.startswith("\\\\?\\"):
            module.__file__ = module_file[4:]

    package_path = getattr(dash_package, "__path__", None)
    if package_path:
        normalized = [path[4:] if path.startswith("\\\\?\\") else path for path in package_path]
        dash_package.__path__ = normalized


_normalize_dash_windows_paths()

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
    # Dash's debug asset loader can build invalid extended-length paths on
    # Windows (for example ``\\?\...\dash\deps/polyfill...`` with a mixed
    # slash).  Run the regular server by default; opt into the debugger only
    # explicitly on platforms/environments where it is known to work.
    app.run(host="127.0.0.1", port=8050, debug=False)
