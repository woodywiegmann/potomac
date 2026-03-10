"""
International Tactical: Composite Risk-On/Risk-Off Backtest
==========================================================
Antonacci-style 40-ETF dual momentum (blended 1/3/6/12m, top 7, abs momentum)
with a COMPOSITE risk-on/risk-off overlay instead of breadth + ACWX only.

Composite includes: breadth, ACWX trend, ACWX momentum, vol, credit, rel strength,
RSI(5), WMA/IWMA trend, Turtle Donchian. Equity weight = graduated(composite, floor)
so we stay invested 60–90% of the time and maximize Calmar.

Usage:
  python intl_composite_risk_backtest.py
  python intl_composite_risk_backtest.py --start 2016-01-01 --floor 0.30
  python intl_composite_risk_backtest.py --sweep   # run weight sweep + baseline
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("pip install yfinance")

from intl_composite_signals import (
    ALL_ETFS_40,
    BREADTH_TICKERS,
    CASH_TICKER,
    TREND_TICKER,
    LOOKBACK_MONTHS,
    DEFAULT_WEIGHTS,
    compute_signals,
    composite_score,
    equity_weight_graduated,
    blended_momentum,
    trailing_return,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_data(start: str, end: str) -> Tuple[Dict[str, pd.Series], Optional[pd.Series]]:
    """
    Fetch Close for all tickers; also ACWX OHLC for mean price (WMA/IWMA).
    Returns (data dict of ticker -> Close series, acwx_mean series or None).
    """
    warmup = 400
    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup)).strftime("%Y-%m-%d")
    all_40 = list(ALL_ETFS_40.keys())
    breadth = [t for t in BREADTH_TICKERS if t not in all_40]
    tickers_close = list(set(all_40 + breadth + [CASH_TICKER, TREND_TICKER, "VIX", "BNDX", "SPY"]))
    print(f"Fetching {len(tickers_close)} tickers (Close) from {fetch_start} to {end}...")
    raw = yf.download(tickers_close, start=fetch_start, end=end, progress=False, auto_adjust=True, group_by="ticker", threads=True)
    data: Dict[str, pd.Series] = {}
    if raw.empty:
        return data, None
    for t in tickers_close:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if t not in raw["Close"].columns:
                    continue
                col = raw["Close"][t].copy().dropna()
            else:
                col = raw["Close"].copy().dropna() if len(tickers_close) == 1 else pd.Series(dtype=float)
                if col.empty and len(tickers_close) > 1:
                    continue
            if len(col) > 0:
                if col.index.tz is not None:
                    col.index = col.index.tz_localize(None)
                data[t] = col
        except (KeyError, TypeError, AttributeError):
            pass

    # ACWX OHLC for mean price (WMA/IWMA)
    acwx_mean = None
    if TREND_TICKER in data:
        try:
            raw_acwx = yf.download(TREND_TICKER, start=fetch_start, end=end, progress=False, auto_adjust=True)
            if not raw_acwx.empty and "High" in raw_acwx.columns and "Low" in raw_acwx.columns:
                raw_acwx.index = raw_acwx.index.tz_localize(None) if raw_acwx.index.tz else raw_acwx.index
                acwx_mean = ((raw_acwx["High"] + raw_acwx["Low"]) / 2).dropna()
        except Exception:
            pass

    return data, acwx_mean


def get_month_end_dates(index: pd.DatetimeIndex, start: str) -> List[pd.Timestamp]:
    mask = index >= pd.Timestamp(start)
    filtered = index[mask]
    if len(filtered) == 0:
        return []
    month_ends = filtered.to_series().groupby([filtered.year, filtered.month]).last()
    return [pd.Timestamp(d) for d in month_ends.values]


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MonthlyRow:
    date: str
    composite: float
    equity_weight: float
    top7: List[str]
    holdings: Dict[str, float]  # ticker -> weight (including BIL for scaled portion)
    period_return: float


@dataclass
class BacktestResult:
    name: str
    equity_curve: pd.Series
    monthly: List[MonthlyRow] = field(default_factory=list)
    cagr: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    calmar: float = 0.0
    avg_equity_weight: float = 0.0
    pct_months_invested: float = 0.0  # % months with equity_weight >= 0.5
    turnover_annual: float = 0.0
    best_year: float = 0.0
    worst_year: float = 0.0


def run_backtest(
    data: Dict[str, pd.Series],
    acwx_mean: Optional[pd.Series],
    start: str,
    end: str,
    weights: Optional[Dict[str, float]] = None,
    floor: float = 0.25,
    top_n: int = 7,
) -> BacktestResult:
    """
    Run 40-ETF dual momentum with composite overlay.
    Each month: composite -> equity_weight; top 7 by blended momentum; abs mom filter;
    final allocation = equity_weight * (top-7 weights) + (1 - equity_weight) * BIL.
    """
    weights = weights or DEFAULT_WEIGHTS
    common_idx = None
    for t in ALL_ETFS_40:
        if t in data:
            if common_idx is None:
                common_idx = data[t].index
            else:
                common_idx = common_idx.union(data[t].index)
    if common_idx is None or CASH_TICKER not in data:
        return BacktestResult(name="Composite", equity_curve=pd.Series(dtype=float))
    common_idx = common_idx.union(data[CASH_TICKER].index).sort_values()
    month_ends = get_month_end_dates(common_idx, start)
    if len(month_ends) < 2:
        return BacktestResult(name="Composite", equity_curve=pd.Series(dtype=float))

    equity_curve = pd.Series(dtype=float)
    equity_curve[month_ends[0]] = 10000.0
    monthly_rows: List[MonthlyRow] = []
    prev_holdings: Dict[str, float] = {}
    total_turnover = 0.0

    for i in range(1, len(month_ends)):
        rebal_date = month_ends[i - 1]
        eval_date = month_ends[i]

        # 1) Composite signals and equity weight
        sigs = compute_signals(data, rebal_date, acwx_mean=acwx_mean)
        comp = composite_score(sigs, weights)
        eq_w = equity_weight_graduated(comp, floor)

        # 2) Rank 40 ETFs by blended momentum
        scores = {}
        for t in ALL_ETFS_40:
            if t not in data:
                continue
            s = blended_momentum(data[t], rebal_date, LOOKBACK_MONTHS)
            if not (s != s or math.isnan(s)):
                scores[t] = s
        if not scores:
            period_ret = 0.0
            if CASH_TICKER in data:
                p0 = data[CASH_TICKER][data[CASH_TICKER].index <= rebal_date]
                p1 = data[CASH_TICKER][data[CASH_TICKER].index <= eval_date]
                if len(p0) and len(p1):
                    period_ret = (1 - eq_w) * (p1.iloc[-1] / p0.iloc[-1] - 1)
            equity_curve[eval_date] = equity_curve.iloc[-1] * (1 + period_ret)
            monthly_rows.append(MonthlyRow(
                date=str(rebal_date.date()), composite=comp, equity_weight=eq_w,
                top7=[], holdings={CASH_TICKER: 1.0}, period_return=period_ret,
            ))
            continue

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top7 = [t for t, _ in ranked[:top_n]]
        slot_w = 1.0 / top_n
        holdings: Dict[str, float] = {}
        for t in top7:
            sc = scores.get(t, 0)
            if sc is not None and not math.isnan(sc) and sc > 0:
                holdings[t] = eq_w * slot_w
            # else: that slot goes to BIL (we add to cash)
        cash_slots = top_n - len(holdings)
        bil_w = (1.0 - eq_w) + eq_w * (cash_slots * slot_w)
        if bil_w > 1e-6:
            holdings[CASH_TICKER] = holdings.get(CASH_TICKER, 0) + bil_w

        # Turnover
        all_tickers = set(prev_holdings.keys()) | set(holdings.keys())
        turn = sum(abs(holdings.get(t, 0) - prev_holdings.get(t, 0)) for t in all_tickers)
        total_turnover += turn
        prev_holdings = holdings.copy()

        # Period return
        period_ret = 0.0
        for t, w in holdings.items():
            if t == CASH_TICKER:
                p0 = data[CASH_TICKER][data[CASH_TICKER].index <= rebal_date]
                p1 = data[CASH_TICKER][data[CASH_TICKER].index <= eval_date]
            else:
                if t not in data:
                    continue
                p0 = data[t][data[t].index <= rebal_date]
                p1 = data[t][data[t].index <= eval_date]
            if len(p0) > 0 and len(p1) > 0:
                period_ret += w * (p1.iloc[-1] / p0.iloc[-1] - 1)
        equity_curve[eval_date] = equity_curve.iloc[-1] * (1 + period_ret)
        monthly_rows.append(MonthlyRow(
            date=str(rebal_date.date()), composite=comp, equity_weight=eq_w,
            top7=top7, holdings=holdings, period_return=period_ret,
        ))

    n_months = len(month_ends) - 1
    n_years = n_months / 12.0
    res = BacktestResult(
        name="Composite overlay",
        equity_curve=equity_curve,
        monthly=monthly_rows,
        turnover_annual=total_turnover / n_years if n_years > 0 else 0,
    )
    if monthly_rows:
        res.avg_equity_weight = float(np.mean([m.equity_weight for m in monthly_rows]))
        res.pct_months_invested = sum(1 for m in monthly_rows if m.equity_weight >= 0.5) / len(monthly_rows) * 100
    return res


def compute_metrics(r: BacktestResult) -> None:
    eq = r.equity_curve.dropna()
    if len(eq) < 2:
        return
    days = (eq.index[-1] - eq.index[0]).days
    yrs = days / 365.25
    r.total_return = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    r.cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    r.max_drawdown = dd.min() * 100
    monthly_ret = eq.pct_change().dropna()
    if monthly_ret.std() > 0:
        r.sharpe = (monthly_ret.mean() - 0.03 / 12) / monthly_ret.std() * math.sqrt(12)
    r.calmar = abs(r.cagr / r.max_drawdown) if r.max_drawdown != 0 else 0
    yr = eq.resample("YE").last().pct_change().dropna() * 100
    if len(yr) > 0:
        r.best_year = yr.max()
        r.worst_year = yr.min()


def run_baseline(
    data: Dict[str, pd.Series],
    start: str,
    end: str,
    top_n: int = 7,
) -> BacktestResult:
    """Binary overlay: invest only when breadth >= 0.6 OR ACWX > 200 SMA (current doc)."""
    from intl_composite_signals import breadth_pct, acwx_trend
    common_idx = None
    for t in ALL_ETFS_40:
        if t in data:
            common_idx = data[t].index if common_idx is None else common_idx.union(data[t].index)
    if common_idx is None or CASH_TICKER not in data:
        return BacktestResult(name="Baseline (breadth+ACWX)", equity_curve=pd.Series(dtype=float))
    common_idx = common_idx.union(data[CASH_TICKER].index).sort_values()
    month_ends = get_month_end_dates(common_idx, start)
    if len(month_ends) < 2:
        return BacktestResult(name="Baseline", equity_curve=pd.Series(dtype=float))

    equity_curve = pd.Series(dtype=float)
    equity_curve[month_ends[0]] = 10000.0
    prev_holdings: Dict[str, float] = {}
    monthly_rows: List[MonthlyRow] = []

    for i in range(1, len(month_ends)):
        rebal_date = month_ends[i - 1]
        eval_date = month_ends[i]
        breadth = breadth_pct(data, BREADTH_TICKERS, rebal_date)
        trend = acwx_trend(data.get(TREND_TICKER), rebal_date)
        invest = breadth >= 0.6 or trend >= 0.5  # trend is 0 or 1
        eq_w = 1.0 if invest else 0.0

        scores = {}
        for t in ALL_ETFS_40:
            if t not in data:
                continue
            s = blended_momentum(data[t], rebal_date, LOOKBACK_MONTHS)
            if not (s != s or math.isnan(s)):
                scores[t] = s
        if not scores:
            period_ret = 0.0
            if CASH_TICKER in data:
                p0 = data[CASH_TICKER][data[CASH_TICKER].index <= rebal_date]
                p1 = data[CASH_TICKER][data[CASH_TICKER].index <= eval_date]
                if len(p0) and len(p1):
                    period_ret = (1 - eq_w) * (p1.iloc[-1] / p0.iloc[-1] - 1)
            equity_curve[eval_date] = equity_curve.iloc[-1] * (1 + period_ret)
            monthly_rows.append(MonthlyRow(
                date=str(rebal_date.date()), composite=1.0 if invest else 0.0,
                equity_weight=eq_w, top7=[], holdings={CASH_TICKER: 1.0}, period_return=period_ret,
            ))
            continue

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top7 = [t for t, _ in ranked[:top_n]]
        slot_w = 1.0 / top_n
        holdings = {}
        for t in top7:
            if scores.get(t, 0) and not math.isnan(scores[t]) and scores[t] > 0:
                holdings[t] = eq_w * slot_w
        bil_w = 1.0 - sum(holdings.values())
        if bil_w > 1e-6:
            holdings[CASH_TICKER] = holdings.get(CASH_TICKER, 0) + bil_w
        prev_holdings = holdings.copy()

        period_ret = 0.0
        for t, w in holdings.items():
            series = data.get(t)
            if series is None:
                continue
            p0 = series[series.index <= rebal_date]
            p1 = series[series.index <= eval_date]
            if len(p0) > 0 and len(p1) > 0:
                period_ret += w * (p1.iloc[-1] / p0.iloc[-1] - 1)
        equity_curve[eval_date] = equity_curve.iloc[-1] * (1 + period_ret)
        monthly_rows.append(MonthlyRow(
            date=str(rebal_date.date()), composite=1.0 if invest else 0.0,
            equity_weight=eq_w, top7=top7, holdings=holdings, period_return=period_ret,
        ))

    n_months = len(month_ends) - 1
    n_years = n_months / 12.0
    res = BacktestResult(
        name="Baseline (breadth+ACWX)",
        equity_curve=equity_curve,
        monthly=monthly_rows,
        turnover_annual=0.0,
    )
    if monthly_rows:
        res.avg_equity_weight = float(np.mean([m.equity_weight for m in monthly_rows]))
        res.pct_months_invested = sum(1 for m in monthly_rows if m.equity_weight >= 0.5) / len(monthly_rows) * 100
    return res


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Intl Tactical Composite Risk Backtest")
    ap.add_argument("--start", default="2016-01-01", help="Start date")
    ap.add_argument("--end", default=None, help="End date (default: today)")
    ap.add_argument("--floor", type=float, default=0.25, help="Min equity weight (graduated floor)")
    ap.add_argument("--sweep", action="store_true", help="Run baseline + composite and export CSV")
    args = ap.parse_args()
    end = args.end or pd.Timestamp.today().strftime("%Y-%m-%d")

    data, acwx_mean = fetch_data(args.start, end)
    available = [t for t in ALL_ETFS_40 if t in data]
    print(f"\n{len(available)}/{len(ALL_ETFS_40)} ETFs available. ACWX mean for WMA/IWMA: {'Yes' if acwx_mean is not None else 'No (using Close)'}")

    # Composite backtest
    print("\nRunning composite overlay backtest...")
    result = run_backtest(data, acwx_mean, args.start, end, floor=args.floor)
    compute_metrics(result)
    print(f"  CAGR: {result.cagr:.1f}%  MaxDD: {result.max_drawdown:.1f}%  Calmar: {result.calmar:.2f}  "
          f"Avg equity: {result.avg_equity_weight:.0%}  Months invested: {result.pct_months_invested:.0f}%")

    if args.sweep:
        print("\nRunning baseline (breadth+ACWX)...")
        baseline = run_baseline(data, args.start, end)
        compute_metrics(baseline)
        print(f"  CAGR: {baseline.cagr:.1f}%  MaxDD: {baseline.max_drawdown:.1f}%  Calmar: {baseline.calmar:.2f}  "
              f"Months invested: {baseline.pct_months_invested:.0f}%")

    # Export monthly composite/equity weight for dashboard
    csv_path = os.path.join(SCRIPT_DIR, "intl_composite_monthly.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Composite", "EquityWeight", "PeriodReturn"])
        for m in result.monthly:
            w.writerow([m.date, f"{m.composite:.4f}", f"{m.equity_weight:.4f}", f"{m.period_return:.6f}"])
    print(f"\nMonthly series saved to: {csv_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
