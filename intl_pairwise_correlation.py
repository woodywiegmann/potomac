"""
International Dual-Momentum Universe -- Pairwise Correlation Screen
====================================================================
Downloads daily prices for the full candidate universe and computes
the pairwise correlation matrix.  Outputs:
  1. Average pairwise correlation for the full set
  2. Heatmap-style ranking of highest-correlated pairs
  3. Each ticker's average correlation vs the rest
  4. Cluster analysis of highly correlated groups

All tickers have been verified at >=$200M AUM as of early 2026.
"""

import sys
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("Required: pip install yfinance pandas numpy")

# ---------------------------------------------------------------------------
# Universe -- 63 tickers, all international, all >=$200M AUM
# Roughly 3/4 developed, 1/4 EM+frontier
# ---------------------------------------------------------------------------

DEVELOPED_COUNTRY = {
    "EWJ":  "Japan",
    "EWG":  "Germany",
    "EWU":  "United Kingdom",
    "EWC":  "Canada",
    "EWA":  "Australia",
    "EWQ":  "France",
    "EWL":  "Switzerland",
    "EWP":  "Spain",
    "EWI":  "Italy",
    "EWD":  "Sweden",
    "EWH":  "Hong Kong",
    "EWS":  "Singapore",
    "EWN":  "Netherlands",
    "EDEN": "Denmark",
}

DEVELOPED_BROAD_FACTOR = {
    "SCZ":  "EAFE Small Cap",
    "DLS":  "Intl SmCap Dividend",
    "AVDV": "Intl SmCap Value",
    "IVLU": "Intl Value Factor",
    "IMTM": "Intl Momentum Factor",
    "IHDG": "Intl Hedged Qual Div Growth",
    "PXF":  "RAFI Dev Mkts ex-US",
    "HDEF": "EAFE High Div Yield",
    "AVDE": "Avantis Intl Equity",
    "IPAC": "iShares Core MSCI Pacific",
    "FLJP": "Franklin Japan",
    "FLGB": "Franklin UK",
    "IVAL": "Intl Quant Value",
}

DEVELOPED_THEMATIC = {
    "COPX": "Copper Miners",
    "SIL":  "Silver Miners",
    "SILJ": "Jr Silver Miners",
    "RING": "Global Gold Miners",
    "URA":  "Uranium",
    "URNM": "Uranium Miners",
    "REMX": "Rare Earth & Strategic Metals",
    "LIT":  "Lithium & Battery Tech",
    "PICK": "Global Metals & Mining",
    "GNR":  "S&P Global Natural Resources",
    "GUNR": "Global Upstream NatRes",
    "MOO":  "Agribusiness",
    "GRID": "Clean Edge Smart Grid/Infra",
    "CGW":  "Global Water",
    "GII":  "Global Infrastructure",
    "INFL": "Inflation Beneficiaries",
    "KXI":  "Global Consumer Staples",
    "MXI":  "Global Materials",
}

EM_COUNTRY = {
    "EWT":  "Taiwan",
    "EWZ":  "Brazil",
    "INDA": "India",
    "FXI":  "China Large-Cap",
    "EWY":  "South Korea",
    "EWW":  "Mexico",
    "ILF":  "Latin America 40",
    "ECH":  "Chile",
    "TUR":  "Turkey",
    "ARGT": "Argentina",
    "VNM":  "Vietnam",
    "THD":  "Thailand",
    "EWM":  "Malaysia",
    "EIDO": "Indonesia",
}

EM_BROAD_THEMATIC = {
    "EMXC": "EM ex-China",
    "AVEM": "Avantis EM Equity",
    "DEM":  "EM High Dividend",
    "EPI":  "WisdomTree India Earnings",
    "GVAL": "Cambria Global Value",
    "KSA":  "Saudi Arabia",
    "KWEB": "China Internet",
    "FLKR": "Franklin South Korea",
    "FLBR": "Franklin Brazil",
    "FLIN": "Franklin India",
    "CQQQ": "China Technology",
    "EEMA": "EM Asia",
}

ALL_TICKERS = {}
ALL_TICKERS.update(DEVELOPED_COUNTRY)
ALL_TICKERS.update(DEVELOPED_BROAD_FACTOR)
ALL_TICKERS.update(DEVELOPED_THEMATIC)
ALL_TICKERS.update(EM_COUNTRY)
ALL_TICKERS.update(EM_BROAD_THEMATIC)

