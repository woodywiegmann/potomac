"""
4-Signal Composite Analytics: Local computation using yfinance
==============================================================
Computes the same 4 signals as the QC backtest, monthly from 2016-01 to 2026-02,
then reports:
  1. Trigger frequency (how often each signal says risk-on vs risk-off)
  2. Signal vs noise (correlation with next-month return, hit rate)
  3. Signal agreement / disagreement
  4. Marginal contribution (leave-one-out Calmar comparison)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

BREADTH_TICKERS = [
    "EWJ", "EWG", "EWU", "EWC", "EWA", "EWQ", "EWL", "EWP",
    "EWI", "EWD", "EWH", "EWS", "EWN", "EDEN", "EWK", "EWO",
    "EWT", "EWZ", "INDA", "FXI", "EWY", "EWW", "EWM", "ECH",
    "TUR", "THD", "EIDO", "EPHE", "KSA", "ARGT", "VNM",
]

ALL_TICKERS = list(set(BREADTH_TICKERS + ["ACWX", "BIL"]))
FLOOR = 0.25


def fetch_data():
    print("Fetching data for", len(ALL_TICKERS), "tickers...")
    raw = yf.download(ALL_TICKERS, start="2015-01-01", end="2026-03-01",
                      auto_adjust=True, progress=False)

    closes = pd.DataFrame()
    highs = pd.DataFrame()
    lows = pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        for t in ALL_TICKERS:
            try:
                closes[t] = raw["Close"][t]
            except KeyError:
                pass
            try:
                highs[t] = raw["High"][t]
            except KeyError:
                pass
            try:
                lows[t] = raw["Low"][t]
            except KeyError:
                pass
    else:
        closes = raw[["Close"]].rename(columns={"Close": ALL_TICKERS[0]})

    print(f"  Got {len(closes)} trading days, {len(closes.columns)} tickers")
    return closes, highs, lows


def compute_monthly_signals(closes, highs, lows):
    """Compute all 4 signals at each month-end."""
    acwx = closes["ACWX"].dropna()
    acwx_hi = highs.get("ACWX", acwx).dropna()
    acwx_lo = lows.get("ACWX", acwx).dropna()

    # Use actual last trading day of each month (not calendar month-end)
    monthly_acwx = acwx.groupby(acwx.index.to_period("M")).apply(lambda x: x.index[-1])
    month_ends = monthly_acwx.values
    month_ends = pd.DatetimeIndex([d for d in month_ends if d >= pd.Timestamp("2016-01-01") and d <= pd.Timestamp("2026-02-28")])

    records = []
    for dt in month_ends:
        mask = closes.index <= dt
        c_slice = closes[mask]
        h_slice = highs[mask] if not highs.empty else c_slice
        l_slice = lows[mask] if not lows.empty else c_slice

        if len(c_slice) < 200:
            continue

        # 1. ACWX 50/200 SMA crossover
        acwx_c = c_slice["ACWX"].dropna()
        if len(acwx_c) >= 200:
            sma50 = acwx_c.iloc[-50:].mean()
            sma200 = acwx_c.iloc[-200:].mean()
            sma_cross = 1.0 if sma50 > sma200 else 0.0
        else:
            sma_cross = 0.5

        # 2. Breadth: % of country ETFs above 200d SMA
        above, total = 0, 0
        for t in BREADTH_TICKERS:
            if t not in c_slice.columns:
                continue
            tc = c_slice[t].dropna()
            if len(tc) < 200:
                continue
            price = tc.iloc[-1]
            sma = tc.iloc[-200:].mean()
            if sma > 0:
                total += 1
                if price > sma:
                    above += 1
        breadth = (above / total) if total > 0 else 0.5

        # 3. RSI(5) on ACWX
        if len(acwx_c) >= 20:
            delta = acwx_c.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1.0 / 5, min_periods=5).mean()
            avg_loss = loss.ewm(alpha=1.0 / 5, min_periods=5).mean()
            rs = avg_gain / avg_loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi_val = rsi_series.iloc[-1]
            rsi5 = float(np.clip(rsi_val / 100.0, 0.0, 1.0)) if not np.isnan(rsi_val) else 0.5
        else:
            rsi5 = 0.5

        # 4. WMA/IWMA on ACWX mean price
        acwx_h = h_slice.get("ACWX", c_slice["ACWX"]).dropna() if "ACWX" in h_slice.columns else acwx_c
        acwx_l = l_slice.get("ACWX", c_slice["ACWX"]).dropna() if "ACWX" in l_slice.columns else acwx_c
        common_idx = acwx_h.index.intersection(acwx_l.index)
        if len(common_idx) >= 15:
            mean_p = (acwx_h.loc[common_idx] + acwx_l.loc[common_idx]) / 2
            period = 7
            w = np.arange(1, period + 1, dtype=float)
            iw = np.arange(period, 0, -1, dtype=float)
            last7 = mean_p.iloc[-period:].values
            if len(last7) == period:
                wma_val = np.dot(last7, w) / w.sum()
                iwma_val = np.dot(last7, iw) / iw.sum()
                wma_iwma = 1.0 if wma_val > iwma_val else 0.0
            else:
                wma_iwma = 0.5
        else:
            wma_iwma = 0.5

        composite = 0.25 * sma_cross + 0.25 * breadth + 0.25 * rsi5 + 0.25 * wma_iwma
        eq_wt = max(composite, FLOOR)

        # next month return on ACWX (for signal quality assessment)
        next_month = month_ends[month_ends > dt]
        if len(next_month) > 0:
            next_dt = next_month[0]
            future_c = closes["ACWX"].dropna()
            if next_dt in future_c.index and dt in future_c.index:
                next_ret = future_c.loc[next_dt] / future_c.loc[dt] - 1
            else:
                next_ret = np.nan
        else:
            next_ret = np.nan

        # BIL return for comparison
        if "BIL" in closes.columns and len(next_month) > 0:
            bil_c = closes["BIL"].dropna()
            next_dt = next_month[0]
            if next_dt in bil_c.index and dt in bil_c.index:
                bil_ret = bil_c.loc[next_dt] / bil_c.loc[dt] - 1
            else:
                bil_ret = 0.0
        else:
            bil_ret = 0.0

        records.append({
            "date": dt,
            "sma_cross": sma_cross,
            "breadth": breadth,
            "rsi5": rsi5,
            "wma_iwma": wma_iwma,
            "composite": composite,
            "eq_wt": eq_wt,
            "next_ret": next_ret,
            "bil_ret": bil_ret,
        })

    df = pd.DataFrame(records)
    return df


def print_trigger_frequency(df):
    signals = ["sma_cross", "breadth", "rsi5", "wma_iwma"]
    n = len(df)

    print(f"\n{'='*70}")
    print(f"  SIGNAL ANALYTICS  ({n} monthly observations)")
    print(f"{'='*70}")

    print(f"\n  1. TRIGGER FREQUENCY")
    print(f"  {'Signal':<14} {'Risk-On%':>10} {'Risk-Off%':>10} {'Mean':>8} {'StdDev':>8}")
    print(f"  {'-'*54}")
    for s in signals:
        vals = df[s].values
        mean_v = vals.mean()
        risk_on_pct = (vals > 0.5).sum() / n * 100
        risk_off_pct = 100 - risk_on_pct
        std = vals.std()
        print(f"  {s:<14} {risk_on_pct:>9.1f}% {risk_off_pct:>9.1f}% {mean_v:>8.3f} {std:>8.3f}")
    print(f"  {'-'*54}")
    comp_mean = df["composite"].mean()
    eq_mean = df["eq_wt"].mean()
    time_invested = (df["eq_wt"] >= 0.5).sum() / n * 100
    print(f"  {'composite':<14} {'':>10} {'':>10} {comp_mean:>8.3f}")
    print(f"  {'equity_wt':<14} {'':>10} {'':>10} {eq_mean:>8.3f}")
    print(f"\n  Time invested (eq_wt >= 50%): {time_invested:.1f}%")
    print(f"  Average equity weight: {eq_mean:.1%}")


def print_signal_quality(df):
    signals = ["sma_cross", "breadth", "rsi5", "wma_iwma"]
    valid = df.dropna(subset=["next_ret"])
    n = len(valid)

    print(f"\n  2. SIGNAL vs NOISE (predictive quality)")
    print(f"     Measured against next month's ACWX return ({n} months with forward data)")
    print(f"  {'Signal':<14} {'Corr w/ Ret':>12} {'Hit Rate':>10} {'Avg Ret ON':>12} {'Avg Ret OFF':>12} {'Spread':>8}")
    print(f"  {'-'*72}")

    for s in signals:
        vals = valid[s].values
        rets = valid["next_ret"].values

        corr = np.corrcoef(vals, rets)[0, 1] if len(vals) > 2 else 0

        on_mask = vals > 0.5
        off_mask = ~on_mask

        if on_mask.sum() > 0:
            on_rets = rets[on_mask]
            avg_on = on_rets.mean() * 100
            hit_on = (on_rets > 0).sum() / len(on_rets) * 100
        else:
            avg_on, hit_on = 0, 0

        if off_mask.sum() > 0:
            off_rets = rets[off_mask]
            avg_off = off_rets.mean() * 100
        else:
            avg_off = 0

        spread = avg_on - avg_off

        print(f"  {s:<14} {corr:>12.3f} {hit_on:>9.1f}% {avg_on:>11.2f}% {avg_off:>11.2f}% {spread:>7.2f}%")

    # Composite
    comp_vals = valid["composite"].values
    comp_corr = np.corrcoef(comp_vals, valid["next_ret"].values)[0, 1]
    comp_on = valid["next_ret"][valid["composite"] > 0.5].mean() * 100
    comp_off = valid["next_ret"][valid["composite"] <= 0.5].mean() * 100 if (valid["composite"] <= 0.5).any() else 0
    print(f"  {'-'*72}")
    print(f"  {'composite':<14} {comp_corr:>12.3f} {'':>10} {comp_on:>11.2f}% {comp_off:>11.2f}% {comp_on-comp_off:>7.2f}%")


def print_agreement(df):
    signals = ["sma_cross", "breadth", "rsi5", "wma_iwma"]
    n = len(df)

    print(f"\n  3. SIGNAL AGREEMENT")
    all_on = ((df[signals] > 0.5).all(axis=1)).sum()
    all_off = ((df[signals] <= 0.5).all(axis=1)).sum()
    mixed = n - all_on - all_off
    print(f"  All 4 risk-on:  {all_on:>4} months ({all_on/n*100:.1f}%)")
    print(f"  All 4 risk-off: {all_off:>4} months ({all_off/n*100:.1f}%)")
    print(f"  Mixed signals:  {mixed:>4} months ({mixed/n*100:.1f}%)")

    print(f"\n  Pairwise agreement rate:")
    print(f"  {'':14}", end="")
    for s in signals:
        print(f" {s[:8]:>8}", end="")
    print()
    for s1 in signals:
        v1 = (df[s1] > 0.5).values
        print(f"  {s1:<14}", end="")
        for s2 in signals:
            v2 = (df[s2] > 0.5).values
            agree = ((v1 & v2) | (~v1 & ~v2)).sum()
            print(f" {agree/n*100:>7.0f}%", end="")
        print()


def print_marginal_contribution(df):
    signals = ["sma_cross", "breadth", "rsi5", "wma_iwma"]
    valid = df.dropna(subset=["next_ret"]).copy()

    print(f"\n  4. MARGINAL CONTRIBUTION (Leave-One-Out)")
    print(f"     Simulated strategy return using composite * ACWX + (1-composite) * BIL")

    def compute_calmar(eq_weights, returns, bil_returns):
        port_rets = eq_weights * returns + (1 - eq_weights) * bil_returns
        cum = (1 + port_rets).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = abs(dd.min())
        n_years = len(port_rets) / 12
        total_ret = cum.iloc[-1] - 1
        cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
        calmar = cagr / max_dd if max_dd > 0 else 0
        return cagr * 100, max_dd * 100, calmar

    rets = valid["next_ret"].values
    bil_rets = valid["bil_ret"].values

    # Full composite
    full_eq = np.maximum(valid["composite"].values, FLOOR)
    full_cagr, full_dd, full_calmar = compute_calmar(
        pd.Series(full_eq), pd.Series(rets), pd.Series(bil_rets))

    print(f"\n  {'Config':<24} {'CAGR':>8} {'MaxDD':>8} {'Calmar':>8}")
    print(f"  {'-'*50}")
    print(f"  {'All 4 signals':<24} {full_cagr:>7.1f}% {full_dd:>7.1f}% {full_calmar:>8.2f}")

    for drop_sig in signals:
        remaining = [s for s in signals if s != drop_sig]
        comp_loo = valid[remaining].mean(axis=1)
        eq_loo = np.maximum(comp_loo.values, FLOOR)
        cagr, dd, calmar = compute_calmar(
            pd.Series(eq_loo), pd.Series(rets), pd.Series(bil_rets))
        delta = calmar - full_calmar
        label = f"Drop {drop_sig}"
        print(f"  {label:<24} {cagr:>7.1f}% {dd:>7.1f}% {calmar:>8.2f}  ({delta:>+.2f})")

    # Also: fully invested (no overlay)
    cagr_full, dd_full, calmar_full = compute_calmar(
        pd.Series(np.ones(len(rets))), pd.Series(rets), pd.Series(bil_rets))
    print(f"  {'No overlay (100% eq)':<24} {cagr_full:>7.1f}% {dd_full:>7.1f}% {calmar_full:>8.2f}")

    # Cash only
    cagr_cash, dd_cash, calmar_cash = compute_calmar(
        pd.Series(np.zeros(len(rets))), pd.Series(rets), pd.Series(bil_rets))
    print(f"  {'100% BIL':<24} {cagr_cash:>7.1f}% {dd_cash:>7.1f}% {calmar_cash:>8.2f}")


def main():
    closes, highs, lows = fetch_data()
    df = compute_monthly_signals(closes, highs, lows)
    print(f"\nComputed {len(df)} monthly signal snapshots")

    print_trigger_frequency(df)
    print_signal_quality(df)
    print_agreement(df)
    print_marginal_contribution(df)

    out_path = "C:\\Users\\WoodyWiegmann\\OneDrive - PFM\\Desktop\\Potomac\\signal_analytics_4sig.csv"
    df.to_csv(out_path, index=False)
    print(f"\n  Raw data saved to {out_path}")
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
