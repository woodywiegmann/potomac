"""
Graduated Penta Backtest (VOO, Unlevered)
==========================================
Starts from the ACTUAL signal architecture:
  Penta (4 indicators, 5-day SMA smoothed):
    1. S&P 500 trend: price > 50-day SMA, smoothed by 5-day SMA
    2. Transports: ^DJT > 5-day SMA
    3. NYSE breadth: ^NYA > 5-day SMA
    4. Credit: LQD > 5-day SMA
  Penta ON = 3+ of 4 green. Penta OFF = 2+ red.

  Overlays:
    5. RSI(14) < 75 (not overbought)
    6. VIX < 5-day SMA (not spiking)

  Composite = Penta*50% + S&P trend*20% + RSI*15% + VIX*15%

Risk-on instrument: VOO (unlevered S&P 500)
Then we compare to CRDBX actual to quantify the leverage gap.

Regime tiers derived from the composite score:
  FULL RISK-ON     composite >= 0.85    100% VOO
  MEDIUM ZONE      0.50 <= comp < 0.85  graduated defensive
  RISK-OFF         0.20 <= comp < 0.50  heavy defensive
  EXTREME TAIL     comp < 0.20 AND VIX spiking   max convexity

Defensive allocations (paper-informed):
  MEDIUM:       40% HEQT + 30% DBMF + 30% SGOV
  RISK-OFF:     40% SGOV + 30% CAOS + 20% DBMF + 10% HEQT
  EXTREME TAIL: 50% CAOS + 50% SGOV

Strategies tested:
  1. Binary VOO/SGOV (baseline -- all-or-nothing at Penta flip)
  2. Graduated + paper-informed defensive blends
  3. VOO buy-and-hold
  4. CRDBX actual (for the return gap comparison)
"""

