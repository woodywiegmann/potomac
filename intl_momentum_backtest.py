"""
International Dual Momentum Backtest
=====================================
Adapted from Gary Antonacci's GEM framework for single-country ETF rotation.

Universe: 16 liquid international single-country ETFs (iShares MSCI)
Signal:   12-month total return (relative momentum for ranking,
          absolute momentum vs T-bills for go-to-cash)
Holding:  Top 7 countries, equal-weight (~14.3% each)
Cash:     SGOV / BIL when absolute momentum fails
Rebal:    Monthly (last trading day)

Go-to-cash trigger options:
  A. Classic:    individual ETF 12m return < BIL 12m return
  B. Dual:       individual ETF negative on BOTH 12m AND 6m
  C. Composite:  average of 1m, 3m, 6m, 12m returns < 0
  D. Aggregate:  EFA 12m return < BIL 12m return (regime filter)
  E. Breadth:    >50% of universe 12m returns < BIL (majority rules)

Usage:
    python intl_momentum_backtest.py
    python intl_momentum_backtest.py --top 5
    python intl_momentum_backtest.py --trigger C --start 2005-01-01
    python intl_momentum_backtest.py --top 3 --trigger A --lookback 6
"""

import argparse
import csv
import datetime
import math
import os
import sys
from dataclasses import dataclass, field

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    print("Required: pip install yfinance pandas numpy")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════════════════════════════
# ETF UNIVERSE
# ═══════════════════════════════════════════════════════════════════════════════

COUNTRY_ETFS = {
    # Developed Markets
    "EWJ":  "Japan",
    "EWG":  "Germany",
    "EWU":  "United Kingdom",
    "EWC":  "Canada",
    "EWA":  "Australia",
    "EWQ":  "France",
    "EWL":  "Switzerland",
    "EWP":  "Spain",
    "EWI":  "Italy",
    # Emerging Markets
    "EWT":  "Taiwan",
    "EWZ":  "Brazil",
    "INDA": "India",
    "FXI":  "China",
    "EWY":  "South Korea",
    "EWW":  "Mexico",
    "EWH":  "Hong Kong",
}

CASH_TICKER = "BIL"
BROAD_INTL_TICKER = "EFA"
BENCHMARKS_DEFAULT = ["EFA", "ACWX", "SPY"]


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_data(start: str, end: str) -> dict:
    """Fetch adjusted close prices for all country ETFs, cash, and benchmarks."""
    warmup_days = 400
    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    all_tickers = list(COUNTRY_ETFS.keys()) + [CASH_TICKER, BROAD_INTL_TICKER] + BENCHMARKS_DEFAULT
    all_tickers = list(set(all_tickers))

    print(f"Fetching {len(all_tickers)} tickers from {fetch_start} to {end}...")
    raw = yf.download(all_tickers, start=fetch_start, end=end, progress=False, auto_adjust=True)

    data = {}
    for ticker in all_tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                col = raw["Close"][ticker].dropna()
            else:
                col = raw["Close"].dropna()
            if len(col) > 0:
                data[ticker] = col
                print(f"  {ticker:>6}: {col.index[0].date()} to {col.index[-1].date()} ({len(col)} days)")
            else:
                print(f"  {ticker:>6}: NO DATA")
        except (KeyError, TypeError):
            print(f"  {ticker:>6}: FAILED")

    return data


def build_total_return_index(prices: pd.Series) -> pd.Series:
    """Convert price series to a total return index starting at 1.0."""
    return prices / prices.iloc[0]


# ═══════════════════════════════════════════════════════════════════════════════
# MOMENTUM CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def trailing_return(prices: pd.Series, months: int, as_of: pd.Timestamp) -> float:
    """Calculate trailing N-month total return as of a given date."""
    lookback_date = as_of - pd.DateOffset(months=months)
    mask = prices.index <= as_of
    recent = prices[mask]
    if len(recent) == 0:
        return np.nan

    mask_old = prices.index <= lookback_date
    old = prices[mask_old]
    if len(old) == 0:
        return np.nan

    return recent.iloc[-1] / old.iloc[-1] - 1


def get_month_end_dates(index: pd.DatetimeIndex, start: str) -> list:
    """Get the last trading day of each month within the date range."""
    mask = index >= pd.Timestamp(start)
    filtered = index[mask]
    month_ends = filtered.to_series().groupby([filtered.year, filtered.month]).last()
    return [pd.Timestamp(d) for d in month_ends.values]


