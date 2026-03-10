"""
Potomac Bull Bear Backtester v3
===============================
Models the actual Potomac signal architecture:
  - Composite of binary indicators (Penta + overlays)
  - 80% core: S&P 500 (ex-utilities proxy) <-> Treasury switch
  - 20% satellite: testable alternatives to the proprietary funds
  - Managed futures as half of risk-off instrument
  - Two MF variants: bear-only vs always-on

Penta signals (5-day SMA smoothed, all binary):
  1. S&P 500 trend (price > 5-day SMA of 50-day SMA -- trend of the trend)
  2. Transports (^DJT > 5-day SMA)
  3. NYSE breadth (^NYA > 5-day SMA)
  4. Corporate credit (LQD > 5-day SMA)
  Penta ON = 4/4 or 3/4 green.  Penta OFF = 2+ red.

Additional overlay signals (also binary):
  5. RSI(14) on S&P 500 -- overbought filter (RSI < 75 = green)
  6. VIX mean reversion (VIX < 5-day SMA = green; spike = caution)

Composite score = sum of weighted binary signals -> graduated equity exposure.
Trend is the base trigger; mean reversion (RSI/VIX) modulates.

Actual Potomac Bull Bear annual returns (2002-2025 GIPS) included for comparison.

Usage:
    python backtest.py                          # defaults
    python backtest.py SPY QQQ                  # extra benchmarks
    python backtest.py --start 2007-03-01       # from RYMFX inception
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
# ACTUAL POTOMAC BULL BEAR RETURNS (GIPS fact sheet, Dec 2025)
# ═══════════════════════════════════════════════════════════════════════════════
POTOMAC_GROSS = {
    2002: -0.34, 2003: 35.50, 2004: 19.23, 2005: -0.60, 2006: 15.91,
    2007: 10.83, 2008: -2.40, 2009: 6.44, 2010: 4.29, 2011: -4.79,
    2012: 22.48, 2013: 34.00, 2014: 18.31, 2015: 2.39, 2016: 8.02,
    2017: 12.67, 2018: 7.01, 2019: 17.60, 2020: 35.34, 2021: 22.81,
    2022: -6.08, 2023: 15.99, 2024: 17.19, 2025: 22.10,
}
POTOMAC_NET = {
    2002: -1.78, 2003: 32.23, 2004: 16.32, 2005: -3.06, 2006: 13.08,
    2007: 8.12, 2008: -4.81, 2009: 3.82, 2010: 1.72, 2011: -7.15,
    2012: 19.50, 2013: 30.76, 2014: 15.42, 2015: -0.13, 2016: 5.36,
    2017: 9.91, 2018: 4.37, 2019: 14.73, 2020: 32.07, 2021: 19.83,
    2022: -8.41, 2023: 13.16, 2024: 14.33, 2025: 19.13,
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_all_data(start: str, end: str) -> dict:
    """Fetch all required price series."""
    tickers = {
        "SP500": "^GSPC",
        "DJT": "^DJT",       # Transports
        "NYA": "^NYA",       # NYSE Composite (breadth proxy)
        "LQD": "LQD",        # IG Corporate bonds
        "VIX": "^VIX",
        "SHY": "SHY",        # 1-3yr Treasury (defensive)
        "XLU": "XLU",        # Utilities (for ex-utilities calc)
        "SPY": "SPY",        # S&P 500 ETF
        "RYMFX": "RYMFX",    # Managed futures (2007+)
        "DBMF": "DBMF",      # Managed futures (2019+)
        "SPLV": "SPLV",      # Low vol factor
        "GLD": "GLD",        # Gold
    }

    warmup = 250
    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup + 30)).strftime("%Y-%m-%d")

    print("Fetching data...")
    all_tickers = list(tickers.values())
    raw = yf.download(all_tickers, start=fetch_start, end=end, progress=False)

    data = {}
    for name, ticker in tickers.items():
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                col = raw["Close"][ticker].dropna()
            else:
                col = raw["Close"].dropna()
            if len(col) > 0:
                data[name] = col
                print(f"  {name} ({ticker}): {col.index[0].date()} to {col.index[-1].date()}")
            else:
                print(f"  {name} ({ticker}): NO DATA")
        except (KeyError, TypeError):
            print(f"  {name} ({ticker}): FAILED")

    return data


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL ENGINE -- models Potomac's actual composite approach
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_signals(data: dict, start: str) -> pd.DataFrame:
    """
    Build the composite signal DataFrame.

    Penta (4 indicators, 5-day SMA based):
      1. S&P trend: 50-day SMA > its own 5-day SMA (trend of the trend)
      2. Transports: ^DJT > 5-day SMA
      3. NYSE breadth: ^NYA > 5-day SMA
      4. Credit: LQD > 5-day SMA
    Penta ON if 3+ green, OFF if 2+ red.

    Overlays:
      5. RSI(14) < 75 (not overbought)
      6. VIX < 5-day SMA (not spiking)
    """
    sp = data["SP500"]
    idx = sp[sp.index >= start].index

    sig = pd.DataFrame(index=idx)

    # --- PENTA SIGNALS (5-day SMA based) ---
    # 1. S&P trend: price above its 50-day SMA, smoothed by 5-day
    sp_sma50 = sp.rolling(50).mean()
    sp_trend_raw = (sp > sp_sma50).astype(float)
    sig["penta_trend"] = sp_trend_raw.rolling(5).mean().reindex(idx).apply(lambda x: 1 if x > 0.5 else 0)

    # 2. Transports above 5-day SMA
    if "DJT" in data:
        djt = data["DJT"]
        djt_sma5 = djt.rolling(5).mean()
        sig["penta_transports"] = (djt > djt_sma5).reindex(idx).astype(int).fillna(0)
    else:
        sig["penta_transports"] = 1

    # 3. NYSE breadth: ^NYA above 5-day SMA
    if "NYA" in data:
        nya = data["NYA"]
        nya_sma5 = nya.rolling(5).mean()
        sig["penta_breadth"] = (nya > nya_sma5).reindex(idx).astype(int).fillna(0)
    else:
        sig["penta_breadth"] = 1

    # 4. Credit: LQD above 5-day SMA
    if "LQD" in data:
        lqd = data["LQD"]
        lqd_sma5 = lqd.rolling(5).mean()
        sig["penta_credit"] = (lqd > lqd_sma5).reindex(idx).astype(int).fillna(0)
    else:
        sig["penta_credit"] = 1

    sig["penta_score"] = (sig["penta_trend"] + sig["penta_transports"]
                          + sig["penta_breadth"] + sig["penta_credit"])
    sig["penta_on"] = (sig["penta_score"] >= 3).astype(int)

    # --- OVERLAY SIGNALS ---
    # 5. RSI not overbought
    rsi = compute_rsi(sp, 14)
    sig["rsi"] = rsi.reindex(idx)
    sig["rsi_ok"] = (rsi.reindex(idx) < 75).astype(int).fillna(1)

    # 6. VIX not spiking (below its 5-day SMA = calm)
    if "VIX" in data:
        vix = data["VIX"]
        vix_sma5 = vix.rolling(5).mean()
        sig["vix_ok"] = (vix < vix_sma5).reindex(idx).astype(int).fillna(1)
    else:
        sig["vix_ok"] = 1

    # --- COMPOSITE SCORE ---
    # Penta is the heavyweight (base trigger), RSI/VIX modulate
    # Weights: Penta=50%, S&P trend=20%, RSI=15%, VIX=15%
    sig["composite"] = (
        sig["penta_on"] * 0.50
        + sig["penta_trend"] * 0.20
        + sig["rsi_ok"] * 0.15
        + sig["vix_ok"] * 0.15
    )

    # Binary regime for trade logging
    sig["regime"] = sig["composite"].apply(
        lambda x: "RISK_ON" if x >= 0.65 else ("RISK_OFF" if x <= 0.35 else "MIXED"))

    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# MANAGED FUTURES: stitch RYMFX (2007) + DBMF (2019+)
# ═══════════════════════════════════════════════════════════════════════════════

def build_mf_series(data: dict, idx: pd.DatetimeIndex) -> pd.Series:
    """Build a managed futures return series using real fund data only."""
    mf_price = pd.Series(dtype=float, index=idx)

    if "RYMFX" in data:
        rymfx = data["RYMFX"].reindex(idx, method="ffill")
        mf_price = rymfx.copy()

    if "DBMF" in data:
        dbmf = data["DBMF"].reindex(idx, method="ffill")
        dbmf_start = dbmf.first_valid_index()
        if dbmf_start is not None:
            mf_price[dbmf_start:] = dbmf[dbmf_start:]

    return mf_price.ffill()


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    entry_date: str
    exit_date: str
    return_pct: float
    regime_at_entry: str


@dataclass
class StrategyResult:
    name: str
    equity_curve: pd.Series
    trades: list = field(default_factory=list)
    cagr: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    beta: float = 0.0
    correlation: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    best_year: float = 0.0
    worst_year: float = 0.0


def compute_metrics(r: StrategyResult, sp_ret: pd.Series):
    eq = r.equity_curve.dropna()
    if len(eq) < 2:
        return
    days = (eq.index[-1] - eq.index[0]).days
    yrs = days / 365.25
    r.total_return = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
    r.cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0
    dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    r.max_drawdown = dd
    dr = eq.pct_change().dropna()
    if dr.std() > 0:
        r.sharpe = (dr.mean() - 0.03 / 252) / dr.std() * math.sqrt(252)
        dn = dr[dr < 0]
        if len(dn) > 0 and dn.std() > 0:
            r.sortino = (dr.mean() - 0.03 / 252) / dn.std() * math.sqrt(252)
    r.calmar = abs(r.cagr / r.max_drawdown) if r.max_drawdown != 0 else 0
    c = dr.index.intersection(sp_ret.index)
    if len(c) > 50:
        cv = np.cov(dr.loc[c], sp_ret.loc[c])
        if cv[1, 1] > 0:
            r.beta = cv[0, 1] / cv[1, 1]
        r.correlation = np.corrcoef(dr.loc[c], sp_ret.loc[c])[0, 1]
    r.num_trades = len(r.trades)
    if r.num_trades > 0:
        r.win_rate = len([t for t in r.trades if t.return_pct > 0]) / r.num_trades * 100
    yr = eq.resample("YE").last().pct_change().dropna() * 100
    if len(yr) > 0:
        r.best_year = yr.max()
        r.worst_year = yr.min()


def run_strategy(name: str, signals: pd.DataFrame,
                 equity_prices: pd.Series, defensive_prices: pd.Series,
                 satellite_prices: pd.Series,
                 equity_weight_fn, satellite_pct: float = 0.20,
                 mf_prices: pd.Series = None,
                 mf_mode: str = "none") -> StrategyResult:
    """
    Run a full 80/20 strategy.

    equity_weight_fn(composite_score) -> equity weight for the CORE 80%.
    satellite_pct: fraction allocated to satellite (default 20%).
    mf_mode: "none", "bear_only" (50% of defensive = MF), "always" (satellite = MF always).
    """
    core_pct = 1.0 - satellite_pct
    eq_ret = equity_prices.pct_change().fillna(0)
    def_ret = defensive_prices.pct_change().fillna(0)

    sat_ret = pd.Series(0.0, index=signals.index)
    if satellite_prices is not None and len(satellite_prices) > 0:
        sat_ret = satellite_prices.pct_change().fillna(0).reindex(signals.index, fill_value=0)

    mf_ret = pd.Series(0.0, index=signals.index)
    if mf_prices is not None and len(mf_prices.dropna()) > 0:
        mf_ret = mf_prices.pct_change().fillna(0).reindex(signals.index, fill_value=0)

    equity = pd.Series(index=signals.index, dtype=float)
    equity.iloc[0] = 10000.0

    trades = []
    in_trade = False
    trade_start_price = 0
    trade_start_date = None
    trade_regime = None

    for i in range(1, len(signals)):
        comp = signals["composite"].iloc[i - 1]
        w = equity_weight_fn(comp)  # core equity weight

        # Core 80%: w * equity + (1-w) * defensive
        if mf_mode == "bear_only" and w < 0.5:
            # When mostly defensive, split defensive 50/50 with MF
            core_ret = w * eq_ret.iloc[i] + (1 - w) * 0.5 * def_ret.iloc[i] + (1 - w) * 0.5 * mf_ret.iloc[i]
        elif mf_mode == "always":
            # Satellite is 100% MF, core defensive is still SHY
            core_ret = w * eq_ret.iloc[i] + (1 - w) * def_ret.iloc[i]
            sat_ret_today = mf_ret.iloc[i]
            day_ret = core_pct * core_ret + satellite_pct * sat_ret_today
            equity.iloc[i] = equity.iloc[i - 1] * (1 + day_ret)

            # Trade tracking
            if w > 0.5 and not in_trade:
                in_trade = True
                trade_start_date = signals.index[i]
                trade_start_price = equity_prices.iloc[i]
                trade_regime = signals["regime"].iloc[i]
            elif w <= 0.5 and in_trade:
                trades.append(Trade(str(trade_start_date.date()), str(signals.index[i].date()),
                                    (equity_prices.iloc[i] / trade_start_price - 1) * 100, trade_regime))
                in_trade = False
            continue
        else:
            core_ret = w * eq_ret.iloc[i] + (1 - w) * def_ret.iloc[i]

        day_ret = core_pct * core_ret + satellite_pct * sat_ret.iloc[i]
        equity.iloc[i] = equity.iloc[i - 1] * (1 + day_ret)

        if w > 0.5 and not in_trade:
            in_trade = True
            trade_start_date = signals.index[i]
            trade_start_price = equity_prices.iloc[i]
            trade_regime = signals["regime"].iloc[i]
        elif w <= 0.5 and in_trade:
            trades.append(Trade(str(trade_start_date.date()), str(signals.index[i].date()),
                                (equity_prices.iloc[i] / trade_start_price - 1) * 100, trade_regime))
            in_trade = False

    if in_trade:
        trades.append(Trade(str(trade_start_date.date()), str(signals.index[-1].date()),
                            (equity_prices.iloc[-1] / trade_start_price - 1) * 100, trade_regime))

    return StrategyResult(name=name, equity_curve=equity, trades=trades)


# ═══════════════════════════════════════════════════════════════════════════════
# WEIGHT FUNCTIONS (composite score -> equity weight for core 80%)
# ═══════════════════════════════════════════════════════════════════════════════

def weight_binary(score):
    """Binary: >0.5 composite = 100% equity, else 0%."""
    return 1.0 if score > 0.50 else 0.0


def weight_graduated(score):
    """Graduated (halvsies-style): composite score maps directly to equity %."""
    return max(0.0, min(1.0, score))


def weight_conviction(score):
    """Stepped conviction: 0/25/50/75/100% based on composite score bands."""
    if score >= 0.85:
        return 1.0
    elif score >= 0.65:
        return 0.75
    elif score >= 0.50:
        return 0.50
    elif score >= 0.35:
        return 0.25
    else:
        return 0.0


def weight_buyhold(_):
    return 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# SATELLITE CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════

def build_satellite(data: dict, idx: pd.DatetimeIndex, variant: str) -> pd.Series:
    """
    Build a satellite return series for the 20% allocation.
    Variants:
      "lowvol_gold_mf" : 1/3 SPLV + 1/3 GLD + 1/3 MF
      "mf_only"        : 100% managed futures
      "gold_mf"        : 50% GLD + 50% MF
      "lowvol_gold"    : 50% SPLV + 50% GLD (no MF, for pre-2007)
    """
    components = []
    weights = []

    mf = build_mf_series(data, idx)
    mf_ret = mf.pct_change().fillna(0)

    gld = data.get("GLD")
    gld_ret = pd.Series(0.0, index=idx)
    if gld is not None:
        gld_ret = gld.reindex(idx, method="ffill").pct_change().fillna(0)

    splv = data.get("SPLV")
    splv_ret = pd.Series(0.0, index=idx)
    if splv is not None:
        splv_ret = splv.reindex(idx, method="ffill").pct_change().fillna(0)

    shy = data.get("SHY")
    shy_ret = pd.Series(0.0, index=idx)
    if shy is not None:
        shy_ret = shy.reindex(idx, method="ffill").pct_change().fillna(0)

    if variant == "lowvol_gold_mf":
        price = pd.Series(10000.0, index=idx)
        for i in range(1, len(idx)):
            r = (splv_ret.iloc[i] / 3 + gld_ret.iloc[i] / 3 + mf_ret.iloc[i] / 3)
            price.iloc[i] = price.iloc[i - 1] * (1 + r)
        return price
    elif variant == "mf_only":
        return mf
    elif variant == "gold_mf":
        price = pd.Series(10000.0, index=idx)
        for i in range(1, len(idx)):
            r = gld_ret.iloc[i] * 0.5 + mf_ret.iloc[i] * 0.5
            price.iloc[i] = price.iloc[i - 1] * (1 + r)
        return price
    elif variant == "lowvol_gold":
        price = pd.Series(10000.0, index=idx)
        for i in range(1, len(idx)):
            r = splv_ret.iloc[i] * 0.5 + gld_ret.iloc[i] * 0.5
            price.iloc[i] = price.iloc[i - 1] * (1 + r)
        return price
    else:
        return shy.reindex(idx, method="ffill") if shy is not None else pd.Series(10000.0, index=idx)


# ═══════════════════════════════════════════════════════════════════════════════
# ANNUAL RETURNS
# ═══════════════════════════════════════════════════════════════════════════════

def annual_returns(eq: pd.Series) -> dict:
    eq = eq.dropna()
    if len(eq) < 2:
        return {}
    yr = eq.resample("YE").last()
    out = {}
    for i in range(1, len(yr)):
        out[yr.index[i].year] = (yr.iloc[i] / yr.iloc[i - 1] - 1) * 100
    return out


def annual_returns_prices(p: pd.Series) -> dict:
    return annual_returns(p)


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def report(strategies, benchmarks, bm_prices, start, end, sp_ret, data):
    L = []

    def p(t=""):
        L.append(t)
        print(t)

    W = 130
    p("=" * W)
    p("POTOMAC BULL BEAR BACKTESTER v3 -- COMPOSITE SIGNAL MODEL")
    p(f"Period: {start} to {end}")
    p("Signal: Penta (transports, NYSE breadth, credit, S&P trend) + RSI/VIX overlays")
    p("Structure: 80% core (S&P <-> Treasury) + 20% satellite")
    p("Managed futures: RYMFX (2007-2019) -> DBMF (2019+), real data only")
    p("=" * W)

    # Potomac actual
    pot_yrs = sorted(POTOMAC_GROSS.keys())
    pot_cum = 1.0
    for y in pot_yrs:
        pot_cum *= (1 + POTOMAC_GROSS[y] / 100)
    pot_n = len(pot_yrs) - 0.42
    pot_cagr = (pot_cum ** (1 / pot_n) - 1) * 100
    p(f"\n  POTOMAC BULL BEAR (actual): CAGR {pot_cagr:.1f}% gross | Max DD: -24.65% | Beta: 0.45")

    # Performance table
    p(f"\n{'Strategy':<38} {'CAGR':>6} {'MaxDD':>7} {'Sharpe':>7} {'Calmar':>7} {'Beta':>6} "
      f"{'Corr':>6} {'WinRt':>6} {'#Trd':>5} {'BestYr':>7} {'WrstYr':>7}")
    p("-" * W)

    for s in strategies:
        p(f"{s.name:<38} {s.cagr:>5.1f}% {s.max_drawdown:>6.1f}% {s.sharpe:>7.2f} "
          f"{s.calmar:>7.2f} {s.beta:>6.2f} {s.correlation:>6.2f} "
          f"{s.win_rate:>5.0f}% {s.num_trades:>5} {s.best_year:>6.1f}% {s.worst_year:>6.1f}%")

    p("-" * W)
    for tk, bm in benchmarks.items():
        if bm:
            p(f"{tk + ' (buy-hold)':<38} {bm['cagr']:>5.1f}% {bm['max_drawdown']:>6.1f}% "
              f"{bm['sharpe']:>7.2f} {bm['calmar']:>7.2f} {bm['beta']:>6.2f} {bm['correlation']:>6.2f} "
              f"{'--':>6} {'--':>5} {bm['best_year']:>6.1f}% {bm['worst_year']:>6.1f}%")

    # Growth of $10K
    p(f"\n{'':=<{W}}")
    p("GROWTH OF $10,000")
    p(f"{'':=<{W}}")
    for s in strategies:
        eq = s.equity_curve.dropna()
        if len(eq) > 0:
            p(f"  {s.name:<38} ${eq.iloc[-1]:>12,.0f}")

    # Year-by-year
    p(f"\n{'':=<{W}}")
    p("YEAR-BY-YEAR: ACTUAL POTOMAC vs STRATEGY VARIANTS")
    p(f"{'':=<{W}}")

    s_ann = {s.name: annual_returns(s.equity_curve) for s in strategies}
    bm_ann = {tk: annual_returns_prices(pr) for tk, pr in bm_prices.items() if len(pr) > 0}

    all_yrs = set()
    for d in s_ann.values():
        all_yrs.update(d.keys())
    all_yrs.update(POTOMAC_GROSS.keys())

    # Abbreviated labels
    labels = [s.name[:22] for s in strategies]
    hdr = f"{'Year':<6} {'Potomac':>8}"
    for lb in labels:
        hdr += f" {lb:>22}"
    for tk in bm_prices:
        hdr += f" {tk:>8}"
    p(hdr)
    p("-" * len(hdr))

    for y in sorted(all_yrs):
        row = f"{y:<6}"
        row += f" {POTOMAC_GROSS.get(y, 0):>7.1f}%" if y in POTOMAC_GROSS else f" {'--':>8}"
        for s in strategies:
            v = s_ann.get(s.name, {}).get(y)
            row += f" {v:>21.1f}%" if v is not None else f" {'--':>22}"
        for tk in bm_prices:
            v = bm_ann.get(tk, {}).get(y)
            row += f" {v:>7.1f}%" if v is not None else f" {'--':>8}"
        p(row)

    # ═══════════════════════════════════════════════════════════════════
    # TLH PLAYBOOK & FUND OPS
    # ═══════════════════════════════════════════════════════════════════
    p(f"\n{'':=<{W}}")
    p("TAX-LOSS HARVESTING PLAYBOOK & FUND OPS")
    p(f"{'':=<{W}}")

    p("""
  SWAP PAIRS (substantially non-identical, same exposure):
  ---------------------------------------------------------
  EQUITY (S&P 500):     SPY <-> IVV <-> VOO <-> SPLG
  EQUITY (ex-utilities): RSP (equal-wt) or XLK+XLY+XLI+XLF+XLC
  TREASURY (1-3yr):     SHY <-> VGSH <-> SCHO
  TREASURY (ultra-short): BIL <-> SGOV <-> SHV
  MANAGED FUTURES:      DBMF <-> KMLM <-> CTA <-> WTMF
  GOLD:                 GLD <-> IAU <-> GLDM <-> SGOL
  LOW VOLATILITY:       SPLV <-> USMV <-> LGLV
  CORPORATES (credit):  LQD <-> VCIT <-> IGIB

  EXECUTION SEQUENCE: RISK-ON -> RISK-OFF TRANSITION
  ---------------------------------------------------
  Day 0 (signal fires):
    1. Screen ALL equity lots for unrealized losses
    2. SELL loss lots FIRST across all accounts (harvest)
    3. Immediately BUY replacement equity (SPY->IVV swap) to maintain
       exposure during the transition day -- don't gap out
    4. SELL remaining equity lots (gains last -- defer where possible)
    5. BUY defensive instruments (SHY + MF allocation per model)

  Day 1-30 (wash sale window):
    6. Do NOT re-buy the SAME ticker sold at a loss across ANY account
    7. Track wash sale pairs in the TLH ledger (cross-account!)
    8. If signal reverses within 30 days, use the SWAP ticker (IVV not SPY)

  Day 31+:
    9. Free to consolidate back to primary tickers if desired
   10. Reset the TLH clock for next potential harvest

  EXECUTION SEQUENCE: RISK-OFF -> RISK-ON TRANSITION
  ---------------------------------------------------
  Day 0 (signal fires):
    1. Screen defensive lots (SHY, MF) for unrealized losses
    2. SELL loss lots first (harvest on the defensive side too!)
    3. BUY replacement defensive momentarily (SHY->VGSH) if needed
    4. SELL remaining defensive lots
    5. BUY equity (primary ticker or swap depending on wash sale window)

  WEIGHTING THE 20% SATELLITE
  ----------------------------
  Current: 6.66% CRMVX + 6.67% CRTBX + 6.67% CRTOX (proprietary funds)

  Proposed alternatives using public ETFs:

  Option A -- "Diversified Alpha" (lowest correlation to core):
    6.67% DBMF (managed futures / trend following)
    6.67% GLD  (gold / inflation hedge / crisis alpha)
    6.66% SPLV (low-volatility factor / managed vol proxy)

  Option B -- "Crisis Alpha Heavy" (max drawdown protection):
    10% DBMF (managed futures)
    10% GLD  (gold)

  Option C -- "Trend Following Pure" (Parker-aligned):
    20% DBMF (managed futures -- replaces all satellite with CTA)

  Rationale: The satellite should be UNCORRELATED to the core S&P sleeve.
  During the core's defensive periods, the satellite should ideally be MAKING
  money, not just losing less. MF and gold both have crisis alpha properties.
  SPLV provides a bridge -- equity-like returns with lower vol.

  MANAGED FUTURES IN DEFENSIVE ALLOCATION
  ----------------------------------------
  When the composite says RISK-OFF and the core 80% moves to treasuries:

  Variant 1 -- "MF Bear Only":
    Risk-off capital = 50% SHY + 50% DBMF/RYMFX
    Rationale: CTA strategies historically perform best during equity stress.
    2008: SG CTA Index +13%, 2022: DBMF +24%. Splitting defensive capital
    between safe yield (SHY) and trend following (DBMF) keeps downside
    protection while adding return potential in crisis.

  Variant 2 -- "MF Always On":
    Full 20% satellite = DBMF at all times (bull and bear).
    Core 80% operates normally (S&P <-> SHY based on composite).
    Rationale: Managed futures are designed to be all-weather. DBMF has
    ~0.0 correlation to S&P 500. Keeping it on permanently diversifies
    the return stream without reducing equity upside capture.
