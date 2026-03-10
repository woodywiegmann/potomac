"""
International Tactical: Risk-On/Risk-Off Dashboard
==================================================
Produces a single-page HTML report (and optional CSV log) showing the composite
risk-on/risk-off signals, composite score, regime, and recommended equity exposure.
Uses the same signal logic as intl_composite_risk_backtest.py (includes RSI(5),
WMA/IWMA trend, and Turtle Donchian).

Run monthly before rebalance (e.g. last trading day):
  python intl_risk_dashboard.py
  python intl_risk_dashboard.py --csv   # also append row to intl_risk_history.csv

Output: intl_risk_dashboard.html (and optionally intl_risk_history.csv).
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("pip install yfinance")

from intl_composite_signals import (
    BREADTH_TICKERS,
    TREND_TICKER,
    CASH_TICKER,
    DEFAULT_WEIGHTS,
    compute_signals,
    composite_score,
    equity_weight_graduated,
    regime_label,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FLOOR = 0.25


def fetch_latest(max_days: int = 500) -> Tuple[Dict[str, pd.Series], Optional[pd.Series]]:
    """Fetch recent data for signal computation. Returns (data, acwx_mean)."""
    end = datetime.now()
    start = (end - timedelta(days=max_days)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    tickers = list(set(
        list(BREADTH_TICKERS) + [CASH_TICKER, TREND_TICKER, "VIX", "BNDX", "SPY"]
    ))
    raw = yf.download(tickers, start=start, end=end_str, progress=False, auto_adjust=True, group_by="ticker")
    data: Dict[str, pd.Series] = {}
    if raw.empty:
        return data, None
    for t in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if t not in raw["Close"].columns:
                    continue
                col = raw["Close"][t].copy().dropna()
            else:
                if len(tickers) > 1:
                    continue
                col = raw["Close"].copy().dropna()
            if len(col) > 0:
                if col.index.tz is not None:
                    col.index = col.index.tz_localize(None)
                data[t] = col
        except (KeyError, TypeError, AttributeError):
            pass
    acwx_mean = None
    if TREND_TICKER in data:
        try:
            raw_acwx = yf.download(TREND_TICKER, start=start, end=end_str, progress=False, auto_adjust=True)
            if not raw_acwx.empty and "High" in raw_acwx.columns and "Low" in raw_acwx.columns:
                raw_acwx.index = raw_acwx.index.tz_localize(None) if raw_acwx.index.tz else raw_acwx.index
                acwx_mean = ((raw_acwx["High"] + raw_acwx["Low"]) / 2).dropna()
        except Exception:
            pass
    return data, acwx_mean


def load_last_12_months() -> list:
    """Load last 12 rows from monthly CSV if produced by backtest."""
    path = os.path.join(SCRIPT_DIR, "intl_composite_monthly.csv")
    if not os.path.isfile(path):
        return []
    try:
        df = pd.read_csv(path)
        if "Date" in df.columns and "Composite" in df.columns and "EquityWeight" in df.columns:
            return df.tail(12).to_dict("records")
    except Exception:
        pass
    return []


def write_html(
    signals: Dict[str, float],
    composite: float,
    equity_weight: float,
    as_of_date: str,
    floor: float = DEFAULT_FLOOR,
    history: list = None,
) -> str:
    """Generate HTML report content."""
    regime = regime_label(composite)
    history = history or []
    rows = []
    for name, val in signals.items():
        pct = f"{val * 100:.1f}%" if 0 <= val <= 1 else str(val)
        interp = "Risk-on" if val >= 0.5 else "Risk-off"
        rows.append(f"    <tr><td>{name}</td><td>{pct}</td><td>{interp}</td></tr>")
    table_body = "\n".join(rows)
    history_rows = []
    for h in history:
        dt = h.get("Date", "")
        comp = h.get("Composite", "")
        ew = h.get("EquityWeight", "")
        history_rows.append(f"    <tr><td>{dt}</td><td>{comp}</td><td>{ew}</td></tr>")
    history_table = "\n".join(history_rows) if history_rows else "    <tr><td colspan=\"3\">No history (run backtest to generate intl_composite_monthly.csv)</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Intl Tactical Risk-On/Risk-Off Dashboard</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 24px; background: #f8f9fa; }}
    h1 {{ color: #1f4e79; }}
    h2 {{ color: #2c6e49; margin-top: 20px; }}
    table {{ border-collapse: collapse; background: white; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #1f4e79; color: white; }}
    .composite {{ font-size: 1.5em; font-weight: bold; }}
    .risk-on {{ color: #2c6e49; }}
    .risk-off {{ color: #8b0000; }}
    .mixed {{ color: #b8860b; }}
    .meta {{ color: #666; font-size: 0.9em; margin-top: 24px; }}
  </style>
</head>
<body>
  <h1>International Tactical: Risk-On / Risk-Off Dashboard</h1>
  <p class="meta">As of <strong>{as_of_date}</strong>. Run monthly before rebalance.</p>

  <h2>Composite score and regime</h2>
  <p>Composite (0–1): <span class="composite">{composite:.3f}</span> &nbsp; Regime: <span class="regime {regime.lower().replace(' ', '-')}">{regime}</span></p>
  <p>Recommended equity exposure (graduated with floor {floor:.0%}): <strong>{equity_weight:.0%}</strong> equities / {1 - equity_weight:.0%} BIL</p>

  <h2>Signal breakdown</h2>
  <table>
    <thead><tr><th>Signal</th><th>Value (0–1)</th><th>Interpretation</th></tr></thead>
    <tbody>
{table_body}
    </tbody>
  </table>

  <h2>Last 12 months (from backtest CSV)</h2>
  <table>
    <thead><tr><th>Date</th><th>Composite</th><th>Equity weight</th></tr></thead>
    <tbody>
{history_table}
    </tbody>
  </table>

  <p class="meta">Includes: Breadth, ACWX trend, ACWX momentum, Vol (VIX), Credit (BNDX), Rel strength, RSI(5), WMA/IWMA, Turtle Donchian. Generated by intl_risk_dashboard.py.</p>
</body>
</html>
"""
    return html


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Intl Tactical Risk Dashboard")
    ap.add_argument("--floor", type=float, default=DEFAULT_FLOOR, help="Min equity weight")
    ap.add_argument("--csv", action="store_true", help="Append one row to intl_risk_history.csv")
    args = ap.parse_args()

    data, acwx_mean = fetch_latest(500)
    if not data or TREND_TICKER not in data:
        print("Could not load data for ACWX; check network and tickers.")
        return
    as_of = data[TREND_TICKER].index.max()
    if pd.isna(as_of):
        print("No valid ACWX date.")
        return
    as_of = pd.Timestamp(as_of)

    signals = compute_signals(data, as_of, acwx_mean=acwx_mean)
    composite = composite_score(signals, DEFAULT_WEIGHTS)
    equity_weight = equity_weight_graduated(composite, args.floor)
    as_of_str = as_of.strftime("%Y-%m-%d")

    history = load_last_12_months()
    html = write_html(signals, composite, equity_weight, as_of_str, args.floor, history)
    out_path = os.path.join(SCRIPT_DIR, "intl_risk_dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written to: {out_path}")
    print(f"  Composite: {composite:.3f}  Equity weight: {equity_weight:.0%}  Regime: {regime_label(composite)}")

    if args.csv:
        hist_path = os.path.join(SCRIPT_DIR, "intl_risk_history.csv")
        file_exists = os.path.isfile(hist_path)
        row = {"Date": as_of_str, "Composite": f"{composite:.4f}", "EquityWeight": f"{equity_weight:.4f}"}
        for k, v in signals.items():
            row[k] = f"{v:.4f}"
        with open(hist_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                w.writeheader()
            w.writerow(row)
        print(f"Appended row to: {hist_path}")


if __name__ == "__main__":
    main()
