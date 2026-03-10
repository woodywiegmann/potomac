"""
ARKK vs NQ (QQQ proxy) Trade-Level Comparison in CRTOX
=======================================================
Uses the actual ARKK trade dates from CRTOX's trade log to compare
what each holding period returned in ARKK vs QQQ (Nasdaq-100 proxy for NQ).
All returns computed from verified daily NAV total-return series.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── TRADE LOG from CRTOX screenshot ──
# (entry_date, exit_date) -- all Long ARKK trades
TRADES = [
    ("2020-02-03", "2020-02-21"),
    ("2018-06-26", "2018-07-18"),
    ("2017-11-17", "2018-01-22"),
    ("2020-02-25", "2020-03-09"),
    ("2020-04-14", "2020-04-16"),
    ("2025-07-01", "2025-07-03"),
    ("2018-09-05", "2018-10-01"),
    ("2018-02-02", "2018-02-07"),
    ("2018-10-11", "2018-10-16"),
    ("2017-09-07", "2017-11-06"),
    ("2020-04-21", "2020-04-27"),
    ("2025-07-07", "2025-08-11"),
    ("2018-02-09", "2018-02-12"),
    ("2020-05-13", "2020-05-15"),
    ("2019-12-16", "2020-01-02"),
    ("2017-05-01", "2017-06-09"),
    ("2019-12-02", "2019-12-04"),
    ("2017-08-18", "2017-08-28"),
    ("2024-01-29", "2024-02-01"),
    ("2023-12-04", "2024-01-22"),
    ("2018-03-05", "2018-03-07"),
    ("2020-06-03", "2020-06-23"),
    ("2025-12-04", "2026-01-02"),
    ("2018-10-25", "2018-11-05"),
    ("2020-06-29", "2020-06-30"),
    ("2019-07-01", "2019-09-03"),
    ("2020-07-13", "2020-08-24"),
    ("2019-05-29", "2019-05-31"),
    ("2018-03-22", "2018-04-02"),
    ("2025-11-18", "2025-12-03"),
    ("2023-06-01", "2023-08-28"),
    ("2015-12-01", "2015-12-02"),
    ("2020-09-04", "2020-09-15"),
    ("2017-06-26", "2017-08-16"),
    ("2025-08-12", "2025-09-05"),
    ("2019-05-23", "2019-05-28"),
    ("2018-11-16", "2018-11-28"),
    ("2018-05-10", "2018-06-22"),
    ("2025-11-07", "2025-11-11"),
    ("2018-04-10", "2018-04-13"),
    ("2024-12-02", "2024-12-16"),
    ("2015-12-23", "2016-01-05"),
    ("2019-05-10", "2019-05-22"),
    ("2020-09-22", "2020-09-28"),
    ("2025-10-27", "2025-11-05"),
    ("2020-10-05", "2021-03-05"),
    ("2024-12-23", "2025-03-17"),
    ("2018-12-21", "2019-01-02"),
    ("2016-08-01", "2016-09-01"),
    ("2018-04-25", "2018-04-27"),
    ("2021-03-09", "2021-03-19"),
    ("2016-10-03", "2016-11-01"),
    ("2025-09-23", "2025-10-03"),
    ("2019-03-08", "2019-05-09"),
    ("2018-07-24", "2018-08-14"),
]


def get_tr(ticker, start, end):
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float)
    h.index = h.index.tz_localize(None)
    nav, divs = h["Close"], h.get("Dividends", pd.Series(0.0, index=h.index))
    sh = 1.0
    v = []
    for dt in h.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            sh *= (1 + d / p)
        v.append(sh * p)
    return pd.Series(v, index=h.index, name=ticker)


def main():
    print("Fetching total-return series...")
    arkk = get_tr("ARKK", "2014-10-01", "2026-02-28")
    qqq  = get_tr("QQQ",  "2014-10-01", "2026-02-28")
    print(f"  ARKK: {arkk.index[0].date()} to {arkk.index[-1].date()} ({len(arkk)} days)")
    print(f"  QQQ:  {qqq.index[0].date()} to {qqq.index[-1].date()} ({len(qqq)} days)")

    L = []
    def p(s=""):
        L.append(s)
        print(s)

    W = 115
    p("=" * W)
    p("ARKK vs QQQ (NQ PROXY): TRADE-LEVEL COMPARISON")
    p("Same entry/exit dates as CRTOX's actual ARKK trades")
    p("=" * W)
    p()

    p(f"{'#':>3}  {'Entry':<12} {'Exit':<12} {'Days':>5}  {'ARKK':>9} {'QQQ':>9} {'Delta':>9}  {'Winner':>6}")
    p("-" * W)

    results = []
    skipped = 0

    for i, (entry_str, exit_str) in enumerate(TRADES, 1):
        entry = pd.Timestamp(entry_str)
        exit_dt = pd.Timestamp(exit_str)

        # Find nearest trading day on or after entry
        arkk_after = arkk[arkk.index >= entry]
        qqq_after = qqq[qqq.index >= entry]
        if len(arkk_after) == 0 or len(qqq_after) == 0:
            skipped += 1
            continue

        # Find nearest trading day on or before exit
        arkk_before = arkk[arkk.index <= exit_dt]
        qqq_before = qqq[qqq.index <= exit_dt]
        if len(arkk_before) == 0 or len(qqq_before) == 0:
            skipped += 1
            continue

        a_entry_dt = arkk_after.index[0]
        a_exit_dt = arkk_before.index[-1]
        q_entry_dt = qqq_after.index[0]
        q_exit_dt = qqq_before.index[-1]

        if a_entry_dt >= a_exit_dt or q_entry_dt >= q_exit_dt:
            skipped += 1
            continue

        a_ret = (arkk.loc[a_exit_dt] / arkk.loc[a_entry_dt] - 1) * 100
        q_ret = (qqq.loc[q_exit_dt] / qqq.loc[q_entry_dt] - 1) * 100
        delta = q_ret - a_ret
        days = (a_exit_dt - a_entry_dt).days
        winner = "QQQ" if q_ret > a_ret else "ARKK"

        results.append({
            "entry": a_entry_dt, "exit": a_exit_dt, "days": days,
            "arkk": a_ret, "qqq": q_ret, "delta": delta, "winner": winner
        })

        p(f"{i:>3}  {a_entry_dt.strftime('%Y-%m-%d'):<12} {a_exit_dt.strftime('%Y-%m-%d'):<12} {days:>5}  "
          f"{a_ret:>+8.2f}% {q_ret:>+8.2f}% {delta:>+8.2f}%  {winner:>6}")

    p("-" * W)

    if skipped > 0:
        p(f"  ({skipped} trades skipped -- dates outside available data range)")
    p()

    # ── SUMMARY ──
    n = len(results)
    qqq_wins = sum(1 for r in results if r["winner"] == "QQQ")
    arkk_wins = n - qqq_wins

    avg_arkk = np.mean([r["arkk"] for r in results])
    avg_qqq = np.mean([r["qqq"] for r in results])
    avg_delta = np.mean([r["delta"] for r in results])
    med_delta = np.median([r["delta"] for r in results])

    # Compounded returns (as if you put $10K into each trade sequentially)
    arkk_cum = 1.0
    qqq_cum = 1.0
    for r in sorted(results, key=lambda x: x["entry"]):
        arkk_cum *= (1 + r["arkk"] / 100)
        qqq_cum *= (1 + r["qqq"] / 100)

    p("=" * W)
    p("SUMMARY")
    p("=" * W)
    p()
    p(f"  Total trades:              {n}")
    p(f"  QQQ won:                   {qqq_wins} ({qqq_wins/n*100:.0f}%)")
    p(f"  ARKK won:                  {arkk_wins} ({arkk_wins/n*100:.0f}%)")
    p()
    p(f"  Avg trade return (ARKK):   {avg_arkk:+.2f}%")
    p(f"  Avg trade return (QQQ):    {avg_qqq:+.2f}%")
    p(f"  Avg delta (QQQ - ARKK):    {avg_delta:+.2f}%")
    p(f"  Median delta:              {med_delta:+.2f}%")
    p()
    p(f"  Compounded (all trades):")
    p(f"    ARKK:  ${10000 * arkk_cum:>10,.0f}  ({(arkk_cum - 1)*100:+.1f}%)")
    p(f"    QQQ:   ${10000 * qqq_cum:>10,.0f}  ({(qqq_cum - 1)*100:+.1f}%)")
    p(f"    Delta: ${10000 * (qqq_cum - arkk_cum):>10,.0f}")
    p()

    # ── BY YEAR ──
    p("-" * W)
    p("BY YEAR")
    p("-" * W)
    p()
    by_year = {}
    for r in results:
        yr = r["entry"].year
        if yr not in by_year:
            by_year[yr] = {"arkk": [], "qqq": [], "delta": [], "n": 0, "qqq_wins": 0}
        by_year[yr]["arkk"].append(r["arkk"])
        by_year[yr]["qqq"].append(r["qqq"])
        by_year[yr]["delta"].append(r["delta"])
        by_year[yr]["n"] += 1
        if r["winner"] == "QQQ":
            by_year[yr]["qqq_wins"] += 1

    p(f"  {'Year':<6} {'Trades':>7} {'QQQ wins':>9} {'Avg ARKK':>10} {'Avg QQQ':>10} {'Avg Delta':>10}")
    p(f"  {'-'*55}")
    for yr in sorted(by_year.keys()):
        d = by_year[yr]
        p(f"  {yr:<6} {d['n']:>7} {d['qqq_wins']:>9} {np.mean(d['arkk']):>+9.2f}% {np.mean(d['qqq']):>+9.2f}% {np.mean(d['delta']):>+9.2f}%")

    # ── BIGGEST DIVERGENCES ──
    p()
    p("-" * W)
    p("BIGGEST DIVERGENCES (QQQ outperformed ARKK most)")
    p("-" * W)
    p()
    sorted_by_delta = sorted(results, key=lambda x: x["delta"], reverse=True)
    for r in sorted_by_delta[:10]:
        p(f"  {r['entry'].strftime('%Y-%m-%d')} to {r['exit'].strftime('%Y-%m-%d')} ({r['days']:>3}d): "
          f"ARKK {r['arkk']:>+7.2f}%  QQQ {r['qqq']:>+7.2f}%  delta {r['delta']:>+7.2f}%")

    p()
    p("-" * W)
    p("BIGGEST DIVERGENCES (ARKK outperformed QQQ most)")
    p("-" * W)
    p()
    for r in sorted_by_delta[-10:]:
        p(f"  {r['entry'].strftime('%Y-%m-%d')} to {r['exit'].strftime('%Y-%m-%d')} ({r['days']:>3}d): "
          f"ARKK {r['arkk']:>+7.2f}%  QQQ {r['qqq']:>+7.2f}%  delta {r['delta']:>+7.2f}%")

    p()
    p("=" * W)
    p("NOTE: QQQ used as proxy for E-mini Nasdaq-100 (NQ) futures.")
    p("NQ tracks the same index with better capital efficiency (margin-based,")
    p("23-hour trading, no ETF expense ratio). Returns would be nearly identical.")
    p("=" * W)

    report = "\n".join(L)
    out = os.path.join(SCRIPT_DIR, "arkk_vs_nq.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
