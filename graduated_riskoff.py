"""
Graduated Risk-Off Backtest
============================
Inspired by Baltussen et al. (2026) "The Best Defensive Strategies":
- Trend-following (DBMF) and put-like payoff (CAOS) are complementary
- Trend protects in prolonged drawdowns; puts protect immediately
- Quality/low-risk equity (HEQT) earns in non-crisis but bleeds on crash
- 50/50 trend + DAR outperforms either alone across 222 years

Instead of binary risk-on / risk-off, we test a graduated defensive posture:

  REGIME            | DETECTION (from CRDBX NAV)                    | ALLOCATION
  ==================|===============================================|=============================
  Full Risk-On      | CRDBX tracks SPY at 1.5-1.8x beta            | (unchanged -- levered S&P)
  Medium Zone       | CRDBX partially exposed or ambiguous          | 40% HEQT + 30% DBMF + 30% SGOV
  Risk-Off          | CRDBX flat (current cash posture)             | 40% SGOV + 30% CAOS + 20% DBMF + 10% HEQT
  Extreme Tail      | CRDBX flat AND S&P down > 2%                  | 50% CAOS + 50% SGOV

Comparison: Binary (100% SGOV on all non-risk-on days) vs Graduated
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
    START, END = "2023-03-01", "2026-02-28"

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

    # ── REGIME DETECTION (4-tier) ──
    regime = pd.Series("EXCLUDED", index=idx)

    for i in range(len(idx)):
        dt = idx[i]
        if dt in dist_window:
            regime.iloc[i] = "EXCLUDED"
            continue

        spy_move = sp.iloc[i]
        crdbx_move = cr.iloc[i]

        if abs(spy_move) < 0.0010:
            regime.iloc[i] = "AMBIGUOUS"
            continue

        # RISK-ON: CRDBX tracks SPY at high beta (>0.7 ratio, meaningful move)
        if abs(spy_move) >= 0.0015:
            ratio = crdbx_move / spy_move if spy_move != 0 else 0
            if ratio > 0.70 and abs(crdbx_move) > 0.002:
                regime.iloc[i] = "RISK_ON"
                continue

        # EXTREME TAIL: CRDBX flat AND S&P down > 2%
        if abs(crdbx_move) < 0.0003 and spy_move <= -0.02:
            regime.iloc[i] = "EXTREME_TAIL"
            continue

        # RISK-OFF: CRDBX flat while SPY moved meaningfully
        if abs(crdbx_move) < 0.0003 and abs(spy_move) >= 0.0015:
            regime.iloc[i] = "RISK_OFF"
            continue

        # MEDIUM ZONE: CRDBX partially tracking or low-conviction
        # (CRDBX moved, but ratio to SPY is low -- partial exposure or transition)
        if abs(spy_move) >= 0.0015:
            ratio = crdbx_move / spy_move if spy_move != 0 else 0
            if 0.15 < ratio <= 0.70 and abs(crdbx_move) > 0.0005:
                regime.iloc[i] = "MEDIUM"
                continue

        regime.iloc[i] = "AMBIGUOUS"

    # ── STRATEGY RETURNS BY REGIME ──
    # Binary baseline: SGOV on all non-risk-on days
    binary_ret = pd.Series(0.0, index=idx)

    # Graduated: different blends per regime
    graduated_ret = pd.Series(0.0, index=idx)

    # Alt graduated: heavier DBMF tilt (Baltussen 50/50 trend+DAR spirit)
    baltussen_ret = pd.Series(0.0, index=idx)

    for i in range(len(idx)):
        r = regime.iloc[i]

        if r == "RISK_ON":
            # Both strategies use CRDBX actual return on risk-on days
            binary_ret.iloc[i] = cr.iloc[i]
            graduated_ret.iloc[i] = cr.iloc[i]
            baltussen_ret.iloc[i] = cr.iloc[i]

        elif r == "EXTREME_TAIL":
            binary_ret.iloc[i] = sg.iloc[i]
            graduated_ret.iloc[i] = 0.50 * ca.iloc[i] + 0.50 * sg.iloc[i]
            baltussen_ret.iloc[i] = 0.40 * ca.iloc[i] + 0.30 * sg.iloc[i] + 0.30 * dm.iloc[i]

        elif r == "RISK_OFF":
            binary_ret.iloc[i] = sg.iloc[i]
            graduated_ret.iloc[i] = (0.40 * sg.iloc[i] + 0.30 * ca.iloc[i]
                                     + 0.20 * dm.iloc[i] + 0.10 * hq.iloc[i])
            baltussen_ret.iloc[i] = (0.33 * sg.iloc[i] + 0.33 * ca.iloc[i]
                                     + 0.34 * dm.iloc[i])

        elif r == "MEDIUM":
            binary_ret.iloc[i] = sg.iloc[i]
            graduated_ret.iloc[i] = (0.40 * hq.iloc[i] + 0.30 * dm.iloc[i]
                                     + 0.30 * sg.iloc[i])
            baltussen_ret.iloc[i] = (0.30 * hq.iloc[i] + 0.35 * dm.iloc[i]
                                     + 0.35 * sg.iloc[i])

        else:
            # EXCLUDED or AMBIGUOUS: use SGOV for all
            binary_ret.iloc[i] = sg.iloc[i]
            graduated_ret.iloc[i] = sg.iloc[i]
            baltussen_ret.iloc[i] = sg.iloc[i]

    # ── PERFORMANCE CALCULATION ──
    strategies = {
        "Binary (100% SGOV)": binary_ret,
        "Graduated (paper-informed)": graduated_ret,
        "Baltussen 50/50 spirit": baltussen_ret,
        "CRDBX Actual": cr,
    }

    n_total = len(idx)
    counts = regime.value_counts()

    L = []
    def p(s=""):
        L.append(s)
        print(s)

    W = 130
    p("=" * W)
    p("GRADUATED RISK-OFF BACKTEST")
    p("Inspired by Baltussen et al. (2026) 'The Best Defensive Strategies: Two Centuries of Evidence'")
    p("=" * W)
    p(f"Period: {idx[0].date()} to {idx[-1].date()}  ({n_total} trading days)")
    p()
    p("REGIME DISTRIBUTION:")
    for r in ["RISK_ON", "MEDIUM", "RISK_OFF", "EXTREME_TAIL", "AMBIGUOUS", "EXCLUDED"]:
        n = counts.get(r, 0)
        pct = n / n_total * 100
        p(f"  {r:.<20} {n:>5} days  ({pct:>5.1f}%)")
    p()

    # Regime allocation key
    p("-" * W)
    p("ALLOCATION BY REGIME:")
    p(f"  {'Regime':.<20} {'Binary (baseline)':.<30} {'Graduated':.<40} {'Baltussen 50/50':.<40}")
    p(f"  {'RISK_ON':.<20} {'CRDBX actual':.<30} {'CRDBX actual':.<40} {'CRDBX actual':.<40}")
    p(f"  {'MEDIUM':.<20} {'100% SGOV':.<30} {'40H + 30D + 30S':.<40} {'30H + 35D + 35S':.<40}")
    p(f"  {'RISK_OFF':.<20} {'100% SGOV':.<30} {'40S + 30C + 20D + 10H':.<40} {'33S + 33C + 34D':.<40}")
    p(f"  {'EXTREME_TAIL':.<20} {'100% SGOV':.<30} {'50C + 50S':.<40} {'40C + 30S + 30D':.<40}")
    p(f"  {'AMBIGUOUS/EXCL':.<20} {'100% SGOV':.<30} {'100% SGOV':.<40} {'100% SGOV':.<40}")
    p(f"  (H=HEQT, D=DBMF, S=SGOV, C=CAOS)")
    p("-" * W)
    p()

    # Full-period cumulative performance
    p("=" * W)
    p("FULL-PERIOD PERFORMANCE (all days, risk-on + defensive)")
    p("=" * W)

    days_span = (idx[-1] - idx[0]).days
    years = days_span / 365.25

    hdr = f"{'Strategy':.<35} {'CAGR':>8} {'Total':>10} {'Vol':>8} {'Sharpe':>8} {'MaxDD':>8} {'Calmar':>8}"
    p(hdr)
    p("-" * W)

    for name, ret in strategies.items():
        cum = (1 + ret).cumprod()
        total = cum.iloc[-1] - 1
        cagr = ((1 + total) ** (1 / years) - 1) * 100
        vol = ret.std() * np.sqrt(252) * 100
        sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0
        peak = cum.cummax()
        dd = (peak - cum) / peak
        maxdd = dd.max() * 100
        calmar = cagr / maxdd if maxdd > 0 else 0

        p(f"{name:.<35} {cagr:>+7.2f}% {total*100:>+9.2f}% {vol:>7.2f}% {sharpe:>8.3f} {maxdd:>7.2f}% {calmar:>8.3f}")

    p()

    # Per-regime breakdown
    for regime_name in ["RISK_OFF", "EXTREME_TAIL", "MEDIUM"]:
        mask = regime == regime_name
        n_r = mask.sum()
        if n_r < 5:
            continue

        p("=" * W)
        p(f"REGIME: {regime_name}  ({n_r} days)")
        p("=" * W)

        sp_r = sp[mask]
        p(f"  S&P on these days: mean {sp_r.mean()*100:+.3f}%, median {sp_r.median()*100:+.3f}%, "
          f"worst {sp_r.min()*100:+.3f}%, best {sp_r.max()*100:+.3f}%")
        p()

        hdr2 = f"  {'Strategy':.<35} {'Mean':>10} {'Median':>10} {'Cum':>10} {'Days+':>8} {'WinRate':>8} {'Beta':>8}"
        p(hdr2)
        p("  " + "-" * (W - 2))

        for name, ret in strategies.items():
            if name == "CRDBX Actual":
                continue
            r = ret[mask]
            mean_r = r.mean() * 100
            med_r = r.median() * 100
            cum_r = ((1 + r).prod() - 1) * 100
            pos = (r > 0).sum()
            win = pos / len(r) * 100
            sp_vals = sp_r.values
            r_vals = r.values
            beta = 0
            if len(sp_vals) > 3 and np.var(sp_vals) > 0:
                beta = np.cov(r_vals, sp_vals)[0, 1] / np.var(sp_vals)

            p(f"  {name:.<35} {mean_r:>+9.4f}% {med_r:>+9.4f}% {cum_r:>+9.3f}% {pos:>8} {win:>7.1f}% {beta:>+8.4f}")

        p()

    # Graduated vs Binary: incremental value
    p("=" * W)
    p("INCREMENTAL VALUE: Graduated vs Binary (non-risk-on days only)")
    p("=" * W)

    non_on = regime != "RISK_ON"
    non_on_excl = non_on & (regime != "EXCLUDED")

    for name, ret in [("Graduated", graduated_ret), ("Baltussen 50/50", baltussen_ret)]:
        r_non = ret[non_on_excl]
        b_non = binary_ret[non_on_excl]
        diff = r_non - b_non

        geo_strat = ((1 + r_non).prod() - 1) * 100
        geo_base = ((1 + b_non).prod() - 1) * 100
        incr = geo_strat - geo_base

        ann_strat = r_non.mean() * 252 * 100
        ann_base = b_non.mean() * 252 * 100
        ann_incr = ann_strat - ann_base

        vol_strat = r_non.std() * np.sqrt(252) * 100
        vol_base = b_non.std() * np.sqrt(252) * 100

        days_better = (diff > 0).sum()
        days_worse = (diff < 0).sum()
        days_same = (diff.abs() < 0.00001).sum()

        p(f"\n  {name}:")
        p(f"    Geometric return (defensive days): {geo_strat:+.3f}%  vs  Binary: {geo_base:+.3f}%  => Incremental: {incr:+.3f}%")
        p(f"    Annualized return:                 {ann_strat:+.2f}%  vs  Binary: {ann_base:+.2f}%  => Incremental: {ann_incr:+.2f}%")
        p(f"    Volatility:                        {vol_strat:.2f}%  vs  Binary: {vol_base:.2f}%")
        p(f"    Days outperforming Binary:          {days_better}  /  Days underperforming: {days_worse}  /  Same: {days_same}")

    p()

    # Year-by-year comparison
    p("=" * W)
    p("YEAR-BY-YEAR: Full portfolio (risk-on + defensive)")
    p("=" * W)
    p(f"  {'Year':.<8} {'Binary':>10} {'Graduated':>12} {'Baltussen':>12} {'CRDBX':>10} {'SPY':>10}")
    p("  " + "-" * (W - 2))

    for year in sorted(set(idx.year)):
        mask_y = idx.year == year
        for name, ret in strategies.items():
            r_y = ret[mask_y]
            yr_ret = ((1 + r_y).prod() - 1) * 100
            if name == "Binary (100% SGOV)":
                bin_yr = yr_ret
            elif name == "Graduated (paper-informed)":
                grad_yr = yr_ret
            elif name == "Baltussen 50/50 spirit":
                balt_yr = yr_ret
            elif name == "CRDBX Actual":
                crdbx_yr = yr_ret

        spy_yr = ((1 + sp[mask_y]).prod() - 1) * 100
        p(f"  {year:<8} {bin_yr:>+9.2f}% {grad_yr:>+11.2f}% {balt_yr:>+11.2f}% {crdbx_yr:>+9.2f}% {spy_yr:>+9.2f}%")

    p()

    # Drawdown analysis: worst 20 days for S&P across all regimes
    p("=" * W)
    p("TOP 20 WORST S&P DAYS -- Strategy comparison")
    p("=" * W)

    sp_sorted = sp.sort_values().head(20)
    hdr3 = f"  {'Date':.<14} {'S&P':>8} {'Regime':.<15} {'Binary':>10} {'Graduated':>12} {'Baltussen':>12}"
    p(hdr3)
    p("  " + "-" * (W - 2))

    for dt in sp_sorted.index:
        r = regime.loc[dt]
        sp_d = sp.loc[dt] * 100
        bin_d = binary_ret.loc[dt] * 100
        grad_d = graduated_ret.loc[dt] * 100
        balt_d = baltussen_ret.loc[dt] * 100
        p(f"  {dt.date()!s:.<14} {sp_d:>+7.2f}% {r:.<15} {bin_d:>+9.4f}% {grad_d:>+11.4f}% {balt_d:>+11.4f}%")

    p()
    p("=" * W)
    p("METHODOLOGY NOTES:")
    p("-" * W)
    p("1. Risk-on days use CRDBX actual returns for all strategies (signal is unchanged)")
    p("2. Regime detection is based on CRDBX NAV behavior vs SPY (same method as h2h.py)")
    p("3. Medium zone = CRDBX partially tracking SPY (ratio 0.15-0.70) -- transition days")
    p("4. Extreme tail = CRDBX flat AND S&P down > 2% on same day")
    p("5. Graduated allocations informed by Baltussen et al. (2026):")
    p("   - CAOS (put-like) = immediate protection, expensive carry => heavy in extreme tail")
    p("   - DBMF (trend-following) = earns in all states, slow to protect => medium + risk-off")
    p("   - HEQT (quality/hedged equity) = earns in non-crisis, bleeds on crash => medium zone")
    p("   - SGOV (cash) = pure preservation, always positive => anchor across all defensive regimes")
    p("6. All returns are actual daily NAV total returns from Yahoo Finance, net of fund ERs")
    p("=" * W)

    out = os.path.join(SCRIPT_DIR, "graduated_riskoff_results.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
