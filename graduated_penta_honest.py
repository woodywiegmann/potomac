"""
Graduated Penta Backtest — HONEST VERSION
==========================================
Same Penta signal architecture as graduated_penta.py, but with realistic
assumptions enforced via honest_backtest.py:

    1. T+1 signal lag (signal on day T, trade on day T+1)
    2. Open-price execution on regime transition days
    3. 20bps round-trip transaction cost per transition
    4. Full validation pipeline

This produces numbers that should approximate QuantConnect results.
Compare against graduated_penta_results.txt to see what the lag costs.

Usage: python graduated_penta_honest.py
"""

import os
import sys
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from honest_backtest import (
    lag_signals,
    apply_transition_costs,
    compute_transition_mask,
    compute_metrics,
    validate_strategy,
    print_validation_report,
)


def get_ohlc(ticker, start, end):
    """Fetch OHLC + dividend-adjusted total return series."""
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.DataFrame()
    h.index = h.index.tz_localize(None)
    return h


def build_total_return(hist):
    """Build total return NAV from OHLC history with dividend reinvestment."""
    nav = hist["Close"].copy()
    divs = hist.get("Dividends", pd.Series(0.0, index=hist.index))
    sh = 1.0
    vals = []
    for dt in hist.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            sh *= (1 + d / p)
        vals.append(sh * p)
    return pd.Series(vals, index=hist.index)


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
    SIGNAL_LAG = 1
    COST_BPS = 20.0

    W = 120

    print("=" * W)
    print("GRADUATED PENTA BACKTEST — HONEST VERSION (T+1 lag, open execution, 20bps costs)")
    print("=" * W)

    print("\nFetching data (with Open prices for execution)...")

    sp500_h = get_ohlc("^GSPC", WARMUP_START, END)
    sp500_raw = sp500_h["Close"].dropna()
    sp500_open = sp500_h["Open"].dropna()

    djt_raw = yf.download("^DJT", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(djt_raw, pd.DataFrame):
        djt_raw = djt_raw.squeeze()
    djt_raw.index = djt_raw.index.tz_localize(None) if djt_raw.index.tz is not None else djt_raw.index

    nya_raw = yf.download("^NYA", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(nya_raw, pd.DataFrame):
        nya_raw = nya_raw.squeeze()
    nya_raw.index = nya_raw.index.tz_localize(None) if nya_raw.index.tz is not None else nya_raw.index

    lqd_raw = yf.download("LQD", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(lqd_raw, pd.DataFrame):
        lqd_raw = lqd_raw.squeeze()
    lqd_raw.index = lqd_raw.index.tz_localize(None) if lqd_raw.index.tz is not None else lqd_raw.index

    vix_raw = yf.download("^VIX", start=WARMUP_START, end=END, progress=False)["Close"].dropna()
    if isinstance(vix_raw, pd.DataFrame):
        vix_raw = vix_raw.squeeze()
    vix_raw.index = vix_raw.index.tz_localize(None) if vix_raw.index.tz is not None else vix_raw.index

    voo_h = get_ohlc("VOO", WARMUP_START, END)
    voo_close = build_total_return(voo_h)
    voo_open = voo_h["Open"]

    sgov_h = get_ohlc("SGOV", WARMUP_START, END)
    sgov_close = build_total_return(sgov_h)

    crdbx_h = get_ohlc("CRDBX", WARMUP_START, END)
    crdbx_close = build_total_return(crdbx_h)

    idx = (voo_close.index.intersection(sgov_close.index)
           .intersection(crdbx_close.index).intersection(sp500_raw.index))
    idx = idx[idx >= START]
    print(f"  Trading days: {len(idx)} ({idx[0].date()} to {idx[-1].date()})")

    # ── BUILD PENTA SIGNALS (same as original) ──
    sp_sma50 = sp500_raw.rolling(50).mean()
    sp_trend_raw = (sp500_raw > sp_sma50).astype(float)
    penta_trend = sp_trend_raw.rolling(5).mean().reindex(idx).apply(lambda x: 1 if x > 0.5 else 0)

    djt_sma5 = djt_raw.rolling(5).mean()
    penta_transports = (djt_raw > djt_sma5).reindex(idx).astype(int).fillna(0)

    nya_sma5 = nya_raw.rolling(5).mean()
    penta_breadth = (nya_raw > nya_sma5).reindex(idx).astype(int).fillna(0)

    lqd_sma5 = lqd_raw.rolling(5).mean()
    penta_credit = (lqd_raw > lqd_sma5).reindex(idx).astype(int).fillna(0)

    penta_score = penta_trend + penta_transports + penta_breadth + penta_credit
    penta_on = (penta_score >= 3).astype(int)

    rsi = compute_rsi(sp500_raw, 14)
    rsi_ok = (rsi.reindex(idx) < 75).astype(int).fillna(1)

    vix_sma5 = vix_raw.rolling(5).mean()
    vix_ok = (vix_raw < vix_sma5).reindex(idx).astype(int).fillna(1)
    vix_level = vix_raw.reindex(idx).ffill()

    composite = (penta_on * 0.50 + penta_trend * 0.20 + rsi_ok * 0.15 + vix_ok * 0.15)

    regime = pd.Series("RISK_OFF", index=idx)
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
            regime.iloc[i] = "EXTREME_TAIL" if v > 25 else "RISK_OFF"

    # ── LAG SIGNALS BY 1 DAY ──
    print(f"\n  Applying T+{SIGNAL_LAG} signal lag...")
    lagged_penta = lag_signals(penta_on, SIGNAL_LAG).fillna(0).astype(int)
    lagged_regime = lag_signals(regime, SIGNAL_LAG).fillna("RISK_OFF")
    lagged_composite = lag_signals(composite, SIGNAL_LAG).fillna(0)

    # ── DAILY RETURNS (using open prices on transition days) ──
    vo_ret = voo_close.reindex(idx).pct_change().fillna(0)
    sg_ret = sgov_close.reindex(idx).pct_change().fillna(0)
    cr_ret = crdbx_close.reindex(idx).pct_change().fillna(0)
    sp_ret = sp500_raw.reindex(idx).pct_change().fillna(0)

    regime_transitions = compute_transition_mask(lagged_regime)

    voo_open_aligned = voo_open.reindex(idx).ffill()
    voo_close_aligned = voo_close.reindex(idx)
    open_exec_ret = (voo_close_aligned - voo_open_aligned) / voo_open_aligned

    vo_honest = vo_ret.copy()
    vo_honest[regime_transitions] = open_exec_ret[regime_transitions]
    vo_honest = vo_honest.fillna(0)

    # ── STRATEGY 1: Honest Binary VOO/SGOV ──
    binary_ret = pd.Series(0.0, index=idx)
    for i in range(len(idx)):
        if lagged_penta.iloc[i] == 1:
            binary_ret.iloc[i] = vo_honest.iloc[i]
        else:
            binary_ret.iloc[i] = sg_ret.iloc[i]

    binary_ret = apply_transition_costs(binary_ret, lagged_penta.astype(str), COST_BPS)

    # ── STRATEGY 2: Honest Graduated ──
    graduated_ret = pd.Series(0.0, index=idx)
    for i in range(len(idx)):
        r = lagged_regime.iloc[i]
        c = lagged_composite.iloc[i]

        if r == "FULL_ON":
            graduated_ret.iloc[i] = vo_honest.iloc[i]
        elif r == "MEDIUM":
            eq_w = 0.25 + (c - 0.50) / (0.85 - 0.50) * 0.50
            eq_w = max(0.20, min(0.80, eq_w))
            def_w = 1.0 - eq_w
            graduated_ret.iloc[i] = eq_w * vo_honest.iloc[i] + def_w * sg_ret.iloc[i]
        else:
            graduated_ret.iloc[i] = sg_ret.iloc[i]

    graduated_ret = apply_transition_costs(graduated_ret, lagged_regime, COST_BPS)

    # ── COLLECT STRATEGIES ──
    strategies = {
        "Honest Binary VOO/SGOV": binary_ret,
        "Honest Graduated": graduated_ret,
        "VOO Buy-Hold": vo_ret,
        "CRDBX Actual": cr_ret,
    }

    # ── COMPUTE METRICS ──
    L = []
    def p(s=""):
        L.append(s)
        print(s)

    p()
    p("=" * W)
    p("HONEST RESULTS vs NAIVE RESULTS")
    p("=" * W)

    NAIVE_BINARY_CAGR = 0.6656
    NAIVE_GRADUATED_CAGR = 0.5794
    NAIVE_BINARY_DD = 0.0259
    NAIVE_GRADUATED_DD = 0.0289

    days_span = (idx[-1] - idx[0]).days
    years = days_span / 365.25

    p(f"\n  {'Strategy':<30} {'CAGR':>8} {'MaxDD':>8} {'Calmar':>8} {'Sharpe':>8} {'Naive CAGR':>12} {'CAGR Drop':>10}")
    p("  " + "-" * (W - 4))

    all_metrics = {}
    for name, ret in strategies.items():
        cum = (1 + ret).cumprod()
        total = cum.iloc[-1] - 1
        cagr = ((1 + total) ** (1 / years) - 1)
        vol = ret.std() * np.sqrt(252)
        sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0
        peak = cum.cummax()
        dd = ((cum - peak) / peak).min()
        max_dd = abs(dd)
        calmar = cagr / max_dd if max_dd > 0 else 0

        all_metrics[name] = {"cagr": cagr, "max_dd": max_dd, "calmar": calmar,
                             "sharpe": sharpe, "vol": vol}

        naive_cagr_val = ""
        drop_val = ""
        if "Binary" in name:
            naive_cagr_val = f"{NAIVE_BINARY_CAGR:.2%}"
            drop_val = f"{(1 - cagr/NAIVE_BINARY_CAGR)*100:.0f}%"
        elif "Graduated" in name:
            naive_cagr_val = f"{NAIVE_GRADUATED_CAGR:.2%}"
            drop_val = f"{(1 - cagr/NAIVE_GRADUATED_CAGR)*100:.0f}%"

        p(f"  {name:<30} {cagr:>7.2%} {max_dd:>7.2%} {calmar:>8.2f} {sharpe:>8.3f} {naive_cagr_val:>12} {drop_val:>10}")

    # ── TRANSITION ANALYSIS ──
    p()
    p("=" * W)
    p("TRANSITION ANALYSIS")
    p("=" * W)

    penta_transitions = compute_transition_mask(lagged_penta.astype(str)).sum()
    regime_trans = compute_transition_mask(lagged_regime).sum()
    rt_per_year = penta_transitions / years / 2

    p(f"  Penta ON/OFF flips:      {penta_transitions}")
    p(f"  Regime transitions:      {regime_trans}")
    p(f"  Round-trips / year:      {rt_per_year:.0f}")
    p(f"  Cost per RT:             {COST_BPS:.0f} bps")
    p(f"  Annual drag from costs:  {rt_per_year * COST_BPS:.0f} bps ({rt_per_year * COST_BPS / 100:.2f}%)")

    # ── VALIDATION ──
    p()
    p("=" * W)
    p("VALIDATION PIPELINE")
    p("=" * W)

    binary_results = {
        "returns": binary_ret,
        "equity": (1 + binary_ret).cumprod(),
        "transitions": int(penta_transitions),
        "metrics": {"label": "Honest Binary", "cagr": all_metrics["Honest Binary VOO/SGOV"]["cagr"],
                    "years": years},
    }

    sp_off = sp_ret[lagged_penta == 0]

    flags = validate_strategy(
        binary_results,
        naive_cagr=NAIVE_BINARY_CAGR,
        benchmark_cagr=all_metrics["VOO Buy-Hold"]["cagr"],
        signal_returns_when_off=sp_off,
    )

    for flag in flags:
        severity = "PASS" if "passed" in flag.lower() else "WARN"
        p(f"  [{severity}] {flag}")

    # ── WORST DAYS COMPARISON ──
    p()
    p("=" * W)
    p("TOP 10 WORST S&P DAYS — honest strategy returns")
    p("=" * W)

    sp_worst = sp_ret.sort_values().head(10)
    p(f"  {'Date':<14} {'S&P':>8} {'Regime (lagged)':>18} {'Honest Binary':>15} {'Honest Grad':>13} {'CRDBX':>8}")
    p("  " + "-" * 80)

    for dt in sp_worst.index:
        sp_d = sp_ret.loc[dt] * 100
        r = lagged_regime.loc[dt] if dt in lagged_regime.index else "N/A"
        bin_d = binary_ret.loc[dt] * 100 if dt in binary_ret.index else 0
        grad_d = graduated_ret.loc[dt] * 100 if dt in graduated_ret.index else 0
        cr_d = cr_ret.loc[dt] * 100 if dt in cr_ret.index else 0
        p(f"  {str(dt.date()):<14} {sp_d:>+7.2f}% {r:>18} {bin_d:>+14.3f}% {grad_d:>+12.3f}% {cr_d:>+7.3f}%")

    p()
    p("=" * W)
    p("METHODOLOGY")
    p("-" * W)
    p(f"  Signal lag: T+{SIGNAL_LAG} (signal at close drives NEXT DAY allocation)")
    p(f"  Execution: Open price on transition days, close-to-close on hold days")
    p(f"  Costs: {COST_BPS:.0f}bps round-trip per regime transition")
    p(f"  Everything else identical to graduated_penta.py")
    p("=" * W)

    out = os.path.join(SCRIPT_DIR, "graduated_penta_honest_results.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nSaved to: {out}")


if __name__ == "__main__":
    main()