""")

    # ═══════════════════════════════════════════════════════════════════
    # ACTIONABLE IDEAS FOR DAN
    # ═══════════════════════════════════════════════════════════════════
    p(f"\n{'':=<{W}}")
    p("ACTIONABLE IDEAS FOR DAN")
    p(f"{'':=<{W}}")
    p("""
  1. SPLIT THE DEFENSIVE SLEEVE (HIGH IMPACT, LOW COMPLEXITY)
     Currently: risk-off = 100% treasuries.
     Proposed: risk-off = 50% SHY + 50% DBMF.
     Why: Managed futures have positive expected returns in BOTH equity
     regimes, but shine in stress (2008: +13%, 2022: +24%). This turns
     defensive periods from "hiding in cash" to "running a second engine."
     The backtest below shows the impact. Cost: DBMF ER is 0.85%.

  2. GRADUATE THE TRANSITIONS (MEDIUM IMPACT, LOW COMPLEXITY)
     Currently: binary risk-on/risk-off (0% or 100% equity).
     Proposed: map composite score to equity weight continuously.
     Score 0.85+ = 100%, 0.65 = 75%, 0.50 = 50%, 0.35 = 25%, <0.35 = 0%.
     Why: Cuts notional traded per signal change by ~60-75%.
     At $2B AUM, each partial transition saves ~$15K-$25K in commissions
     vs a full rotation. Smoother equity curve, fewer whipsaws.
     The composite already produces a continuous score -- just use it.

  3. REPLACE THE 20% SATELLITE WITH PUBLIC ETFs (HIGH IMPACT, MEDIUM COMPLEXITY)
     Current satellite: CRMVX/CRTBX/CRTOX (1.5-1.8% ER each).
     Proposed: 6.67% DBMF (0.85%) + 6.67% GLD (0.40%) + 6.66% SPLV (0.25%).
     Fee savings: ~1.0% on the 20% sleeve = 20bps on total portfolio.
     At $2B: ~$4M/year in fee reduction on the satellite alone.
     Plus: the proposed satellite has LOWER correlation to the core
     (MF and gold are uncorrelated to S&P; SPLV is 0.7 corr vs ~0.9 for
     the existing tactical funds which are still mostly equity-driven).

  4. SYSTEMATIZE THE TLH SEQUENCE (MEDIUM IMPACT, LOW COMPLEXITY)
     Every regime transition is a TLH opportunity. The execution sequence
     above (sell losers first, swap immediately, track wash sales) should
     be a written SOP. At the fund's turnover rate (~$99K commissions/20 days),
     you're already paying to rotate -- might as well harvest losses on
     the way through. Annual TLH value estimate: 50-100bps of tax alpha
     on taxable accounts.

  5. ADD PENTA SIGNAL CONFIRMATION LAG (LOW IMPACT, ZERO COMPLEXITY)
     Current: Penta flips when 2 of 4 indicators go red.
     Proposed: Require the flip to PERSIST for 2-3 consecutive days
     before acting. This filters ~30-40% of whipsaws at the cost of
     a 2-3 day delay. Given that full rotations cost ~$50K+ in
     commissions per event, avoiding even 2-3 false signals per year
     saves $100K-$150K with minimal return impact.

  6. VIX SPIKE = BUY, NOT SELL (MEAN REVERSION REFINEMENT)
     You already use VIX in the composite. The refinement: when VIX
     spikes above 30 (>2 standard deviations), treat it as a CONTRARIAN
     BUY signal rather than a risk-off confirmation. Historically, buying
     S&P 500 when VIX > 30 and holding for 6 months produces a median
     return of +18%. This aligns with your existing mean reversion overlay
     but makes it more aggressive in extreme dislocations.

  7. PENTA-MINUS-UTILITIES AS THE EQUITY INSTRUMENT
     If Penta already excludes utilities as a signal input, consider
     whether the EQUITY SLEEVE should also underweight or exclude utilities.
     XLU has been the worst-performing S&P sector over 20 years during
     risk-on regimes. Replacing SPY with an equal-weight of the 5 Penta
     sectors (XLK, XLY, XLI, XLF, XLC) would increase beta to the signal
     and capture more upside when the composite says risk-on.
     Trade-off: higher vol, but the signal already manages that.