BUCKET_LABELS = {}
for t in DEVELOPED_COUNTRY:   BUCKET_LABELS[t] = "Dev Country"
for t in DEVELOPED_BROAD_FACTOR: BUCKET_LABELS[t] = "Dev Factor/Broad"
for t in DEVELOPED_THEMATIC:  BUCKET_LABELS[t] = "Dev Thematic"
for t in EM_COUNTRY:          BUCKET_LABELS[t] = "EM Country"
for t in EM_BROAD_THEMATIC:   BUCKET_LABELS[t] = "EM Broad/Thematic"

LOOKBACK_YEARS = 5

# ---------------------------------------------------------------------------

def fetch_prices(tickers: list, years: int = LOOKBACK_YEARS) -> pd.DataFrame:
    """Download adjusted close prices in batches to avoid throttling."""
    end = pd.Timestamp.now()
    start = end - pd.DateOffset(years=years)
    batch_size = 15
    frames = []
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        print(f"  Downloading batch {i // batch_size + 1}: {', '.join(batch)}")
        df = yf.download(batch, start=start, end=end, auto_adjust=True,
                         progress=False)["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame(batch[0])
        frames.append(df)
    combined = pd.concat(frames, axis=1)
    combined = combined.dropna(how="all")
    return combined


def correlation_analysis(prices: pd.DataFrame):
    """Compute daily-return correlation matrix and summary stats."""
    returns = prices.pct_change().dropna()
    corr = returns.corr()
    return returns, corr


def top_corr_pairs(corr: pd.DataFrame, n: int = 40):
    """Return the N most correlated pairs."""
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append((cols[i], cols[j], corr.iloc[i, j]))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:n]


def bottom_corr_pairs(corr: pd.DataFrame, n: int = 20):
    """Return the N least correlated (or most negatively correlated) pairs."""
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append((cols[i], cols[j], corr.iloc[i, j]))
    pairs.sort(key=lambda x: x[2])
    return pairs[:n]


def avg_corr_per_ticker(corr: pd.DataFrame) -> pd.Series:
    """Average pairwise correlation for each ticker vs the rest."""
    n = len(corr)
    totals = corr.sum(axis=1) - 1.0  # subtract self-correlation of 1
    return (totals / (n - 1)).sort_values(ascending=False)


def cluster_report(corr: pd.DataFrame, threshold: float = 0.80):
    """Find groups of tickers where all pairwise correlations > threshold."""
    cols = corr.columns.tolist()
    high_pairs = {}
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if corr.iloc[i, j] >= threshold:
                high_pairs.setdefault(cols[i], set()).add(cols[j])
                high_pairs.setdefault(cols[j], set()).add(cols[i])
    return high_pairs


