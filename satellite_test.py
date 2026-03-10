"""
POTOMAC BULL BEAR SATELLITE OPTIMIZER
=====================================
Tests different compositions and rebalancing methods for the 20% satellite
sleeve of Bull Bear, using CRDBX (corrected total return) as the fixed 80% core.

Actual CRDBX stats (from Potomac dashboard, as of 2026-01-31):
  CAGR: 17.53% | MDD: -24.69% | Beta: 0.70 | Corr: 0.55
  Sharpe: 0.23 | Sortino: 0.45 | StdDev: 19.21

Satellite candidates: CRMVX, CRTBX, CRTOX, ARB, DBMF, CAOS, HEQT, GLD, SPLV
Rebalancing methods: Equal-weight, Hoffstein staggered, Arnott overrebalancing,
                     inverse-vol (risk parity), momentum-tilted
"""

import yfinance as yf
import pandas as pd
import numpy as np
import math
import os
import warnings
warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
START = "2020-08-01"
END = "2026-02-01"
CORE_WEIGHT = 0.80
SAT_WEIGHT = 0.20
REBAL_FREQ = "ME"  # month-end
RF_ANNUAL = 0.03

# ─── DATA ────────────────────────────────────────────────────────────────────

def get_total_return_series(ticker: str, start: str, end: str) -> pd.Series:
    """Build a total-return index that correctly reinvests distributions."""
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end, auto_adjust=False)
    if h.empty:
        return pd.Series(dtype=float)
    h.index = h.index.tz_localize(None)
    nav = h["Close"]
    divs = h["Dividends"] if "Dividends" in h.columns else pd.Series(0.0, index=h.index)
    shares = 1.0
    vals = []
    for dt in h.index:
        d = divs.loc[dt] if dt in divs.index else 0.0
        p = nav.loc[dt]
        if d > 0 and p > 0:
            shares *= (1 + d / p)
        vals.append(shares * p)
    return pd.Series(vals, index=h.index, name=ticker)


def fetch_all(tickers: list, start: str, end: str) -> dict:
    """Fetch total-return series for all tickers."""
    data = {}
    for tk in tickers:
        print(f"  {tk}...", end=" ")
        s = get_total_return_series(tk, start, end)
        if len(s) > 0:
            data[tk] = s
            print(f"{s.index[0].date()} to {s.index[-1].date()} ({len(s)} days)")
        else:
            print("NO DATA")
    return data


# ─── METRICS ─────────────────────────────────────────────────────────────────

def compute_metrics(prices: pd.Series, sp_ret: pd.Series) -> dict:
    dr = prices.pct_change().dropna()
    if len(dr) < 10:
        return None
    yrs = (prices.index[-1] - prices.index[0]).days / 365.25
    cagr = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / yrs) - 1) * 100
    cummax = prices.cummax()
    dd = ((prices - cummax) / cummax)
    max_dd = dd.min() * 100
    dd_end = dd.idxmin()
    dd_start = prices[:dd_end].idxmax() if dd_end > prices.index[0] else prices.index[0]
    ann_vol = dr.std() * math.sqrt(252) * 100
    sharpe = (dr.mean() - RF_ANNUAL / 252) / dr.std() * math.sqrt(252) if dr.std() > 0 else 0
    down = dr[dr < 0]
    sortino = (dr.mean() - RF_ANNUAL / 252) / down.std() * math.sqrt(252) if len(down) > 0 and down.std() > 0 else 0
    calmar = abs(cagr / max_dd) if max_dd != 0 else 0
    sp_aligned = sp_ret.reindex(dr.index, method="ffill").fillna(0)
    try:
        cv = np.cov(dr, sp_aligned)
        beta = cv[0, 1] / cv[1, 1] if cv[1, 1] > 0 else 0
        corr = np.corrcoef(dr, sp_aligned)[0, 1]
    except:
        beta, corr = 0, 0
    yr = prices.resample("YE").last().pct_change().dropna() * 100
    return {
        "cagr": cagr, "max_dd": max_dd, "dd_period": f"{dd_start.strftime('%m/%Y')}-{dd_end.strftime('%m/%Y')}",
        "ann_vol": ann_vol, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "beta": beta, "corr": corr,
        "best_yr": yr.max() if len(yr) > 0 else 0,
        "worst_yr": yr.min() if len(yr) > 0 else 0,
        "yearly": yr,
        "growth": prices.iloc[-1] / prices.iloc[0] * 10000,
    }


