"""
International Universe -- Iterative Correlation Trimming
=========================================================
Starting from the full 71-ticker candidate universe, iteratively drops
the ticker with the HIGHEST average pairwise correlation at each step.
Shows how avg pairwise corr improves as the universe shrinks from 71
down to 30.

Uses the pre-computed correlation matrix from intl_pairwise_correlation.py
(recomputed from returns here to avoid stale data issues).
"""

import sys, os
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("Required: pip install yfinance pandas numpy")

# ---------------------------------------------------------------------------
# Same universe definition as intl_pairwise_correlation.py
# ---------------------------------------------------------------------------
DEVELOPED_COUNTRY = {
    "EWJ": "Japan", "EWG": "Germany", "EWU": "United Kingdom",
    "EWC": "Canada", "EWA": "Australia", "EWQ": "France",
    "EWL": "Switzerland", "EWP": "Spain", "EWI": "Italy",
    "EWD": "Sweden", "EWH": "Hong Kong", "EWS": "Singapore",
    "EWN": "Netherlands", "EDEN": "Denmark",
}
DEVELOPED_BROAD_FACTOR = {
    "SCZ": "EAFE Small Cap", "DLS": "Intl SmCap Dividend",
    "AVDV": "Intl SmCap Value", "IVLU": "Intl Value Factor",
    "IMTM": "Intl Momentum Factor", "IHDG": "Intl Hedged Qual Div Growth",
    "PXF": "RAFI Dev Mkts ex-US", "HDEF": "EAFE High Div Yield",
    "AVDE": "Avantis Intl Equity", "IPAC": "iShares Core MSCI Pacific",
    "FLJP": "Franklin Japan", "FLGB": "Franklin UK", "IVAL": "Intl Quant Value",
}
DEVELOPED_THEMATIC = {
    "COPX": "Copper Miners", "SIL": "Silver Miners", "SILJ": "Jr Silver Miners",
    "RING": "Global Gold Miners", "URA": "Uranium", "URNM": "Uranium Miners",
    "REMX": "Rare Earth & Strategic Metals", "LIT": "Lithium & Battery Tech",
    "PICK": "Global Metals & Mining", "GNR": "S&P Global Natural Resources",
    "GUNR": "Global Upstream NatRes", "MOO": "Agribusiness",
    "GRID": "Clean Edge Smart Grid/Infra", "CGW": "Global Water",
    "GII": "Global Infrastructure", "INFL": "Inflation Beneficiaries",
    "KXI": "Global Consumer Staples", "MXI": "Global Materials",
}
EM_COUNTRY = {
    "EWT": "Taiwan", "EWZ": "Brazil", "INDA": "India",
    "FXI": "China Large-Cap", "EWY": "South Korea", "EWW": "Mexico",
    "ILF": "Latin America 40", "ECH": "Chile", "TUR": "Turkey",
    "ARGT": "Argentina", "VNM": "Vietnam", "THD": "Thailand",
    "EWM": "Malaysia", "EIDO": "Indonesia",
}
EM_BROAD_THEMATIC = {
    "EMXC": "EM ex-China", "AVEM": "Avantis EM Equity",
    "DEM": "EM High Dividend", "EPI": "WisdomTree India Earnings",
    "GVAL": "Cambria Global Value", "KSA": "Saudi Arabia",
    "KWEB": "China Internet", "FLKR": "Franklin South Korea",
    "FLBR": "Franklin Brazil", "FLIN": "Franklin India",
    "CQQQ": "China Technology", "EEMA": "EM Asia",
}

ALL_TICKERS = {}
ALL_TICKERS.update(DEVELOPED_COUNTRY)
ALL_TICKERS.update(DEVELOPED_BROAD_FACTOR)
ALL_TICKERS.update(DEVELOPED_THEMATIC)
ALL_TICKERS.update(EM_COUNTRY)
ALL_TICKERS.update(EM_BROAD_THEMATIC)

BUCKET_LABELS = {}
for t in DEVELOPED_COUNTRY:      BUCKET_LABELS[t] = "Dev Country"
for t in DEVELOPED_BROAD_FACTOR: BUCKET_LABELS[t] = "Dev Factor"
for t in DEVELOPED_THEMATIC:     BUCKET_LABELS[t] = "Dev Thematic"
for t in EM_COUNTRY:             BUCKET_LABELS[t] = "EM Country"
for t in EM_BROAD_THEMATIC:      BUCKET_LABELS[t] = "EM Broad"

# ---------------------------------------------------------------------------

def fetch_prices(tickers, years=5):
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
    return pd.concat(frames, axis=1).dropna(how="all")


def calc_avg_pairwise(corr):
    """Average of all off-diagonal correlations."""
    n = len(corr)
    total = (corr.values.sum() - n) / (n * (n - 1))
    return total


def avg_corr_per_ticker(corr):
    n = len(corr)
    return ((corr.sum(axis=1) - 1.0) / (n - 1)).sort_values(ascending=False)


