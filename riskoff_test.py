"""
CRDBX RISK-OFF SLEEVE BACKTEST
==============================
Detects when CRDBX is in cash (risk-off) vs leveraged equity (risk-on)
from daily NAV behavior, then tests replacing the cash allocation with:
  25% CAOS + 50% cash + 25% DBMF

Detection logic:
  - CRDBX risk-on = ~1.5x beta to S&P (VOO + futures)
  - CRDBX risk-off = ~0% daily change (money market / cash)
  - Use rolling 5-day beta to classify regime
"""

import yfinance as yf
import pandas as pd
import numpy as np
import math
import os
import warnings
warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RF_ANNUAL = 0.05  # ~5% money market rate (recent)
RF_DAILY = RF_ANNUAL / 252

def get_total_return_series(ticker, start, end):
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float)
    h.index = h.index.tz_localize(None)
    nav = h["Close"]
    divs = h.get("Dividends", pd.Series(0.0, index=h.index))
    shares = 1.0
    vals = []
    for dt in h.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            shares *= (1 + d / p)
        vals.append(shares * p)
    return pd.Series(vals, index=h.index, name=ticker)


def rolling_beta(x, y, window=5):
    """Rolling OLS beta of x on y."""
    betas = pd.Series(np.nan, index=x.index)
    for i in range(window, len(x)):
        xi = x.iloc[i-window:i].values
        yi = y.iloc[i-window:i].values
        cov = np.cov(xi, yi)
        if cov[1, 1] > 1e-12:
            betas.iloc[i] = cov[0, 1] / cov[1, 1]
        else:
            betas.iloc[i] = 0
    return betas


def compute_metrics(prices, sp_ret, label=""):
    dr = prices.pct_change().dropna()
    if len(dr) < 30:
        return None
    yrs = (prices.index[-1] - prices.index[0]).days / 365.25
    cagr = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / yrs) - 1) * 100
    cummax = prices.cummax()
    dd = ((prices - cummax) / cummax)
    max_dd = dd.min() * 100
    dd_end = dd.idxmin()
    dd_start = prices[:dd_end].idxmax() if dd_end > prices.index[0] else prices.index[0]
    ann_vol = dr.std() * math.sqrt(252) * 100
    sharpe = (dr.mean() - 0.03 / 252) / dr.std() * math.sqrt(252) if dr.std() > 0 else 0
    down = dr[dr < 0]
    sortino = (dr.mean() - 0.03 / 252) / down.std() * math.sqrt(252) if len(down) > 0 and down.std() > 0 else 0
    calmar = abs(cagr / max_dd) if max_dd != 0 else 0
    sp_aligned = sp_ret.reindex(dr.index, method="ffill").fillna(0)
    try:
        cv = np.cov(dr, sp_aligned)
        beta = cv[0, 1] / cv[1, 1] if cv[1, 1] > 0 else 0
        corr = np.corrcoef(dr, sp_aligned)[0, 1]
    except:
        beta, corr = 0, 0
    yr = prices.resample("YE").last().pct_change().dropna() * 100
    return {
        "label": label, "cagr": cagr, "max_dd": max_dd,
        "dd_period": f"{dd_start.strftime('%m/%Y')}-{dd_end.strftime('%m/%Y')}",
        "ann_vol": ann_vol, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "beta": beta, "corr": corr,
        "best_yr": yr.max() if len(yr) > 0 else 0,
        "worst_yr": yr.min() if len(yr) > 0 else 0,
        "yearly": yr,
        "growth": prices.iloc[-1] / prices.iloc[0] * 10000,
    }


