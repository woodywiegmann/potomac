"""
List all verified risk-off days with returns for CRDBX, SPY, SGOV, DBMF, CAOS.
Strict filter: CRDBX flat while S&P moved. Distribution dates excluded.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import os, warnings, csv
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

    idx = crdbx.index.intersection(spy.index).intersection(sgov.index)
    idx = idx.intersection(dbmf.index).intersection(caos.index)
    idx = idx[idx >= START]

    cr = crdbx.reindex(idx).pct_change().fillna(0)
    sp = spy.reindex(idx).pct_change().fillna(0)
    sg = sgov.reindex(idx).pct_change().fillna(0)
    dm = dbmf.reindex(idx).pct_change().fillna(0)
    ca = caos.reindex(idx).pct_change().fillna(0)

    dist_window = set()
    for d in crdbx_dist:
        for offset in [-1, 0, 1]:
            dist_window.add(d + pd.Timedelta(days=offset))

    # Strict detection
    off_days = []
    for i in range(len(idx)):
        dt = idx[i]
        if dt in dist_window:
            continue
        if abs(sp.iloc[i]) < 0.0015:
            continue
        if abs(cr.iloc[i]) < 0.0003:
            off_days.append(dt)

    print(f"Verified risk-off days: {len(off_days)}")

    # Build output
    L = []
    L.append(f"CRDBX VERIFIED RISK-OFF DAYS: {idx[0].date()} to {idx[-1].date()}")
    L.append(f"Total: {len(off_days)} days where |CRDBX| < 0.03% and |S&P| >= 0.15%")
    L.append(f"Distribution dates +/- 1 day excluded")
    L.append("")
    L.append(f"{'#':>4}  {'Date':<12} {'SPY':>9} {'CRDBX':>9} {'SGOV':>9} {'DBMF':>9} {'CAOS':>9}  {'EqWt 3-way':>11} {'50/50 SC':>11}")
    L.append("-" * 100)

    blend3_cum = 1.0
    blend2_cum = 1.0
    sgov_cum = 1.0

    for n, dt in enumerate(off_days, 1):
        s = sp.loc[dt] * 100
        c = cr.loc[dt] * 100
        g = sg.loc[dt] * 100
        d = dm.loc[dt] * 100
        a = ca.loc[dt] * 100
        b3 = (dm.loc[dt] + ca.loc[dt] + sg.loc[dt]) / 3 * 100
        b2 = (sg.loc[dt] * 0.5 + ca.loc[dt] * 0.5) * 100

        blend3_cum *= (1 + b3 / 100)
        blend2_cum *= (1 + b2 / 100)
        sgov_cum *= (1 + sg.loc[dt])

        L.append(f"{n:>4}  {dt.strftime('%Y-%m-%d'):<12} {s:>+8.2f}% {c:>+8.2f}% {g:>+8.2f}% {d:>+8.2f}% {a:>+8.2f}%  {b3:>+10.2f}% {b2:>+10.2f}%")

    L.append("-" * 100)
    L.append("")
    L.append(f"CUMULATIVE (geometric, compounded across all {len(off_days)} risk-off days):")
    L.append(f"  SGOV:                  {(sgov_cum - 1)*100:+.2f}%")
    L.append(f"  EqWt DBMF/CAOS/SGOV:   {(blend3_cum - 1)*100:+.2f}%")
    L.append(f"  50/50 SGOV/CAOS:       {(blend2_cum - 1)*100:+.2f}%")
    L.append(f"  Incremental (3-way):   {(blend3_cum - sgov_cum)*100:+.2f}%")
    L.append(f"  Incremental (50/50):   {(blend2_cum - sgov_cum)*100:+.2f}%")

    report = "\n".join(L)
    print(report)

    out = os.path.join(SCRIPT_DIR, "riskoff_daylist.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nSaved to: {out}")

    # Also save as CSV
    csv_path = os.path.join(SCRIPT_DIR, "riskoff_daylist.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["#", "Date", "SPY", "CRDBX", "SGOV", "DBMF", "CAOS", "EqWt_3way", "50_50_SGOV_CAOS"])
        for n, dt in enumerate(off_days, 1):
            w.writerow([
                n,
                dt.strftime("%Y-%m-%d"),
                f"{sp.loc[dt]*100:+.4f}%",
                f"{cr.loc[dt]*100:+.4f}%",
                f"{sg.loc[dt]*100:+.4f}%",
                f"{dm.loc[dt]*100:+.4f}%",
                f"{ca.loc[dt]*100:+.4f}%",
                f"{(dm.loc[dt]+ca.loc[dt]+sg.loc[dt])/3*100:+.4f}%",
                f"{(sg.loc[dt]*0.5+ca.loc[dt]*0.5)*100:+.4f}%",
            ])
    print(f"CSV saved to: {csv_path}")

if __name__ == "__main__":
    main()
