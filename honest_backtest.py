"""
Honest Backtest Module
======================
Enforces realistic assumptions on all local backtests so results
approximate what QuantConnect (and reality) will produce.

Every strategy Jack builds must use this module. No exceptions.

Usage:
    from honest_backtest import (
        lag_signals, apply_transition_costs, compute_honest_returns,
        validate_strategy, print_validation_report, reconcile_with_qc,
    )

Root causes this module addresses:
    1. Same-day signal + same-day execution (look-ahead bias)
    2. Close-to-close returns on signal change days (should be close-to-open)
    3. Zero transaction costs
    4. No validation pipeline before declaring victory
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))


def lag_signals(signals: pd.DataFrame | pd.Series, lag: int = 1) -> pd.DataFrame | pd.Series:
    """Shift signals forward by `lag` days so day-T signal drives day-T+lag allocation.

    This is the single most important function in the module. Without it,
    backtests capture returns from information they couldn't have acted on.
    """
    return signals.shift(lag)


def compute_transition_mask(allocation: pd.Series) -> pd.Series:
    """Identify days where the allocation changed (regime transitions)."""
    return allocation != allocation.shift(1)


def apply_transition_costs(
    returns: pd.Series,
    allocation: pd.Series,
    cost_bps: float = 20.0,
) -> pd.Series:
    """Subtract round-trip transaction costs on days when allocation changes.

    Args:
        returns: daily strategy returns
        allocation: regime/allocation label for each day (e.g. "FULL_ON", "RISK_OFF")
        cost_bps: round-trip cost in basis points per transition
    """
    transitions = compute_transition_mask(allocation)
    cost = cost_bps / 10_000
    adjusted = returns.copy()
    adjusted[transitions] -= cost
    return adjusted


def compute_open_execution_returns(
    close_prices: pd.Series,
    open_prices: pd.Series,
    allocation_changed: pd.Series,
) -> pd.Series:
    """On signal-change days, use close-to-open return for execution gap.

    On normal days: return = close[t] / close[t-1] - 1
    On transition days: return = close[t] / open[t] - 1  (entered at open)

    The gap between yesterday's close and today's open is the slippage
    that local backtests ignore. On risk-off days this gap is often large
    and negative — exactly when you need the signal to work.
    """
    normal_ret = close_prices.pct_change()
    open_ret = (close_prices - open_prices) / open_prices

    returns = normal_ret.copy()
    returns[allocation_changed] = open_ret[allocation_changed]
    return returns.fillna(0.0)


def compute_honest_returns(
    signals: pd.Series | pd.DataFrame,
    instrument_close: pd.Series,
    instrument_open: pd.Series | None = None,
    signal_lag: int = 1,
    cost_bps: float = 20.0,
    label: str = "strategy",
) -> dict:
    """Full honest backtest pipeline for a binary risk-on/risk-off strategy.

    Returns dict with:
        - returns: pd.Series of daily returns
        - equity: pd.Series of cumulative equity curve
        - transitions: int count of regime switches
        - metrics: dict of performance metrics
    """
    lagged = lag_signals(signals, lag=signal_lag).fillna(0)

    transitions = compute_transition_mask(lagged)
    n_transitions = transitions.sum()

    if instrument_open is not None:
        base_ret = compute_open_execution_returns(
            instrument_close, instrument_open, transitions,
        )
    else:
        base_ret = instrument_close.pct_change().fillna(0)

    strategy_ret = base_ret * lagged

    if cost_bps > 0:
        strategy_ret = apply_transition_costs(strategy_ret, lagged, cost_bps)

    equity = (1 + strategy_ret).cumprod()

    return {
        "returns": strategy_ret,
        "equity": equity,
        "transitions": int(n_transitions),
        "lagged_signals": lagged,
        "metrics": compute_metrics(strategy_ret, equity, label),
    }


def compute_metrics(
    returns: pd.Series,
    equity: pd.Series,
    label: str = "",
) -> dict:
    """Standard performance metrics in Potomac priority order."""
    if len(returns) < 10:
        return {}

    days = (returns.index[-1] - returns.index[0]).days
    years = days / 365.25 if days > 0 else 1

    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1

    vol = returns.std() * np.sqrt(252)
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_dd = drawdown.min()

    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    win_rate = (returns > 0).sum() / len(returns)

    return {
        "label": label,
        "cagr": cagr,
        "total_return": total,
        "volatility": vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "win_rate": win_rate,
        "years": years,
        "trading_days": len(returns),
    }


def validate_strategy(
    honest_results: dict,
    naive_cagr: float | None = None,
    benchmark_cagr: float | None = None,
    signal_returns_when_off: pd.Series | None = None,
) -> list[str]:
    """Run the validation pipeline. Returns list of warnings/flags.

    Checks:
        1. If naive (no-lag) CAGR drops > 30% with lag, alpha was timing illusion
        2. If CAGR < benchmark after costs, strategy doesn't survive execution
        3. Signal accuracy: do risk-off days actually have negative market returns?
        4. Transition frequency: > 30 round-trips/year = whipsaw risk
    """
    flags = []
    m = honest_results["metrics"]
    years = m.get("years", 1)
    transitions = honest_results["transitions"]
    rt_per_year = transitions / years / 2  # round-trips

    if naive_cagr is not None:
        drop_pct = (1 - m["cagr"] / naive_cagr) * 100 if naive_cagr != 0 else 0
        if drop_pct > 30:
            flags.append(
                f"CAGR dropped {drop_pct:.0f}% with signal lag "
                f"({naive_cagr*100:.1f}% -> {m['cagr']*100:.1f}%). "
                f"Most of the alpha was timing illusion."
            )

    if benchmark_cagr is not None:
        if m["cagr"] < benchmark_cagr:
            flags.append(
                f"Strategy CAGR ({m['cagr']*100:.1f}%) is below benchmark "
                f"({benchmark_cagr*100:.1f}%) after costs. Does not survive execution."
            )

    if signal_returns_when_off is not None and len(signal_returns_when_off) > 10:
        pct_negative = (signal_returns_when_off < 0).mean()
        if pct_negative < 0.55:
            flags.append(
                f"Signal accuracy is weak: only {pct_negative*100:.0f}% of risk-off days "
                f"had negative market returns (need > 55% to add value)."
            )

    if rt_per_year > 30:
        flags.append(
            f"Excessive transitions: {rt_per_year:.0f} round-trips/year. "
            f"At 20bps/rt, that's {rt_per_year * 20:.0f}bps/year of drag. "
            f"Whipsaw cost may eat the alpha."
        )

    if not flags:
        flags.append("All checks passed. Strategy survives honest assumptions.")

    return flags


def print_validation_report(
    honest_results: dict,
    flags: list[str],
    naive_metrics: dict | None = None,
) -> list[str]:
    """Print a formatted validation report."""
    lines = []

    def p(s=""):
        lines.append(s)
        print(s)

    W = 100
    m = honest_results["metrics"]

    p("=" * W)
    p(f"HONEST BACKTEST VALIDATION: {m.get('label', 'Strategy')}")
    p("=" * W)

    if naive_metrics:
        p(f"\n  {'Metric':<20} {'Naive (no lag)':<20} {'Honest (T+1, costs)':<20} {'Delta':<15}")
        p("  " + "-" * 75)
        for key, fmt in [("cagr", ".2%"), ("max_dd", ".2%"), ("calmar", ".2f"),
                         ("sharpe", ".3f"), ("volatility", ".2%")]:
            naive_val = naive_metrics.get(key, 0)
            honest_val = m.get(key, 0)
            delta = honest_val - naive_val
            p(f"  {key:<20} {format(naive_val, fmt):<20} {format(honest_val, fmt):<20} {format(delta, fmt):<15}")

    else:
        p(f"\n  CAGR:         {m['cagr']:.2%}")
        p(f"  Max DD:       {m['max_dd']:.2%}")
        p(f"  Calmar:       {m['calmar']:.2f}")
        p(f"  Sharpe:       {m['sharpe']:.3f}")
        p(f"  Volatility:   {m['volatility']:.2%}")
        p(f"  Win Rate:     {m['win_rate']:.1%}")

    p(f"\n  Transitions:  {honest_results['transitions']}")
    p(f"  RT/year:      {honest_results['transitions'] / m.get('years', 1) / 2:.0f}")

    p(f"\n  VALIDATION FLAGS:")
    for flag in flags:
        severity = "PASS" if "passed" in flag.lower() else "WARN"
        p(f"    [{severity}] {flag}")

    p("=" * W)
    return lines


def reconcile_with_qc(
    local_returns: pd.Series,
    qc_returns: pd.Series,
    tolerance_bps: float = 50.0,
) -> pd.DataFrame:
    """Compare local backtest returns against QuantConnect results day-by-day.

    Args:
        local_returns: daily returns from local backtest
        qc_returns: daily returns from QuantConnect backtest
        tolerance_bps: flag days where discrepancy exceeds this (in bps)

    Returns:
        DataFrame with columns: date, local, qc, diff_bps, flagged
    """
    common = local_returns.index.intersection(qc_returns.index)
    if len(common) == 0:
        print("WARNING: No overlapping dates between local and QC returns.")
        return pd.DataFrame()

    local_aligned = local_returns.reindex(common).fillna(0)
    qc_aligned = qc_returns.reindex(common).fillna(0)

    diff_bps = (local_aligned - qc_aligned) * 10_000
    flagged = diff_bps.abs() > tolerance_bps

    result = pd.DataFrame({
        "date": common,
        "local_ret": local_aligned.values,
        "qc_ret": qc_aligned.values,
        "diff_bps": diff_bps.values,
        "flagged": flagged.values,
    })

    n_flagged = flagged.sum()
    total = len(common)
    mean_diff = diff_bps.mean()
    max_diff = diff_bps.abs().max()

    print(f"\n=== QC Reconciliation ===")
    print(f"  Overlapping days:   {total}")
    print(f"  Flagged (>{tolerance_bps:.0f}bps):  {n_flagged} ({n_flagged/total*100:.1f}%)")
    print(f"  Mean diff:          {mean_diff:.1f} bps")
    print(f"  Max diff:           {max_diff:.1f} bps")
    print(f"  Local cum return:   {(1 + local_aligned).prod() - 1:.2%}")
    print(f"  QC cum return:      {(1 + qc_aligned).prod() - 1:.2%}")

    if n_flagged > 0:
        print(f"\n  Worst discrepancy days:")
        worst = result[result["flagged"]].sort_values("diff_bps", key=abs, ascending=False).head(10)
        for _, row in worst.iterrows():
            print(f"    {row['date'].date()}: local {row['local_ret']*100:+.3f}% "
                  f"vs QC {row['qc_ret']*100:+.3f}% (diff: {row['diff_bps']:+.1f} bps)")

    return result


def load_qc_results(json_path: str | Path) -> pd.Series:
    """Load QuantConnect backtest results JSON and extract daily returns.

    Expects the standard QC backtest result JSON with a 'Charts' key
    containing 'Strategy Equity' series.
    """
    import json

    path = Path(json_path)
    with open(path) as f:
        data = json.load(f)

    equity_data = data.get("Charts", {}).get("Strategy Equity", {}).get("Series", {}).get("Equity", {}).get("Values", [])

    if not equity_data:
        for key in data.get("Charts", {}):
            series = data["Charts"][key].get("Series", {})
            for s_key in series:
                vals = series[s_key].get("Values", [])
                if len(vals) > 50:
                    equity_data = vals
                    break
            if equity_data:
                break

    if not equity_data:
        raise ValueError(f"Could not find equity series in {path}")

    dates = []
    values = []
    for point in equity_data:
        ts = point.get("x", 0)
        val = point.get("y", 0)
        dt = pd.Timestamp(ts, unit="s")
        dates.append(dt)
        values.append(val)

    equity = pd.Series(values, index=pd.DatetimeIndex(dates), name="QC_Equity")
    equity = equity[~equity.index.duplicated(keep="last")]
    equity = equity.sort_index()

    return equity.pct_change().fillna(0)
