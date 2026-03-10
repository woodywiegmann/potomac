"""
Regression of risk-off bucket: Strategy Return = alpha + beta * S&P 500 Return
over verified risk-off days (CRDBX flat, SPY moved). Matches the scatter and
table in "Trade Concepts for Testing" (Feb 2026).
"""

import os
import warnings
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


def ols_beta_r2(x, y):
    """OLS: y = alpha + beta * x. Returns (beta, r_squared)."""
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 3:
        return np.nan, np.nan
    x_mean, y_mean = x.mean(), y.mean()
    cov = np.cov(x, y)[0, 1]
    var_x = np.var(x, ddof=1)
    if var_x <= 0:
        return 0.0, 0.0
    beta = cov / var_x
    alpha = y_mean - beta * x_mean
    ss_tot = np.sum((y - y_mean) ** 2)
    y_hat = alpha + beta * x
    ss_res = np.sum((y - y_hat) ** 2)
    r_sq = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    return beta, r_sq


def max_drawdown(daily_ret):
    """Max drawdown from daily returns (decimal). Returns percentage."""
    cum = np.cumprod(1.0 + np.asarray(daily_ret, dtype=float))
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / np.where(peak > 0, peak, 1)
    return dd.max() * 100


def upside_downside_capture(strat_ret, bench_ret):
    """
    Upside capture: (compound strat return on bench-up days) / (compound bench return on those days) * 100.
    Downside capture: (compound strat return on bench-down days) / (compound bench return on those days) * 100.
    bench_ret, strat_ret are 1d arrays (same length). Returns (upside_pct, downside_pct).
    """
    bench_ret = np.asarray(bench_ret, dtype=float)
    strat_ret = np.asarray(strat_ret, dtype=float)
    up = bench_ret > 0
    down = bench_ret < 0
    upside_pct = np.nan
    if up.sum() > 0:
        bench_up = (1 + bench_ret[up]).prod() - 1
        strat_up = (1 + strat_ret[up]).prod() - 1
        if abs(bench_up) > 1e-12:
            upside_pct = (strat_up / bench_up) * 100
    downside_pct = np.nan
    if down.sum() > 0:
        bench_down = (1 + bench_ret[down]).prod() - 1  # negative
        strat_down = (1 + strat_ret[down]).prod() - 1
        if abs(bench_down) > 1e-12:
            downside_pct = (strat_down / bench_down) * 100
    return upside_pct, downside_pct


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

    # Risk-off: CRDBX flat, SPY moved, exclude distribution window
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
        regime.iloc[i] = "AMBIGUOUS"

    off = regime == "OFF"
    n_off = off.sum()
    sp_off = sp[off].values
    sp_off_pct = sp_off * 100

    # Calendar span for annualizing geometric return (risk-off days only)
    off_dates = idx[off]
    years_span = (off_dates.max() - off_dates.min()).days / 365.25
    if years_span < 0.01:
        years_span = 1.0

    # Strategy returns on risk-off days (same definitions as h2h / memo)
    strategies = {
        "SGOV (current)": sg[off].values,
        "50/50 SGOV/CAOS": (0.50 * sg[off] + 0.50 * ca[off]).values,
        "EqWt 3-Way (CAOS/DBMF/SGOV)": ((dm[off] + ca[off] + sg[off]) / 3).values,
        "15H/15D/70S (HEQT/DBMF/SGOV)": (0.15 * hq[off] + 0.15 * dm[off] + 0.70 * sg[off]).values,
        "CAOS": ca[off].values,
    }

    # Per-strategy: geometric ann return, max DD, upside/downside capture vs S&P, beta, R²
    results = []
    for name, y_raw in strategies.items():
        y = y_raw
        beta, r2 = ols_beta_r2(sp_off, y)
        geo_total = (1 + y).prod() - 1
        geo_ann = ((1 + geo_total) ** (1 / years_span) - 1) * 100
        mdd = max_drawdown(y)
        up_cap, down_cap = upside_downside_capture(y, sp_off)
        results.append({
            "Strategy": name,
            "Geo Ann %": geo_ann,
            "Max DD %": mdd,
            "Upside Capture %": up_cap,
            "Downside Capture %": down_cap,
            "Beta (to S&P)": beta,
            "R²": r2,
        })

    # Console and file output
    df = pd.DataFrame(results)
    W = 100
    print()
    print("=" * W)
    print("RISK-OFF BUCKET — Performance & Regression vs S&P 500")
    print("=" * W)
    print(f"Sample: {n_off} risk-off days (Mar 2023 – Feb 2026). Capture ratios relative to S&P on same days.")
    print()
    print(df.to_string(index=False, float_format=lambda x: f"{x:.4f}" if abs(x) < 10 else f"{x:.2f}"))
    print("=" * W)

    out_path = os.path.join(SCRIPT_DIR, "riskoff_regression_results.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("RISK-OFF BUCKET — Performance & Regression vs S&P 500\n")
        f.write("Regression: Strategy Return = Alpha + Beta × S&P 500 Daily Return (Beta and R² reported).\n")
        f.write(f"Sample: {n_off} risk-off days (Mar 2023 – Feb 2026). Capture vs S&P on risk-off days only.\n\n")
        f.write(df.to_string(index=False, float_format=lambda x: f"{x:.4f}" if abs(x) < 10 else f"{x:.2f}"))
    print(f"\nResults saved to: {out_path}")

    # Optional: scatter chart with regression lines (like Trade Concepts image)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 5))
        colors = {"SGOV (current)": "#888888", "50/50 SGOV/CAOS": "#7dcea0",
                  "EqWt 3-Way (CAOS/DBMF/SGOV)": "#1a5276", "15H/15D/70S (HEQT/DBMF/SGOV)": "#5d6d7e",
                  "CAOS": "#c0392b"}
        for name, y_raw in strategies.items():
            y_pct = y_raw * 100
            ax.scatter(sp_off_pct, y_pct, s=10, alpha=0.4, color=colors.get(name, "#333"), label=name)
            beta, _ = ols_beta_r2(sp_off, y_raw)
            alpha = float(np.nanmean(y_raw) - beta * np.nanmean(sp_off))
            x_line = np.linspace(sp_off_pct.min(), sp_off_pct.max(), 50)
            y_line = (alpha + beta * x_line / 100) * 100
            ax.plot(x_line, y_line, color=colors.get(name, "#333"), linewidth=1.2, linestyle="-")
        ax.axhline(0, color="#ccc", linewidth=0.5)
        ax.axvline(0, color="#ccc", linewidth=0.5)
        ax.set_xlabel("S&P 500 Daily Return (%)")
        ax.set_ylabel("Strategy Return (%)")
        ax.set_title("Risk-Off Day Returns vs S&P — Regression Lines")
        ax.legend(loc="upper right", fontsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        chart_path = os.path.join(SCRIPT_DIR, "riskoff_regression_chart.png")
        fig.tight_layout()
        fig.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Chart saved to: {chart_path}")
    except ImportError:
        print("(Install matplotlib to generate riskoff_regression_chart.png)")


if __name__ == "__main__":
    main()
