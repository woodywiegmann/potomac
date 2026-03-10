"""
COMOD composite: 3 indicators (DBC trend, DFII10 real rates, Dollar).
3/3 bullish = risk on; 1/3 bearish = risk off.
Missing data on rebalance date → carry forward previous COMOD; first month missing → risk off.
"""

import pandas as pd
import numpy as np


def _series_at_or_before(series: pd.Series, dt) -> float | None:
    """Last value on or before dt. Returns None if no data."""
    if series is None or series.empty:
        return None
    series = series.loc[:dt]
    if series.empty:
        return None
    return float(series.iloc[-1])


def _price_series(df) -> pd.Series | None:
    """Single price series from DataFrame (Close, Adj Close, or first numeric column)."""
    if df is None or df.empty:
        return None
    for col in ("Close", "Adj Close"):
        if col in df.columns:
            return df[col]
    if len(df.columns):
        return df.iloc[:, 0]
    return None


def commodity_trend_bull(dt, data: dict) -> bool | None:
    """
    DBC (yfinance). Bullish = DBC above 200d SMA, or 9m return > 0.
    Returns True/False or None if missing data.
    """
    df = data.get("dbc")
    s = _price_series(df) if df is not None else None
    if s is None or s.empty:
        return None
    s = s.loc[:dt]
    if len(s) < 2:
        return None
    close = float(s.iloc[-1])
    # 200d SMA (need 200 trading days)
    if len(s) < 200:
        # Fallback: 9m return > 0 if we have enough history
        lookback = min(189, len(s) - 1)  # ~9 months
        if lookback < 1:
            return None
        start_price = float(s.iloc[-1 - lookback])
        return (close / start_price - 1) > 0 if start_price and start_price > 0 else None
    sma200 = s.rolling(200).mean().iloc[-1]
    if pd.isna(sma200):
        return None
    return close > sma200


def real_rates_bull(dt, data: dict) -> bool | None:
    """
    FRED DFII10. Bullish = DFII10 < 0 or DFII10 below 12-month average.
    Returns True/False or None if missing.
    """
    series = data.get("dfii10")
    if series is None or series.empty:
        return None
    s = series.loc[:dt]
    if s.empty:
        return None
    val = float(s.iloc[-1])
    if pd.isna(val):
        return None
    # 12-month average (FRED business days ~252)
    if len(s) < 20:
        return val < 0
    window = min(252, len(s))
    avg = float(s.iloc[-window:].mean())
    if pd.isna(avg):
        return val < 0
    return val < 0 or val < avg


def dollar_bull(dt, data: dict) -> bool | None:
    """
    DXY (yfinance DX-Y.NYB or FRED). Bullish = below 200d SMA (weak/falling dollar).
    Returns True/False or None if missing.
    """
    df = data.get("dxy")
    s = _price_series(df) if df is not None else None
    if s is None or s.empty:
        return None
    s = s.loc[:dt]
    if len(s) < 2:
        return None
    close = float(s.iloc[-1])
    if len(s) < 200:
        return None  # require 200d for SMA
    sma200 = s.rolling(200).mean().iloc[-1]
    if pd.isna(sma200):
        return None
    return close < sma200


def comod_risk_on(dt, data: dict, prev_risk_on: bool | None) -> bool:
    """
    Risk on iff all 3 indicators bullish.
    If any indicator missing → return prev_risk_on (no change).
    If prev_risk_on is None (first rebalance) and any missing → risk off (False).
    """
    c = commodity_trend_bull(dt, data)
    r = real_rates_bull(dt, data)
    d = dollar_bull(dt, data)
    if c is None or r is None or d is None:
        return prev_risk_on if prev_risk_on is not None else False
    return bool(c and r and d)
