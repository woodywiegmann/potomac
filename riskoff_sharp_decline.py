"""
Performance of each risk-off strategy on days where S&P was sharply down.
Uses the same regime detection as h2h.py / riskoff_regression.py.
Targets the worst ~60+ S&P days within the risk-off sample.
"""

import os, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_tr(ticker, start, end):
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float), set()
    h.index = h.index.tz_localize(None)
    nav = h["Close"]
    divs = h.get("Dividends", pd.Series(0.0, index=h.index))
    dist_dates = set(divs[divs > 0].index)
    sh = 1.0
    v = []
    for dt in h.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            sh *= (1 + d / p)
        v.append(sh * p)
    return pd.Series(v, index=h.index, name=ticker), dist_dates


def main():
    START, END = "2023-03-01", "2026-02-26"

    print("Fetching total-return series...")
    crdbx, crdbx_dist = get_tr("CRDBX", "2022-12-01", END)
    spy, _ = get_tr("SPY", "2022-12-01", END)
    sgov, _ = get_tr("SGOV", "2022-12-01", END)
    dbmf, _ = get_tr("DBMF", "2022-12-01", END)
    caos, _ = get_tr("CAOS", "2023-03-01", END)
    heqt, _ = get_tr("HEQT", "2022-12-01", END)

    idx = (crdbx.index.intersection(spy.index).intersection(sgov.index)
           .intersection(dbmf.index).intersection(caos.index).intersection(heqt.index))
    idx = idx[idx >= START]

    cr = crdbx.reindex(idx).pct_change().fillna(0)
    sp = spy.reindex(idx).pct_change().fillna(0)
    sg = sgov.reindex(idx).pct_change().fillna(0)
    dm = dbmf.reindex(idx).pct_change().fillna(0)
    ca = caos.reindex(idx).pct_change().fillna(0)
    hq = heqt.reindex(idx).pct_change().fillna(0)

    dist_window = set()
    for d in crdbx_dist:
        for offset in [-1, 0, 1]:
            dist_window.add(d + pd.Timedelta(days=offset))

    regime = pd.Series("AMBIGUOUS", index=idx)
    for i in range(len(idx)):
        dt = idx[i]
        if dt in dist_window:
            regime.iloc[i] = "EXCLUDED"
            continue
        spy_move, crdbx_move = sp.iloc[i], cr.iloc[i]
        if abs(spy_move) < 0.0015:
            regime.iloc[i] = "AMBIGUOUS"
            continue
        if abs(crdbx_move) < 0.0003 and abs(spy_move) >= 0.0015:
            regime.iloc[i] = "OFF"
            continue
        ratio = crdbx_move / spy_move
        if ratio > 0.70 and abs(crdbx_move) > 0.002:
            regime.iloc[i] = "ON"
            continue

    off = regime == "OFF"
    n_off = off.sum()

    sp_off = sp[off]
    sg_off = sg[off]
    dm_off = dm[off]
    ca_off = ca[off]
    hq_off = hq[off]

    strats = {
        "SGOV": sg_off,
        "50/50 SGOV/CAOS": 0.50 * sg_off + 0.50 * ca_off,
        "EqWt 3-Way": (dm_off + ca_off + sg_off) / 3,
        "15H/15D/70S": 0.15 * hq_off + 0.15 * dm_off + 0.70 * sg_off,
        "CAOS only": ca_off,
        "DBMF only": dm_off,
    }

    # Find threshold to get ~60+ days: sort S&P risk-off returns, take bottom N
    sp_off_sorted = sp_off.sort_values()
    # Find the cutoff that gives us at least 60 days of S&P < 0
    sp_down_off = sp_off[sp_off < 0].sort_values()
    n_down = len(sp_down_off)

    if n_down >= 60:
        target_n = 60
        threshold = sp_down_off.iloc[target_n - 1]
        sharp = sp_off <= threshold
    else:
        sharp = sp_off < 0
        target_n = n_down
        threshold = sp_down_off.iloc[-1] if n_down > 0 else 0

    n_sharp = sharp.sum()
    thresh_pct = threshold * 100

    L = []
    def p(s=""):
        L.append(s)
        print(s)

    W = 130
    p("=" * W)
    p("RISK-OFF STRATEGY PERFORMANCE ON SHARP S&P DECLINE DAYS")
    p("=" * W)
    p(f"Universe: {n_off} verified risk-off days (Mar 2023 - Feb 2026)")
    p(f"Filter: S&P 500 daily return <= {thresh_pct:.2f}% on risk-off days")
    p(f"Result: {n_sharp} days where S&P was sharply down while fund was defensive")
    p()
    p(f"S&P 500 on these {n_sharp} days:")
    sp_sharp = sp_off[sharp]
    p(f"  Mean:    {sp_sharp.mean()*100:+.3f}%")
    p(f"  Median:  {sp_sharp.median()*100:+.3f}%")
    p(f"  Worst:   {sp_sharp.min()*100:+.3f}%")
    p(f"  Best:    {sp_sharp.max()*100:+.3f}%  (still negative)")
    p(f"  Cum:     {((1+sp_sharp).prod()-1)*100:+.2f}%")
    p()

    # Header
    p("-" * W)
    hdr1 = f"{'Strategy':.<30}"
    hdr2 = f"{'':.<30}"
    for label in ["Mean", "Median", "Worst Day", "Best Day", "Cumulative", "Days +", "Days -", "Win Rate", "Beta"]:
        hdr1 += f" {label:>12}"
    p(hdr1)
    p("-" * W)

    for name, series in strats.items():
        s = series[sharp]
        mean_r = s.mean() * 100
        med_r = s.median() * 100
        worst = s.min() * 100
        best = s.max() * 100
        cum = ((1 + s).prod() - 1) * 100
        pos = (s > 0).sum()
        neg = (s <= 0).sum()
        win = pos / len(s) * 100 if len(s) > 0 else 0

        sp_vals = sp_off[sharp].values
        s_vals = s.values
        if len(sp_vals) > 3 and np.var(sp_vals) > 0:
            beta = np.cov(s_vals, sp_vals)[0, 1] / np.var(sp_vals)
        else:
            beta = 0

        row = f"{name:.<30} {mean_r:>+11.4f}% {med_r:>+11.4f}% {worst:>+11.4f}% {best:>+11.4f}% {cum:>+11.3f}% {pos:>12} {neg:>12} {win:>11.1f}% {beta:>12.4f}"
        p(row)

    p("-" * W)
    p()

    # Quintile breakdown: split sharp decline days into quintiles by S&P severity
    p("=" * W)
    p("QUINTILE BREAKDOWN: Strategy performance by S&P decline severity")
    p("=" * W)

    sp_sharp_sorted = sp_off[sharp].sort_values()
    quintile_size = len(sp_sharp_sorted) // 5
    remainder = len(sp_sharp_sorted) % 5

    quintile_labels = ["Q1 (worst)", "Q2", "Q3", "Q4", "Q5 (mildest)"]
    quintile_indices = []
    start_i = 0
    for q in range(5):
        extra = 1 if q < remainder else 0
        end_i = start_i + quintile_size + extra
        quintile_indices.append(sp_sharp_sorted.index[start_i:end_i])
        start_i = end_i

    for q_idx, (q_label, q_dates) in enumerate(zip(quintile_labels, quintile_indices)):
        sp_q = sp_off[sharp].loc[q_dates]
        p(f"\n  {q_label}: {len(q_dates)} days, S&P range [{sp_q.min()*100:+.2f}%, {sp_q.max()*100:+.2f}%], avg {sp_q.mean()*100:+.2f}%")
        for name, series in strats.items():
            s_q = series.loc[q_dates]
            avg = s_q.mean() * 100
            cum = ((1 + s_q).prod() - 1) * 100
            pos = (s_q > 0).sum()
            p(f"    {name:.<28} avg {avg:>+.4f}%  cum {cum:>+.3f}%  ({pos}/{len(q_dates)} positive)")

    p()
    p("=" * W)

    # Day-by-day detail: top 20 worst S&P days
    p()
    p("TOP 20 WORST S&P DAYS (risk-off) -- Strategy returns")
    p("-" * W)
    top20 = sp_off[sharp].sort_values().head(20)
    hdr = f"{'Date':.<14} {'S&P':>8}"
    for name in strats:
        short_name = name[:12]
        hdr += f" {short_name:>12}"
    p(hdr)
    p("-" * W)

    for dt in top20.index:
        row = f"{dt.date()!s:.<14} {sp_off.loc[dt]*100:>+7.3f}%"
        for name, series in strats.items():
            row += f" {series.loc[dt]*100:>+11.4f}%"
        p(row)

    p("-" * W)
    p()
    p("NOTES:")
    p("  - Risk-off detection: |CRDBX| < 0.03%, |SPY| >= 0.15%, distribution dates excluded")
    p("  - Returns are actual daily NAV total returns from Yahoo Finance")
    p("  - 'Days +' = strategy returned positive while S&P was down (the whole point)")
    p("  - Beta < 0 means strategy tends to profit when S&P drops (convexity)")
    p("=" * W)

    out = os.path.join(SCRIPT_DIR, "riskoff_sharp_decline.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