# ─── REBALANCING METHODS ────────────────────────────────────────────────────

def equal_weight_rebal(sat_returns: pd.DataFrame, rebal_dates: pd.DatetimeIndex) -> pd.Series:
    """Standard equal-weight with monthly rebalancing."""
    n = sat_returns.shape[1]
    weights = np.ones(n) / n
    port_ret = pd.Series(0.0, index=sat_returns.index)
    last_rebal = sat_returns.index[0]
    current_w = weights.copy()

    for i, dt in enumerate(sat_returns.index):
        if dt in rebal_dates or i == 0:
            current_w = weights.copy()
        day_ret = sat_returns.loc[dt].values
        port_ret.loc[dt] = np.dot(current_w, day_ret)
        current_w = current_w * (1 + day_ret)
        s = current_w.sum()
        if s > 0:
            current_w = current_w / s
    return port_ret


def hoffstein_staggered(sat_returns: pd.DataFrame, rebal_dates: pd.DatetimeIndex,
                        n_tranches: int = 4) -> pd.Series:
    """Hoffstein rebalance timing luck mitigation: N overlapping sub-portfolios
    each rebalanced on a different week of the month."""
    n_assets = sat_returns.shape[1]
    target_w = np.ones(n_assets) / n_assets
    tranche_weights = [target_w.copy() for _ in range(n_tranches)]
    tranche_rebal_offset = [i * 5 for i in range(n_tranches)]  # offset by ~1 week each
    port_ret = pd.Series(0.0, index=sat_returns.index)

    for i, dt in enumerate(sat_returns.index):
        for t in range(n_tranches):
            if i > 0 and (i - tranche_rebal_offset[t]) % 21 == 0:
                tranche_weights[t] = target_w.copy()

        day_ret = sat_returns.loc[dt].values
        tranche_rets = [np.dot(tranche_weights[t], day_ret) for t in range(n_tranches)]
        port_ret.loc[dt] = np.mean(tranche_rets)

        for t in range(n_tranches):
            tranche_weights[t] = tranche_weights[t] * (1 + day_ret)
            s = tranche_weights[t].sum()
            if s > 0:
                tranche_weights[t] = tranche_weights[t] / s
    return port_ret


def arnott_overrebalance(sat_returns: pd.DataFrame, rebal_dates: pd.DatetimeIndex,
                         lookback: int = 63, tilt: float = 0.03) -> pd.Series:
    """Arnott smart/over-rebalancing: at each rebalance, overweight the
    recent underperformer by 'tilt' and underweight the outperformer."""
    n = sat_returns.shape[1]
    base_w = np.ones(n) / n
    current_w = base_w.copy()
    port_ret = pd.Series(0.0, index=sat_returns.index)
    cum_ret = (1 + sat_returns).cumprod()

    for i, dt in enumerate(sat_returns.index):
        if dt in rebal_dates and i > lookback:
            past = cum_ret.iloc[i - lookback:i]
            period_ret = (past.iloc[-1] / past.iloc[0] - 1).values
            rank = np.argsort(np.argsort(period_ret))
            adj = (n / 2.0 - rank - 0.5) * tilt / (n / 2.0)
            new_w = base_w + adj
            new_w = np.maximum(new_w, 0.02)
            new_w = new_w / new_w.sum()
            current_w = new_w

        day_ret = sat_returns.loc[dt].values
        port_ret.loc[dt] = np.dot(current_w, day_ret)
        current_w = current_w * (1 + day_ret)
        s = current_w.sum()
        if s > 0:
            current_w = current_w / s
    return port_ret


