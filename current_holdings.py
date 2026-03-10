"""Compute current top-7 momentum ETFs as of latest data."""
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

ALL_ETFS = {
    "EWJ": "Japan", "EWG": "Germany", "EWQ": "France",
    "EWI": "Italy", "EWD": "Sweden", "EWL": "Switzerland",
    "EWP": "Spain", "EWH": "Hong Kong", "EWS": "Singapore",
    "EDEN": "Denmark", "IHDG": "Intl Hedged Qual Div",
    "RING": "Gold Miners", "SIL": "Silver Miners",
    "URA": "Uranium", "KXI": "Global Staples",
    "LIT": "Lithium", "REMX": "Rare Earth",
    "COPX": "Copper Miners", "PICK": "Metals Mining",
    "GNR": "Global NatRes", "CGW": "Global Water",
    "GII": "Global Infra", "INFL": "Inflation Beneficiaries",
    "MOO": "Agribusiness", "EWT": "Taiwan", "EWZ": "Brazil",
    "INDA": "India", "FXI": "China", "EWY": "South Korea",
    "EWW": "Mexico", "ILF": "LatAm 40", "ECH": "Chile",
    "TUR": "Turkey", "ARGT": "Argentina", "VNM": "Vietnam",
    "THD": "Thailand", "EWM": "Malaysia", "EIDO": "Indonesia",
    "KSA": "Saudi Arabia", "KWEB": "China Internet",
}

tickers = list(ALL_ETFS.keys()) + ["BIL", "CAOS", "SGOV"]
print(f"Fetching {len(tickers)} tickers...")
raw = yf.download(tickers, start="2025-01-01", end="2026-03-04", auto_adjust=True, progress=False)

closes = pd.DataFrame()
if isinstance(raw.columns, pd.MultiIndex):
    for t in tickers:
        try:
            closes[t] = raw["Close"][t]
        except KeyError:
            pass

latest_date = closes.index[-1]
print(f"Latest date: {latest_date.strftime('%Y-%m-%d')}")

scores = {}
for t in ALL_ETFS:
    if t not in closes.columns:
        continue
    c = closes[t].dropna()
    if len(c) < 252:
        continue
    cur = c.iloc[-1]
    rets = []
    for months in [1, 3, 6, 12]:
        days = int(months * 21)
        if len(c) > days:
            past = c.iloc[-(days+1)]
            if past > 0:
                rets.append(cur / past - 1)
    if rets:
        scores[t] = sum(rets) / len(rets)

ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

print(f"\n{'Rank':<5} {'Ticker':<7} {'Name':<28} {'Blended Mom':>12} {'Status':>10}")
print("-" * 66)
for i, (t, s) in enumerate(ranked):
    status = "HOLD" if i < 7 and s > 0 else ("-> BIL" if i < 7 else "")
    marker = " ***" if i < 7 else ""
    print(f"{i+1:<5} {t:<7} {ALL_ETFS[t]:<28} {s*100:>11.2f}% {status:>10}{marker}")

top7 = ranked[:7]
eq_wt = 0.91
slot = eq_wt / 7
cash = 1.0 - sum(slot for _, s in top7 if s > 0)

print(f"\n{'='*66}")
print(f"CURRENT PORTFOLIO (Equity Weight = 91%)")
print(f"{'='*66}")
print(f"{'Ticker':<7} {'Name':<28} {'Weight':>8}")
print("-" * 45)
for t, s in top7:
    if s > 0:
        print(f"{t:<7} {ALL_ETFS[t]:<28} {slot*100:>7.1f}%")
    else:
        print(f"{'BIL':<7} {'T-Bills (neg momentum)':<28} {slot*100:>7.1f}%")
        cash += slot
if cash > 0.001:
    sgov_w = cash * 0.5
    caos_w = cash * 0.5
    print(f"{'SGOV':<7} {'0-3M Treasury (risk-off)':<28} {sgov_w*100:>7.1f}%")
    print(f"{'CAOS':<7} {'Tail Risk ETF (risk-off)':<28} {caos_w*100:>7.1f}%")
print("-" * 45)
print(f"{'TOTAL':<36} {'100.0%':>8}")
