"""Risk-off day returns since CRDBX inception -- daily and geometric."""

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

def main():
    START, END = "2020-07-01", "2026-02-21"
    print("Fetching total-return series (NAV + reinvested distributions)...")
    crdbx = get_tr("CRDBX", START, END)
    spy   = get_tr("SPY",   START, END)
    sgov  = get_tr("SGOV",  START, END)
    dbmf  = get_tr("DBMF",  START, END)
    caos  = get_tr("CAOS",  "2023-03-01", END)

    idx = crdbx.index.intersection(spy.index).intersection(sgov.index).intersection(dbmf.index)
    cr = crdbx.reindex(idx).pct_change().fillna(0)
    sp = spy.reindex(idx).pct_change().fillna(0)
    sg = sgov.reindex(idx).pct_change().fillna(0)
    dm = dbmf.reindex(idx).pct_change().fillna(0)

    # Regime detection
    b5 = rbeta(cr, sp, 5)
    regime = pd.Series("UNK", index=idx)
    regime[b5 > 0.6] = "ON"
    regime[b5 < 0.3] = "OFF"
    regime[(b5 >= 0.3) & (b5 <= 0.6)] = "OFF"
    for i in range(len(idx)):
        if abs(sp.iloc[i]) > 0.003 and abs(cr.iloc[i]) < 0.0005:
            regime.iloc[i] = "OFF"
        elif abs(sp.iloc[i]) > 0.002 and abs(cr.iloc[i]) > abs(sp.iloc[i]) * 1.0:
            regime.iloc[i] = "ON"

    off = regime == "OFF"
    n_off = off.sum()

    L = []
    def p(s=""):
        L.append(s)
        print(s)

    p("=" * 72)
    p("RISK-OFF DAY RETURNS -- SINCE CRDBX INCEPTION")
    p(f"Period: {idx[0].date()} to {idx[-1].date()}")
    p(f"Total trading days: {len(idx)}  |  Risk-off days: {n_off} ({n_off/len(idx)*100:.0f}%)")
    p("Regime detected from CRDBX daily NAV vs S&P 500")
    p("All returns: daily NAV total return (distributions reinvested)")
    p("=" * 72)

    # Full period (Jul 2020 - Feb 2026): CRDBX, SGOV, DBMF
    p()
    p("-" * 72)
    p("FULL PERIOD: July 2020 - February 2026")
    p(f"Risk-off days: {n_off}")
    p("-" * 72)
    p()

    cr_off = cr[off]
    sg_off = sg[off]
    dm_off = dm[off]

    header = f"{'':.<26} {'CRDBX':>14} {'SGOV':>14} {'DBMF':>14}"
    p(header)
    p("-" * 72)
    p(f"{'Avg daily return':.<26} {cr_off.mean()*100:>+13.4f}% {sg_off.mean()*100:>+13.4f}% {dm_off.mean()*100:>+13.4f}%")
    p(f"{'Annualized (daily x 252)':.<26} {cr_off.mean()*252*100:>+13.2f}% {sg_off.mean()*252*100:>+13.2f}% {dm_off.mean()*252*100:>+13.2f}%")

    cr_geo = ((1 + cr_off).prod() - 1) * 100
    sg_geo = ((1 + sg_off).prod() - 1) * 100
    dm_geo = ((1 + dm_off).prod() - 1) * 100
    p(f"{'Geometric (compounded)':.<26} {cr_geo:>+13.2f}% {sg_geo:>+13.2f}% {dm_geo:>+13.2f}%")

    cr_vol = cr_off.std() * np.sqrt(252) * 100
    sg_vol = sg_off.std() * np.sqrt(252) * 100
    dm_vol = dm_off.std() * np.sqrt(252) * 100
    p(f"{'Ann. volatility':.<26} {cr_vol:>13.2f}% {sg_vol:>13.2f}% {dm_vol:>13.2f}%")

    cr_min = cr_off.min() * 100
    sg_min = sg_off.min() * 100
    dm_min = dm_off.min() * 100
    p(f"{'Worst single day':.<26} {cr_min:>+13.2f}% {sg_min:>+13.2f}% {dm_min:>+13.2f}%")

    cr_max = cr_off.max() * 100
    sg_max = sg_off.max() * 100
    dm_max = dm_off.max() * 100
    p(f"{'Best single day':.<26} {cr_max:>+13.2f}% {sg_max:>+13.2f}% {dm_max:>+13.2f}%")

    # CAOS period (Mar 2023+)
    caos_idx = idx.intersection(caos.index)
    off_caos = regime.reindex(caos_idx) == "OFF"
    ca = caos.reindex(caos_idx).pct_change().fillna(0)
    n_off_c = off_caos.sum()

    cr2 = cr.reindex(caos_idx)[off_caos]
    sg2 = sg.reindex(caos_idx)[off_caos]
    dm2 = dm.reindex(caos_idx)[off_caos]
    ca2 = ca[off_caos]

    p()
    p("-" * 72)
    p(f"CAOS PERIOD: March 2023 - February 2026")
    p(f"Risk-off days: {n_off_c}")
    p("-" * 72)
    p()

    header2 = f"{'':.<26} {'CRDBX':>10} {'SGOV':>10} {'DBMF':>10} {'CAOS':>10}"
    p(header2)
    p("-" * 72)
    p(f"{'Avg daily return':.<26} {cr2.mean()*100:>+9.4f}% {sg2.mean()*100:>+9.4f}% {dm2.mean()*100:>+9.4f}% {ca2.mean()*100:>+9.4f}%")
    p(f"{'Annualized (daily x 252)':.<26} {cr2.mean()*252*100:>+9.2f}% {sg2.mean()*252*100:>+9.2f}% {dm2.mean()*252*100:>+9.2f}% {ca2.mean()*252*100:>+9.2f}%")

    cr2g = ((1+cr2).prod()-1)*100
    sg2g = ((1+sg2).prod()-1)*100
    dm2g = ((1+dm2).prod()-1)*100
    ca2g = ((1+ca2).prod()-1)*100
    p(f"{'Geometric (compounded)':.<26} {cr2g:>+9.2f}% {sg2g:>+9.2f}% {dm2g:>+9.2f}% {ca2g:>+9.2f}%")

    p(f"{'Ann. volatility':.<26} {cr2.std()*np.sqrt(252)*100:>9.2f}% {sg2.std()*np.sqrt(252)*100:>9.2f}% {dm2.std()*np.sqrt(252)*100:>9.2f}% {ca2.std()*np.sqrt(252)*100:>9.2f}%")
    p(f"{'Worst single day':.<26} {cr2.min()*100:>+9.2f}% {sg2.min()*100:>+9.2f}% {dm2.min()*100:>+9.2f}% {ca2.min()*100:>+9.2f}%")
    p(f"{'Best single day':.<26} {cr2.max()*100:>+9.2f}% {sg2.max()*100:>+9.2f}% {dm2.max()*100:>+9.2f}% {ca2.max()*100:>+9.2f}%")

    p()
    p("=" * 72)

    out = os.path.join(SCRIPT_DIR, "riskoff_daily_returns.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSaved to: {out}")

if __name__ == "__main__":
    main()
