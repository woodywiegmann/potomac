"""
Breadth Signal Variant Comparison
=================================
Tests multiple breadth configurations within the 4-signal composite
to find the one that maximizes predictive value and Calmar ratio.

Variants tested:
  A. Current: 200d SMA, continuous 0-1
  B. 50d SMA, continuous 0-1
  C. 50d SMA, binary at 60%
  D. 50d SMA, binary at 70%
  E. 100d SMA, continuous 0-1
  F. 100d SMA, binary at 60%

Other 3 signals held constant: SMA crossover, RSI(5), WMA/IWMA.
"""

import numpy as np
import pandas as pd
import yfinance as yf
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
    print(f"  Got {len(closes)} days, {len(closes.columns)} tickers")
    return closes, highs, lows


def compute_breadth(c_slice, sma_period, threshold=None):
    """Compute breadth with given SMA period and optional binary threshold."""
    above, total = 0, 0
    for t in BREADTH_TICKERS:
        if t not in c_slice.columns:
            continue
        tc = c_slice[t].dropna()
        if len(tc) < sma_period:
            continue
        price = tc.iloc[-1]
        sma = tc.iloc[-sma_period:].mean()
        if sma > 0:
            total += 1
            if price > sma:
                above += 1
    if total == 0:
        return 0.5
    pct = above / total
    if threshold is not None:
        return 1.0 if pct >= threshold else 0.0
    return pct


def compute_other_signals(c_slice, h_slice, l_slice):
    """Compute the 3 non-breadth signals."""
    acwx_c = c_slice["ACWX"].dropna()

    # SMA crossover
    if len(acwx_c) >= 200:
        sma50 = acwx_c.iloc[-50:].mean()
        sma200 = acwx_c.iloc[-200:].mean()
        sma_cross = 1.0 if sma50 > sma200 else 0.0
    else:
        sma_cross = 0.5

    # RSI(5)
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

    # WMA/IWMA
    acwx_h = h_slice["ACWX"].dropna() if "ACWX" in h_slice.columns else acwx_c
    acwx_l = l_slice["ACWX"].dropna() if "ACWX" in l_slice.columns else acwx_c
    common = acwx_h.index.intersection(acwx_l.index)
    if len(common) >= 15:
        mean_p = (acwx_h.loc[common] + acwx_l.loc[common]) / 2
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

    return sma_cross, rsi5, wma_iwma


VARIANTS = {
    "A: 200d cont":     {"sma": 200, "threshold": None},
    "B: 50d cont":      {"sma": 50,  "threshold": None},
    "C: 50d bin@60%":   {"sma": 50,  "threshold": 0.60},
    "D: 50d bin@70%":   {"sma": 50,  "threshold": 0.70},
    "E: 100d cont":     {"sma": 100, "threshold": None},
    "F: 100d bin@60%":  {"sma": 100, "threshold": 0.60},
}


def run_analysis(closes, highs, lows):
    acwx = closes["ACWX"].dropna()
    monthly_acwx = acwx.groupby(acwx.index.to_period("M")).apply(lambda x: x.index[-1])
    month_ends = pd.DatetimeIndex([d for d in monthly_acwx.values
                                   if d >= pd.Timestamp("2016-01-01")
                                   and d <= pd.Timestamp("2026-02-28")])

    all_records = {name: [] for name in VARIANTS}

    for dt in month_ends:
        mask = closes.index <= dt
        c_slice = closes[mask]
        h_slice = highs[mask] if not highs.empty else c_slice
        l_slice = lows[mask] if not lows.empty else c_slice

        if len(c_slice) < 200:
            continue

        sma_cross, rsi5, wma_iwma = compute_other_signals(c_slice, h_slice, l_slice)

        # Next month ACWX return
        next_months = month_ends[month_ends > dt]
        if len(next_months) > 0:
            next_dt = next_months[0]
            ac = closes["ACWX"].dropna()
            next_ret = (ac.loc[next_dt] / ac.loc[dt] - 1) if (next_dt in ac.index and dt in ac.index) else np.nan
        else:
            next_ret = np.nan

        # BIL return
        if "BIL" in closes.columns and len(next_months) > 0:
            bil = closes["BIL"].dropna()
            next_dt = next_months[0]
            bil_ret = (bil.loc[next_dt] / bil.loc[dt] - 1) if (next_dt in bil.index and dt in bil.index) else 0.0
        else:
            bil_ret = 0.0

        for name, cfg in VARIANTS.items():
            b = compute_breadth(c_slice, cfg["sma"], cfg["threshold"])
            composite = 0.25 * sma_cross + 0.25 * b + 0.25 * rsi5 + 0.25 * wma_iwma
            eq_wt = max(composite, FLOOR)
            all_records[name].append({
                "date": dt,
                "breadth": b,
                "sma_cross": sma_cross,
                "rsi5": rsi5,
                "wma_iwma": wma_iwma,
                "composite": composite,
                "eq_wt": eq_wt,
                "next_ret": next_ret,
                "bil_ret": bil_ret,
            })

    return {name: pd.DataFrame(recs) for name, recs in all_records.items()}


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


