"""Local 50/25/25 combined portfolio analysis."""
import numpy as np, pandas as pd, yfinance as yf
import warnings; warnings.filterwarnings("ignore")

LB = ["ED","GIS","DUK","EXC","HSY","AEP","CMS","SO","UNH","WEC",
      "MDLZ","KO","XEL","PNW","JNJ","PG","T","CI","ATO","EVRG"]
tickers = LB + ["SPY","ACWX","CRDBX"]
raw = yf.download(tickers, start="2021-01-01", end="2026-03-05",
                  auto_adjust=True, progress=False)
c = pd.DataFrame()
if isinstance(raw.columns, pd.MultiIndex):
    for t in tickers:
        try: c[t] = raw["Close"][t]
        except: pass

m = c.resample("ME").last().pct_change().dropna(how="all")
avail = [t for t in LB if t in m.columns]
defensive = m[avail].mean(axis=1)
intl = m.get("ACWX", pd.Series(dtype=float))
crdbx = m.get("CRDBX", pd.Series(dtype=float))
spy = m.get("SPY", pd.Series(dtype=float))

common = defensive.dropna().index.intersection(intl.dropna().index).intersection(crdbx.dropna().index)
df = pd.DataFrame({
    "CRDBX_50pct": crdbx.loc[common],
    "Defensive_25pct": defensive.loc[common],
    "IntlTactical_25pct": intl.loc[common],
    "SPY": spy.loc[common],
})
df["Combined"] = 0.50 * df["CRDBX_50pct"] + 0.25 * df["Defensive_25pct"] + 0.25 * df["IntlTactical_25pct"]

def met(r, name):
    cum = (1 + r).cumprod()
    tot = cum.iloc[-1] - 1
    n = len(r) / 12
    cagr = (1 + tot) ** (1/n) - 1 if n > 0 else 0
    mdd = abs(((cum - cum.cummax()) / cum.cummax()).min())
    cal = cagr / mdd if mdd > 0 else 0
    vol = r.std() * 12**0.5
    sh = cagr / vol if vol > 0 else 0
    bc = np.cov(r, df["SPY"])
    beta = bc[0, 1] / bc[1, 1] if bc[1, 1] != 0 else 0
    return {"name": name, "cagr": cagr*100, "mdd": mdd*100, "cal": cal,
            "sh": sh, "vol": vol*100, "beta": beta, "tot": tot*100}

start = common[0].strftime("%Y-%m")
end_dt = common[-1].strftime("%Y-%m")
print("=" * 75)
print(f"  COMBINED 50/25/25 ({len(common)} months, {start} to {end_dt})")
print("=" * 75)
print(f"  {'Strategy':<20} {'CAGR':>7} {'MaxDD':>7} {'Calmar':>7} {'Sharpe':>7} {'Vol':>6} {'Beta':>6} {'Total':>8}")
print(f"  {'-'*72}")
for col in ["Combined", "CRDBX_50pct", "Defensive_25pct", "IntlTactical_25pct", "SPY"]:
    r = met(df[col], col)
    print(f"  {r['name']:<20} {r['cagr']:>6.1f}% {r['mdd']:>6.1f}% {r['cal']:>7.2f} {r['sh']:>7.2f} {r['vol']:>5.1f}% {r['beta']:>5.2f} {r['tot']:>7.1f}%")

print()
print("  CORRELATIONS:")
corr = df[["CRDBX_50pct", "Defensive_25pct", "IntlTactical_25pct", "SPY"]].corr()
print(corr.round(3).to_string())
print()

# Year-by-year
print("  ANNUAL RETURNS:")
print(f"  {'Year':<6} {'Combined':>10} {'CRDBX':>10} {'Defensive':>10} {'IntlTact':>10} {'SPY':>10}")
print(f"  {'-'*56}")
for year in sorted(set(common.year)):
    mask = df.index.year == year
    if mask.sum() == 0: continue
    for col, label in [("Combined","Combined"),("CRDBX_50pct","CRDBX"),
                       ("Defensive_25pct","Defensive"),("IntlTactical_25pct","IntlTact"),("SPY","SPY")]:
        yr_ret = (1 + df.loc[mask, col]).prod() - 1
        if col == "Combined":
            print(f"  {year:<6}", end="")
        print(f" {yr_ret*100:>9.1f}%", end="")
    print()
