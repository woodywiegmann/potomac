"""
Low-Beta Stock Screener for BTAL Replication
=============================================
Screens S&P 500 + S&P 400 for:
  - 3-year beta < 0.70 (weekly returns vs SPX)
  - Market cap > $10B
  - Positive trailing earnings (quality filter)
Outputs ranked list with TLH swap pairs by sector.
"""

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

SECTOR_TLH_PAIRS = {
    "Consumer Staples": ["PG", "KO", "PEP", "MDLZ", "CL", "KMB", "GIS", "SJM", "HSY", "MKC", "HRL", "CPB", "CAG", "K", "WMT", "COST", "KR"],
    "Health Care": ["JNJ", "ABT", "BMY", "MRK", "LLY", "AMGN", "GILD", "VRTX", "REGN", "ZTS", "CI", "HUM", "ELV", "UNH", "MDT", "BDX", "BAX", "SYK"],
    "Utilities": ["DUK", "SO", "NEE", "D", "AEP", "SRE", "EXC", "XEL", "WEC", "ED", "ES", "DTE", "CMS", "ATO", "NI", "EVRG", "PNW"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA", "O", "SPG", "WELL", "DLR", "AVB", "EQR", "VTR", "ARE", "MAA"],
    "Communication Services": ["VZ", "T", "TMUS", "CMCSA", "CHTR"],
    "Industrials": ["WM", "RSG", "GD", "LMT", "RTX", "HON", "MMM", "JCI", "EMR", "ITW", "ROK", "SWK", "PH", "CMI"],
    "Consumer Discretionary": ["MCD", "YUM", "SBUX", "DPZ", "CMG", "DG", "DLTR", "ROST", "TJX", "NKE"],
    "Financials": ["BRK-B", "JPM", "BAC", "WFC", "C", "USB", "PNC", "TFC", "MTB", "FITB", "HBAN", "KEY", "CFG", "RF"],
    "Information Technology": ["CSCO", "IBM", "INTC", "TXN", "ADI", "PAYX", "ADP", "FISV", "FIS"],
    "Materials": ["APD", "SHW", "ECL", "LIN", "NEM", "FCX", "NUE", "CF", "MOS", "ALB"],
    "Energy": ["XOM", "CVX", "COP", "EOG", "SLB", "PXD", "VLO", "MPC", "PSX", "OXY"],
}


def get_sp500_tickers():
    """Get S&P 500 tickers from Wikipedia."""
    try:
        tables = pd.read_html(SP500_URL)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        sectors = dict(zip(tickers, df["GICS Sector"]))
        return tickers, sectors
    except Exception as e:
        print(f"  Wikipedia fetch failed ({e}), using hardcoded large-cap list")
        return _fallback_tickers()


def _fallback_tickers():
    tickers = []
    sectors = {}
    for sector, names in SECTOR_TLH_PAIRS.items():
        for t in names:
            tickers.append(t)
            sectors[t] = sector
    return tickers, sectors


def compute_beta(stock_returns, market_returns):
    """OLS beta from aligned weekly returns."""
    aligned = pd.concat([stock_returns, market_returns], axis=1).dropna()
    if len(aligned) < 52:
        return None
    x = aligned.iloc[:, 1].values
    y = aligned.iloc[:, 0].values
    cov = np.cov(y, x)
    if cov[1, 1] == 0:
        return None
    return cov[0, 1] / cov[1, 1]


def main():
    print("=" * 70)
    print("  LOW-BETA STOCK SCREENER (BTAL Replication)")
    print("=" * 70)

    tickers, sector_map = get_sp500_tickers()
    print(f"\n  Fetched {len(tickers)} tickers")

    all_tickers = list(set(tickers + ["SPY"]))
    print(f"  Downloading 3 years of weekly data...")
    raw = yf.download(all_tickers, start="2023-03-01", end="2026-03-04",
                      interval="1wk", auto_adjust=True, progress=False)

    closes = pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        for t in all_tickers:
            try:
                closes[t] = raw["Close"][t]
            except KeyError:
                pass
    print(f"  Got {len(closes)} weeks, {len(closes.columns)} tickers")

    weekly_returns = closes.pct_change().dropna(how="all")
    spy_ret = weekly_returns.get("SPY")
    if spy_ret is None:
        print("  ERROR: No SPY data")
        return

    print(f"\n  Computing betas...")
    results = []
    for t in tickers:
        if t not in weekly_returns.columns or t == "SPY":
            continue
        stock_ret = weekly_returns[t]
        beta = compute_beta(stock_ret, spy_ret)
        if beta is None:
            continue

        info = None
        try:
            tk = yf.Ticker(t)
            info = tk.info
        except Exception:
            pass

        mktcap = info.get("marketCap", 0) if info else 0
        pe = info.get("trailingPE", None) if info else None
        roe = info.get("returnOnEquity", None) if info else None
        de = info.get("debtToEquity", None) if info else None
        sector = sector_map.get(t, info.get("sector", "Unknown") if info else "Unknown")

        results.append({
            "ticker": t,
            "beta": beta,
            "mktcap_B": mktcap / 1e9 if mktcap else 0,
            "pe": pe,
            "roe": roe,
            "debt_equity": de,
            "sector": sector,
        })

    df = pd.DataFrame(results)
    print(f"  Computed betas for {len(df)} stocks")

    # Apply filters
    filtered = df[
        (df["beta"] < 0.70) &
        (df["mktcap_B"] >= 10) &
        (df["pe"].notna()) & (df["pe"] > 0)
    ].copy()

    # Quality filter where data available
    quality_mask = pd.Series(True, index=filtered.index)
    if "roe" in filtered.columns:
        has_roe = filtered["roe"].notna()
        quality_mask = quality_mask & (~has_roe | (filtered["roe"] > 0.08))
    if "debt_equity" in filtered.columns:
        has_de = filtered["debt_equity"].notna()
        quality_mask = quality_mask & (~has_de | (filtered["debt_equity"] < 200))
    filtered = filtered[quality_mask]

    filtered = filtered.sort_values("beta")

    print(f"\n  {'='*80}")
    print(f"  LOW-BETA CANDIDATES (beta < 0.70, mkt cap > $10B, positive earnings)")
    print(f"  {'='*80}")
    print(f"  {'Rank':<5} {'Ticker':<7} {'Beta':>6} {'MktCap':>8} {'P/E':>7} {'ROE':>7} {'D/E':>7}  {'Sector'}")
    print(f"  {'-'*78}")

    for i, (_, row) in enumerate(filtered.iterrows()):
        pe_str = f"{row['pe']:.1f}" if pd.notna(row['pe']) else "n/a"
        roe_str = f"{row['roe']*100:.0f}%" if pd.notna(row['roe']) else "n/a"
        de_str = f"{row['debt_equity']:.0f}" if pd.notna(row['debt_equity']) else "n/a"
        marker = " ***" if i < 20 else ""
        print(f"  {i+1:<5} {row['ticker']:<7} {row['beta']:>6.2f} {row['mktcap_B']:>7.1f}B {pe_str:>7} {roe_str:>7} {de_str:>7}  {row['sector']}{marker}")

    top20 = filtered.head(20)

    # Generate TLH swap pairs
    print(f"\n  {'='*80}")
    print(f"  TLH SWAP PAIRS (top 20)")
    print(f"  {'='*80}")
    print(f"  {'Primary':<8} {'Sector':<25} {'Swap Candidates'}")
    print(f"  {'-'*70}")

    for _, row in top20.iterrows():
        t = row["ticker"]
        sect = row["sector"]
        same_sector = filtered[
            (filtered["sector"] == sect) &
            (filtered["ticker"] != t)
        ]["ticker"].tolist()[:3]

        if not same_sector:
            for sector_name, sector_tickers in SECTOR_TLH_PAIRS.items():
                if sect and sector_name.lower() in sect.lower():
                    same_sector = [s for s in sector_tickers if s != t][:3]
                    break

        swap_str = ", ".join(same_sector) if same_sector else "(no direct swap - use sector ETF)"
        print(f"  {t:<8} {sect:<25} {swap_str}")

    # Save to CSV
    out_path = "C:\\Users\\WoodyWiegmann\\OneDrive - PFM\\Desktop\\Potomac\\low_beta_candidates.csv"
    filtered.to_csv(out_path, index=False)
    print(f"\n  Full list saved to {out_path}")

    # Summary stats
    print(f"\n  SUMMARY:")
    print(f"  Total candidates passing filters: {len(filtered)}")
    print(f"  Top 20 average beta: {top20['beta'].mean():.3f}")
    print(f"  Top 20 average mkt cap: ${top20['mktcap_B'].mean():.1f}B")
    print(f"  Sector breakdown (top 20):")
    for sect, count in top20["sector"].value_counts().items():
        print(f"    {sect}: {count}")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
