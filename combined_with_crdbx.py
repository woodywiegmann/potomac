"""Combined 4-sleeve analysis using actual CRDBX returns (gross of ER)."""
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

LOW_BETA = ["ED", "GIS", "DUK", "EXC", "HSY", "AEP", "CMS", "SO",
            "UNH", "WEC", "MDLZ", "KO", "XEL", "PNW", "JNJ",
            "PG", "T", "CI", "ATO", "EVRG"]

tickers = LOW_BETA + ["SPY", "GLD", "ACWX", "CRDBX"]
print("Fetching...")
raw = yf.download(tickers, start="2020-07-01", end="2026-03-05",
                  auto_adjust=True, progress=False)
closes = pd.DataFrame()
if isinstance(raw.columns, pd.MultiIndex):
    for t in tickers:
        try: closes[t] = raw["Close"][t]
        except: pass

monthly = closes.resample("ME").last().pct_change().dropna(how="all")

avail = [t for t in LOW_BETA if t in monthly.columns]
defensive = monthly[avail].mean(axis=1)
intl = monthly.get("ACWX", pd.Series(dtype=float))
gold = monthly.get("GLD", pd.Series(dtype=float))
crdbx_net = monthly.get("CRDBX", pd.Series(dtype=float))
crdbx_gross = crdbx_net + 0.0139/12  # add back ER monthly

common = defensive.dropna().index
for s in [intl, gold, crdbx_gross]:
    common = common.intersection(s.dropna().index)

df = pd.DataFrame({
    "CRDBX_Gross": crdbx_gross.loc[common],
    "CRDBX_Net": crdbx_net.loc[common],
    "Defensive": defensive.loc[common],
    "Intl_Tactical": intl.loc[common],
    "GoldDigger": gold.loc[common],
    "SPY": monthly["SPY"].loc[common],
})
df["Combined_4Sleeve"] = df[["CRDBX_Gross", "Defensive", "Intl_Tactical", "GoldDigger"]].mean(axis=1)

def metrics(rets, name):
    cum = (1 + rets).cumprod()
    total = cum.iloc[-1] - 1
    n = len(rets) / 12
    cagr = (1 + total) ** (1/n) - 1 if n > 0 else 0
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = abs(dd.min())
    calmar = cagr / mdd if mdd > 0 else 0
    vol = rets.std() * np.sqrt(12)
    sharpe = cagr / vol if vol > 0 else 0
    beta_cov = np.cov(rets, df["SPY"])
    beta = beta_cov[0,1] / beta_cov[1,1] if beta_cov[1,1] != 0 else 0
    return {"name": name, "cagr": cagr*100, "mdd": mdd*100, "calmar": calmar,
            "sharpe": sharpe, "vol": vol*100, "total": total*100, "beta": beta}

print(f"\n{'='*80}")
print(f"  CORRELATION MATRIX ({len(common)} months, {common[0].strftime('%Y-%m')} to {common[-1].strftime('%Y-%m')})")
print(f"{'='*80}")
corr = df[["CRDBX_Gross", "Defensive", "Intl_Tactical", "GoldDigger", "SPY"]].corr()
print(corr.round(3).to_string())

print(f"\n{'='*80}")
print(f"  PERFORMANCE")
print(f"{'='*80}")
print(f"  {'Strategy':<22} {'CAGR':>7} {'MaxDD':>7} {'Calmar':>7} {'Sharpe':>7} {'Vol':>7} {'Beta':>6} {'Total':>8}")
print(f"  {'-'*74}")
for col in ["CRDBX_Gross", "CRDBX_Net", "Defensive", "Intl_Tactical", "GoldDigger", "Combined_4Sleeve", "SPY"]:
    m = metrics(df[col], col)
    print(f"  {m['name']:<22} {m['cagr']:>6.1f}% {m['mdd']:>6.1f}% {m['calmar']:>7.2f} {m['sharpe']:>7.2f} {m['vol']:>6.1f}% {m['beta']:>5.2f} {m['total']:>7.1f}%")

print(f"\n  CRDBX ER: 1.39%. Gross = net + 1.39%/yr added back.")
print(f"  'Gross' approximates the strategy return without mutual fund fees.")

df.to_csv("C:\\Users\\WoodyWiegmann\\OneDrive - PFM\\Desktop\\Potomac\\combined_crdbx_monthly.csv")
print(f"\n  Saved to combined_crdbx_monthly.csv")