# ═══════════════════════════════════════════════════════════════════════════════
# ABSOLUTE MOMENTUM TRIGGERS
# ═══════════════════════════════════════════════════════════════════════════════

def trigger_classic(etf_prices, cash_prices, as_of, lookback_months=12, **kw):
    """Option A: ETF 12m return > BIL 12m return."""
    etf_ret = trailing_return(etf_prices, lookback_months, as_of)
    cash_ret = trailing_return(cash_prices, lookback_months, as_of)
    if np.isnan(etf_ret) or np.isnan(cash_ret):
        return False
    return etf_ret > cash_ret


def trigger_dual(etf_prices, cash_prices, as_of, **kw):
    """Option B: ETF must be positive on BOTH 12m AND 6m basis."""
    ret_12 = trailing_return(etf_prices, 12, as_of)
    ret_6 = trailing_return(etf_prices, 6, as_of)
    if np.isnan(ret_12) or np.isnan(ret_6):
        return False
    return ret_12 > 0 and ret_6 > 0


def trigger_composite(etf_prices, cash_prices, as_of, **kw):
    """Option C: Average of 1m, 3m, 6m, 12m returns > 0."""
    rets = [trailing_return(etf_prices, m, as_of) for m in [1, 3, 6, 12]]
    valid = [r for r in rets if not np.isnan(r)]
    if len(valid) == 0:
        return False
    return np.mean(valid) > 0


def trigger_aggregate(etf_prices, cash_prices, as_of, lookback_months=12, broad_prices=None, **kw):
    """Option D: Broad international (EFA) 12m return > BIL 12m return."""
    if broad_prices is None:
        return trigger_classic(etf_prices, cash_prices, as_of, lookback_months)
    broad_ret = trailing_return(broad_prices, lookback_months, as_of)
    cash_ret = trailing_return(cash_prices, lookback_months, as_of)
    if np.isnan(broad_ret) or np.isnan(cash_ret):
        return False
    return broad_ret > cash_ret


def trigger_breadth(etf_prices, cash_prices, as_of, lookback_months=12, all_etf_prices=None, **kw):
    """Option E: >50% of universe must have 12m return > BIL to stay invested."""
    if all_etf_prices is None:
        return trigger_classic(etf_prices, cash_prices, as_of, lookback_months)
    cash_ret = trailing_return(cash_prices, lookback_months, as_of)
    if np.isnan(cash_ret):
        return False
    above_count = 0
    total = 0
    for ticker, prices in all_etf_prices.items():
        ret = trailing_return(prices, lookback_months, as_of)
        if not np.isnan(ret):
            total += 1
            if ret > cash_ret:
                above_count += 1
    if total == 0:
        return False
    return above_count / total > 0.5


TRIGGERS = {
    "A": ("Classic (ETF 12m > BIL 12m)", trigger_classic),
    "B": ("Dual (12m > 0 AND 6m > 0)", trigger_dual),
    "C": ("Composite (avg 1/3/6/12m > 0)", trigger_composite),
    "D": ("Aggregate (EFA 12m > BIL 12m)", trigger_aggregate),
    "E": ("Breadth (>50% universe > BIL)", trigger_breadth),
}


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MonthlySnapshot:
    date: str
    holdings: dict          # ticker -> weight
    cash_pct: float
    top7_tickers: list
    top7_returns: list
    cash_return: float
    abs_mom_pass: dict      # ticker -> bool

@dataclass
class StrategyResult:
    name: str
    equity_curve: pd.Series
    monthly_snapshots: list = field(default_factory=list)
    cagr: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    volatility: float = 0.0
    win_months: float = 0.0
    pct_invested: float = 0.0
    avg_countries: float = 0.0
    turnover_annual: float = 0.0
    best_year: float = 0.0
    worst_year: float = 0.0


