"""
SPLV Single-Stock Replication Module
======================================
Replicates Invesco S&P 500 Low Volatility ETF (SPLV) methodology.
Selects 50 lowest-volatility S&P 500 stocks by trailing 252-day
daily return standard deviation. Equal-weighted.

No quality gate -- low volatility IS the filter.

Importable by both backtest engine and live dashboard.
"""

import numpy as np
import pandas as pd

N_STOCKS = 50


def compute_volatility_scores(prices, date, tickers):
    """
    Compute trailing 252-day realized volatility for all tickers as of date.
    Returns DataFrame with columns: vol_252d, vol_pctile (lower vol = higher rank)
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

        daily_rets = series.pct_change().iloc[-252:].dropna()
        if len(daily_rets) < 200:
            continue

        vol_252 = daily_rets.std() * np.sqrt(252)

        records.append({"ticker": t, "vol_252d": vol_252})

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).set_index("ticker")
    df["vol_pctile"] = (1.0 - df["vol_252d"].rank(pct=True)) * 100

    return df


def select_low_vol_portfolio(prices, date, tickers, n=N_STOCKS):
    """
    Select the N lowest-volatility stocks as of date.
    Returns list of (ticker, weight) tuples and the scores DataFrame.
    """
    scores = compute_volatility_scores(prices, date, tickers)
    if scores.empty:
        return [], scores

    top = scores.sort_values("vol_252d", ascending=True).head(n)
    weight = 1.0 / max(len(top), 1)

    holdings = [(t, weight) for t in top.index]
    return holdings, scores