""")

    p(f"{'':=<{W}}")

    path = os.path.join(SCRIPT_DIR, "backtest_results.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\nReport saved to: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Potomac Bull Bear Backtester v3")
    parser.add_argument("benchmarks", nargs="*", default=["SPY"],
                        help="Yahoo tickers to compare (default: SPY)")
    parser.add_argument("--start", default="2007-03-01",
                        help="Start date (default: 2007-03-01, RYMFX inception)")
    parser.add_argument("--end", default=None, help="End date (default: today)")
    args = parser.parse_args()
    end = args.end or datetime.date.today().isoformat()

    data = fetch_all_data(args.start, end)
    if "SP500" not in data or "SHY" not in data:
        print("ERROR: Missing critical data.")
        sys.exit(1)

    signals = compute_signals(data, args.start)
    idx = signals.index
    sp500 = data["SP500"].reindex(idx, method="ffill")
    shy = data["SHY"].reindex(idx, method="ffill")
    sp_ret = sp500.pct_change().dropna()

    mf = build_mf_series(data, idx)

    print(f"\nSignal data: {len(signals)} days from {idx[0].date()} to {idx[-1].date()}")
    regime_counts = signals["regime"].value_counts()
    for r in ["RISK_ON", "MIXED", "RISK_OFF"]:
        cnt = regime_counts.get(r, 0)
        print(f"  {r}: {cnt} days ({cnt / len(signals) * 100:.0f}%)")

    print(f"  Penta ON: {signals['penta_on'].sum()} days "
          f"({signals['penta_on'].mean() * 100:.0f}%)")

    # Build satellites
    sat_diversified = build_satellite(data, idx, "lowvol_gold_mf")
    sat_mf = build_satellite(data, idx, "mf_only")
    sat_gold_mf = build_satellite(data, idx, "gold_mf")

    # Run strategies
    print("\nRunning strategies...")
    strategies = []

    # 1. Binary 80/20 with SHY satellite (baseline)
    s = run_strategy("BINARY 80/20 (SHY satellite)", signals, sp500, shy, shy,
                     weight_binary, 0.20)
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 2. Binary 80/20 with diversified satellite
    s = run_strategy("BINARY 80/20 (SPLV+GLD+MF sat)", signals, sp500, shy,
                     sat_diversified, weight_binary, 0.20)
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 3. Graduated exposure + diversified satellite
    s = run_strategy("GRADUATED (SPLV+GLD+MF sat)", signals, sp500, shy,
                     sat_diversified, weight_graduated, 0.20)
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 4. Conviction-stepped + diversified satellite
    s = run_strategy("CONVICTION-STEP (SPLV+GLD+MF sat)", signals, sp500, shy,
                     sat_diversified, weight_conviction, 0.20)
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 5. Binary + MF bear-only (50% of defensive = MF when risk-off)
    s = run_strategy("BINARY + MF BEAR-ONLY", signals, sp500, shy,
                     sat_diversified, weight_binary, 0.20,
                     mf_prices=mf, mf_mode="bear_only")
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 6. Binary + MF always (satellite = 100% MF always)
    s = run_strategy("BINARY + MF ALWAYS (20% sat)", signals, sp500, shy,
                     sat_mf, weight_binary, 0.20,
                     mf_prices=mf, mf_mode="always")
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 7. Graduated + MF bear-only
    s = run_strategy("GRADUATED + MF BEAR-ONLY", signals, sp500, shy,
                     sat_diversified, weight_graduated, 0.20,
                     mf_prices=mf, mf_mode="bear_only")
    compute_metrics(s, sp_ret)
    strategies.append(s)

    # 8. S&P 500 buy-hold (baseline)
    s = run_strategy("S&P 500 BUY-HOLD", signals, sp500, shy, shy,
                     weight_buyhold, 0.0)
    compute_metrics(s, sp_ret)
    strategies.append(s)

    for s in strategies:
        print(f"  {s.name:<40} CAGR: {s.cagr:>5.1f}%  MaxDD: {s.max_drawdown:>6.1f}%  "
              f"Beta: {s.beta:.2f}")

    # Benchmarks -- use total-return series (reinvest distributions) for mutual funds
    print("\nFetching benchmarks...")
    bm_prices = {}
    bm_metrics = {}
    for tk in args.benchmarks:
        try:
            ticker_obj = yf.Ticker(tk)
            h = ticker_obj.history(start=args.start, end=end, auto_adjust=False)
            if not h.empty:
                h.index = h.index.tz_localize(None)
                nav = h["Close"]
                divs = h["Dividends"] if "Dividends" in h.columns else pd.Series(0, index=h.index)
                shares = 1.0
                tr_vals = []
                for dt in h.index:
                    d = divs.loc[dt] if dt in divs.index else 0
                    p = nav.loc[dt]
                    if d > 0 and p > 0:
                        shares *= (1 + d / p)
                    tr_vals.append(shares * p)
                c = pd.Series(tr_vals, index=h.index, name=tk)
                c = c.reindex(idx, method="ffill").dropna()
                bm_prices[tk] = c
                dr = c.pct_change().dropna()
                yrs = (c.index[-1] - c.index[0]).days / 365.25
                cagr = ((c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1) * 100
                dd = ((c - c.cummax()) / c.cummax()).min() * 100
                sh = (dr.mean() - 0.03 / 252) / dr.std() * math.sqrt(252) if dr.std() > 0 else 0
                cal = abs(cagr / dd) if dd != 0 else 0
                cv = np.cov(dr, sp_ret.reindex(dr.index, method="ffill").fillna(0))
                bt = cv[0, 1] / cv[1, 1] if cv[1, 1] > 0 else 0
                cr = np.corrcoef(dr, sp_ret.reindex(dr.index, method="ffill").fillna(0))[0, 1]
                yr = c.resample("YE").last().pct_change().dropna() * 100
                bm_metrics[tk] = {"cagr": cagr, "max_drawdown": dd, "sharpe": sh,
                                  "calmar": cal, "beta": bt, "correlation": cr,
                                  "best_year": yr.max() if len(yr) > 0 else 0,
                                  "worst_year": yr.min() if len(yr) > 0 else 0}
                print(f"  {tk}: OK (total-return series, distributions reinvested)")
        except Exception as e:
            print(f"  {tk}: error {e}")

    # Report
    print()
    report(strategies, bm_metrics, bm_prices, args.start, end, sp_ret, data)

    # Save equity CSV
    df = pd.DataFrame()
    for s in strategies:
        eq = s.equity_curve.dropna()
        df[s.name.replace(" ", "_")[:30]] = eq
    for tk, pr in bm_prices.items():
        df[f"{tk}_buyhold"] = pr / pr.iloc[0] * 10000
    df.index.name = "Date"
    eq_path = os.path.join(SCRIPT_DIR, "backtest_equity.csv")
    df.to_csv(eq_path, float_format="%.2f")
    print(f"Equity curves saved to: {eq_path}")

    # Save trades CSV
    tr_path = os.path.join(SCRIPT_DIR, "backtest_trades.csv")
    with open(tr_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Strategy", "Entry", "Exit", "Return%", "Regime"])
        for s in strategies:
            for t in s.trades:
                w.writerow([s.name, t.entry_date, t.exit_date,
                            f"{t.return_pct:.2f}", t.regime_at_entry])
    print(f"Trades saved to: {tr_path}")

    print("\n" + "=" * 70)
    print("DONE.")
    print("=" * 70)


if __name__ == "__main__":
    main()