def run_backtest(data: dict, start: str, end: str, top_n: int = 7,
                 lookback_months: int = 12, trigger_key: str = "A") -> StrategyResult:
    """
    Run the international dual momentum backtest.
    """
    trigger_name, trigger_fn = TRIGGERS[trigger_key]
    name = f"Top {top_n} EW | Trigger {trigger_key}: {trigger_name} | {lookback_months}m lookback"

    cash_prices = data.get(CASH_TICKER)
    broad_prices = data.get(BROAD_INTL_TICKER)

    common_idx = None
    for ticker in COUNTRY_ETFS:
        if ticker in data:
            if common_idx is None:
                common_idx = data[ticker].index
            else:
                common_idx = common_idx.union(data[ticker].index)

    if cash_prices is not None:
        common_idx = common_idx.union(cash_prices.index)

    common_idx = common_idx.sort_values()
    month_ends = get_month_end_dates(common_idx, start)

    if len(month_ends) < 2:
        print("ERROR: Not enough month-end dates for backtest.")
        return StrategyResult(name=name, equity_curve=pd.Series(dtype=float))

    all_etf_prices = {t: data[t] for t in COUNTRY_ETFS if t in data}

    equity_curve = pd.Series(dtype=float)
    equity_curve[month_ends[0]] = 10000.0

    prev_holdings = {}
    snapshots = []
    total_turnover = 0.0

    for i in range(1, len(month_ends)):
        rebal_date = pd.Timestamp(month_ends[i - 1])
        eval_date = pd.Timestamp(month_ends[i])

        # Rank countries by trailing return
        returns = {}
        for ticker in COUNTRY_ETFS:
            if ticker not in data:
                continue
            ret = trailing_return(data[ticker], lookback_months, rebal_date)
            if not np.isnan(ret):
                returns[ticker] = ret

        if len(returns) == 0:
            equity_curve[eval_date] = equity_curve.iloc[-1]
            continue

        ranked = sorted(returns.items(), key=lambda x: x[1], reverse=True)
        top_tickers = [t for t, r in ranked[:top_n]]
        top_returns_at_rebal = {t: r for t, r in ranked[:top_n]}

        cash_ret_12m = trailing_return(cash_prices, lookback_months, rebal_date) if cash_prices is not None else 0.0
        if np.isnan(cash_ret_12m):
            cash_ret_12m = 0.0

        # Apply absolute momentum filter to each selected country
        abs_mom_pass = {}
        for ticker in top_tickers:
            trigger_kwargs = {
                "lookback_months": lookback_months,
                "broad_prices": broad_prices,
                "all_etf_prices": all_etf_prices,
            }
            passes = trigger_fn(data[ticker], cash_prices, rebal_date, **trigger_kwargs)
            abs_mom_pass[ticker] = passes

        invest_tickers = [t for t in top_tickers if abs_mom_pass.get(t, False)]
        weight_per_slot = 1.0 / top_n

        holdings = {}
        for t in invest_tickers:
            holdings[t] = weight_per_slot
        cash_weight = 1.0 - sum(holdings.values())

        # Calculate turnover
        all_tickers_in_play = set(list(prev_holdings.keys()) + list(holdings.keys()))
        turn = sum(abs(holdings.get(t, 0) - prev_holdings.get(t, 0)) for t in all_tickers_in_play)
        total_turnover += turn

        # Calculate period return (rebal_date to eval_date)
        period_return = 0.0
        for ticker, weight in holdings.items():
            prices = data[ticker]
            p_start = prices[prices.index <= rebal_date]
            p_end = prices[prices.index <= eval_date]
            if len(p_start) > 0 and len(p_end) > 0:
                ret = p_end.iloc[-1] / p_start.iloc[-1] - 1
                period_return += weight * ret

        # Cash return
        if cash_weight > 0 and cash_prices is not None:
            p_start = cash_prices[cash_prices.index <= rebal_date]
            p_end = cash_prices[cash_prices.index <= eval_date]
            if len(p_start) > 0 and len(p_end) > 0:
                cash_period_ret = p_end.iloc[-1] / p_start.iloc[-1] - 1
                period_return += cash_weight * cash_period_ret

        equity_curve[eval_date] = equity_curve.iloc[-1] * (1 + period_return)

        snapshots.append(MonthlySnapshot(
            date=str(rebal_date.date()),
            holdings=holdings.copy(),
            cash_pct=cash_weight * 100,
            top7_tickers=top_tickers,
            top7_returns=[returns.get(t, 0) for t in top_tickers],
            cash_return=cash_ret_12m,
            abs_mom_pass=abs_mom_pass.copy(),
        ))

        prev_holdings = holdings.copy()

    n_months = len(month_ends) - 1
    n_years = n_months / 12.0

    result = StrategyResult(
        name=name,
        equity_curve=equity_curve,
        monthly_snapshots=snapshots,
        turnover_annual=total_turnover / n_years if n_years > 0 else 0,
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_metrics(r: StrategyResult):
    eq = r.equity_curve.dropna()
    if len(eq) < 2:
        return
    days = (eq.index[-1] - eq.index[0]).days
    yrs = days / 365.25
    r.total_return = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    r.cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0

    # Drawdown
    running_max = eq.cummax()
    dd_series = (eq - running_max) / running_max
    r.max_drawdown = dd_series.min() * 100

    # Monthly returns
    monthly_ret = eq.pct_change().dropna()
    r.volatility = monthly_ret.std() * math.sqrt(12) * 100

    if monthly_ret.std() > 0:
        annual_rf = 0.03
        monthly_rf = annual_rf / 12
        excess = monthly_ret - monthly_rf
        r.sharpe = excess.mean() / monthly_ret.std() * math.sqrt(12)
        downside = monthly_ret[monthly_ret < 0]
        if len(downside) > 0 and downside.std() > 0:
            r.sortino = excess.mean() / downside.std() * math.sqrt(12)

    r.calmar = abs(r.cagr / r.max_drawdown) if r.max_drawdown != 0 else 0
    r.win_months = (monthly_ret > 0).sum() / len(monthly_ret) * 100

    if r.monthly_snapshots:
        invested_counts = [top_n_minus_cash(s) for s in r.monthly_snapshots]
        r.avg_countries = np.mean(invested_counts)
        r.pct_invested = np.mean([1 - s.cash_pct / 100 for s in r.monthly_snapshots]) * 100

    yr = eq.resample("YE").last().pct_change().dropna() * 100
    if len(yr) > 0:
        r.best_year = yr.max()
        r.worst_year = yr.min()


def top_n_minus_cash(snapshot: MonthlySnapshot) -> int:
    return len(snapshot.holdings)


def annual_returns(eq: pd.Series) -> dict:
    eq = eq.dropna()
    if len(eq) < 2:
        return {}
    yr = eq.resample("YE").last()
    out = {}
    for i in range(1, len(yr)):
        out[yr.index[i].year] = (yr.iloc[i] / yr.iloc[i - 1] - 1) * 100
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# BENCHMARK
# ═══════════════════════════════════════════════════════════════════════════════

def compute_benchmark(prices: pd.Series, month_ends: list) -> dict:
    """Compute metrics for a buy-and-hold benchmark using month-end prices."""
    eq = prices.reindex(month_ends, method="ffill").dropna()
    if len(eq) < 2:
        return {}
    eq = eq / eq.iloc[0] * 10000

    days = (eq.index[-1] - eq.index[0]).days
    yrs = days / 365.25
    total = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    mr = eq.pct_change().dropna()
    vol = mr.std() * math.sqrt(12) * 100
    sh = 0
    if mr.std() > 0:
        sh = (mr.mean() - 0.03 / 12) / mr.std() * math.sqrt(12)
    cal = abs(cagr / dd) if dd != 0 else 0
    yr = eq.resample("YE").last().pct_change().dropna() * 100

    return {
        "equity": eq,
        "cagr": cagr, "total": total, "max_dd": dd, "sharpe": sh,
        "calmar": cal, "vol": vol,
        "best_year": yr.max() if len(yr) > 0 else 0,
        "worst_year": yr.min() if len(yr) > 0 else 0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def report(strategies: list, benchmarks: dict, start: str, end: str):
    L = []

    def p(t=""):
        L.append(t)
        print(t)

    W = 130
    p("=" * W)
    p("INTERNATIONAL DUAL MOMENTUM BACKTEST")
    p(f"Period: {start} to {end}")
    p(f"Universe: {len(COUNTRY_ETFS)} single-country ETFs (iShares MSCI)")
    p(f"Methodology: Gary Antonacci Dual Momentum (relative + absolute)")
    p("=" * W)

    p(f"\nCountry universe:")
    for ticker, country in COUNTRY_ETFS.items():
        p(f"  {ticker:>6}  {country}")

    # Performance table
    p(f"\n{'Strategy':<60} {'CAGR':>6} {'Total':>8} {'MaxDD':>7} {'Sharpe':>7} {'Sortino':>8} "
      f"{'Calmar':>7} {'Vol':>6} {'Win%':>5} {'AvgN':>5} {'Inv%':>5} {'Turn':>6} {'BstYr':>7} {'WstYr':>7}")
    p("-" * W)

    for s in strategies:
        p(f"{s.name[:60]:<60} {s.cagr:>5.1f}% {s.total_return:>7.0f}% {s.max_drawdown:>6.1f}% "
          f"{s.sharpe:>7.2f} {s.sortino:>8.2f} {s.calmar:>7.2f} {s.volatility:>5.1f}% "
          f"{s.win_months:>4.0f}% {s.avg_countries:>5.1f} {s.pct_invested:>4.0f}% "
          f"{s.turnover_annual:>5.0f}% {s.best_year:>6.1f}% {s.worst_year:>6.1f}%")

    p("-" * W)
    for tk, bm in benchmarks.items():
        if bm:
            p(f"{tk + ' (buy-hold)':<60} {bm['cagr']:>5.1f}% {bm['total']:>7.0f}% {bm['max_dd']:>6.1f}% "
              f"{bm['sharpe']:>7.2f} {'--':>8} {bm['calmar']:>7.2f} {bm['vol']:>5.1f}% "
              f"{'--':>5} {'--':>5} {'100':>4}% {'--':>6} {bm['best_year']:>6.1f}% {bm['worst_year']:>6.1f}%")

    # Growth of $10K
    p(f"\n{'':=<{W}}")
    p("GROWTH OF $10,000")
    p(f"{'':=<{W}}")
    for s in strategies:
        eq = s.equity_curve.dropna()
        if len(eq) > 0:
            p(f"  {s.name[:60]:<60} ${eq.iloc[-1]:>12,.0f}")
    for tk, bm in benchmarks.items():
        if bm and "equity" in bm:
            eq = bm["equity"]
            p(f"  {tk + ' (buy-hold)':<60} ${eq.iloc[-1]:>12,.0f}")

    # Year-by-year
    p(f"\n{'':=<{W}}")
    p("YEAR-BY-YEAR RETURNS")
    p(f"{'':=<{W}}")

    s_ann = {s.name[:25]: annual_returns(s.equity_curve) for s in strategies}
    bm_ann = {}
    for tk, bm in benchmarks.items():
        if bm and "equity" in bm:
            bm_ann[tk] = annual_returns(bm["equity"])

    all_yrs = set()
    for d in list(s_ann.values()) + list(bm_ann.values()):
        all_yrs.update(d.keys())

    labels = [s.name[:25] for s in strategies]
    hdr = f"{'Year':<6}"
    for lb in labels:
        hdr += f" {lb:>25}"
    for tk in benchmarks:
        hdr += f" {tk:>10}"
    p(hdr)
    p("-" * len(hdr))

    for y in sorted(all_yrs):
        row = f"{y:<6}"
        for s in strategies:
            v = s_ann.get(s.name[:25], {}).get(y)
            row += f" {v:>24.1f}%" if v is not None else f" {'--':>25}"
        for tk in benchmarks:
            v = bm_ann.get(tk, {}).get(y)
            row += f" {v:>9.1f}%" if v is not None else f" {'--':>10}"
        p(row)

    # Monthly holdings detail (last 12 months)
    p(f"\n{'':=<{W}}")
    p("RECENT HOLDINGS (LAST 12 MONTHS)")
    p(f"{'':=<{W}}")

    if strategies and strategies[0].monthly_snapshots:
        recent = strategies[0].monthly_snapshots[-12:]
        for snap in recent:
            invested = [t for t, w in snap.holdings.items()]
            failed = [t for t in snap.top7_tickers if t not in invested]
            p(f"\n  {snap.date}:")
            p(f"    Top 7:    {', '.join(snap.top7_tickers)}")
            p(f"    Invested: {', '.join(invested) if invested else 'NONE (100% cash)'}")
            if failed:
                p(f"    Failed absolute momentum: {', '.join(failed)} -> SGOV")
            p(f"    Cash %:   {snap.cash_pct:.1f}%")

    # Trigger comparison if multiple strategies
    if len(strategies) > 1:
        p(f"\n{'':=<{W}}")
        p("TRIGGER COMPARISON SUMMARY")
        p(f"{'':=<{W}}")
        p(f"  {'Trigger':<50} {'CAGR':>7} {'MaxDD':>8} {'Sharpe':>8} {'Avg Countries':>15} {'% Invested':>12}")
        p(f"  {'-'*100}")
        for s in strategies:
            p(f"  {s.name[:50]:<50} {s.cagr:>6.1f}% {s.max_drawdown:>7.1f}% "
              f"{s.sharpe:>8.2f} {s.avg_countries:>15.1f} {s.pct_invested:>11.0f}%")

    p(f"\n{'':=<{W}}")

    path = os.path.join(SCRIPT_DIR, "intl_momentum_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nReport saved to: {path}")

    return L


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="International Dual Momentum Backtest")
    parser.add_argument("--top", type=int, default=7,
                        help="Number of top countries to hold (default: 7)")
    parser.add_argument("--lookback", type=int, default=12,
                        help="Lookback period in months (default: 12)")
    parser.add_argument("--trigger", default="ALL",
                        help="Absolute momentum trigger: A/B/C/D/E or ALL (default: ALL)")
    parser.add_argument("--start", default="2004-01-01",
                        help="Start date (default: 2004-01-01)")
    parser.add_argument("--end", default=None, help="End date (default: today)")
    args = parser.parse_args()
    end = args.end or datetime.date.today().isoformat()

    data = fetch_data(args.start, end)

    available = [t for t in COUNTRY_ETFS if t in data]
    print(f"\n{len(available)}/{len(COUNTRY_ETFS)} country ETFs available")
    if CASH_TICKER not in data:
        print(f"WARNING: {CASH_TICKER} not available. Absolute momentum filter may not work correctly.")

    # Determine month-end dates
    common_idx = None
    for ticker in available:
        if common_idx is None:
            common_idx = data[ticker].index
        else:
            common_idx = common_idx.union(data[ticker].index)
    common_idx = common_idx.sort_values()
    month_ends = get_month_end_dates(common_idx, args.start)
    print(f"Backtest period: {month_ends[0].date() if month_ends else 'N/A'} to "
          f"{month_ends[-1].date() if month_ends else 'N/A'} ({len(month_ends)} months)")

    # Run strategies
    print("\nRunning backtests...")
    strategies = []

    if args.trigger == "ALL":
        trigger_keys = ["A", "B", "C", "D", "E"]
    else:
        trigger_keys = [args.trigger.upper()]

    for tk in trigger_keys:
        if tk not in TRIGGERS:
            print(f"Unknown trigger: {tk}")
            continue
        print(f"  Running trigger {tk}: {TRIGGERS[tk][0]}...")
        s = run_backtest(data, args.start, end, top_n=args.top,
                         lookback_months=args.lookback, trigger_key=tk)
        compute_metrics(s)
        strategies.append(s)
        print(f"    CAGR: {s.cagr:.1f}%  MaxDD: {s.max_drawdown:.1f}%  "
              f"Sharpe: {s.sharpe:.2f}  Avg Countries: {s.avg_countries:.1f}")

    # Benchmarks
    print("\nComputing benchmarks...")
    bm_results = {}
    for bm_ticker in BENCHMARKS_DEFAULT:
        if bm_ticker in data:
            bm = compute_benchmark(data[bm_ticker], month_ends)
            if bm:
                bm_results[bm_ticker] = bm
                print(f"  {bm_ticker}: CAGR {bm['cagr']:.1f}%  MaxDD {bm['max_dd']:.1f}%")

    # Report
    print()
    report(strategies, bm_results, args.start, end)

    # Save equity curves CSV
    df = pd.DataFrame()
    for s in strategies:
        col_name = f"Trigger_{s.name.split('Trigger ')[1][0]}" if "Trigger" in s.name else s.name[:30]
        df[col_name] = s.equity_curve
    for tk, bm in bm_results.items():
        if "equity" in bm:
            df[f"{tk}_buyhold"] = bm["equity"]
    df.index.name = "Date"
    eq_path = os.path.join(SCRIPT_DIR, "intl_momentum_equity.csv")
    df.to_csv(eq_path, float_format="%.2f")
    print(f"Equity curves saved to: {eq_path}")

    # Save monthly holdings CSV
    if strategies:
        snap_path = os.path.join(SCRIPT_DIR, "intl_momentum_holdings.csv")
        with open(snap_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Strategy", "Date", "Ticker", "Country", "Weight%",
                         "12m_Return%", "AbsMom_Pass", "Cash%"])
            for s in strategies:
                trig = s.name.split("Trigger ")[1][0] if "Trigger" in s.name else "?"
                for snap in s.monthly_snapshots:
                    for ticker in snap.top7_tickers:
                        weight = snap.holdings.get(ticker, 0) * 100
                        ret_idx = snap.top7_tickers.index(ticker)
                        ret_12m = snap.top7_returns[ret_idx] * 100 if ret_idx < len(snap.top7_returns) else 0
                        passes = snap.abs_mom_pass.get(ticker, False)
                        w.writerow([f"Trigger_{trig}", snap.date, ticker,
                                    COUNTRY_ETFS.get(ticker, ""), f"{weight:.1f}",
                                    f"{ret_12m:.1f}", "Y" if passes else "N",
                                    f"{snap.cash_pct:.1f}"])
        print(f"Monthly holdings saved to: {snap_path}")

    print("\n" + "=" * 70)
    print("DONE.")
    print("=" * 70)


if __name__ == "__main__":
    main()
