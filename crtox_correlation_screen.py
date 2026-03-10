"""
CRTOX Universe Expansion -- Correlation Screening Tool
=======================================================
For each candidate ETF, computes:
  1. Average pairwise correlation with the proposed universe
  2. Max pairwise correlation (identifies redundancy)
  3. Marginal impact on universe-wide avg pairwise correlation if added
  4. Correlation to SPY (market beta proxy)

Ranks candidates by how much they'd reduce the universe avg correlation.
"""

import math, sys, os
import warnings
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    print("Required: pip install yfinance pandas numpy")
    sys.exit(1)

# ── Current proposed universe (from crtox_momentum_analysis.py) ──────────────
PROPOSED_UNIVERSE = [
    "SMH", "IBB", "XBI", "SIL", "SILJ", "XME", "COPX",
    "URNM", "PAVE", "ITA", "XAR", "ILF", "EFV", "ARKK",
    "CIBR", "AMLP", "CTA", "DBMF", "IWO", "EMXC",
]

# ── Candidate ETFs to screen ────────────────────────────────────────────────
CANDIDATES = {
    "BTAL":  "Anti-Beta (mkt neutral)",
    "GLDM":  "Physical Gold",
    "PDBC":  "Broad Commodities",
    "VNQ":   "US REITs",
    "XLRE":  "Real Estate Sector",
    "REMX":  "Rare Earth Metals",
    "TAN":   "Solar Energy",
    "ICLN":  "Clean Energy",
    "WEAT":  "Wheat (agriculture)",
    "DBA":   "Broad Agriculture",
    "PFF":   "Preferred Stock",
    "PFFD":  "Preferred Stock (div)",
    "JETS":  "Airlines/Travel",
    "KWEB":  "China Internet",
    "CQQQ":  "China Tech",
    "QAI":   "Hedge Fund Multi-Strat",
    "CCRV":  "Commodity Carry",
    "UNG":   "Natural Gas",
    "PPLT":  "Platinum",
    "WOOD":  "Timber/Forestry",
    "PHO":   "Water Resources",
    "HACK":  "Cybersecurity (alt)",
    "FTGC":  "Commodity (active)",
    "MJ":    "Cannabis",
    "BITQ":  "Bitcoin/Crypto Equity",
    "GNR":   "Global Natural Resources",
}

BENCHMARKS = ["SPY", "QQQ"]

LOOKBACK_DAYS = 504  # ~2 years of trading days for correlation calc


def fetch_prices(tickers, start, end):
    print(f"  Fetching {len(tickers)} tickers ...")
    data = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]].rename(columns={"Close": tickers[0]})
    prices = prices.ffill().dropna(how="all")
    return prices


def avg_pairwise_corr(corr_matrix):
    vals = corr_matrix.values
    upper = vals[np.triu_indices_from(vals, k=1)]
    return np.nanmean(upper)


def max_pairwise_corr(corr_matrix, ticker):
    if ticker not in corr_matrix.columns:
        return np.nan, ""
    row = corr_matrix.loc[ticker].drop(ticker, errors="ignore")
    idx = row.abs().idxmax()
    return row[idx], idx