def main():
    tickers = list(ALL_TICKERS.keys())
    n_dev = len(DEVELOPED_COUNTRY) + len(DEVELOPED_BROAD_FACTOR) + len(DEVELOPED_THEMATIC)
    n_em = len(EM_COUNTRY) + len(EM_BROAD_THEMATIC)
    print(f"\nInternational Dual-Momentum Universe: Pairwise Correlation Screen")
    print(f"=" * 70)
    print(f"Total tickers: {len(tickers)}")
    print(f"  Developed:  {n_dev}  ({100*n_dev/len(tickers):.1f}%)")
    print(f"  EM+Frontier: {n_em}  ({100*n_em/len(tickers):.1f}%)")
    print(f"\nFetching {LOOKBACK_YEARS}-year daily prices...")

    prices = fetch_prices(tickers)
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        print(f"\n  WARNING: No data for: {', '.join(missing)}")
        tickers = [t for t in tickers if t in prices.columns]
        prices = prices[tickers]

    available = prices.dropna(axis=1, how="all").columns.tolist()
    print(f"\n  Tickers with data: {len(available)}")

    returns, corr = correlation_analysis(prices[available])
    n_pairs = len(available) * (len(available) - 1) // 2
    all_corrs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            all_corrs.append(corr.iloc[i, j])

    avg_corr = np.mean(all_corrs)
    med_corr = np.median(all_corrs)

    print(f"\n{'=' * 70}")
    print(f"OVERALL STATISTICS")
    print(f"{'=' * 70}")
    print(f"  Total unique pairs:        {n_pairs:,}")
    print(f"  Average pairwise corr:     {avg_corr:.4f}")
    print(f"  Median pairwise corr:      {med_corr:.4f}")
    print(f"  Min pairwise corr:         {min(all_corrs):.4f}")
    print(f"  Max pairwise corr:         {max(all_corrs):.4f}")
    print(f"  Pairs > 0.90:              {sum(1 for c in all_corrs if c > 0.90)}")
    print(f"  Pairs > 0.80:              {sum(1 for c in all_corrs if c > 0.80)}")
    print(f"  Pairs > 0.70:              {sum(1 for c in all_corrs if c > 0.70)}")
    print(f"  Pairs < 0.30:              {sum(1 for c in all_corrs if c < 0.30)}")
    print(f"  Pairs < 0.10:              {sum(1 for c in all_corrs if c < 0.10)}")

    # --- Top correlated pairs ---
    print(f"\n{'=' * 70}")
    print(f"TOP 40 MOST CORRELATED PAIRS")
    print(f"{'=' * 70}")
    print(f"{'Pair':<30} {'Corr':>7}  {'Bucket A':<20} {'Bucket B':<20}")
    print(f"{'-'*30} {'-'*7}  {'-'*20} {'-'*20}")
    for a, b, c in top_corr_pairs(corr, 40):
        lbl_a = BUCKET_LABELS.get(a, "?")
        lbl_b = BUCKET_LABELS.get(b, "?")
        print(f"{a + ' / ' + b:<30} {c:>7.4f}  {lbl_a:<20} {lbl_b:<20}")

    # --- Lowest correlated pairs ---
    print(f"\n{'=' * 70}")
    print(f"TOP 20 LEAST CORRELATED PAIRS (diversification gems)")
    print(f"{'=' * 70}")
    print(f"{'Pair':<30} {'Corr':>7}  {'Bucket A':<20} {'Bucket B':<20}")
    print(f"{'-'*30} {'-'*7}  {'-'*20} {'-'*20}")
    for a, b, c in bottom_corr_pairs(corr, 20):
        lbl_a = BUCKET_LABELS.get(a, "?")
        lbl_b = BUCKET_LABELS.get(b, "?")
        print(f"{a + ' / ' + b:<30} {c:>7.4f}  {lbl_a:<20} {lbl_b:<20}")

    # --- Per-ticker average correlation ---
    print(f"\n{'=' * 70}")
    print(f"PER-TICKER AVERAGE CORRELATION (highest = most redundant)")
    print(f"{'=' * 70}")
    avg = avg_corr_per_ticker(corr)
    print(f"{'Ticker':<8} {'Avg Corr':>9}  {'Bucket':<20} {'Name':<40}")
    print(f"{'-'*8} {'-'*9}  {'-'*20} {'-'*40}")
    for t, c in avg.items():
        print(f"{t:<8} {c:>9.4f}  {BUCKET_LABELS.get(t, '?'):<20} {ALL_TICKERS.get(t, ''):<40}")

    # --- High-correlation clusters ---
    print(f"\n{'=' * 70}")
    print(f"HIGH-CORRELATION CLUSTERS (threshold >= 0.80)")
    print(f"{'=' * 70}")
    clusters = cluster_report(corr, 0.80)
    if not clusters:
        print("  No pairs above 0.80 threshold.")
    else:
        seen = set()
        for anchor in sorted(clusters.keys()):
            group = frozenset([anchor] + list(clusters[anchor]))
            if group not in seen:
                seen.add(group)
                members = sorted(group)
                print(f"\n  Cluster: {', '.join(members)}")
                for m in members:
                    print(f"    {m:<8} {BUCKET_LABELS.get(m, '?'):<20} {ALL_TICKERS.get(m, '')}")

    # --- Composition summary ---
    print(f"\n{'=' * 70}")
    print(f"UNIVERSE COMPOSITION")
    print(f"{'=' * 70}")
    for bucket_name in ["Dev Country", "Dev Factor/Broad", "Dev Thematic",
                         "EM Country", "EM Broad/Thematic"]:
        members = [t for t in available if BUCKET_LABELS.get(t) == bucket_name]
        bucket_avg = []
        for t in members:
            bucket_avg.append(avg[t])
        if bucket_avg:
            print(f"  {bucket_name:<20}  {len(members):>3} tickers  "
                  f"avg corr = {np.mean(bucket_avg):.4f}")

    # --- Save correlation matrix to CSV ---
    out_path = r"c:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac\intl_corr_matrix.csv"
    corr.to_csv(out_path)
    print(f"\nCorrelation matrix saved to: {out_path}")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
