"""
Penta Risk-On / Risk-Off Signal Module
========================================
PROXY signals until Woody provides the real Penta spec.
Architecture: single get_regime() function that returns the regime flag
and individual signal values. Drop-in replaceable.

Proxy composite (4 indicators, evaluated daily):
  1. SPY > 200-day SMA (binary)
  2. VIX < 20 (binary)
  3. 10Y yield: 50-day ROC negative = bullish (binary)
  4. Credit: LQD vs SHY ratio > 50-day SMA (binary)

Decision: 3 of 4 bullish = RISK ON, else RISK OFF

Replace this module with the real Penta signals when ready.
The backtest only calls get_regime() -- everything else is internal.
"""

import numpy as np
import pandas as pd

RISK_ON = "RISK_ON"
RISK_OFF = "RISK_OFF"

# Tickers needed by this signal module
REQUIRED_TICKERS = ["SPY", "^VIX", "^TNX", "LQD", "SHY"]


def _sma(series, window):
    return series.rolling(window, min_periods=window).mean()


def _roc(series, window):
    return series / series.shift(window) - 1.0


def get_regime(prices, date):
    """
    Evaluate risk-on/risk-off regime as of `date`.

    Args:
        prices: dict of ticker -> pd.Series (daily closes, DatetimeIndex)
        date: pd.Timestamp or datetime

    Returns:
        (regime, signals_dict)
        regime: "RISK_ON" or "RISK_OFF"
        signals_dict: {signal_name: {"value": float, "bullish": bool}}
    """
    signals = {}

    # Signal 1: SPY > 200-day SMA
    spy = prices.get("SPY")
    if spy is not None:
        spy_hist = spy.loc[:date].dropna()
        if len(spy_hist) >= 200:
            sma_200 = spy_hist.iloc[-200:].mean()
            current = spy_hist.iloc[-1]
            signals["SPY > 200d SMA"] = {
                "value": current / sma_200 - 1.0,
                "bullish": current > sma_200,
            }

    # Signal 2: VIX < 20
    vix = prices.get("^VIX")
    if vix is None:
        vix = prices.get("VIX")
    if vix is not None:
        vix_hist = vix.loc[:date].dropna()
        if len(vix_hist) > 0:
            current_vix = vix_hist.iloc[-1]
            signals["VIX < 20"] = {
                "value": current_vix,
                "bullish": current_vix < 20,
            }

    # Signal 3: 10Y yield 50-day ROC negative (falling rates = bullish)
    tnx = prices.get("^TNX")
    if tnx is None:
        tnx = prices.get("TNX")
    if tnx is not None:
        tnx_hist = tnx.loc[:date].dropna()
        if len(tnx_hist) >= 50:
            roc_50 = tnx_hist.iloc[-1] / tnx_hist.iloc[-50] - 1.0
            signals["10Y Yield ROC < 0"] = {
                "value": roc_50,
                "bullish": roc_50 < 0,
            }

    # Signal 4: Credit (LQD vs SHY ratio > 50d SMA)
    lqd = prices.get("LQD")
    shy = prices.get("SHY")
    if lqd is not None and shy is not None:
        lqd_hist = lqd.loc[:date].dropna()
        shy_hist = shy.loc[:date].dropna()
        if len(lqd_hist) >= 50 and len(shy_hist) >= 50:
            common = lqd_hist.index.intersection(shy_hist.index)
            if len(common) >= 50:
                ratio = lqd_hist.reindex(common) / shy_hist.reindex(common)
                ratio_sma = ratio.iloc[-50:].mean()
                current_ratio = ratio.iloc[-1]
                signals["Credit LQD/SHY > 50d"] = {
                    "value": current_ratio / ratio_sma - 1.0,
                    "bullish": current_ratio > ratio_sma,
                }

    bullish_count = sum(1 for s in signals.values() if s["bullish"])
    total = len(signals)

    regime = RISK_ON if bullish_count >= 3 else RISK_OFF

    return regime, signals