def bucket_composition(tickers):
    """Count tickers per bucket."""
    counts = {}
    for t in tickers:
        b = BUCKET_LABELS.get(t, "?")
        counts[b] = counts.get(b, 0) + 1
    return counts


def main():
    tickers = list(ALL_TICKERS.keys())
    print(f"Fetching 5-year daily prices for {len(tickers)} tickers...")
    prices = fetch_prices(tickers)

    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        print(f"  No data for: {', '.join(missing)}")
        tickers = [t for t in tickers if t in prices.columns]

    prices = prices[tickers].dropna(how="all")
    returns = prices.pct_change().dropna()

    remaining = list(tickers)
    target = 30
    drop_log = []

    print(f"\n{'='*85}")
    print(f"ITERATIVE TRIMMING: {len(remaining)} -> {target} tickers")
    print(f"{'='*85}")
    print(f"{'Step':>4}  {'Dropped':<8} {'Name':<35} {'Bucket':<15} "
          f"{'AvgCorr':>8} {'Remaining':>4}  {'Universe AvgCorr':>16}")
    print(f"{'-'*4}  {'-'*8} {'-'*35} {'-'*15} {'-'*8} {'-'*4}  {'-'*16}")

    corr = returns[remaining].corr()
    avg0 = calc_avg_pairwise(corr)
    print(f"{'0':>4}  {'--':<8} {'(starting universe)':<35} {'--':<15} "
          f"{'--':>8} {len(remaining):>4}  {avg0:>16.4f}")

    step = 0
    while len(remaining) > target:
        corr = returns[remaining].corr()
        avg_per = avg_corr_per_ticker(corr)
        worst = avg_per.index[0]
        worst_corr = avg_per.iloc[0]

        remaining.remove(worst)
        step += 1

        corr_new = returns[remaining].corr()
        new_avg = calc_avg_pairwise(corr_new)

        name = ALL_TICKERS.get(worst, "")
        bucket = BUCKET_LABELS.get(worst, "?")
        drop_log.append((step, worst, name, bucket, worst_corr, len(remaining), new_avg))

        print(f"{step:>4}  {worst:<8} {name:<35} {bucket:<15} "
              f"{worst_corr:>8.4f} {len(remaining):>4}  {new_avg:>16.4f}")

    # --- Final universe ---
    print(f"\n{'='*85}")
    print(f"FINAL UNIVERSE: {len(remaining)} tickers  |  Avg pairwise corr: {new_avg:.4f}")
    print(f"{'='*85}")

    comp = bucket_composition(remaining)
    total_dev = comp.get("Dev Country", 0) + comp.get("Dev Factor", 0) + comp.get("Dev Thematic", 0)
    total_em = comp.get("EM Country", 0) + comp.get("EM Broad", 0)
    print(f"\n  Composition:")
    for b in ["Dev Country", "Dev Factor", "Dev Thematic", "EM Country", "EM Broad"]:
        print(f"    {b:<20} {comp.get(b, 0):>3}")
    print(f"    {'---':<20} {'---':>3}")
    print(f"    {'Developed total':<20} {total_dev:>3}  ({100*total_dev/len(remaining):.1f}%)")
    print(f"    {'EM total':<20} {total_em:>3}  ({100*total_em/len(remaining):.1f}%)")

    print(f"\n  Tickers ({len(remaining)}):")
    print(f"  {'Ticker':<8} {'Bucket':<15} {'Name':<40}")
    print(f"  {'-'*8} {'-'*15} {'-'*40}")

    final_corr = returns[remaining].corr()
    final_avg = avg_corr_per_ticker(final_corr)
    for t in sorted(remaining, key=lambda x: (BUCKET_LABELS.get(x, "Z"), x)):
        print(f"  {t:<8} {BUCKET_LABELS.get(t, '?'):<15} {ALL_TICKERS.get(t, ''):<40} "
              f"avg_corr={final_avg[t]:.4f}")

    # --- Pairs still above 0.90 ---
    cols = final_corr.columns.tolist()
    hot = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if final_corr.iloc[i, j] > 0.90:
                hot.append((cols[i], cols[j], final_corr.iloc[i, j]))
    hot.sort(key=lambda x: x[2], reverse=True)

    print(f"\n  Remaining pairs > 0.90 correlation: {len(hot)}")
    if hot:
        for a, b, c in hot:
            print(f"    {a} / {b}: {c:.4f}")

    # --- Key milestones ---
    print(f"\n{'='*85}")
    print(f"KEY MILESTONES")
    print(f"{'='*85}")
    milestones = [71, 65, 60, 55, 50, 45, 40, 35, 30]
    print(f"  {'Count':>5}  {'Avg Pairwise Corr':>18}  {'Delta from 71':>14}")
    print(f"  {'-'*5}  {'-'*18}  {'-'*14}")
    print(f"  {71:>5}  {avg0:>18.4f}  {'baseline':>14}")
    for entry in drop_log:
        cnt = entry[5]
        ac = entry[6]
        if cnt in milestones:
            print(f"  {cnt:>5}  {ac:>18.4f}  {ac - avg0:>+14.4f}")


if __name__ == "__main__":
    main()