import os, sys, warnings, math
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_tr(ticker, start, end):
    """Total return series with manual dividend reinvestment."""
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


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def main():
    START = "2023-03-01"
    END = "2026-02-28"
    WARMUP_START = "2022-06-01"

    print("=" * 130)
    print("GRADUATED PENTA BACKTEST -- VOO (UNLEVERED)")
    print("Signal-driven regime detection, not reverse-engineered from CRDBX NAV")
    print("=" * 130)

    # ── FETCH DATA ──
    print("\nFetching data...")
    # Signal inputs
    sp500_raw = yf.download("^GSPC", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(sp500_raw, pd.DataFrame):
        sp500_raw = sp500_raw.squeeze()
    sp500_raw.index = sp500_raw.index.tz_localize(None)

    djt_raw = yf.download("^DJT", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(djt_raw, pd.DataFrame):
        djt_raw = djt_raw.squeeze()
    djt_raw.index = djt_raw.index.tz_localize(None)

    nya_raw = yf.download("^NYA", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(nya_raw, pd.DataFrame):
        nya_raw = nya_raw.squeeze()
    nya_raw.index = nya_raw.index.tz_localize(None)

    lqd_raw = yf.download("LQD", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(lqd_raw, pd.DataFrame):
        lqd_raw = lqd_raw.squeeze()
    lqd_raw.index = lqd_raw.index.tz_localize(None)

    vix_raw = yf.download("^VIX", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(vix_raw, pd.DataFrame):
        vix_raw = vix_raw.squeeze()
    vix_raw.index = vix_raw.index.tz_localize(None)

    # Instruments (total return)
    voo, _ = get_tr("VOO", WARMUP_START, END)
    sgov, _ = get_tr("SGOV", WARMUP_START, END)
    dbmf, _ = get_tr("DBMF", WARMUP_START, END)
    caos, _ = get_tr("CAOS", "2023-01-01", END)
    heqt, _ = get_tr("HEQT", WARMUP_START, END)
    crdbx, _ = get_tr("CRDBX", WARMUP_START, END)

    print(f"  S&P 500: {sp500_raw.index[0].date()} to {sp500_raw.index[-1].date()}")
    print(f"  VOO:     {voo.index[0].date()} to {voo.index[-1].date()}")
    print(f"  CRDBX:   {crdbx.index[0].date()} to {crdbx.index[-1].date()}")

    # ── BUILD PENTA SIGNALS ──
    print("\nComputing Penta signals...")

    # Common index (all instruments must be present)
    idx = (voo.index.intersection(sgov.index).intersection(dbmf.index)
           .intersection(caos.index).intersection(heqt.index)
           .intersection(crdbx.index).intersection(sp500_raw.index))
    idx = idx[idx >= START]
    print(f"  Trading days in scope: {len(idx)} ({idx[0].date()} to {idx[-1].date()})")

    # Penta indicator 1: S&P trend (price > 50-day SMA, smoothed by 5-day)
    sp_sma50 = sp500_raw.rolling(50).mean()
    sp_trend_raw = (sp500_raw > sp_sma50).astype(float)
    penta_trend = sp_trend_raw.rolling(5).mean().reindex(idx).apply(lambda x: 1 if x > 0.5 else 0)

    # Penta indicator 2: Transports > 5-day SMA
    djt_sma5 = djt_raw.rolling(5).mean()
    penta_transports = (djt_raw > djt_sma5).reindex(idx).astype(int).fillna(0)

    # Penta indicator 3: NYSE breadth > 5-day SMA
    nya_sma5 = nya_raw.rolling(5).mean()
    penta_breadth = (nya_raw > nya_sma5).reindex(idx).astype(int).fillna(0)

    # Penta indicator 4: Credit (LQD > 5-day SMA)
    lqd_sma5 = lqd_raw.rolling(5).mean()
    penta_credit = (lqd_raw > lqd_sma5).reindex(idx).astype(int).fillna(0)

    penta_score = penta_trend + penta_transports + penta_breadth + penta_credit
    penta_on = (penta_score >= 3).astype(int)

    # Overlay: RSI(14) not overbought
    rsi = compute_rsi(sp500_raw, 14)
    rsi_ok = (rsi.reindex(idx) < 75).astype(int).fillna(1)

    # Overlay: VIX not spiking (below 5-day SMA)
    vix_sma5 = vix_raw.rolling(5).mean()
    vix_ok = (vix_raw < vix_sma5).reindex(idx).astype(int).fillna(1)
    vix_level = vix_raw.reindex(idx).ffill()

    # Composite score
    composite = (penta_on * 0.50 + penta_trend * 0.20 + rsi_ok * 0.15 + vix_ok * 0.15)

    # ── REGIME FROM COMPOSITE ──
    regime = pd.Series("RISK_ON", index=idx)
    for i in range(len(idx)):
        c = composite.iloc[i]
        v = vix_level.iloc[i] if not pd.isna(vix_level.iloc[i]) else 20
        if c >= 0.85:
            regime.iloc[i] = "FULL_ON"
        elif c >= 0.50:
            regime.iloc[i] = "MEDIUM"
        elif c >= 0.20:
            regime.iloc[i] = "RISK_OFF"
        else:
            # comp < 0.20: everything is red
            if v > 25:
                regime.iloc[i] = "EXTREME_TAIL"
            else:
                regime.iloc[i] = "RISK_OFF"

    # ── DAILY RETURNS ──
    vo = voo.reindex(idx).pct_change().fillna(0)
    sg = sgov.reindex(idx).pct_change().fillna(0)
    dm = dbmf.reindex(idx).pct_change().fillna(0)
    ca = caos.reindex(idx).pct_change().fillna(0)
    hq = heqt.reindex(idx).pct_change().fillna(0)
    cr = crdbx.reindex(idx).pct_change().fillna(0)
    sp_ret = sp500_raw.reindex(idx).pct_change().fillna(0)

    # ── STRATEGY 1: Binary VOO/SGOV ──
    binary_ret = pd.Series(0.0, index=idx)
    for i in range(len(idx)):
        if penta_on.iloc[i] == 1:
            binary_ret.iloc[i] = vo.iloc[i]
        else:
            binary_ret.iloc[i] = sg.iloc[i]

    # ── STRATEGY 2: Graduated + paper-informed defensive ──
    graduated_ret = pd.Series(0.0, index=idx)
    for i in range(len(idx)):
        r = regime.iloc[i]
        c = composite.iloc[i]

        if r == "FULL_ON":
            graduated_ret.iloc[i] = vo.iloc[i]

        elif r == "MEDIUM":
            # Partial equity + defensive blend
            # Map composite 0.50-0.85 to equity weight 0.25-0.75
            eq_w = 0.25 + (c - 0.50) / (0.85 - 0.50) * 0.50
            eq_w = max(0.20, min(0.80, eq_w))
            def_w = 1.0 - eq_w
            # Defensive portion: 40% HEQT + 30% DBMF + 30% SGOV
            def_ret = 0.40 * hq.iloc[i] + 0.30 * dm.iloc[i] + 0.30 * sg.iloc[i]
            graduated_ret.iloc[i] = eq_w * vo.iloc[i] + def_w * def_ret

        elif r == "RISK_OFF":
            # 40% SGOV + 30% CAOS + 20% DBMF + 10% HEQT
            graduated_ret.iloc[i] = (0.40 * sg.iloc[i] + 0.30 * ca.iloc[i]
                                     + 0.20 * dm.iloc[i] + 0.10 * hq.iloc[i])

        elif r == "EXTREME_TAIL":
            # 50% CAOS + 50% SGOV
            graduated_ret.iloc[i] = 0.50 * ca.iloc[i] + 0.50 * sg.iloc[i]

    # ── STRATEGY 3: Graduated + simple defensive (no CAOS/HEQT) ──
    grad_simple_ret = pd.Series(0.0, index=idx)
    for i in range(len(idx)):
        r = regime.iloc[i]
        c = composite.iloc[i]

        if r == "FULL_ON":
            grad_simple_ret.iloc[i] = vo.iloc[i]
        elif r == "MEDIUM":
            eq_w = 0.25 + (c - 0.50) / (0.85 - 0.50) * 0.50
            eq_w = max(0.20, min(0.80, eq_w))
            def_w = 1.0 - eq_w
            def_ret = 0.50 * sg.iloc[i] + 0.50 * dm.iloc[i]
            grad_simple_ret.iloc[i] = eq_w * vo.iloc[i] + def_w * def_ret
        elif r in ("RISK_OFF", "EXTREME_TAIL"):
            grad_simple_ret.iloc[i] = 0.60 * sg.iloc[i] + 0.40 * dm.iloc[i]

    # ── COLLECT ALL STRATEGIES ──
    strategies = {
        "Binary VOO/SGOV": binary_ret,
        "Graduated (paper-informed)": graduated_ret,
        "Graduated (simple SGOV/DBMF)": grad_simple_ret,
        "VOO Buy-Hold": vo,
        "CRDBX Actual": cr,
    }

    # ══════════════════════════════════════════════════════════════════════
    # REPORT
    # ══════════════════════════════════════════════════════════════════════
    L = []
    def p(s=""):
        L.append(s)
        print(s)

    W = 140

    p()
    p("=" * W)
    p("SIGNAL DIAGNOSTICS")
    p("=" * W)
    counts = regime.value_counts()
    n = len(idx)
    p(f"  Penta ON:           {penta_on.sum():>5} days  ({penta_on.mean()*100:>5.1f}%)")
    p(f"  Penta OFF:          {(penta_on == 0).sum():>5} days  ({(1-penta_on.mean())*100:>5.1f}%)")
    p()
    p("  Penta sub-indicators (% of days ON):")
    p(f"    S&P Trend:        {penta_trend.mean()*100:>5.1f}%")
    p(f"    Transports:       {penta_transports.mean()*100:>5.1f}%")
    p(f"    NYSE Breadth:     {penta_breadth.mean()*100:>5.1f}%")
    p(f"    Credit (LQD):     {penta_credit.mean()*100:>5.1f}%")
    p()
    p("  Overlay filters:")
    p(f"    RSI OK (<75):     {rsi_ok.mean()*100:>5.1f}%")
    p(f"    VIX OK (<5d SMA): {vix_ok.mean()*100:>5.1f}%")
    p()
    p("  Composite score distribution:")
    p(f"    Mean:             {composite.mean():.3f}")
    p(f"    Median:           {composite.median():.3f}")
    p(f"    Std:              {composite.std():.3f}")
    p()
    p("  REGIME DISTRIBUTION (from composite score):")
    for r in ["FULL_ON", "MEDIUM", "RISK_OFF", "EXTREME_TAIL"]:
        cnt = counts.get(r, 0)
        pct = cnt / n * 100
        p(f"    {r:.<20} {cnt:>5} days  ({pct:>5.1f}%)")

    p()
    p("-" * W)
    p("  REGIME MAPPING:")
    p(f"    {'FULL_ON':.<20} composite >= 0.85                    => 100% VOO")
    p(f"    {'MEDIUM':.<20} 0.50 <= composite < 0.85             => partial VOO + 40H/30D/30S defensive")
    p(f"    {'RISK_OFF':.<20} 0.20 <= composite < 0.50             => 40S + 30C + 20D + 10H")
    p(f"    {'EXTREME_TAIL':.<20} composite < 0.20 AND VIX > 25     => 50C + 50S")
    p(f"    (H=HEQT, D=DBMF, S=SGOV, C=CAOS)")
    p("-" * W)

    # ── FULL-PERIOD PERFORMANCE ──
    p()
    p("=" * W)
    p("FULL-PERIOD PERFORMANCE")
    p("=" * W)

    days_span = (idx[-1] - idx[0]).days
    years = days_span / 365.25

    hdr = f"{'Strategy':.<40} {'CAGR':>8} {'Total':>10} {'Vol':>8} {'Sharpe':>8} {'MaxDD':>8} {'Calmar':>8} {'Beta':>8}"
    p(hdr)
    p("-" * W)

    strat_metrics = {}
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
        beta = 0
        common = ret.index.intersection(sp_ret.index)
        if len(common) > 50:
            cv = np.cov(ret.reindex(common), sp_ret.reindex(common))
            if cv[1, 1] > 0:
                beta = cv[0, 1] / cv[1, 1]

        strat_metrics[name] = {"cagr": cagr, "total": total * 100, "vol": vol,
                                "sharpe": sharpe, "maxdd": maxdd, "calmar": calmar, "beta": beta}

        p(f"{name:.<40} {cagr:>+7.2f}% {total*100:>+9.2f}% {vol:>7.2f}% {sharpe:>8.3f} "
          f"{maxdd:>7.2f}% {calmar:>8.3f} {beta:>+8.3f}")

    p()

    # ── RETURN GAP: VOO strategies vs CRDBX ──
    p("=" * W)
    p("RETURN GAP: VOO (unlevered) vs CRDBX (levered) -- what leverage buys")
    p("=" * W)

    crdbx_cagr = strat_metrics["CRDBX Actual"]["cagr"]
    for name in ["Binary VOO/SGOV", "Graduated (paper-informed)", "Graduated (simple SGOV/DBMF)"]:
        m = strat_metrics[name]
        gap = crdbx_cagr - m["cagr"]
        dd_diff = strat_metrics["CRDBX Actual"]["maxdd"] - m["maxdd"]
        vol_diff = strat_metrics["CRDBX Actual"]["vol"] - m["vol"]
        sharpe_diff = m["sharpe"] - strat_metrics["CRDBX Actual"]["sharpe"]

        p(f"\n  {name} vs CRDBX:")
        p(f"    CAGR gap:        {gap:+.2f}%  (CRDBX higher by this much)")
        p(f"    MaxDD gap:       {dd_diff:+.2f}%  (positive = CRDBX more drawdown)")
        p(f"    Vol gap:         {vol_diff:+.2f}%  (positive = CRDBX more volatile)")
        p(f"    Sharpe gap:      {sharpe_diff:+.3f}  (positive = VOO strategy better risk-adjusted)")
        p(f"    Beta gap:        {m['beta']:+.3f} vs {strat_metrics['CRDBX Actual']['beta']:+.3f}")

    p()

    # ── HOW MUCH EXTRA RETURN NEEDED TO MATCH CRDBX ──
    p("=" * W)
    p("BREAKEVEN ANALYSIS: What would the graduated strategy need to match CRDBX?")
    p("=" * W)

    grad_m = strat_metrics["Graduated (paper-informed)"]
    gap_cagr = crdbx_cagr - grad_m["cagr"]

    # Count defensive days
    n_def = ((regime == "MEDIUM") | (regime == "RISK_OFF") | (regime == "EXTREME_TAIL")).sum()
    n_on = (regime == "FULL_ON").sum()
    def_frac = n_def / n
    on_frac = n_on / n

    # Extra return needed per defensive day
    if n_def > 0:
        extra_per_def_day = gap_cagr / 252 / def_frac * 100 if def_frac > 0 else 0
    else:
        extra_per_def_day = 0

    p(f"  CRDBX CAGR:                     {crdbx_cagr:+.2f}%")
    p(f"  Graduated VOO CAGR:             {grad_m['cagr']:+.2f}%")
    p(f"  Gap to close:                   {gap_cagr:+.2f}%")
    p(f"  Days in full risk-on:           {n_on} ({on_frac*100:.1f}%)")
    p(f"  Days in defensive modes:        {n_def} ({def_frac*100:.1f}%)")
    p(f"  Extra bps/day needed on def:    {extra_per_def_day:.2f} bps")
    p()
    p("  Translation: To close the gap, the graduated defensive allocation would")
    p(f"  need an extra {extra_per_def_day:.1f} bps/day on the {def_frac*100:.0f}% of days it's in defensive mode.")
    p(f"  Or equivalently, {gap_cagr:.2f}% more CAGR from the defensive instruments alone.")
    p()
    p("  Sources of that gap:")
    p("    1. CRDBX uses ~1.5-1.8x leverage on risk-on days (VOO is 1.0x)")
    p("    2. CRDBX's proprietary signal may differ from our Penta proxy")
    p("    3. CRDBX has timing alpha from the actual signal implementation")
    p()

    # ── SHARPE/CALMAR COMPARISON ──
    p("  But risk-adjusted returns tell a different story:")
    p(f"    Sharpe:  Graduated {grad_m['sharpe']:.3f}  vs  CRDBX {strat_metrics['CRDBX Actual']['sharpe']:.3f}")
    p(f"    Calmar:  Graduated {grad_m['calmar']:.3f}  vs  CRDBX {strat_metrics['CRDBX Actual']['calmar']:.3f}")
    p(f"    MaxDD:   Graduated {grad_m['maxdd']:.2f}%  vs  CRDBX {strat_metrics['CRDBX Actual']['maxdd']:.2f}%")
    p()
    crdbx_sharpe = strat_metrics["CRDBX Actual"]["sharpe"]
    if grad_m["sharpe"] > crdbx_sharpe:
        p("  => The graduated VOO strategy has BETTER risk-adjusted returns than CRDBX.")
        p("     The raw CAGR gap is entirely a leverage effect, not an alpha deficit.")
        leverage_implied = crdbx_cagr / grad_m["cagr"] if grad_m["cagr"] > 0 else 0
        p(f"     Implied leverage ratio: {leverage_implied:.2f}x")
    else:
        p("  => CRDBX has better risk-adjusted returns; there may be true alpha in the signal.")

    p()

    # ── PER-REGIME ANALYSIS ──
    for regime_name in ["FULL_ON", "MEDIUM", "RISK_OFF", "EXTREME_TAIL"]:
        mask = regime == regime_name
        n_r = mask.sum()
        if n_r < 3:
            continue

        p("=" * W)
        p(f"REGIME: {regime_name}  ({n_r} days, {n_r/n*100:.1f}%)")
        p("=" * W)

        sp_r = sp_ret[mask]
        p(f"  S&P 500: mean {sp_r.mean()*100:+.4f}%, worst {sp_r.min()*100:+.3f}%, best {sp_r.max()*100:+.3f}%")
        p(f"  Composite score: mean {composite[mask].mean():.3f}, min {composite[mask].min():.3f}, max {composite[mask].max():.3f}")
        p()

        hdr2 = f"  {'Strategy':.<40} {'Mean':>10} {'Median':>10} {'Cum':>10} {'WinRate':>8}"
        p(hdr2)
        p("  " + "-" * (W - 2))

        for name, ret in strategies.items():
            r_vals = ret[mask]
            mean_r = r_vals.mean() * 100
            med_r = r_vals.median() * 100
            cum_r = ((1 + r_vals).prod() - 1) * 100
            pos = (r_vals > 0).sum()
            win = pos / len(r_vals) * 100 if len(r_vals) > 0 else 0

            p(f"  {name:.<40} {mean_r:>+9.4f}% {med_r:>+9.4f}% {cum_r:>+9.3f}% {win:>7.1f}%")
        p()

    # ── YEAR-BY-YEAR ──
    p("=" * W)
    p("YEAR-BY-YEAR")
    p("=" * W)
    hdr3 = f"  {'Year':.<8}"
    for name in strategies:
        short = name[:18]
        hdr3 += f" {short:>20}"
    hdr3 += f" {'S&P 500':>10}"
    p(hdr3)
    p("  " + "-" * (W - 2))

    for year in sorted(set(idx.year)):
        mask_y = idx.year == year
        row = f"  {year:<8}"
        for name, ret in strategies.items():
            yr_ret = ((1 + ret[mask_y]).prod() - 1) * 100
            row += f" {yr_ret:>+19.2f}%"
        spy_yr = ((1 + sp_ret[mask_y]).prod() - 1) * 100
        row += f" {spy_yr:>+9.2f}%"
        p(row)

    p()

    # ── WORST S&P DAYS ──
    p("=" * W)
    p("TOP 20 WORST S&P DAYS -- regime and strategy returns")
    p("=" * W)

    sp_worst = sp_ret.sort_values().head(20)
    hdr4 = f"  {'Date':.<14} {'S&P':>8} {'Regime':.<15} {'Comp':>6} {'Binary':>10} {'Graduated':>12} {'CRDBX':>10}"
    p(hdr4)
    p("  " + "-" * (W - 2))

    for dt in sp_worst.index:
        sp_d = sp_ret.loc[dt] * 100
        r = regime.loc[dt]
        c = composite.loc[dt]
        bin_d = binary_ret.loc[dt] * 100
        grad_d = graduated_ret.loc[dt] * 100
        cr_d = cr.loc[dt] * 100
        p(f"  {dt.date()!s:.<14} {sp_d:>+7.2f}% {r:.<15} {c:>5.2f} {bin_d:>+9.4f}% {grad_d:>+11.4f}% {cr_d:>+9.4f}%")

    p()

    # ── SIGNAL TRANSITION LOG ──
    p("=" * W)
    p("SIGNAL TRANSITIONS (Penta ON/OFF flips)")
    p("=" * W)

    transitions = []
    for i in range(1, len(idx)):
        prev = penta_on.iloc[i - 1]
        curr = penta_on.iloc[i]
        if prev != curr:
            direction = "ON" if curr == 1 else "OFF"
            transitions.append((idx[i], direction, composite.iloc[i], sp_ret.iloc[i] * 100))

    p(f"  Total transitions: {len(transitions)}")
    p(f"  Average days between flips: {n / max(len(transitions), 1):.0f}")
    p()
    p(f"  {'Date':.<14} {'Direction':.<10} {'Composite':>10} {'S&P that day':>14}")
    p("  " + "-" * 60)
    for dt, direction, comp, sp_d in transitions:
        p(f"  {dt.date()!s:.<14} {direction:.<10} {comp:>10.3f} {sp_d:>+13.2f}%")

    p()

    # ── METHODOLOGY ──
    p("=" * W)
    p("METHODOLOGY")
    p("-" * W)
    p("1. Signal: Penta composite (4 trend/breadth/credit indicators + RSI/VIX overlays)")
    p("   Same architecture as backtest.py, same weights: Penta=50%, Trend=20%, RSI=15%, VIX=15%")
    p("2. Risk-on instrument: VOO (Vanguard S&P 500 ETF, 1.0x, ER 0.03%)")
    p("   NOT CRDBX (which uses ~1.5-1.8x leverage via derivatives)")
    p("3. Regime tiers derived from composite score, not reverse-engineered from CRDBX NAV")
    p("4. Defensive allocations informed by Baltussen et al. (2026):")
    p("   - CAOS (put-like) = immediate protection => extreme tail + risk-off")
    p("   - DBMF (trend-following) = positive carry in all regimes => medium + risk-off")
    p("   - HEQT (quality/hedged equity) = earns in non-crisis => medium zone")
    p("   - SGOV (cash) = preservation anchor")
    p("5. All returns: actual daily NAV total return from Yahoo Finance, net of fund ERs")
    p("6. The CAGR gap between VOO and CRDBX strategies = the cost of being unlevered")
    p("   This gap is NOT alpha -- it's leverage. Compare Sharpe and Calmar for true alpha.")
    p("=" * W)

    out = os.path.join(SCRIPT_DIR, "graduated_penta_results.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
