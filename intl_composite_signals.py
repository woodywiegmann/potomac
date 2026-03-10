"""
International Tactical: Composite Risk-On/Risk-Off Signals
==========================================================
Shared signal and composite logic for the 40-ETF Antonacci-style dual momentum
strategy. Replaces the binary breadth + ACWX 200 SMA overlay with a weighted
composite of multiple signals, including:

  - Breadth (% MSCI country ETFs above 200d SMA)
  - ACWX trend (above 200d SMA)
  - ACWX momentum (blended 1/3/6/12m, normalized)
  - Volatility (VIX-based: low vol = risk-on)
  - Credit (BNDX above 200d SMA)
  - Relative strength (ACWX 12m - SPY 12m, normalized)
  - RSI(5) on ACWX (Book Mar 4 2026: early trend, 50% equilibrium; >50 = risk-on)
  - WMA/IWMA trend (WMA & IWMA PDF: WMA > IWMA = trend = risk-on)
  - Turtle Donchian (20/55 breakout trend: in Turtle long = risk-on)

Composite = weighted sum of normalized signals -> [0, 1].
Equity weight = graduated(composite, floor) or stepped(composite, bands).

Usage:
  from intl_composite_signals import (
      ALL_ETFS_40, BREADTH_TICKERS, compute_signals, composite_score,
      equity_weight_graduated, equity_weight_stepped, DEFAULT_WEIGHTS,
  )
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════════
# UNIVERSE (from qc_intl_40etf_breadth_deploy)
# ═══════════════════════════════════════════════════════════════════════════════

ALL_ETFS_40 = {
    "EWJ": "Japan", "EWG": "Germany", "EWQ": "France",
    "EWI": "Italy", "EWD": "Sweden", "EWL": "Switzerland",
    "EWP": "Spain", "EWH": "Hong Kong", "EWS": "Singapore",
    "EDEN": "Denmark",
    "IHDG": "Intl Hedged Qual Div Growth",
    "RING": "Global Gold Miners", "SIL": "Silver Miners",
    "URA": "Uranium", "KXI": "Global Consumer Staples",
    "LIT": "Lithium & Battery Tech", "REMX": "Rare Earth Metals",
    "COPX": "Copper Miners", "PICK": "Global Metals Mining",
    "GNR": "S&P Global NatRes", "CGW": "Global Water",
    "GII": "Global Infrastructure", "INFL": "Inflation Beneficiaries",
    "MOO": "Agribusiness",
    "EWT": "Taiwan", "EWZ": "Brazil", "INDA": "India",
    "FXI": "China", "EWY": "South Korea", "EWW": "Mexico",
    "ILF": "LatAm 40", "ECH": "Chile", "TUR": "Turkey",
    "ARGT": "Argentina", "VNM": "Vietnam", "THD": "Thailand",
    "EWM": "Malaysia", "EIDO": "Indonesia",
    "KSA": "Saudi Arabia", "KWEB": "China Internet",
}

BREADTH_TICKERS = [
    "EWJ", "EWG", "EWU", "EWC", "EWA", "EWQ", "EWL", "EWP",
    "EWI", "EWD", "EWH", "EWS", "EWN", "EDEN", "EWK", "EWO",
    "EWT", "EWZ", "INDA", "FXI", "EWY", "EWW", "EWM", "ECH",
    "TUR", "THD", "EIDO", "EPHE", "KSA", "ARGT", "VNM",
]

CASH_TICKER = "BIL"
TREND_TICKER = "ACWX"
LOOKBACK_MONTHS = [1, 3, 6, 12]
SMA_PERIOD = 200

# Default composite weights (sum = 1). Include RSI(5), WMA/IWMA, Turtle.
DEFAULT_WEIGHTS = {
    "breadth": 0.18,
    "acwx_trend": 0.15,
    "acwx_mom": 0.12,
    "vol_ok": 0.12,
    "credit_ok": 0.08,
    "rel_strength": 0.05,
    "rsi5": 0.12,       # RSI(5) > 50 = early trend (Book Mar 4 2026)
    "wma_iwma": 0.10,   # WMA > IWMA = trend (WMA & IWMA PDF)
    "turtle": 0.08,     # Turtle Donchian trend confirmation
}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def trailing_return(prices: pd.Series, months: int, as_of: pd.Timestamp) -> float:
    """Trailing N-month total return as of as_of."""
    lookback = as_of - pd.DateOffset(months=months)
    mask = prices.index <= as_of
    recent = prices[mask]
    if len(recent) == 0:
        return np.nan
    mask_old = prices.index <= lookback
    old = prices[mask_old]
    if len(old) == 0:
        return np.nan
    return float(recent.iloc[-1] / old.iloc[-1] - 1.0)


def blended_momentum(
    prices: pd.Series,
    as_of: pd.Timestamp,
    lookback_months: list = None,
) -> float:
    """Blended 1/3/6/12m return (average)."""
    lookback_months = lookback_months or LOOKBACK_MONTHS
    rets = [trailing_return(prices, m, as_of) for m in lookback_months]
    valid = [r for r in rets if not (r != r or math.isnan(r))]
    if not valid:
        return np.nan
    return float(np.mean(valid))


def sma(prices: pd.Series, period: int, as_of: pd.Timestamp) -> float:
    """Simple moving average as of as_of (using only data <= as_of)."""
    mask = prices.index <= as_of
    s = prices[mask].tail(period)
    if len(s) < period:
        return np.nan
    return float(s.mean())


# ═══════════════════════════════════════════════════════════════════════════════
# CORE SIGNALS (0–1)
# ═══════════════════════════════════════════════════════════════════════════════

def breadth_pct(
    data: Dict[str, pd.Series],
    breadth_tickers: list,
    as_of: pd.Timestamp,
    sma_period: int = SMA_PERIOD,
) -> float:
    """% of breadth tickers above 200d SMA. Return in [0, 1]."""
    above = 0
    total = 0
    for ticker in breadth_tickers:
        if ticker not in data:
            continue
        p = data[ticker]
        mask = p.index <= as_of
        if len(p[mask]) < sma_period:
            continue
        price = p[mask].iloc[-1]
        ma = sma(p, sma_period, as_of)
        if math.isnan(ma) or ma <= 0:
            continue
        total += 1
        if price > ma:
            above += 1
    if total == 0:
        return 0.5
    return above / total


def acwx_trend(
    acwx: pd.Series,
    as_of: pd.Timestamp,
    sma_period: int = SMA_PERIOD,
) -> float:
    """ACWX above 200d SMA -> 1 else 0."""
    if acwx is None or len(acwx) == 0:
        return 0.5
    mask = acwx.index <= as_of
    s = acwx[mask]
    if len(s) < sma_period:
        return 0.5
    price = s.iloc[-1]
    ma = sma(acwx, sma_period, as_of)
    if math.isnan(ma):
        return 0.5
    return 1.0 if price > ma else 0.0


def acwx_momentum_norm(
    acwx: pd.Series,
    as_of: pd.Timestamp,
    lookback_months: list = None,
    clip_lo: float = -0.20,
    clip_hi: float = 0.20,
) -> float:
    """Blended ACWX momentum normalized to [0, 1]."""
    mom = blended_momentum(acwx, as_of, lookback_months or LOOKBACK_MONTHS)
    if math.isnan(mom):
        return 0.5
    x = np.clip(mom, clip_lo, clip_hi)
    return float((x - clip_lo) / (clip_hi - clip_lo))


def vol_ok(vix: Optional[pd.Series], as_of: pd.Timestamp, vix_cap: float = 30.0) -> float:
    """Low VIX = risk-on. 1 - min(1, VIX/30)."""
    if vix is None or len(vix) == 0:
        return 0.5
    mask = vix.index <= as_of
    s = vix[mask]
    if len(s) == 0:
        return 0.5
    v = float(s.iloc[-1])
    return float(1.0 - min(1.0, v / vix_cap))


def credit_ok(
    bndx: Optional[pd.Series],
    as_of: pd.Timestamp,
    sma_period: int = SMA_PERIOD,
) -> float:
    """BNDX above 200d SMA -> 1 else 0."""
    if bndx is None or len(bndx) == 0:
        return 0.5
    mask = bndx.index <= as_of
    if len(bndx[mask]) < sma_period:
        return 0.5
    price = bndx[mask].iloc[-1]
    ma = sma(bndx, sma_period, as_of)
    if math.isnan(ma):
        return 0.5
    return 1.0 if price > ma else 0.0


def rel_strength_norm(
    acwx: pd.Series,
    spy: Optional[pd.Series],
    as_of: pd.Timestamp,
    months: int = 12,
    clip_lo: float = -0.20,
    clip_hi: float = 0.20,
) -> float:
    """ACWX 12m - SPY 12m normalized to [0, 1]. Positive = ex-US leading = risk-on."""
    if spy is None or len(spy) == 0:
        return 0.5
    r_acwx = trailing_return(acwx, months, as_of)
    r_spy = trailing_return(spy, months, as_of)
    if math.isnan(r_acwx) or math.isnan(r_spy):
        return 0.5
    diff = r_acwx - r_spy
    x = np.clip(diff, clip_lo, clip_hi)
    return float((x - clip_lo) / (clip_hi - clip_lo))


# ═══════════════════════════════════════════════════════════════════════════════
# RSI(5) — Book Mar 4 2026: early trend, 50% equilibrium
# ═══════════════════════════════════════════════════════════════════════════════

def rsi(series: pd.Series, period: int = 5) -> pd.Series:
    """RSI with Wilder smoothing (alpha = 1/period)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi5_signal(close: pd.Series, as_of: pd.Timestamp, period: int = 5) -> float:
    """RSI(5) normalized to [0, 1]. >50% = risk-on (early trend)."""
    if close is None or len(close) < period + 5:
        return 0.5
    mask = close.index <= as_of
    s = close[mask]
    if len(s) < period + 5:
        return 0.5
    r = rsi(s, period)
    val = r.iloc[-1]
    if math.isnan(val):
        return 0.5
    # Map 0–100 to 0–1; 50 = equilibrium = 0.5
    return float(np.clip(val / 100.0, 0.0, 1.0))