def invvol_rebal(sat_returns: pd.DataFrame, rebal_dates: pd.DatetimeIndex,
                 lookback: int = 63) -> pd.Series:
    """Inverse-volatility (risk-parity lite): weight by 1/vol."""
    n = sat_returns.shape[1]
    current_w = np.ones(n) / n
    port_ret = pd.Series(0.0, index=sat_returns.index)

    for i, dt in enumerate(sat_returns.index):
        if dt in rebal_dates and i > lookback:
            window = sat_returns.iloc[i - lookback:i]
            vols = window.std().values
            vols = np.where(vols < 1e-8, 1e-8, vols)
            inv = 1.0 / vols
            current_w = inv / inv.sum()

        day_ret = sat_returns.loc[dt].values
        port_ret.loc[dt] = np.dot(current_w, day_ret)
        current_w = current_w * (1 + day_ret)
        s = current_w.sum()
        if s > 0:
            current_w = current_w / s
    return port_ret


def momentum_tilt(sat_returns: pd.DataFrame, rebal_dates: pd.DatetimeIndex,
                  lookback: int = 126, tilt: float = 0.05) -> pd.Series:
    """Momentum-tilted: overweight the recent best performer."""
    n = sat_returns.shape[1]
    base_w = np.ones(n) / n
    current_w = base_w.copy()
    port_ret = pd.Series(0.0, index=sat_returns.index)
    cum_ret = (1 + sat_returns).cumprod()

    for i, dt in enumerate(sat_returns.index):
        if dt in rebal_dates and i > lookback:
            past = cum_ret.iloc[i - lookback:i]
            period_ret = (past.iloc[-1] / past.iloc[0] - 1).values
            rank = np.argsort(np.argsort(period_ret))
            adj = (rank - n / 2.0 + 0.5) * tilt / (n / 2.0)
            new_w = base_w + adj
            new_w = np.maximum(new_w, 0.02)
            new_w = new_w / new_w.sum()
            current_w = new_w

        day_ret = sat_returns.loc[dt].values
        port_ret.loc[dt] = np.dot(current_w, day_ret)
        current_w = current_w * (1 + day_ret)
        s = current_w.sum()
        if s > 0:
            current_w = current_w / s
    return port_ret


# ─── PORTFOLIO CONSTRUCTION ─────────────────────────────────────────────────