def main():
    all_tickers = list(set(PROPOSED_UNIVERSE + list(CANDIDATES.keys()) + BENCHMARKS))

    print("=" * 78)
    print("  CRTOX UNIVERSE EXPANSION -- CORRELATION SCREEN")
    print("=" * 78)

    prices = fetch_prices(all_tickers, "2022-01-01", pd.Timestamp.today().strftime("%Y-%m-%d"))

    missing = [t for t in all_tickers if t not in prices.columns]
    if missing:
        print(f"  WARNING: No data for: {missing}")

    returns = prices.pct_change().dropna()
    if len(returns) > LOOKBACK_DAYS:
        returns = returns.iloc[-LOOKBACK_DAYS:]

    avail_proposed = [t for t in PROPOSED_UNIVERSE if t in returns.columns]
    corr_base = returns[avail_proposed].corr()
    base_avg = avg_pairwise_corr(corr_base)

    print(f"\n  Proposed universe: {len(avail_proposed)} tickers with data")
    print(f"  Baseline avg pairwise correlation: {base_avg:.4f}")
    print(f"  Correlation window: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")

    # ── High-corr pairs in baseline ──────────────────────────────────────────
    print(f"\n  {'-' * 72}")
    print(f"  HIGH-CORRELATION PAIRS IN PROPOSED UNIVERSE (>0.70)")
    print(f"  {'-' * 72}")
    cols = corr_base.columns.tolist()
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = corr_base.iloc[i, j]
            if abs(c) >= 0.70:
                pairs.append((cols[i], cols[j], c))
    pairs.sort(key=lambda x: -abs(x[2]))
    for a, b, c in pairs:
        flag = " *** OVERLAP" if c > 0.85 else ""
        print(f"    {a:6s} / {b:6s}  r = {c:+.3f}{flag}")
    if not pairs:
        print("    None")

    # ── Screen each candidate ────────────────────────────────────────────────
    print(f"\n  {'-' * 72}")
    print(f"  CANDIDATE SCREENING")
    print(f"  {'-' * 72}")

    results = []
    for ticker, desc in CANDIDATES.items():
        if ticker in avail_proposed:
            continue
        if ticker not in returns.columns:
            print(f"    {ticker:6s}  -- NO DATA, skipping")
            continue

        candidate_tickers = avail_proposed + [ticker]
        corr_expanded = returns[candidate_tickers].corr()
        expanded_avg = avg_pairwise_corr(corr_expanded)
        marginal = expanded_avg - base_avg

        corr_to_universe = corr_expanded.loc[ticker, avail_proposed]
        avg_to_univ = corr_to_universe.mean()
        max_corr_val = corr_to_universe.abs().max()
        max_corr_name = corr_to_universe.abs().idxmax()
        min_corr_val = corr_to_universe.min()
        min_corr_name = corr_to_universe.idxmin()

        spy_corr = returns[[ticker, "SPY"]].corr().iloc[0, 1] if "SPY" in returns.columns else np.nan
        qqq_corr = returns[[ticker, "QQQ"]].corr().iloc[0, 1] if "QQQ" in returns.columns else np.nan

        ann_ret = returns[ticker].mean() * 252
        ann_vol = returns[ticker].std() * math.sqrt(252)

        results.append({
            "Ticker": ticker,
            "Description": desc,
            "Avg Corr to Univ": avg_to_univ,
            "Max Corr": max_corr_val,
            "Max Corr With": max_corr_name,
            "Min Corr": min_corr_val,
            "Min Corr With": min_corr_name,
            "Marginal Impact": marginal,
            "New Univ Avg": expanded_avg,
            "Corr to SPY": spy_corr,
            "Corr to QQQ": qqq_corr,
            "Ann Ret": ann_ret,
            "Ann Vol": ann_vol,
        })

    results.sort(key=lambda x: x["Marginal Impact"])

    print(f"\n  {'Ticker':<7} {'Description':<26} {'AvgCorr':>8} {'MaxCorr':>8} {'MaxWith':>6} "
          f"{'Marginal':>9} {'NewAvg':>8} {'SPY_r':>7} {'AnnRet':>8} {'AnnVol':>8}")
    print(f"  {'-' * 110}")
    for r in results:
        print(f"  {r['Ticker']:<7} {r['Description']:<26} {r['Avg Corr to Univ']:>+8.3f} "
              f"{r['Max Corr']:>8.3f} {r['Max Corr With']:>6} "
              f"{r['Marginal Impact']:>+9.4f} {r['New Univ Avg']:>8.4f} "
              f"{r['Corr to SPY']:>+7.3f} {r['Ann Ret']:>+8.1%} {r['Ann Vol']:>8.1%}")

    # ── Top picks detail ─────────────────────────────────────────────────────
    top_n = min(8, len(results))
    print(f"\n  {'=' * 72}")
    print(f"  TOP {top_n} CANDIDATES (largest correlation reduction)")
    print(f"  {'=' * 72}")
    for i, r in enumerate(results[:top_n]):
        print(f"\n  {i+1}. {r['Ticker']} -- {r['Description']}")
        print(f"     Avg corr to universe:  {r['Avg Corr to Univ']:+.3f}")
        print(f"     Max corr:  {r['Max Corr']:+.3f} (with {r['Max Corr With']})")
        print(f"     Min corr:  {r['Min Corr']:+.3f} (with {r['Min Corr With']})")
        print(f"     Marginal impact on universe avg: {r['Marginal Impact']:+.4f}")
        print(f"     Corr to SPY: {r['Corr to SPY']:+.3f}  |  Corr to QQQ: {r['Corr to QQQ']:+.3f}")
        print(f"     Ann Return: {r['Ann Ret']:+.1%}  |  Ann Vol: {r['Ann Vol']:.1%}")

    # ── Simulate adding top candidates incrementally ─────────────────────────
    print(f"\n  {'=' * 72}")
    print(f"  INCREMENTAL ADDITION SIMULATION")
    print(f"  (Adding candidates one at a time in order of marginal benefit)")
    print(f"  {'=' * 72}")

    running_universe = avail_proposed.copy()
    running_avg = base_avg
    print(f"\n  {'Step':<6} {'Added':<8} {'Universe Size':>14} {'Avg Pairwise Corr':>18} {'Change':>10}")
    print(f"  {'-' * 60}")
    print(f"  {'Base':<6} {'--':<8} {len(running_universe):>14} {running_avg:>18.4f} {'--':>10}")

    for i, r in enumerate(results[:top_n]):
        ticker = r["Ticker"]
        if ticker not in returns.columns:
            continue
        running_universe.append(ticker)
        new_corr = returns[running_universe].corr()
        new_avg = avg_pairwise_corr(new_corr)
        delta = new_avg - running_avg
        running_avg = new_avg
        print(f"  {f'+{i+1}':<6} {ticker:<8} {len(running_universe):>14} {running_avg:>18.4f} {delta:>+10.4f}")

    print(f"\n  Final universe avg pairwise correlation: {running_avg:.4f}")
    print(f"  Reduction from baseline: {running_avg - base_avg:+.4f}")
    print(f"  Final universe ({len(running_universe)} tickers): {running_universe}")

    # ── Full correlation matrix for top picks + universe ─────────────────────
    top_tickers = [r["Ticker"] for r in results[:top_n] if r["Ticker"] in returns.columns]
    full_set = avail_proposed + top_tickers
    full_corr = returns[full_set].corr()
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crtox_corr_screen_results.csv")
    full_corr.to_csv(out_path)
    print(f"\n  Full correlation matrix saved to: {out_path}")


if __name__ == "__main__":
    main()