# ═══════════════════════════════════════════════════════════════════════════════
# WMA / IWMA — WMA & IWMA PDF: trend when WMA > IWMA
# ═══════════════════════════════════════════════════════════════════════════════

def wma(series: pd.Series, period: int) -> pd.Series:
    """Front-loaded WMA: weights 1, 2, ..., period."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(
        lambda x: np.dot(x, weights) / weights.sum() if len(x) == period else np.nan,
        raw=True,
    )


def iwma(series: pd.Series, period: int) -> pd.Series:
    """Back-loaded IWMA: weights period, period-1, ..., 1."""
    weights = np.arange(period, 0, -1, dtype=float)
    return series.rolling(period).apply(
        lambda x: np.dot(x, weights) / weights.sum() if len(x) == period else np.nan,
        raw=True,
    )


def wma_iwma_trend(
    mean_price: pd.Series,
    as_of: pd.Timestamp,
    period: int = 7,
) -> float:
    """Trend = WMA > IWMA -> 1 else 0. Mean price = (High+Low)/2."""
    if mean_price is None or len(mean_price) < period + 5:
        return 0.5
    mask = mean_price.index <= as_of
    s = mean_price[mask].copy()
    w = wma(s, period)
    iw = iwma(s, period)
    if len(w.dropna()) == 0:
        return 0.5
    # Last valid
    valid_idx = w.last_valid_index()
    if valid_idx is None:
        return 0.5
    wv = w.loc[valid_idx]
    iwv = iw.loc[valid_idx]
    if math.isnan(wv) or math.isnan(iwv):
        return 0.5
    return 1.0 if wv > iwv else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# TURTLE DONCHIAN — System 1 (20/10), System 2 (55/20)
# ═══════════════════════════════════════════════════════════════════════════════

def turtle_long_series(
    close: pd.Series,
    entry_short: int = 20,
    exit_short: int = 10,
    entry_long: int = 55,
    exit_long: int = 20,
) -> pd.Series:
    """
    Compute Turtle long state (0 or 1) for each date.
    S1: long when close > 20d high; exit when close < 10d low.
    S2: long when close > 55d high; exit when close < 20d low.
    Turtle long = in S1 or in S2. (Skip-if-winner for S1 omitted for composite.)
    """
    roll_20h = close.rolling(entry_short).max()
    roll_10l = close.rolling(exit_short).min()
    roll_55h = close.rolling(entry_long).max()
    roll_20l = close.rolling(exit_long).min()
    values = []
    in_s1 = False
    in_s2 = False
    for i in range(len(close)):
        if i < entry_long:
            values.append(np.nan)
            continue
        c = close.iloc[i]
        r20h = roll_20h.iloc[i]
        r10l = roll_10l.iloc[i]
        r55h = roll_55h.iloc[i]
        r20l = roll_20l.iloc[i]
        if pd.isna(c) or pd.isna(r20h) or pd.isna(r10l) or pd.isna(r55h) or pd.isna(r20l):
            values.append(1.0 if (in_s1 or in_s2) else 0.0)
            continue
        # Exits first
        if in_s1 and c < r10l:
            in_s1 = False
        if in_s2 and c < r20l:
            in_s2 = False
        # Entries
        if c > r20h:
            in_s1 = True
        if c > r55h:
            in_s2 = True
        values.append(1.0 if (in_s1 or in_s2) else 0.0)
    return pd.Series(values, index=close.index)


def turtle_signal(close: pd.Series, as_of: pd.Timestamp) -> float:
    """Turtle long state at as_of: 1 if in Turtle long else 0."""
    if close is None or len(close) < 60:
        return 0.5
    mask = close.index <= as_of
    s = close[mask]
    if len(s) < 60:
        return 0.5
    turtle = turtle_long_series(s, 20, 10, 55, 20)
    last_valid = turtle.dropna()
    if len(last_valid) == 0:
        return 0.5
    val = last_valid.iloc[-1]
    return float(val)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPUTE ALL SIGNALS + COMPOSITE + EQUITY WEIGHT
# ═══════════════════════════════════════════════════════════════════════════════

def compute_signals(
    data: Dict[str, pd.Series],
    as_of: pd.Timestamp,
    *,
    breadth_tickers: list = None,
    lookback_months: list = None,
    sma_period: int = SMA_PERIOD,
    acwx_mean: Optional[pd.Series] = None,
) -> Dict[str, float]:
    """
    Compute all risk-on/risk-off signals as of as_of.
    data: dict of ticker -> price series (Close). For WMA/IWMA we need
          acwx_mean = (High+Low)/2 for ACWX if available; else we use Close.
    Returns dict of signal name -> value in [0, 1].
    """
    breadth_tickers = breadth_tickers or BREADTH_TICKERS
    lookback_months = lookback_months or LOOKBACK_MONTHS
    acwx = data.get(TREND_TICKER)
    vix = data.get("VIX")
    bndx = data.get("BNDX")
    spy = data.get("SPY")

    signals = {}

    # Breadth
    signals["breadth"] = breadth_pct(data, breadth_tickers, as_of, sma_period)

    # ACWX trend
    signals["acwx_trend"] = acwx_trend(acwx, as_of, sma_period) if acwx is not None else 0.5

    # ACWX momentum
    signals["acwx_mom"] = acwx_momentum_norm(acwx, as_of, lookback_months) if acwx is not None else 0.5

    # Vol
    signals["vol_ok"] = vol_ok(vix, as_of)

    # Credit
    signals["credit_ok"] = credit_ok(bndx, as_of, sma_period)

    # Relative strength
    signals["rel_strength"] = rel_strength_norm(acwx, spy, as_of, 12) if acwx is not None else 0.5

    # RSI(5) on ACWX
    signals["rsi5"] = rsi5_signal(acwx, as_of, 5) if acwx is not None else 0.5

    # WMA/IWMA trend (use mean price if provided, else Close)
    series_for_wma = (acwx_mean if acwx_mean is not None and len(acwx_mean) > 0 else acwx)
    signals["wma_iwma"] = wma_iwma_trend(series_for_wma, as_of, 7) if series_for_wma is not None else 0.5

    # Turtle
    signals["turtle"] = turtle_signal(acwx, as_of) if acwx is not None else 0.5

    return signals


def composite_score(signals: Dict[str, float], weights: Dict[str, float] = None) -> float:
    """Weighted sum of signals. weights default to DEFAULT_WEIGHTS."""
    weights = weights or DEFAULT_WEIGHTS
    total = 0.0
    wsum = 0.0
    for k, w in weights.items():
        if k in signals and w > 0:
            total += w * signals[k]
            wsum += w
    if wsum <= 0:
        return 0.5
    return float(np.clip(total / wsum, 0.0, 1.0))


def equity_weight_graduated(composite: float, floor: float = 0.25) -> float:
    """Graduated: equity_weight = composite, with floor."""
    return float(np.clip(max(composite, floor), 0.0, 1.0))


def equity_weight_stepped(
    composite: float,
    bands: Tuple[Tuple[float, float], ...] = ((0.25, 0.0), (0.50, 0.5), (0.75, 0.75), (1.01, 1.0)),
) -> float:
    """Stepped: (threshold, weight). composite < 0.25 -> 0; 0.25–0.50 -> 0.5; etc."""
    for thresh, w in bands:
        if composite < thresh:
            return w
    return 1.0


def regime_label(composite: float, risk_on_thresh: float = 0.65, risk_off_thresh: float = 0.35) -> str:
    """Risk-On / Mixed / Risk-Off from composite."""
    if composite >= risk_on_thresh:
        return "Risk-On"
    if composite <= risk_off_thresh:
        return "Risk-Off"
    return "Mixed"
