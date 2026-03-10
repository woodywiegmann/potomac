"""
Risk-off day analysis since CRDBX inception.
Outputs: full list of risk-off days with daily returns for each instrument,
         plus summary stats for individual components and blended portfolios.
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

def rbeta(x, y, w=5):
    b = pd.Series(np.nan, index=x.index)
    for i in range(w, len(x)):
        c = np.cov(x.iloc[i-w:i].values, y.iloc[i-w:i].values)
        if c[1,1] > 1e-12:
            b.iloc[i] = c[0,1] / c[1,1]
    return b

def stats_block(name, series):
    avg = series.mean() * 100
    ann = series.mean() * 252 * 100
    geo = ((1 + series).prod() - 1) * 100
    vol = series.std() * np.sqrt(252) * 100
    worst = series.min() * 100
    best = series.max() * 100
    return {"name": name, "avg": avg, "ann": ann, "geo": geo, "vol": vol, "worst": worst, "best": best, "n": len(series)}

def main():
    START, END = "2020-07-01", "2026-02-21"
    print("Fetching total-return series (NAV + reinvested distributions)...")
    tickers = {"CRDBX": START, "SPY": START, "SGOV": START, "DBMF": START,
               "KMLM": START, "ARB": START, "CAOS": "2023-03-01"}
    raw = {}
    for tk, st in tickers.items():
        raw[tk] = get_tr(tk, st, END)
        if len(raw[tk]) > 0:
            print(f"  {tk}: {raw[tk].index[0].date()} to {raw[tk].index[-1].date()} ({len(raw[tk])} days)")
        else:
            print(f"  {tk}: NO DATA")

    # Common index (full period, excludes CAOS)
    idx = raw["CRDBX"].index
    for tk in ["SPY", "SGOV", "DBMF", "KMLM", "ARB"]:
        idx = idx.intersection(raw[tk].index)

    rets = {}
    for tk in ["CRDBX", "SPY", "SGOV", "DBMF", "KMLM", "ARB"]:
        rets[tk] = raw[tk].reindex(idx).pct_change().fillna(0)

    # CAOS on its own index
    caos_idx = idx.intersection(raw["CAOS"].index)
    rets["CAOS"] = raw["CAOS"].reindex(caos_idx).pct_change().fillna(0)

    # Regime detection
    b5 = rbeta(rets["CRDBX"], rets["SPY"], 5)
    regime = pd.Series("ON", index=idx)
    regime[b5 < 0.3] = "OFF"
    regime[(b5 >= 0.3) & (b5 <= 0.6)] = "OFF"
    for i in range(len(idx)):
        cr = abs(rets["CRDBX"].iloc[i])
        sr = abs(rets["SPY"].iloc[i])
        if sr > 0.003 and cr < 0.0005:
            regime.iloc[i] = "OFF"
        elif sr > 0.002 and cr > sr * 1.0:
            regime.iloc[i] = "ON"
    regime[b5.isna()] = "ON"

    off = regime == "OFF"
    off_dates = idx[off]
    n_off = off.sum()

    # ── CSV: Full list of risk-off days ──
    csv_path = os.path.join(SCRIPT_DIR, "riskoff_days.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "SPY", "CRDBX", "SGOV", "DBMF", "KMLM", "ARB", "CAOS"])
        for dt in off_dates:
            row = [dt.strftime("%Y-%m-%d")]
            for tk in ["SPY", "CRDBX", "SGOV", "DBMF", "KMLM", "ARB"]:
                row.append(f"{rets[tk].loc[dt]*100:+.4f}%")
            if dt in caos_idx:
                row.append(f"{rets['CAOS'].loc[dt]*100:+.4f}%")
            else:
                row.append("")
            w.writerow(row)
    print(f"\nRisk-off day list saved to: {csv_path} ({n_off} rows)")

    # ── SUMMARY REPORT ──
    L = []
    def p(s=""):
        L.append(s)
        print(s)

    p("=" * 90)
    p("RISK-OFF DAY RETURNS -- SINCE CRDBX INCEPTION")
    p(f"Period: {idx[0].date()} to {idx[-1].date()}")
    p(f"Total trading days: {len(idx)}  |  Risk-off days: {n_off} ({n_off/len(idx)*100:.0f}%)")
    p("Regime detected from CRDBX daily NAV vs S&P 500")
    p("All returns: daily NAV total return (distributions reinvested)")
    p("=" * 90)

    # ── FULL PERIOD: individual components ──
    p()
    p("-" * 90)
    p("INDIVIDUAL COMPONENTS -- FULL PERIOD (Jul 2020 - Feb 2026)")
    p(f"Risk-off days: {n_off}")
    p("-" * 90)
    p()

    full_tickers = ["CRDBX", "SGOV", "DBMF", "KMLM", "ARB"]
    full_stats = [stats_block(tk, rets[tk][off]) for tk in full_tickers]

    hdr = f"{'':.<26}"
    for s in full_stats:
        hdr += f" {s['name']:>12}"
    p(hdr)
    p("-" * 90)
    row_avg = f"{'Avg daily return':.<26}"
    row_ann = f"{'Annualized (daily x 252)':.<26}"
    row_geo = f"{'Geometric (compounded)':.<26}"
    row_vol = f"{'Ann. volatility':.<26}"
    row_min = f"{'Worst single day':.<26}"
    row_max = f"{'Best single day':.<26}"
    for s in full_stats:
        row_avg += f" {s['avg']:>+11.4f}%"
        row_ann += f" {s['ann']:>+11.2f}%"
        row_geo += f" {s['geo']:>+11.2f}%"
        row_vol += f" {s['vol']:>11.2f}%"
        row_min += f" {s['worst']:>+11.2f}%"
        row_max += f" {s['best']:>+11.2f}%"
    p(row_avg)
    p(row_ann)
    p(row_geo)
    p(row_vol)
    p(row_min)
    p(row_max)

    # ── CAOS PERIOD: individual components ──
    off_caos = regime.reindex(caos_idx) == "OFF"
    n_off_c = off_caos.sum()

    p()
    p("-" * 90)
    p(f"INDIVIDUAL COMPONENTS -- CAOS PERIOD (Mar 2023 - Feb 2026)")
    p(f"Risk-off days: {n_off_c}")
    p("-" * 90)
    p()

    caos_tickers = ["CRDBX", "SGOV", "DBMF", "KMLM", "ARB", "CAOS"]
    caos_stats = []
    for tk in caos_tickers:
        if tk == "CAOS":
            caos_stats.append(stats_block(tk, rets["CAOS"][off_caos]))
        else:
            caos_stats.append(stats_block(tk, rets[tk].reindex(caos_idx)[off_caos]))

    hdr2 = f"{'':.<26}"
    for s in caos_stats:
        hdr2 += f" {s['name']:>10}"
    p(hdr2)
    p("-" * 90)
    for label, key in [("Avg daily return", "avg"), ("Annualized (daily x 252)", "ann"),
                        ("Geometric (compounded)", "geo"), ("Ann. volatility", "vol"),
                        ("Worst single day", "worst"), ("Best single day", "best")]:
        row = f"{label:.<26}"
        for s in caos_stats:
            if key in ["vol"]:
                row += f" {s[key]:>9.2f}%"
            else:
                row += f" {s[key]:>+9.2f}%"
        p(row)

    # ── BLENDED PORTFOLIOS (equal-weight, CAOS period only) ──
    p()
    p("-" * 90)
    p("EQUAL-WEIGHT BLENDED PORTFOLIOS -- RISK-OFF DAYS ONLY")
    p(f"CAOS period: Mar 2023 - Feb 2026 ({n_off_c} risk-off days)")
    p("-" * 90)
    p()

    # Build blended daily returns on risk-off days (CAOS period)
    cr_c = rets["CRDBX"].reindex(caos_idx)[off_caos]
    sg_c = rets["SGOV"].reindex(caos_idx)[off_caos]
    dm_c = rets["DBMF"].reindex(caos_idx)[off_caos]
    km_c = rets["KMLM"].reindex(caos_idx)[off_caos]
    ar_c = rets["ARB"].reindex(caos_idx)[off_caos]
    ca_c = rets["CAOS"][off_caos]

    blends = {
        "CRDBX Actual (baseline)": cr_c,
        "EqWt DBMF/CAOS/SGOV":    (dm_c + ca_c + sg_c) / 3,
        "EqWt KMLM/CAOS/SGOV":    (km_c + ca_c + sg_c) / 3,
        "EqWt KMLM/CAOS/ARB":     (km_c + ca_c + ar_c) / 3,
    }

    blend_stats = [stats_block(name, series) for name, series in blends.items()]

    hdr3 = f"{'':.<26}"
    for s in blend_stats:
        short = s["name"][:20]
        hdr3 += f" {short:>22}"
    p(hdr3)
    p("-" * 90 + "-" * 20)
    for label, key in [("Avg daily return", "avg"), ("Annualized (daily x 252)", "ann"),
                        ("Geometric (compounded)", "geo"), ("Ann. volatility", "vol"),
                        ("Worst single day", "worst"), ("Best single day", "best")]:
        row = f"{label:.<26}"
        for s in blend_stats:
            if key in ["vol"]:
                row += f" {s[key]:>21.2f}%"
            else:
                row += f" {s[key]:>+21.2f}%"
        p(row)

    p()
    p("=" * 90)

    # Save
    out = os.path.join(SCRIPT_DIR, "riskoff_daily_returns.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSummary saved to: {out}")
    print(f"Full day-by-day list: {csv_path}")

if __name__ == "__main__":
    main()
