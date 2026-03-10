"""
Head-to-head: CRDBX vs EqWt DBMF/CAOS/SGOV on risk-off days.
Strict regime detection: only days where CRDBX is verifiably flat.
Filters out distribution dates and ambiguous days.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_tr(ticker, start, end):
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float), set()
    h.index = h.index.tz_localize(None)
    nav, divs = h["Close"], h.get("Dividends", pd.Series(0.0, index=h.index))
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
    START, END = "2023-03-01", "2026-02-21"

    print("Fetching total-return series...")
    crdbx, crdbx_dist = get_tr("CRDBX", "2022-12-01", END)
    spy, _   = get_tr("SPY",   "2022-12-01", END)
    sgov, _  = get_tr("SGOV",  "2022-12-01", END)
    dbmf, _  = get_tr("DBMF",  "2022-12-01", END)
    caos, _  = get_tr("CAOS",  "2023-03-01", END)
    usmv, _  = get_tr("USMV",  "2022-12-01", END)
    heqt, _  = get_tr("HEQT",  "2022-12-01", END)

    # CRDBX distribution dates to exclude
    print(f"  CRDBX distribution dates (excluded): {sorted(d.date() for d in crdbx_dist)}")

    idx = crdbx.index.intersection(spy.index).intersection(sgov.index)
    idx = idx.intersection(dbmf.index).intersection(caos.index).intersection(usmv.index)
    idx = idx.intersection(heqt.index)
    idx = idx[idx >= START]

    cr = crdbx.reindex(idx).pct_change().fillna(0)
    sp = spy.reindex(idx).pct_change().fillna(0)
    sg = sgov.reindex(idx).pct_change().fillna(0)
    dm = dbmf.reindex(idx).pct_change().fillna(0)
    ca = caos.reindex(idx).pct_change().fillna(0)
    um = usmv.reindex(idx).pct_change().fillna(0)
    hq = heqt.reindex(idx).pct_change().fillna(0)

    # ── STRICT REGIME DETECTION ──
    # Rule 1: Exclude distribution dates (+/- 1 day buffer)
    dist_window = set()
    for d in crdbx_dist:
        for offset in [-1, 0, 1]:
            dist_window.add(d + pd.Timedelta(days=offset))

    regime = pd.Series("AMBIGUOUS", index=idx)

    for i in range(len(idx)):
        dt = idx[i]

        # Skip distribution dates
        if dt in dist_window:
            regime.iloc[i] = "EXCLUDED"
            continue

        spy_move = sp.iloc[i]
        crdbx_move = cr.iloc[i]

        # If SPY barely moved, can't tell -- mark ambiguous
        if abs(spy_move) < 0.0015:
            regime.iloc[i] = "AMBIGUOUS"
            continue

        # STRICT risk-off: CRDBX within +/-0.03% of zero while SPY moved
        if abs(crdbx_move) < 0.0003 and abs(spy_move) >= 0.0015:
            regime.iloc[i] = "OFF"
            continue

        # Risk-on: CRDBX tracks SPY at meaningful ratio (>0.7)
        ratio = crdbx_move / spy_move
        if ratio > 0.70 and abs(crdbx_move) > 0.002:
            regime.iloc[i] = "ON"
            continue

        # Everything else is ambiguous -- do NOT include
        regime.iloc[i] = "AMBIGUOUS"

    off = regime == "OFF"
    on = regime == "ON"
    excluded = regime == "EXCLUDED"
    ambiguous = regime == "AMBIGUOUS"

    n_total = len(idx)
    n_off = off.sum()
    n_on = on.sum()
    n_exc = excluded.sum()
    n_amb = ambiguous.sum()

    # Validate
    if on.sum() > 10:
        on_beta = np.cov(cr[on], sp[on])[0,1] / np.var(sp[on])
    else:
        on_beta = 0
    if off.sum() > 10:
        off_beta = np.cov(cr[off], sp[off])[0,1] / np.var(sp[off])
    else:
        off_beta = 0

    # Blends on risk-off days
    blend_3way = (dm + ca + sg) / 3
    blend_2way = 0.50 * sg + 0.50 * ca
    blend_custom = 0.10 * um + 0.20 * ca + 0.40 * sg + 0.30 * dm
    blend_30c = 0.30 * ca + 0.10 * dm + 0.60 * sg
    blend_heqt = 0.15 * hq + 0.15 * dm + 0.70 * sg

    # Impute SGOV return for CRDBX on risk-off days (NAV rounding fix)
    cr_off_imputed = sg[off].copy()

    b3_off = blend_3way[off]
    b2_off = blend_2way[off]
    bc_off = blend_custom[off]
    b30c_off = blend_30c[off]
    bheqt_off = blend_heqt[off]
    sp_off = sp[off]

    # Beta to S&P on risk-off days
    cr_beta_off, b3_beta_off, b2_beta_off, bc_beta_off, b30c_beta_off, bheqt_beta_off = 0, 0, 0, 0, 0, 0
    if off.sum() > 10:
        cr_beta_off = np.cov(cr_off_imputed, sp_off)[0,1] / np.var(sp_off)
        b3_beta_off = np.cov(b3_off, sp_off)[0,1] / np.var(sp_off)
        b2_beta_off = np.cov(b2_off, sp_off)[0,1] / np.var(sp_off)
        bc_beta_off = np.cov(bc_off, sp_off)[0,1] / np.var(sp_off)
        b30c_beta_off = np.cov(b30c_off, sp_off)[0,1] / np.var(sp_off)
        bheqt_beta_off = np.cov(bheqt_off, sp_off)[0,1] / np.var(sp_off)

    def calc(series):
        avg = series.mean() * 100
        ann = series.mean() * 252 * 100
        geo = ((1 + series).prod() - 1) * 100
        vol = series.std() * np.sqrt(252) * 100
        med = series.median() * 100
        pos = (series > 0).sum()
        neg = (series < 0).sum()
        flat = (series.abs() < 0.00005).sum()
        best = series.max() * 100
        return {"avg": avg, "ann": ann, "geo": geo, "vol": vol, "med": med,
                "pos": pos, "neg": neg, "flat": flat, "best": best, "n": len(series)}

    s1 = calc(cr_off_imputed)
    s2 = calc(b3_off)
    s3 = calc(b2_off)
    s4 = calc(bc_off)
    s5 = calc(b30c_off)
    s6 = calc(bheqt_off)

    L = []
    def p(s=""):
        L.append(s)
        print(s)

    W = 145
    p("=" * W)
    p("HEAD TO HEAD: RISK-OFF DAYS (STRICT FILTER)")
    p("=" * W)
    p(f"Period: {idx[0].date()} to {idx[-1].date()}")
    p(f"Total trading days:   {n_total}")
    p(f"Risk-off days:        {n_off}  ({n_off/n_total*100:.1f}%)")
    p(f"Risk-on days:         {n_on}  ({n_on/n_total*100:.1f}%)")
    p(f"Distribution dates:   {n_exc}  (excluded)")
    p(f"Ambiguous days:       {n_amb}  (SPY < 0.15% or CRDBX not clearly flat)")
    p()
    p("Filter criteria:")
    p("  Risk-off = |CRDBX daily return| < 0.03%  AND  |S&P| >= 0.15%")
    p("  Distribution dates +/- 1 day excluded")
    p("  Days where S&P moved < 0.15% = ambiguous, not counted")
    p()
    p("Regime validation:")
    p(f"  Risk-on  beta (CRDBX vs S&P): {on_beta:.2f}x")
    p(f"  Risk-off beta (CRDBX vs S&P): {off_beta:.4f}x")
    p()

    p("-" * W)
    p(f"{'':.<26} {'CRDBX':>14} {'EqWt 3-way':>16} {'50/50':>16} {'30C/10D/60S':>16} {'15H/15D/70S':>16} {'Custom Mix':>16}")
    p(f"{'':.<26} {'(SGOV imputed)':>14} {'DBMF/CAOS/SGOV':>16} {'SGOV/CAOS':>16} {'CAOS-heavy':>16} {'HEQT blend':>16} {'10U/20C/40S/30D':>16}")
    p("-" * W)
    p(f"{'Avg daily return':.<26} {s1['avg']:>+13.4f}% {s2['avg']:>+15.4f}% {s3['avg']:>+15.4f}% {s5['avg']:>+15.4f}% {s6['avg']:>+15.4f}% {s4['avg']:>+15.4f}%")
    p(f"{'Median daily return':.<26} {s1['med']:>+13.4f}% {s2['med']:>+15.4f}% {s3['med']:>+15.4f}% {s5['med']:>+15.4f}% {s6['med']:>+15.4f}% {s4['med']:>+15.4f}%")
    p(f"{'Annualized (daily x 252)':.<26} {s1['ann']:>+13.2f}% {s2['ann']:>+15.2f}% {s3['ann']:>+15.2f}% {s5['ann']:>+15.2f}% {s6['ann']:>+15.2f}% {s4['ann']:>+15.2f}%")
    p(f"{'Geometric (compounded)':.<26} {s1['geo']:>+13.2f}% {s2['geo']:>+15.2f}% {s3['geo']:>+15.2f}% {s5['geo']:>+15.2f}% {s6['geo']:>+15.2f}% {s4['geo']:>+15.2f}%")
    p(f"{'Ann. volatility':.<26} {s1['vol']:>13.2f}% {s2['vol']:>15.2f}% {s3['vol']:>15.2f}% {s5['vol']:>15.2f}% {s6['vol']:>15.2f}% {s4['vol']:>15.2f}%")
    p(f"{'Beta to S&P':.<26} {cr_beta_off:>14.4f} {b3_beta_off:>16.4f} {b2_beta_off:>16.4f} {b30c_beta_off:>16.4f} {bheqt_beta_off:>16.4f} {bc_beta_off:>16.4f}")
    p(f"{'Best single day':.<26} {s1['best']:>+13.2f}% {s2['best']:>+15.2f}% {s3['best']:>+15.2f}% {s5['best']:>+15.2f}% {s6['best']:>+15.2f}% {s4['best']:>+15.2f}%")
    p(f"{'Days positive':.<26} {s1['pos']:>14} {s2['pos']:>16} {s3['pos']:>16} {s5['pos']:>16} {s6['pos']:>16} {s4['pos']:>16}")
    p(f"{'Days negative':.<26} {s1['neg']:>14} {s2['neg']:>16} {s3['neg']:>16} {s5['neg']:>16} {s6['neg']:>16} {s4['neg']:>16}")
    p(f"{'Days flat (< 0.005%)':.<26} {s1['flat']:>14} {s2['flat']:>16} {s3['flat']:>16} {s5['flat']:>16} {s6['flat']:>16} {s4['flat']:>16}")
    p()

    d2_geo = s2["geo"] - s1["geo"]
    d3_geo = s3["geo"] - s1["geo"]
    d4_geo = s4["geo"] - s1["geo"]
    d5_geo = s5["geo"] - s1["geo"]
    d6_geo = s6["geo"] - s1["geo"]
    d2_ann = s2["ann"] - s1["ann"]
    d3_ann = s3["ann"] - s1["ann"]
    d4_ann = s4["ann"] - s1["ann"]
    d5_ann = s5["ann"] - s1["ann"]
    d6_ann = s6["ann"] - s1["ann"]
    p(f"{'Incremental geometric':.<26} {'--':>14} {d2_geo:>+15.2f}% {d3_geo:>+15.2f}% {d5_geo:>+15.2f}% {d6_geo:>+15.2f}% {d4_geo:>+15.2f}%")
    p(f"{'Incremental annualized':.<26} {'--':>14} {d2_ann:>+15.2f}% {d3_ann:>+15.2f}% {d5_ann:>+15.2f}% {d6_ann:>+15.2f}% {d4_ann:>+15.2f}%")
    p()
    p("-" * W)
    p("Blend key:")
    p("  EqWt 3-way    = 33% DBMF + 33% CAOS + 34% SGOV")
    p("  50/50         = 50% SGOV + 50% CAOS")
    p("  30C/10D/60S   = 30% CAOS + 10% DBMF + 60% SGOV")
    p("  15H/15D/70S   = 15% HEQT + 15% DBMF + 70% SGOV")
    p("  Custom Mix    = 10% USMV + 20% CAOS + 40% SGOV + 30% DBMF")
    p("-" * W)
    p("ASSUMPTION NOTE")
    p("-" * W)
    p("CRDBX column uses SGOV daily returns as a proxy for money market")
    p("income. CRDBX's NAV is reported to two decimal places (~$14/share),")
    p("so daily money market accrual (~$0.003/share at 5% annual) is below")
    p("the rounding threshold and appears as 0.0000% on any single day.")
    p("Imputing SGOV's actual daily return gives a fair baseline that")
    p("reflects the ~5% annualized yield the fund is earning on its cash")
    p("position, net of SGOV's 0.09% expense ratio.")
    p()
    p("CAOS and DBMF returns are actual daily NAV total returns from Yahoo")
    p("Finance, net of each fund's own expense ratio (CAOS 0.63%, DBMF")
    p("0.85%). No additional fee adjustment is applied.")
    p()
    p("=" * W)

    out = os.path.join(SCRIPT_DIR, "h2h_riskoff.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSaved to: {out}")

if __name__ == "__main__":
    main()
