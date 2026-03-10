"""
Combined 4-Sleeve Portfolio Analysis
=====================================
Computes correlation matrix, combined returns, and comparison vs SPY.
Uses local proxies: low-beta basket, international tactical (ACWX-based),
GLD for gold, XLK/SPY leveraged for 1114 proxy.
"""
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

LOW_BETA = ["ED", "GIS", "DUK", "EXC", "HSY", "AEP", "CMS", "SO",
            "UNH", "WEC", "MDLZ", "KO", "XEL", "PNW", "JNJ",
            "PG", "T", "CI", "ATO", "EVRG"]

def fetch():
    tickers = LOW_BETA + ["SPY", "GLD", "ACWX", "SHV", "UUP"]
    raw = yf.download(tickers, start="2016-01-01", end="2026-03-01",
                      auto_adjust=True, progress=False)
    closes = pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            try: closes[t] = raw["Close"][t]
            except KeyError: pass
    return closes

def main():
    print("Fetching data...")
    closes = fetch()
    monthly = closes.resample("ME").last().pct_change().dropna(how="all")

    avail_lb = [t for t in LOW_BETA if t in monthly.columns]
    sleeve_defensive = monthly[avail_lb].mean(axis=1)
    sleeve_intl = monthly.get("ACWX", pd.Series(dtype=float))
    sleeve_gold = monthly.get("GLD", pd.Series(dtype=float))
    sleeve_1114 = monthly.get("SPY", pd.Series(dtype=float)) * 1.5  # proxy for leveraged sector rotation

    common = sleeve_defensive.index
    for s in [sleeve_intl, sleeve_gold, sleeve_1114]:
        common = common.intersection(s.dropna().index)

    df = pd.DataFrame({
        "1114_Leveraged": sleeve_1114.loc[common],
        "Defensive": sleeve_defensive.loc[common],
        "Intl_Tactical": sleeve_intl.loc[common],
        "GoldDigger": sleeve_gold.loc[common],
        "SPY": monthly["SPY"].loc[common],
    })

    combined = df[["1114_Leveraged", "Defensive", "Intl_Tactical", "GoldDigger"]].mean(axis=1)
    df["Combined_4Sleeve"] = combined

    print(f"\n{'='*70}")
    print(f"  CORRELATION MATRIX ({len(common)} months)")
    print(f"{'='*70}")
    corr = df[["1114_Leveraged", "Defensive", "Intl_Tactical", "GoldDigger", "SPY"]].corr()
    print(corr.round(3).to_string())

    print(f"\n{'='*70}")
    print(f"  PERFORMANCE COMPARISON")
    print(f"{'='*70}")

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

    print(f"\n  {'Strategy':<22} {'CAGR':>7} {'MaxDD':>7} {'Calmar':>7} {'Sharpe':>7} {'Vol':>7} {'Beta':>6} {'Total':>8}")
    print(f"  {'-'*74}")
    for col in ["1114_Leveraged", "Defensive", "Intl_Tactical", "GoldDigger", "Combined_4Sleeve", "SPY"]:
        m = metrics(df[col], col)
        print(f"  {m['name']:<22} {m['cagr']:>6.1f}% {m['mdd']:>6.1f}% {m['calmar']:>7.2f} {m['sharpe']:>7.2f} {m['vol']:>6.1f}% {m['beta']:>5.2f} {m['total']:>7.1f}%")

    print(f"\n{'='*70}")
    print(f"  DIVERSIFICATION BENEFIT")
    print(f"{'='*70}")
    spy_m = metrics(df["SPY"], "SPY")
    comb_m = metrics(df["Combined_4Sleeve"], "Combined")
    print(f"  Combined 4-Sleeve Calmar: {comb_m['calmar']:.2f}")
    print(f"  SPY Calmar:               {spy_m['calmar']:.2f}")
    print(f"  Improvement:              {comb_m['calmar']/spy_m['calmar']:.1f}x")
    print(f"  Combined Beta:            {comb_m['beta']:.2f}")
    print(f"  Combined Vol:             {comb_m['vol']:.1f}% vs SPY {spy_m['vol']:.1f}%")

    out = "C:\\Users\\WoodyWiegmann\\OneDrive - PFM\\Desktop\\Potomac\\combined_portfolio_monthly.csv"
    df.to_csv(out)
    print(f"\n  Saved to {out}")

if __name__ == "__main__":
    main()
