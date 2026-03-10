"""
International Universe -- Smart De-Dup + Constrained Trim (v2)
===============================================================
Phase 1: Hard-drop one ticker from each near-duplicate pair (>0.95 corr),
          keeping the one with higher AUM / better liquidity.
Phase 2: Greedy trim with a dev/EM composition floor so we don't
          accidentally skew the universe.
Phase 3: Show the final universe at multiple target sizes (50, 45, 40, 35).
"""

import sys
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("Required: pip install yfinance pandas numpy")

# ---------------------------------------------------------------------------
# Universe
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

DEV_BUCKETS = {"Dev Country", "Dev Factor", "Dev Thematic"}
EM_BUCKETS  = {"EM Country", "EM Broad"}

# Phase 1: hard de-dup rules.  For each pair >0.95, drop the one with
# lower AUM (verified from screener / web search).
HARD_DROPS = [
    ("FLJP",  "EWJ",  "Same Japan -- FLJP lower AUM"),
    ("FLKR",  "EWY",  "Same South Korea -- FLKR lower AUM"),
    ("FLBR",  "EWZ",  "Same Brazil -- FLBR lower AUM"),
    ("FLGB",  "EWU",  "Same UK -- FLGB lower AUM"),
    ("FLIN",  "INDA", "Same India -- FLIN lower AUM"),
    ("EPI",   "INDA", "India earnings tilt but 0.96 corr -- EPI lower AUM"),
    ("URNM",  "URA",  "Same uranium -- URNM lower AUM"),
    ("SILJ",  "SIL",  "Jr silver miners 0.97 corr with SIL -- SILJ lower AUM"),
    ("GUNR",  "GNR",  "Same nat resources -- GUNR lower AUM, higher fee"),
    ("CQQQ",  "KWEB", "Both China tech/internet 0.93 -- keep KWEB (purer intl play)"),
    ("EEMA",  "AVEM", "EM Asia vs EM broad 0.96 -- EEMA more redundant"),
]

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
    n = len(corr)
    return (corr.values.sum() - n) / (n * (n - 1))


def avg_corr_per_ticker(corr):
    n = len(corr)
    return ((corr.sum(axis=1) - 1.0) / (n - 1)).sort_values(ascending=False)


def is_dev(t):
    return BUCKET_LABELS.get(t, "") in DEV_BUCKETS

def is_em(t):
    return BUCKET_LABELS.get(t, "") in EM_BUCKETS

def composition(tickers):
    dev = sum(1 for t in tickers if is_dev(t))
    em  = sum(1 for t in tickers if is_em(t))
    return dev, em

def bucket_detail(tickers):
    counts = {}
    for t in tickers:
        b = BUCKET_LABELS.get(t, "?")
        counts[b] = counts.get(b, 0) + 1
    return counts


def constrained_trim(returns, remaining, target, dev_floor_pct=0.60):
    """
    Greedy trim with a constraint: never drop a developed ticker if doing so
    would push developed % below dev_floor_pct of the remaining universe.
    """
    log = []
    while len(remaining) > target:
        corr = returns[remaining].corr()
        avg_per = avg_corr_per_ticker(corr)

        dropped = False
        for candidate in avg_per.index:
            trial = [t for t in remaining if t != candidate]
            dev, em = composition(trial)
            dev_pct = dev / len(trial)
            if is_dev(candidate) and dev_pct < dev_floor_pct:
                continue
            remaining.remove(candidate)
            corr_new = returns[remaining].corr()
            new_avg = calc_avg_pairwise(corr_new)
            log.append((candidate, ALL_TICKERS.get(candidate, ""),
                        BUCKET_LABELS.get(candidate, "?"),
                        avg_per[candidate], len(remaining), new_avg))
            dropped = True
            break

        if not dropped:
            # all remaining candidates are dev and constrained -- relax and drop highest anyway
            candidate = avg_per.index[0]
            remaining.remove(candidate)
            corr_new = returns[remaining].corr()
            new_avg = calc_avg_pairwise(corr_new)
            log.append((candidate, ALL_TICKERS.get(candidate, ""),
                        BUCKET_LABELS.get(candidate, "?"),
                        avg_per[candidate], len(remaining), new_avg))

    return remaining, log


