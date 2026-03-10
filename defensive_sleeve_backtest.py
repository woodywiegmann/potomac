"""
Defensive Sleeve Backtest: Low-Beta Basket + Long-Dated Puts vs BTAL
=====================================================================
Compares:
  A) BTAL ETF (net of 1.53% ER, already reflected in price)
  B) Low-beta quintile basket + simulated put overlay
  C) Low-beta quintile basket alone (no puts)
  D) SPY (benchmark)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

LOW_BETA_BASKET = [
    "JNJ", "PG", "KO", "PEP", "WMT", "DUK", "SO", "VZ",
    "MCD", "CL", "WM", "ED", "GIS", "MRK", "LMT",
    "CSCO", "TXN", "ADP", "SHW", "AMT",
]

START = "2019-01-01"
END = "2026-03-01"
PUT_COST_ANNUAL_PCT = 0.025


def fetch_data():
    tickers = LOW_BETA_BASKET + ["SPY", "BTAL", "^VIX"]
    print(f"  Fetching {len(tickers)} tickers...")
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)

    closes = pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            try:
                closes[t] = raw["Close"][t]
            except KeyError:
                pass
    print(f"  Got {len(closes)} trading days")
    return closes


def compute_monthly_returns(closes):
    monthly = closes.resample("ME").last()
    returns = monthly.pct_change().dropna(how="all")
    return returns


def simulate_put_overlay(spy_monthly, vix_monthly, annual_cost=PUT_COST_ANNUAL_PCT):
    """
    Simulate long-dated put P&L:
    - Monthly cost = annual_cost / 12
    - In months where SPY drops > 5%, puts pay out ~2x the drop beyond 5%
    - In months where SPY drops > 10%, puts pay ~3x (convexity)
    """
    put_pnl = pd.Series(0.0, index=spy_monthly.index)
    monthly_cost = annual_cost / 12

    for i, (dt, spy_ret) in enumerate(spy_monthly.items()):
        cost = -monthly_cost
        if spy_ret < -0.05:
            excess_drop = abs(spy_ret) - 0.05
            payout = excess_drop * 2.0
            if spy_ret < -0.10:
                payout += (abs(spy_ret) - 0.10) * 1.0
            cost += payout
        put_pnl.iloc[i] = cost

    return put_pnl


def compute_metrics(returns, name):
    if len(returns) == 0:
        return {}
    cum = (1 + returns).cumprod()
    total = cum.iloc[-1] - 1
    n_years = len(returns) / 12
    cagr = (1 + total) ** (1 / n_years) - 1 if n_years > 0 else 0
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = abs(dd.min())
    calmar = cagr / max_dd if max_dd > 0 else 0
    vol = returns.std() * np.sqrt(12)
    sharpe = cagr / vol if vol > 0 else 0
    return {
        "name": name,
        "cagr": cagr * 100,
        "max_dd": max_dd * 100,
        "calmar": calmar,
        "sharpe": sharpe,
        "vol": vol * 100,
        "total_return": total * 100,
    }


def main():
    print("=" * 70)
    print("  DEFENSIVE SLEEVE BACKTEST")
    print("  Low-Beta Basket + Puts vs BTAL")
    print(f"  Period: {START} to {END}")
    print("=" * 70)

    closes = fetch_data()
    monthly = compute_monthly_returns(closes)

    # Strategy A: BTAL
    btal_ret = monthly.get("BTAL", pd.Series(dtype=float)).dropna()

    # Strategy B: Equal-weight low-beta basket
    available = [t for t in LOW_BETA_BASKET if t in monthly.columns]
    basket_ret = monthly[available].mean(axis=1).dropna()

    # Strategy C: Low-beta basket + put overlay
    spy_ret = monthly.get("SPY", pd.Series(dtype=float)).dropna()
    vix_ret = monthly.get("^VIX", pd.Series(dtype=float)).dropna()

    common_idx = basket_ret.index.intersection(spy_ret.index)
    basket_common = basket_ret.loc[common_idx]
    spy_common = spy_ret.loc[common_idx]
    put_pnl = simulate_put_overlay(spy_common, vix_ret)
    basket_plus_puts = basket_common + put_pnl

    # Strategy D: SPY
    spy_full = spy_ret.dropna()

    strategies = [
        (basket_plus_puts, "Low-Beta + Puts"),
        (basket_ret, "Low-Beta Only"),
    ]
    if len(btal_ret) > 12:
        strategies.append((btal_ret, "BTAL ETF"))
    strategies.append((spy_full, "SPY (benchmark)"))

    # Align all to common dates for fair comparison
    if len(btal_ret) > 12:
        common = basket_plus_puts.index
        for ret, _ in strategies:
            common = common.intersection(ret.index)
    else:
        common = basket_plus_puts.index.intersection(spy_full.index)

    print(f"\n  {'='*70}")
    print(f"  RESULTS ({len(common)} months, {common[0].strftime('%Y-%m')} to {common[-1].strftime('%Y-%m')})")
    print(f"  {'='*70}")
    print(f"  {'Strategy':<22} {'CAGR':>7} {'MaxDD':>7} {'Calmar':>7} {'Sharpe':>7} {'Vol':>7} {'Total':>8}")
    print(f"  {'-'*68}")

    for ret, name in strategies:
        r = ret.reindex(common).dropna()
        m = compute_metrics(r, name)
        if m:
            print(f"  {m['name']:<22} {m['cagr']:>6.1f}% {m['max_dd']:>6.1f}% "
                  f"{m['calmar']:>7.2f} {m['sharpe']:>7.2f} {m['vol']:>6.1f}% {m['total_return']:>7.1f}%")

    # Beta comparison
    print(f"\n  --- Beta Analysis ---")
    for ret, name in strategies:
        r = ret.reindex(common).dropna()
        s = spy_full.reindex(common).dropna()
        aligned = pd.concat([r, s], axis=1).dropna()
        if len(aligned) > 12:
            cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
            beta = cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 0
            corr = np.corrcoef(aligned.iloc[:, 0], aligned.iloc[:, 1])[0, 1]
            print(f"  {name:<22} beta={beta:>6.3f}  corr={corr:>6.3f}")

    # Fee comparison
    print(f"\n  --- Annual Fee Comparison (on $165K defensive sleeve, 30% of $550K) ---")
    sleeve_aum = 165_000
    btal_fee = sleeve_aum * 0.0153
    basket_fee = 20 * 4 * 1  # 20 stocks, 4 rebalances, ~$1 commission
    put_fee = sleeve_aum * PUT_COST_ANNUAL_PCT
    print(f"  BTAL ETF:           ${btal_fee:>8,.0f}/yr (1.53% ER)")
    print(f"  Low-Beta basket:    ${basket_fee:>8,.0f}/yr (commissions only)")
    print(f"  Put options:        ${put_fee:>8,.0f}/yr (~{PUT_COST_ANNUAL_PCT*100:.1f}% premium)")
    print(f"  Basket + Puts:      ${basket_fee + put_fee:>8,.0f}/yr")
    print(f"  NET SAVINGS:        ${btal_fee - basket_fee - put_fee:>8,.0f}/yr")
    print(f"  + TLH alpha (est):  $2,000-5,000/yr (not available with BTAL)")

    # Save results
    out = "C:\\Users\\WoodyWiegmann\\OneDrive - PFM\\Desktop\\Potomac\\defensive_backtest_results.csv"
    df_out = pd.DataFrame()
    for ret, name in strategies:
        r = ret.reindex(common).dropna()
        df_out[name] = r
    df_out.to_csv(out)
    print(f"\n  Monthly returns saved to {out}")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
