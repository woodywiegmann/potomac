"""
JMOM Single-Stock Replication Module
======================================
Reverse-engineers JPMorgan US Momentum Factor ETF (JMOM) methodology.
Selects top 50 S&P 500 stocks by composite momentum with quality gate.

Signals:
  - 12-1 month price return (skip most recent month)
  - Risk-adjusted momentum (12m return / 12m daily volatility)
  - Composite: equal-weight both signals

Quality gate (pass/fail):
  - ROE > 10%
  - Debt/Equity < 1.5 (150 in yfinance units)
  - Positive trailing EPS

Importable by both backtest engine and live dashboard.
"""

import io
import numpy as np
import pandas as pd
import requests as _requests

WIKI_HEADERS = {"User-Agent": "PotomacJMOM/1.0 (woody@potomacfund.com)"}
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

N_STOCKS = 50
WEIGHT = 1.0 / N_STOCKS


def get_sp500_tickers():
    try:
        resp = _requests.get(SP500_URL, headers=WIKI_HEADERS, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        sectors = dict(zip(tickers, df["GICS Sector"]))
        return tickers, sectors
    except Exception as e:
        print(f"  WARNING: S&P 500 fetch failed ({e})")
        return [], {}


def compute_momentum_scores(prices, date, tickers):
    """
    Compute momentum scores for all tickers as of a given date.
    Returns DataFrame with columns: mom_12_1, risk_adj_mom, composite_score
    """
    hist = prices.loc[:date]
    if len(hist) < 252:
        return pd.DataFrame()

    records = []
    for t in tickers:
        if t not in hist.columns:
            continue
        series = hist[t].dropna()
        if len(series) < 252:
            continue

        p_now = series.iloc[-1]
        p_12m = series.iloc[-252]
        p_1m = series.iloc[-21]

        if p_12m <= 0 or p_1m <= 0:
            continue

        mom_12_1 = (p_1m / p_12m) - 1.0

        daily_rets = series.pct_change().iloc[-252:]
        vol_12m = daily_rets.std() * np.sqrt(252)
        risk_adj_mom = mom_12_1 / vol_12m if vol_12m > 0 else 0

        records.append({
            "ticker": t,
            "mom_12_1": mom_12_1,
            "risk_adj_mom": risk_adj_mom,
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).set_index("ticker")

    df["mom_pctile"] = df["mom_12_1"].rank(pct=True) * 100
    df["risk_adj_pctile"] = df["risk_adj_mom"].rank(pct=True) * 100
    df["composite_score"] = 0.5 * df["mom_pctile"] + 0.5 * df["risk_adj_pctile"]

    return df


def apply_quality_gate(scores_df, fundamentals):
    """Filter stocks that fail quality gate. Returns passing tickers."""
    passing = []
    for t in scores_df.index:
        fund = fundamentals.get(t, {})
        if not fund:
            passing.append(t)
            continue

        roe = fund.get("roe")
        de = fund.get("debt_equity")
        eps = fund.get("trailing_eps")

        if roe is not None and roe < 0.10:
            continue
        if de is not None and de > 150:
            continue
        if eps is not None and eps <= 0:
            continue

        passing.append(t)

    return passing


def select_portfolio(prices, fundamentals, date, tickers, n=N_STOCKS):
    """
    Select top N momentum stocks with quality gate as of date.
    Returns list of (ticker, weight) tuples.
    """
    scores = compute_momentum_scores(prices, date, tickers)
    if scores.empty:
        return [], scores

    passing = apply_quality_gate(scores, fundamentals)
    eligible = scores.loc[scores.index.isin(passing)]

    top = eligible.sort_values("composite_score", ascending=False).head(n)
    weight = 1.0 / max(len(top), 1)

    holdings = [(t, weight) for t in top.index]
    return holdings, scores