def main():
    # Common period: CAOS data starts March 2023
    START = "2023-03-01"
    END = "2026-02-21"

    print("=" * 110)
    print("CRDBX RISK-OFF SLEEVE BACKTEST")
    print(f"Period: {START} to {END} (limited by CAOS data availability)")
    print("Detecting risk-on/risk-off from CRDBX daily NAV vs S&P 500")
    print("=" * 110)

    # Fetch data
    print("\nFetching total-return series...")
    tickers = ["CRDBX", "SPY", "CAOS", "DBMF", "SHY"]
    data = {}
    for tk in tickers:
        s = get_total_return_series(tk, "2022-12-01", END)
        if len(s) > 0:
            print(f"  {tk}: {s.index[0].date()} to {s.index[-1].date()} ({len(s)} days)")
            data[tk] = s
        else:
            print(f"  {tk}: NO DATA")

    # Build common index
    crdbx = data["CRDBX"]
    spy = data["SPY"]
    idx = crdbx[crdbx.index >= START].index
    idx = idx.intersection(spy.index)
    for tk in ["CAOS", "DBMF"]:
        if tk in data:
            idx = idx.intersection(data[tk].index)

    crdbx_p = crdbx.reindex(idx)
    spy_p = spy.reindex(idx)
    crdbx_ret = crdbx_p.pct_change().fillna(0)
    spy_ret = spy_p.pct_change().fillna(0)

    caos_p = data["CAOS"].reindex(idx, method="ffill")
    dbmf_p = data["DBMF"].reindex(idx, method="ffill")
    caos_ret = caos_p.pct_change().fillna(0)
    dbmf_ret = dbmf_p.pct_change().fillna(0)

    # Detect regime from CRDBX NAV behavior
    print("\nDetecting risk-on/risk-off regime from CRDBX NAV...")
    beta_5d = rolling_beta(crdbx_ret, spy_ret, window=5)

    # Classify: beta > 0.6 = risk-on, beta < 0.3 = risk-off, in between = mixed
    regime = pd.Series("UNKNOWN", index=idx)
    regime[beta_5d > 0.6] = "RISK_ON"
    regime[beta_5d < 0.3] = "RISK_OFF"
    regime[(beta_5d >= 0.3) & (beta_5d <= 0.6)] = "TRANSITION"
    regime[beta_5d.isna()] = "UNKNOWN"

    # Also use same-day heuristic for confirmation
    # If |CRDBX_ret| < 0.05% and |SPY_ret| > 0.3% => definitely risk-off
    # If CRDBX/SPY ratio > 1.0 and both moved => definitely risk-on
    for i in range(len(idx)):
        cr = abs(crdbx_ret.iloc[i])
        sr = abs(spy_ret.iloc[i])
        if sr > 0.003 and cr < 0.0005:
            regime.iloc[i] = "RISK_OFF"
        elif sr > 0.002 and cr > sr * 1.0:
            regime.iloc[i] = "RISK_ON"

    n_on = (regime == "RISK_ON").sum()
    n_off = (regime == "RISK_OFF").sum()
    n_trans = (regime == "TRANSITION").sum()
    n_unk = (regime == "UNKNOWN").sum()
    print(f"  RISK_ON:    {n_on:>4} days ({n_on/len(idx)*100:.1f}%)")
    print(f"  RISK_OFF:   {n_off:>4} days ({n_off/len(idx)*100:.1f}%)")
    print(f"  TRANSITION: {n_trans:>4} days ({n_trans/len(idx)*100:.1f}%)")
    print(f"  UNKNOWN:    {n_unk:>4} days ({n_unk/len(idx)*100:.1f}%)")

    # Show average beta in each regime
    for r in ["RISK_ON", "RISK_OFF", "TRANSITION"]:
        mask = regime == r
        if mask.sum() > 0:
            avg_b = beta_5d[mask].mean()
            avg_crdbx = crdbx_ret[mask].mean() * 252 * 100
            avg_spy = spy_ret[mask].mean() * 252 * 100
            print(f"  {r}: avg beta={avg_b:.2f}, CRDBX ann={avg_crdbx:.1f}%, SPY ann={avg_spy:.1f}%")

    # Strategy variants
    print("\nBuilding strategy variants...")
    strategies = {}

    # 1. CRDBX actual (baseline)
    strategies["CRDBX Actual"] = crdbx_ret.copy()

    # 2. Modified: replace risk-off days with 25% CAOS + 50% cash + 25% DBMF
    mod1 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod1.iloc[i] = 0.25 * caos_ret.iloc[i] + 0.50 * RF_DAILY + 0.25 * dbmf_ret.iloc[i]
    strategies["Modified: 25%CAOS+50%Cash+25%DBMF (risk-off)"] = mod1

    # 3. Modified: replace risk-off with 50% CAOS + 50% DBMF (no cash)
    mod2 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod2.iloc[i] = 0.50 * caos_ret.iloc[i] + 0.50 * dbmf_ret.iloc[i]
    strategies["Modified: 50%CAOS+50%DBMF (risk-off)"] = mod2

    # 4. Modified: replace risk-off with 25% CAOS + 25% DBMF + 50% SHY
    shy_ret = data["SHY"].reindex(idx, method="ffill").pct_change().fillna(0)
    mod3 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod3.iloc[i] = 0.25 * caos_ret.iloc[i] + 0.25 * dbmf_ret.iloc[i] + 0.50 * shy_ret.iloc[i]
    strategies["Modified: 25%CAOS+25%DBMF+50%SHY (risk-off)"] = mod3

    # 5. Modified: replace risk-off with 33% CAOS + 33% DBMF + 34% cash
    mod4 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod4.iloc[i] = 0.333 * caos_ret.iloc[i] + 0.333 * dbmf_ret.iloc[i] + 0.334 * RF_DAILY
    strategies["Modified: 33%CAOS+33%DBMF+34%Cash (risk-off)"] = mod4

    # 6. Modified: 100% DBMF only during risk-off
    mod5 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod5.iloc[i] = dbmf_ret.iloc[i]
    strategies["Modified: 100%DBMF (risk-off)"] = mod5

    # 7. Modified: 100% CAOS only during risk-off
    mod6 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod6.iloc[i] = caos_ret.iloc[i]
    strategies["Modified: 100%CAOS (risk-off)"] = mod6

    # 8. Keep risk-off as 100% cash (pure money market) -- what they do now
    mod7 = crdbx_ret.copy()
    for i in range(len(idx)):
        if regime.iloc[i] in ["RISK_OFF", "TRANSITION"]:
            mod7.iloc[i] = RF_DAILY
    strategies["Baseline: 100%Cash (risk-off, current)"] = mod7

    # Compute metrics
    print("\n" + "=" * 110)
    print(f"{'Strategy':<55} {'CAGR':>6} {'MaxDD':>7} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} "
          f"{'Beta':>6} {'Corr':>6} {'Vol':>6} {'$10K':>8}")
    print("-" * 110)

    all_results = []
    for name, ret_series in strategies.items():
        prices = (1 + ret_series).cumprod() * 10000
        m = compute_metrics(prices, spy_ret, name)
        if m:
            all_results.append(m)
            print(f"{name[:54]:<55} {m['cagr']:>5.1f}% {m['max_dd']:>6.1f}% "
                  f"{m['sharpe']:>7.2f} {m['sortino']:>8.2f} {m['calmar']:>7.2f} "
                  f"{m['beta']:>6.2f} {m['corr']:>6.2f} {m['ann_vol']:>5.1f}% "
                  f"${m['growth']:>7,.0f}")

    # Year-by-year
    print("\n" + "=" * 110)
    print("YEAR-BY-YEAR COMPARISON")
    print("=" * 110)
    header = f"{'Year':<6}"
    for r in all_results:
        short = r["label"][:20]
        header += f" {short:>14}"
    print(header)
    print("-" * (6 + 15 * len(all_results)))

    all_years = set()
    for r in all_results:
        all_years.update(r["yearly"].index.year)
    for yr in sorted(all_years):
        line = f"{yr:<6}"
        for r in all_results:
            match = r["yearly"][r["yearly"].index.year == yr]
            if len(match) > 0:
                line += f" {match.iloc[0]:>13.1f}%"
            else:
                line += f" {'--':>14}"
        print(line)

    # Risk-off period analysis
    print("\n" + "=" * 110)
    print("RISK-OFF PERIOD ANALYSIS")
    print("=" * 110)

    # Find consecutive risk-off stretches
    off_mask = regime.isin(["RISK_OFF", "TRANSITION"])
    off_starts = []
    off_ends = []
    in_off = False
    for i in range(len(idx)):
        if off_mask.iloc[i] and not in_off:
            off_starts.append(i)
            in_off = True
        elif not off_mask.iloc[i] and in_off:
            off_ends.append(i - 1)
            in_off = False
    if in_off:
        off_ends.append(len(idx) - 1)

    print(f"\nNumber of risk-off periods: {len(off_starts)}")
    total_off_days = off_mask.sum()
    print(f"Total risk-off days: {total_off_days} ({total_off_days/len(idx)*100:.1f}% of period)")

    if len(off_starts) > 0:
        durations = [off_ends[j] - off_starts[j] + 1 for j in range(len(off_starts))]
        print(f"Average duration: {np.mean(durations):.1f} days")
        print(f"Longest stretch: {max(durations)} days")
        print(f"Shortest stretch: {min(durations)} days")

    # Return during risk-off periods for each strategy
    print(f"\n{'Strategy':<55} {'Ann Return (risk-off days only)':>30}")
    print("-" * 86)
    for name, ret_series in strategies.items():
        off_returns = ret_series[off_mask]
        ann = off_returns.mean() * 252 * 100
        print(f"{name[:54]:<55} {ann:>29.2f}%")

    # Risk-on confirmation: what's the average beta during risk-on?
    print(f"\nRisk-on validation:")
    on_mask = regime == "RISK_ON"
    if on_mask.sum() > 0:
        on_crdbx = crdbx_ret[on_mask]
        on_spy = spy_ret[on_mask]
        if on_spy.std() > 0:
            actual_beta = np.cov(on_crdbx, on_spy)[0, 1] / np.var(on_spy)
            print(f"  Actual CRDBX beta during risk-on days: {actual_beta:.2f}")
            print(f"  (confirms leveraged VOO + futures at ~1.5x)")

    # Save results
    out = []
    out.append("=" * 110)
    out.append("CRDBX RISK-OFF SLEEVE BACKTEST RESULTS")
    out.append(f"Period: {START} to {END}")
    out.append("Detection: Rolling 5-day beta of CRDBX vs S&P + same-day heuristic")
    out.append(f"Risk-on: {n_on} days ({n_on/len(idx)*100:.1f}%) | Risk-off: {n_off} days ({n_off/len(idx)*100:.1f}%)")
    out.append("=" * 110)
    out.append("")
    out.append(f"{'Strategy':<55} {'CAGR':>6} {'MaxDD':>7} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} "
               f"{'Beta':>6} {'Corr':>6} {'Vol':>6} {'$10K':>8}")
    out.append("-" * 110)
    for m in all_results:
        out.append(f"{m['label'][:54]:<55} {m['cagr']:>5.1f}% {m['max_dd']:>6.1f}% "
                   f"{m['sharpe']:>7.2f} {m['sortino']:>8.2f} {m['calmar']:>7.2f} "
                   f"{m['beta']:>6.2f} {m['corr']:>6.2f} {m['ann_vol']:>5.1f}% "
                   f"${m['growth']:>7,.0f}")

    out_path = os.path.join(SCRIPT_DIR, "riskoff_results.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