def build_portfolio(core_ret: pd.Series, sat_ret: pd.Series,
                    core_w: float = CORE_WEIGHT, sat_w: float = SAT_WEIGHT) -> pd.Series:
    """Combine core and satellite daily returns into a total portfolio return series."""
    idx = core_ret.index.intersection(sat_ret.index)
    port_ret = core_w * core_ret.reindex(idx) + sat_w * sat_ret.reindex(idx)
    port_prices = (1 + port_ret).cumprod()
    port_prices.iloc[0] = 1.0 + port_ret.iloc[0]
    return port_prices * 10000 / port_prices.iloc[0] * (1 + port_ret.iloc[0])


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 100)
    print("POTOMAC BULL BEAR SATELLITE OPTIMIZER")
    print(f"Period: {START} to {END}")
    print("Core: 80% CRDBX (actual total return, distributions reinvested)")
    print("Satellite: 20% -- testing compositions and rebalancing methods")
    print("=" * 100)

    # Fetch data
    all_tickers = ["CRDBX", "CRMVX", "CRTBX", "CRTOX",
                   "ARB", "DBMF", "HEQT",
                   "GLD", "SPLV", "SPY", "SHY"]
    print("\nFetching total-return series (distributions reinvested)...")
    raw = fetch_all(all_tickers, "2020-01-01", END)

    # Common date index from START
    core_prices = raw["CRDBX"]
    core_prices = core_prices[core_prices.index >= START]
    idx = core_prices.index
    core_ret = core_prices.pct_change().fillna(0)

    sp_ret = raw["SPY"].pct_change().fillna(0)

    # Build satellite return DataFrames for each ticker
    sat_daily = {}
    for tk in ["CRMVX", "CRTBX", "CRTOX", "ARB", "DBMF", "HEQT", "GLD", "SPLV"]:
        if tk in raw:
            s = raw[tk].reindex(idx, method="ffill")
            sat_daily[tk] = s.pct_change().fillna(0)

    rebal_dates = idx.to_series().resample(REBAL_FREQ).last().values
    rebal_idx = pd.DatetimeIndex([d for d in rebal_dates if d in idx])

    # ── SATELLITE COMPOSITIONS ──
    compositions = {
        "Current (CRMVX+CRTBX+CRTOX)": ["CRMVX", "CRTBX", "CRTOX"],
        "DBMF+GLD+SPLV": ["DBMF", "GLD", "SPLV"],
        "ARB+DBMF+GLD": ["ARB", "DBMF", "GLD"],
        "ARB+DBMF+SPLV": ["ARB", "DBMF", "SPLV"],
        "ARB+GLD+SPLV": ["ARB", "GLD", "SPLV"],
        "ARB+DBMF+GLD+SPLV": ["ARB", "DBMF", "GLD", "SPLV"],
        "DBMF+GLD": ["DBMF", "GLD"],
        "ARB+DBMF": ["ARB", "DBMF"],
        "ARB only (20%)": ["ARB"],
        "DBMF only (20%)": ["DBMF"],
        "GLD only (20%)": ["GLD"],
    }

    # Add HEQT combos (shorter history, from Nov 2021)
    heqt_compositions = {
        "HEQT+DBMF+ARB": ["HEQT", "DBMF", "ARB"],
        "HEQT+ARB+GLD": ["HEQT", "ARB", "GLD"],
        "HEQT+DBMF": ["HEQT", "DBMF"],
        "HEQT only (20%)": ["HEQT"],
    }

    rebal_methods = {
        "EqWt": equal_weight_rebal,
        "Hoffstein": hoffstein_staggered,
        "Arnott": arnott_overrebalance,
        "InvVol": invvol_rebal,
        "Momentum": momentum_tilt,
    }

    # ── RUN ALL COMBINATIONS ──
    print("\nRunning portfolio combinations...")
    results = []

    for comp_name, tickers in {**compositions, **heqt_compositions}.items():
        available = [tk for tk in tickers if tk in sat_daily]
        if len(available) != len(tickers):
            continue

        sat_df = pd.DataFrame({tk: sat_daily[tk] for tk in available}).dropna()

        if comp_name in heqt_compositions:
            common_start = sat_df.index[0]
            local_core_ret = core_ret[core_ret.index >= common_start]
            local_idx = local_core_ret.index.intersection(sat_df.index)
            local_rebal = pd.DatetimeIndex([d for d in rebal_idx if d in local_idx])
            sat_df = sat_df.reindex(local_idx).fillna(0)
            note = f" [from {common_start.strftime('%Y-%m')}]"
        else:
            local_core_ret = core_ret
            local_idx = idx.intersection(sat_df.index)
            local_rebal = rebal_idx
            sat_df = sat_df.reindex(local_idx).fillna(0)
            note = ""

        for method_name, method_fn in rebal_methods.items():
            if len(available) == 1:
                sat_ret_series = sat_df.iloc[:, 0]
            else:
                sat_ret_series = method_fn(sat_df, local_rebal)

            port_ret = CORE_WEIGHT * local_core_ret.reindex(sat_ret_series.index).fillna(0) + \
                       SAT_WEIGHT * sat_ret_series
            port_prices = (1 + port_ret).cumprod() * 10000
            if len(port_prices) < 60:
                continue

            m = compute_metrics(port_prices, sp_ret)
            if m:
                label = f"{comp_name} | {method_name}{note}"
                m["label"] = label
                m["composition"] = comp_name
                m["method"] = method_name
                m["prices"] = port_prices
                results.append(m)

    # Also add standalone benchmarks
    for tk in ["CRDBX", "SPY"]:
        if tk in raw:
            p = raw[tk][raw[tk].index >= START]
            m = compute_metrics(p, sp_ret)
            if m:
                m["label"] = f"{tk} STANDALONE"
                m["composition"] = tk
                m["method"] = "buy-hold"
                m["prices"] = p / p.iloc[0] * 10000
                results.append(m)

    # Current Bull Bear (80% CRDBX + 20% equal CRMVX/CRTBX/CRTOX)
    # already in results as "Current (CRMVX+CRTBX+CRTOX) | EqWt"

    # ── SORT AND DISPLAY ──
    print(f"\nTotal combinations tested: {len(results)}")

    # Sort by CAGR
    results.sort(key=lambda x: x["cagr"], reverse=True)

    # Full table
    print("\n" + "=" * 140)
    print(f"{'Portfolio':<52} {'CAGR':>6} {'MaxDD':>7} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} "
          f"{'Beta':>6} {'Corr':>6} {'Vol':>6} {'BestYr':>7} {'WrstYr':>7} {'$10K':>8}")
    print("-" * 140)

    # Print actual CRDBX from dashboard first
    print(f"{'>>> CRDBX ACTUAL (Potomac dashboard) <<<':<52} {'17.53':>6}% {'-24.69':>6}% "
          f"{'0.23':>7} {'0.45':>8} {'0.71':>7} {'0.70':>6} {'0.55':>6} {'19.21':>6} "
          f"{'--':>7} {'--':>7} {'--':>8}")
    print("-" * 140)

    for r in results:
        label = r["label"][:51]
        print(f"{label:<52} {r['cagr']:>5.1f}% {r['max_dd']:>6.1f}% "
              f"{r['sharpe']:>7.2f} {r['sortino']:>8.2f} {r['calmar']:>7.2f} "
              f"{r['beta']:>6.2f} {r['corr']:>6.2f} {r['ann_vol']:>5.1f}% "
              f"{r['best_yr']:>6.1f}% {r['worst_yr']:>6.1f}% "
              f"${r['growth']:>7,.0f}")

    # ── TOP 4 PORTFOLIOS ──
    # Exclude standalone benchmarks from "top 4"
    portfolio_results = [r for r in results if r["method"] != "buy-hold"]

    # Rank by a composite score: high CAGR, low drawdown, high Sharpe
    for r in portfolio_results:
        r["score"] = r["cagr"] * 0.4 + (-r["max_dd"]) * 0.3 + r["sharpe"] * 10 * 0.3

    portfolio_results.sort(key=lambda x: x["score"], reverse=True)
    top4 = portfolio_results[:4]

    print("\n" + "=" * 140)
    print("TOP 4 PORTFOLIOS (ranked by composite: 40% CAGR + 30% drawdown protection + 30% Sharpe)")
    print("=" * 140)

    for rank, r in enumerate(top4, 1):
        print(f"\n  #{rank}: {r['label']}")
        print(f"      CAGR: {r['cagr']:.2f}%  |  Max DD: {r['max_dd']:.2f}%  |  Sharpe: {r['sharpe']:.2f}  |  "
              f"Sortino: {r['sortino']:.2f}  |  Calmar: {r['calmar']:.2f}")
        print(f"      Beta: {r['beta']:.2f}  |  Corr: {r['corr']:.2f}  |  Vol: {r['ann_vol']:.1f}%  |  "
              f"Growth of $10K: ${r['growth']:,.0f}")
        print(f"      DD period: {r['dd_period']}  |  Best year: {r['best_yr']:.1f}%  |  Worst year: {r['worst_yr']:.1f}%")

    print(f"\n  BENCHMARK: CRDBX ACTUAL (Potomac dashboard, inception 08/01/20 to 01/31/26)")
    print(f"      CAGR: 17.53%  |  Max DD: -24.69%  |  Sharpe: 0.23  |  "
          f"Sortino: 0.45  |  Calmar: 0.71")
    print(f"      Beta: 0.70  |  Corr: 0.55  |  Vol: 19.21%")

    # ── YEAR-BY-YEAR for top 4 vs CRDBX ──
    print("\n" + "=" * 140)
    print("YEAR-BY-YEAR: TOP 4 vs CRDBX ACTUAL")
    print("=" * 140)

    # CRDBX actual annual returns (verified from Morningstar)
    crdbx_actual_yr = {2020: 9.83, 2021: 28.23, 2022: -8.54, 2023: 19.14, 2024: 19.82, 2025: 17.90}

    header = f"{'Year':<6} {'CRDBX Actual':>13}"
    for rank, r in enumerate(top4, 1):
        short = r['composition'][:18]
        method = r['method'][:8]
        header += f" {'#'+str(rank)+' '+short:>22}"
    print(header)
    print("-" * (6 + 14 + 23 * 4))

    all_years = set()
    for r in top4:
        if "yearly" in r:
            all_years.update(r["yearly"].index.year)
    all_years = sorted(all_years)

    for yr in all_years:
        actual = crdbx_actual_yr.get(yr, None)
        act_str = f"{actual:+.1f}%" if actual is not None else "--"
        line = f"{yr:<6} {act_str:>13}"
        for r in top4:
            if "yearly" in r:
                ydf = r["yearly"]
                match = ydf[ydf.index.year == yr]
                if len(match) > 0:
                    line += f" {match.iloc[0]:>21.1f}%"
                else:
                    line += f" {'--':>22}"
            else:
                line += f" {'--':>22}"
        print(line)

    # ── INDIVIDUAL SATELLITE COMPONENT STATS ──
    print("\n" + "=" * 100)
    print("INDIVIDUAL SATELLITE COMPONENT ANALYSIS (total return, distributions reinvested)")
    print("=" * 100)
    print(f"{'Ticker':<8} {'CAGR':>7} {'MaxDD':>7} {'Sharpe':>7} {'Beta':>6} {'Corr':>6} {'Vol':>6} "
          f"{'2021':>7} {'2022':>7} {'2023':>7} {'2024':>7} {'2025':>7}")
    print("-" * 100)

    for tk in ["CRMVX", "CRTBX", "CRTOX", "ARB", "DBMF", "HEQT", "GLD", "SPLV"]:
        if tk not in raw:
            continue
        p = raw[tk]
        p = p[p.index >= START]
        if len(p) < 60:
            p_full = raw[tk]
            p = p_full[p_full.index >= p_full.index[0]]
        m = compute_metrics(p, sp_ret)
        if not m:
            continue
        yr = m.get("yearly", pd.Series())
        yr_vals = {}
        for y in [2021, 2022, 2023, 2024, 2025]:
            match = yr[yr.index.year == y]
            yr_vals[y] = f"{match.iloc[0]:+.1f}%" if len(match) > 0 else "--"

        print(f"{tk:<8} {m['cagr']:>6.1f}% {m['max_dd']:>6.1f}% {m['sharpe']:>7.2f} "
              f"{m['beta']:>6.2f} {m['corr']:>6.2f} {m['ann_vol']:>5.1f}% "
              f"{yr_vals[2021]:>7} {yr_vals[2022]:>7} {yr_vals[2023]:>7} "
              f"{yr_vals[2024]:>7} {yr_vals[2025]:>7}")

    # ── SAVE ──
    out_path = os.path.join(SCRIPT_DIR, "satellite_results.txt")
    # Re-run print to file
    import io, sys
    old_stdout = sys.stdout
    sys.stdout = buf = io.StringIO()

    print("=" * 140)
    print("POTOMAC BULL BEAR SATELLITE OPTIMIZER -- RESULTS")
    print(f"Period: {START} to {END}")
    print("Core: 80% CRDBX (total return, distributions reinvested)")
    print("Satellite: 20% -- tested compositions x rebalancing methods")
    print("=" * 140)

    print(f"\n{'Portfolio':<52} {'CAGR':>6} {'MaxDD':>7} {'Sharpe':>7} {'Sortino':>8} {'Calmar':>7} "
          f"{'Beta':>6} {'Corr':>6} {'Vol':>6} {'BestYr':>7} {'WrstYr':>7} {'$10K':>8}")
    print("-" * 140)
    print(f"{'>>> CRDBX ACTUAL (Potomac dashboard) <<<':<52} {'17.53':>6}% {'-24.69':>6}% "
          f"{'0.23':>7} {'0.45':>8} {'0.71':>7} {'0.70':>6} {'0.55':>6} {'19.21':>6} "
          f"{'--':>7} {'--':>7} {'--':>8}")
    print("-" * 140)
    for r_item in results:
        label = r_item["label"][:51]
        print(f"{label:<52} {r_item['cagr']:>5.1f}% {r_item['max_dd']:>6.1f}% "
              f"{r_item['sharpe']:>7.2f} {r_item['sortino']:>8.2f} {r_item['calmar']:>7.2f} "
              f"{r_item['beta']:>6.2f} {r_item['corr']:>6.2f} {r_item['ann_vol']:>5.1f}% "
              f"{r_item['best_yr']:>6.1f}% {r_item['worst_yr']:>6.1f}% "
              f"${r_item['growth']:>7,.0f}")

    print("\n" + "=" * 140)
    print("TOP 4 PORTFOLIOS")
    print("=" * 140)
    for rank, r in enumerate(top4, 1):
        print(f"\n  #{rank}: {r['label']}")
        print(f"      CAGR: {r['cagr']:.2f}%  |  Max DD: {r['max_dd']:.2f}%  |  Sharpe: {r['sharpe']:.2f}  |  "
              f"Sortino: {r['sortino']:.2f}  |  Calmar: {r['calmar']:.2f}")
        print(f"      Beta: {r['beta']:.2f}  |  Corr: {r['corr']:.2f}  |  Vol: {r['ann_vol']:.1f}%  |  "
              f"Growth of $10K: ${r['growth']:,.0f}")
        print(f"      DD period: {r['dd_period']}  |  Best year: {r['best_yr']:.1f}%  |  Worst year: {r['worst_yr']:.1f}%")

    print(f"\n  BENCHMARK: CRDBX ACTUAL (Potomac, 08/01/20 - 01/31/26)")
    print(f"      CAGR: 17.53%  |  Max DD: -24.69%  |  Sharpe: 0.23  |  Sortino: 0.45  |  Calmar: 0.71")
    print(f"      Beta: 0.70  |  Corr: 0.55  |  Vol: 19.21%")

    print("\n" + "=" * 140)
    print("YEAR-BY-YEAR: TOP 4 vs CRDBX ACTUAL")
    print("=" * 140)
    print(header)
    print("-" * (6 + 14 + 23 * 4))
    for yr in all_years:
        actual = crdbx_actual_yr.get(yr, None)
        act_str = f"{actual:+.1f}%" if actual is not None else "--"
        line = f"{yr:<6} {act_str:>13}"
        for r in top4:
            ydf = r.get("yearly", pd.Series())
            match = ydf[ydf.index.year == yr]
            if len(match) > 0:
                line += f" {match.iloc[0]:>21.1f}%"
            else:
                line += f" {'--':>22}"
        print(line)

    print("\n" + "=" * 100)
    print("INDIVIDUAL SATELLITE COMPONENTS")
    print("=" * 100)
    print(f"{'Ticker':<8} {'CAGR':>7} {'MaxDD':>7} {'Sharpe':>7} {'Beta':>6} {'Corr':>6} {'Vol':>6} "
          f"{'2021':>7} {'2022':>7} {'2023':>7} {'2024':>7} {'2025':>7}")
    print("-" * 100)
    for tk in ["CRMVX", "CRTBX", "CRTOX", "ARB", "DBMF", "HEQT", "GLD", "SPLV"]:
        if tk not in raw:
            continue
        p = raw[tk]
        p = p[p.index >= START]
        if len(p) < 60:
            continue
        m = compute_metrics(p, sp_ret)
        if not m:
            continue
        yr_s = m.get("yearly", pd.Series())
        yr_vals = {}
        for y in [2021, 2022, 2023, 2024, 2025]:
            match = yr_s[yr_s.index.year == y]
            yr_vals[y] = f"{match.iloc[0]:+.1f}%" if len(match) > 0 else "--"
        print(f"{tk:<8} {m['cagr']:>6.1f}% {m['max_dd']:>6.1f}% {m['sharpe']:>7.2f} "
              f"{m['beta']:>6.2f} {m['corr']:>6.2f} {m['ann_vol']:>5.1f}% "
              f"{yr_vals[2021]:>7} {yr_vals[2022]:>7} {yr_vals[2023]:>7} "
              f"{yr_vals[2024]:>7} {yr_vals[2025]:>7}")

    sys.stdout = old_stdout
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
