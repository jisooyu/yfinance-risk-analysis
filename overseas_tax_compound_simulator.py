
import pandas as pd

INITIAL_CAPITAL = 100_000_000
ANNUAL_RETURN = 0.30
YEARS = 5
TAX_RATE = 0.22
BASIC_DEDUCTION = 2_500_000

def tax_on_overseas_gain(gain):
    return max(0, gain - BASIC_DEDUCTION) * TAX_RATE

def simulate_sell_every_year(initial_capital=INITIAL_CAPITAL, annual_return=ANNUAL_RETURN, years=YEARS):
    capital = initial_capital
    rows = []
    for year in range(1, years + 1):
        start = capital
        pre_tax = start * (1 + annual_return)
        gain = pre_tax - start
        tax = tax_on_overseas_gain(gain)
        end = pre_tax - tax
        rows.append({
            "year": year,
            "start_capital": round(start),
            "pre_tax_value": round(pre_tax),
            "gain": round(gain),
            "tax": round(tax),
            "end_capital": round(end),
        })
        capital = end
    return pd.DataFrame(rows)

def simulate_hold_until_final_year(initial_capital=INITIAL_CAPITAL, annual_return=ANNUAL_RETURN, years=YEARS):
    rows = []
    for year in range(1, years + 1):
        pre_tax = initial_capital * ((1 + annual_return) ** year)
        if year < years:
            tax = 0
            end = pre_tax
        else:
            total_gain = pre_tax - initial_capital
            tax = tax_on_overseas_gain(total_gain)
            end = pre_tax - tax
        rows.append({
            "year": year,
            "pre_tax_value": round(pre_tax),
            "tax": round(tax),
            "end_capital": round(end),
        })
    return pd.DataFrame(rows)

def compare():
    yearly = simulate_sell_every_year()
    hold = simulate_hold_until_final_year()
    final_yearly = int(yearly.iloc[-1]["end_capital"])
    final_hold = int(hold.iloc[-1]["end_capital"])
    summary = pd.DataFrame([
        {
            "strategy": "sell_every_year",
            "final_after_tax_value": final_yearly,
            "after_tax_profit": final_yearly - INITIAL_CAPITAL,
            "after_tax_total_return_pct": round((final_yearly / INITIAL_CAPITAL - 1) * 100, 2),
            "total_tax_paid": int(yearly["tax"].sum()),
        },
        {
            "strategy": "hold_until_final_year",
            "final_after_tax_value": final_hold,
            "after_tax_profit": final_hold - INITIAL_CAPITAL,
            "after_tax_total_return_pct": round((final_hold / INITIAL_CAPITAL - 1) * 100, 2),
            "total_tax_paid": int(hold["tax"].sum()),
        },
    ])
    summary["difference_vs_sell_every_year"] = summary["final_after_tax_value"] - final_yearly
    return yearly, hold, summary

if __name__ == "__main__":
    yearly, hold, summary = compare()
    print("\n=== Sell every year ===")
    print(yearly.to_string(index=False))
    print("\n=== Hold until final year ===")
    print(hold.to_string(index=False))
    print("\n=== Summary ===")
    print(summary.to_string(index=False))