def print_universe(remaining, returns, label=""):
    corr = returns[remaining].corr()
    avg_pw = calc_avg_pairwise(corr)
    avg_per = avg_corr_per_ticker(corr)
    dev, em = composition(remaining)

    print(f"\n{'='*85}")
    print(f"{label}: {len(remaining)} tickers  |  Avg pairwise corr: {avg_pw:.4f}")
    print(f"{'='*85}")

    bd = bucket_detail(remaining)
    print(f"\n  Composition:  Dev {dev} ({100*dev/len(remaining):.0f}%)  |  "
          f"EM {em} ({100*em/len(remaining):.0f}%)")
    for b in ["Dev Country", "Dev Factor", "Dev Thematic", "EM Country", "EM Broad"]:
        print(f"    {b:<20} {bd.get(b, 0):>3}")

    print(f"\n  {'Ticker':<8} {'Bucket':<15} {'AvgCorr':>8}  {'Name':<40}")
    print(f"  {'-'*8} {'-'*15} {'-'*8}  {'-'*40}")
    for t in sorted(remaining, key=lambda x: (BUCKET_LABELS.get(x, "Z"), avg_per.get(x, 0))):
        print(f"  {t:<8} {BUCKET_LABELS.get(t, '?'):<15} {avg_per[t]:>8.4f}  "
              f"{ALL_TICKERS.get(t, ''):<40}")

    # pairs still > 0.90
    cols = corr.columns.tolist()
    hot = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if corr.iloc[i, j] > 0.90:
                hot.append((cols[i], cols[j], corr.iloc[i, j]))
    hot.sort(key=lambda x: x[2], reverse=True)
    if hot:
        print(f"\n  WARNING: {len(hot)} pair(s) still > 0.90:")
        for a, b, c in hot:
            print(f"    {a} / {b}: {c:.4f}")
    else:
        print(f"\n  No pairs > 0.90 -- clean universe.")

    return avg_pw


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

    # -----------------------------------------------------------------------
    # Phase 1: Hard de-duplication
    # -----------------------------------------------------------------------
    remaining = list(tickers)
    corr_full = returns[remaining].corr()
    avg0 = calc_avg_pairwise(corr_full)

    print(f"\n{'='*85}")
    print(f"PHASE 1: HARD DE-DUPLICATION (pairs > 0.95 corr)")
    print(f"{'='*85}")
    print(f"Starting: {len(remaining)} tickers, avg pairwise corr = {avg0:.4f}\n")

    for drop, keep, reason in HARD_DROPS:
        if drop in remaining and keep in remaining:
            c = corr_full.loc[drop, keep] if drop in corr_full.index and keep in corr_full.index else 0
            remaining.remove(drop)
            print(f"  DROP {drop:<6} (keep {keep:<6})  corr={c:.4f}  {reason}")
        elif drop not in remaining:
            print(f"  SKIP {drop:<6} -- already removed")

    corr_post1 = returns[remaining].corr()
    avg1 = calc_avg_pairwise(corr_post1)
    dev1, em1 = composition(remaining)

    print(f"\nAfter Phase 1: {len(remaining)} tickers, "
          f"avg pairwise corr = {avg1:.4f} (was {avg0:.4f})")
    print(f"  Dev: {dev1} ({100*dev1/len(remaining):.0f}%)  "
          f"EM: {em1} ({100*em1/len(remaining):.0f}%)")

    # Show remaining >0.90 pairs after dedup
    cols = corr_post1.columns.tolist()
    hot90 = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if corr_post1.iloc[i, j] > 0.90:
                hot90.append((cols[i], cols[j], corr_post1.iloc[i, j]))
    hot90.sort(key=lambda x: x[2], reverse=True)
    if hot90:
        print(f"\n  Pairs still > 0.90 after de-dup: {len(hot90)}")
        for a, b, c in hot90:
            print(f"    {a} / {b}: {c:.4f}")

    # -----------------------------------------------------------------------
    # Phase 2: Constrained greedy trim to multiple targets
    # -----------------------------------------------------------------------
    print(f"\n{'='*85}")
    print(f"PHASE 2: CONSTRAINED GREEDY TRIM (dev floor = 60%)")
    print(f"{'='*85}")

    targets = [50, 45, 40, 35]
    snapshots = {}

    working = list(remaining)
    for target in targets:
        if len(working) <= target:
            print(f"\n  Already at or below {target}, skipping.")
            snapshots[target] = list(working)
            continue

        working, log = constrained_trim(returns, list(working), target, dev_floor_pct=0.60)

        print(f"\n  Trimming to {target}:")
        print(f"  {'Dropped':<8} {'Name':<35} {'Bucket':<15} {'AvgCorr':>8} "
              f"{'Left':>4}  {'UnivCorr':>9}")
        print(f"  {'-'*8} {'-'*35} {'-'*15} {'-'*8} {'-'*4}  {'-'*9}")
        for ticker, name, bucket, ac, cnt, uc in log:
            print(f"  {ticker:<8} {name:<35} {bucket:<15} {ac:>8.4f} "
                  f"{cnt:>4}  {uc:>9.4f}")

        snapshots[target] = list(working)

    # -----------------------------------------------------------------------
    # Phase 3: Print final universes
    # -----------------------------------------------------------------------
    print(f"\n\n{'#'*85}")
    print(f"FINAL UNIVERSES AT EACH TARGET SIZE")
    print(f"{'#'*85}")

    milestone_corrs = {}
    for target in targets:
        avg_c = print_universe(snapshots[target], returns,
                               label=f"TARGET {target}")
        milestone_corrs[target] = avg_c

    # Summary table
    print(f"\n\n{'='*85}")
    print(f"SUMMARY")
    print(f"{'='*85}")
    print(f"  {'Stage':<30} {'Count':>5}  {'AvgCorr':>8}  {'Dev%':>5}  {'EM%':>5}")
    print(f"  {'-'*30} {'-'*5}  {'-'*8}  {'-'*5}  {'-'*5}")

    print(f"  {'Full universe':<30} {len(tickers):>5}  {avg0:>8.4f}  "
          f"{100*composition(tickers)[0]/len(tickers):>5.0f}  "
          f"{100*composition(tickers)[1]/len(tickers):>5.0f}")

    print(f"  {'After de-dup (Phase 1)':<30} {len(remaining):>5}  {avg1:>8.4f}  "
          f"{100*dev1/len(remaining):>5.0f}  {100*em1/len(remaining):>5.0f}")

    for target in targets:
        snap = snapshots[target]
        d, e = composition(snap)
        print(f"  {'Trimmed to ' + str(target):<30} {len(snap):>5}  "
              f"{milestone_corrs[target]:>8.4f}  "
              f"{100*d/len(snap):>5.0f}  {100*e/len(snap):>5.0f}")


if __name__ == "__main__":
    main()