def report(all_dfs):
    print(f"\n{'='*80}")
    print(f"  BREADTH VARIANT COMPARISON (4-signal composite, equal weight)")
    print(f"{'='*80}")

    # Header
    print(f"\n  {'Variant':<18} {'Risk-On%':>9} {'Mean':>6} {'Corr':>6} {'Spread':>8} "
          f"{'CAGR':>7} {'MaxDD':>7} {'Calmar':>7} {'Agr w/SMA':>9} {'TimeInv':>8}")
    print(f"  {'-'*90}")

    for name, df in all_dfs.items():
        n = len(df)
        valid = df.dropna(subset=["next_ret"])
        nv = len(valid)

        # Trigger frequency
        risk_on_pct = (df["breadth"] > 0.5).sum() / n * 100
        mean_b = df["breadth"].mean()

        # Predictive quality
        if nv > 5:
            corr = np.corrcoef(valid["breadth"].values, valid["next_ret"].values)[0, 1]
            on_mask = valid["breadth"] > 0.5
            avg_on = valid.loc[on_mask, "next_ret"].mean() * 100 if on_mask.sum() > 0 else 0
            avg_off = valid.loc[~on_mask, "next_ret"].mean() * 100 if (~on_mask).sum() > 0 else 0
            spread = avg_on - avg_off
        else:
            corr, spread = 0, 0

        # Calmar (full composite)
        eq = np.maximum(valid["composite"].values, FLOOR)
        cagr, maxdd, calmar = compute_calmar(
            pd.Series(eq), pd.Series(valid["next_ret"].values), pd.Series(valid["bil_ret"].values))

        # Agreement with SMA crossover
        agree = ((df["breadth"] > 0.5) == (df["sma_cross"] > 0.5)).sum() / n * 100

        # Time invested
        time_inv = (df["eq_wt"] >= 0.5).sum() / n * 100

        print(f"  {name:<18} {risk_on_pct:>8.1f}% {mean_b:>6.3f} {corr:>6.3f} {spread:>7.2f}% "
              f"{cagr:>6.1f}% {maxdd:>6.1f}% {calmar:>7.2f} {agree:>8.0f}% {time_inv:>7.1f}%")

    # Also show: drop breadth entirely (3-signal)
    print(f"  {'-'*90}")
    ref_df = list(all_dfs.values())[0]
    valid = ref_df.dropna(subset=["next_ret"])
    comp_no_b = (valid["sma_cross"] + valid["rsi5"] + valid["wma_iwma"]) / 3
    eq_no_b = np.maximum(comp_no_b.values, FLOOR)
    cagr_nb, maxdd_nb, calmar_nb = compute_calmar(
        pd.Series(eq_no_b), pd.Series(valid["next_ret"].values), pd.Series(valid["bil_ret"].values))
    print(f"  {'No breadth (3sig)':<18} {'n/a':>9} {'n/a':>6} {'n/a':>6} {'n/a':>8} "
          f"{cagr_nb:>6.1f}% {maxdd_nb:>6.1f}% {calmar_nb:>7.2f} {'n/a':>9} {'n/a':>8}")

    # 100% equity
    eq_full = np.ones(len(valid))
    cagr_f, maxdd_f, calmar_f = compute_calmar(
        pd.Series(eq_full), pd.Series(valid["next_ret"].values), pd.Series(valid["bil_ret"].values))
    print(f"  {'100% equity':18} {'':>9} {'':>6} {'':>6} {'':>8} "
          f"{cagr_f:>6.1f}% {maxdd_f:>6.1f}% {calmar_f:>7.2f}")

    print()

    # Detailed: best variant's breadth distribution
    print(f"\n  --- Detailed Signal Comparison ---")
    print(f"\n  Monthly breadth values (mean / p25 / p50 / p75):")
    for name, df in all_dfs.items():
        b = df["breadth"]
        print(f"    {name:<18}  mean={b.mean():.3f}  p25={b.quantile(0.25):.3f}  "
              f"p50={b.quantile(0.5):.3f}  p75={b.quantile(0.75):.3f}")

    # Leave-one-out for each variant: what happens to Calmar when you drop breadth
    print(f"\n  --- Marginal Calmar Contribution of Each Breadth Variant ---")
    print(f"  {'Variant':<18} {'4sig Calmar':>12} {'3sig (no B)':>12} {'Delta':>8}")
    print(f"  {'-'*54}")
    for name, df in all_dfs.items():
        valid = df.dropna(subset=["next_ret"])
        eq_4 = np.maximum(valid["composite"].values, FLOOR)
        _, _, cal4 = compute_calmar(
            pd.Series(eq_4), pd.Series(valid["next_ret"].values), pd.Series(valid["bil_ret"].values))
        comp3 = (valid["sma_cross"] + valid["rsi5"] + valid["wma_iwma"]) / 3
        eq_3 = np.maximum(comp3.values, FLOOR)
        _, _, cal3 = compute_calmar(
            pd.Series(eq_3), pd.Series(valid["next_ret"].values), pd.Series(valid["bil_ret"].values))
        delta = cal4 - cal3
        marker = " <-- best" if delta > 0 else ""
        print(f"  {name:<18} {cal4:>12.3f} {cal3:>12.3f} {delta:>+7.3f}{marker}")

    print(f"\n{'='*80}")


def main():
    closes, highs, lows = fetch_data()
    all_dfs = run_analysis(closes, highs, lows)
    report(all_dfs)

    out = "C:\\Users\\WoodyWiegmann\\OneDrive - PFM\\Desktop\\Potomac\\breadth_variant_results.csv"
    combined = []
    for name, df in all_dfs.items():
        df_copy = df.copy()
        df_copy["variant"] = name
        combined.append(df_copy)
    pd.concat(combined).to_csv(out, index=False)
    print(f"  Raw data saved to {out}")


if __name__ == "__main__":
    main()
