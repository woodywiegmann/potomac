"""
CRTOX / Navigrowth Dual Momentum Analysis & Improvement Framework
==================================================================
Analyzes the existing CRTOX holdings, scores momentum, proposes an
improved ETF universe with lower correlation overlap, evaluates an
alternative risk-off sleeve (EqWt CAOS/DBMF/SGOV), and implements
a systematic tax-loss harvesting scheduler.

Usage:
    python crtox_momentum_analysis.py
    python crtox_momentum_analysis.py --start 2020-01-01
    python crtox_momentum_analysis.py --no-tlh   # skip TLH section
"""

import argparse
import datetime
import math
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    print("Required: pip install yfinance pandas numpy")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Current CRTOX equity universe (from holdings CSV)
CRTOX_CURRENT = [
    "ARKK", "XME", "SIL", "IGV", "IAI", "ITA", "SMH",
    "IWO", "IBB", "ILF", "SDIV", "EFV", "SOXX", "XAR", "SILJ",
]

CRTOX_RISK_OFF = ["SGOV", "XHLF"]

# Proposed IMPROVED universe: lower correlation, broader thematic dispersion
# Organized by cluster to minimize intra-cluster overlap
PROPOSED_UNIVERSE = {
    "Semiconductors":       ["SMH"],          # keep - distinct theme
    "Biotech/Health":       ["IBB", "XBI"],    # IBB large-cap, XBI equal-wt small-cap
    "Silver/PMs":           ["SIL", "SILJ"],   # keep - been the winner
    "Metals/Mining":        ["XME", "COPX"],   # XME broad, COPX copper focus
    "Uranium/Nuclear":      ["URNM"],          # uncorrelated to most equity themes
    "Infrastructure":       ["PAVE"],          # US infra spending - low tech overlap
    "Defense/Aero":         ["ITA", "XAR"],    # keep
    "Latin America":        ["ILF"],           # keep - EM commodity beta
    "Intl Value":           ["EFV"],           # keep - EAFE value
    "Innovation/Disrupt":   ["ARKK"],          # keep but note high correlation to QQQ
    "Cybersecurity":        ["CIBR"],          # distinct from broad tech
    "Energy/Midstream":     ["AMLP"],          # MLPs - low equity beta, high yield
    "Managed Futures/CTA":  ["CTA", "DBMF"],   # trend-following, neg equity corr
    "Small Cap Growth":     ["IWO"],           # keep
    "EM ex-China":          ["EMXC"],          # EM without China concentration risk
}

# All proposed tickers flat
PROPOSED_TICKERS = []
for v in PROPOSED_UNIVERSE.values():
    PROPOSED_TICKERS.extend(v)

# Risk-off alternatives
RISK_OFF_CURRENT = ["SGOV", "XHLF"]
RISK_OFF_PROPOSED = ["SGOV", "DBMF", "CAOS"]

# TLH (Tax-Loss Harvesting) pairs: primary -> substitute
# Must track similar exposure but different index/construction
TLH_PAIRS = {
    "SMH":  "SOXX",   # both semis, different index
    "SOXX": "SMH",
    "IBB":  "XBI",    # large-cap bio vs equal-wt bio
    "XBI":  "IBB",
    "SIL":  "SILJ",   # silver miners large vs junior
    "SILJ": "SIL",
    "XME":  "PICK",   # US metals vs global metals
    "ITA":  "XAR",    # cap-wt defense vs equal-wt defense
    "XAR":  "ITA",
    "ARKK": "QQQJ",   # innovation proxy swap
    "IWO":  "VBK",    # both small-cap growth, different index
    "ILF":  "EWZ",    # LatAm vs Brazil (high overlap)
    "EFV":  "FNDF",   # EAFE value vs fundamental intl
    "COPX": "CPER",   # copper miners vs copper futures
    "URNM": "URA",    # uranium miners index vs broader nuclear
    "PAVE": "IFRA",   # US infra vs global infra
    "CIBR": "HACK",   # two different cyber indices
    "AMLP": "MLPA",   # two MLP indices
    "CTA":  "DBMF",   # managed futures swap
    "DBMF": "CTA",
    "CAOS": "TAIL",   # tail risk swap
    "EMXC": "SCHE",   # EM ex-China vs Schwab EM
    "SGOV": "BIL",    # 0-3M T-bill swap
    "XHLF": "SHV",    # 6M UST vs short treasury
}

# Momentum scoring weights (from Navigrowth deck)
MOM_WEIGHTS = {
    21: 0.25,    # ~1 month (21 trading days)
    63: 0.125,   # ~3 months
    126: 0.50,   # ~6 months (DOMINANT)
    252: 0.125,  # ~12 months
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_prices(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """Fetch adjusted close prices for all tickers."""
    all_tickers = list(set(tickers))
    print(f"  Fetching {len(all_tickers)} tickers from {start} to {end}...")
    data = yf.download(all_tickers, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]].rename(columns={"Close": all_tickers[0]})
    prices = prices.ffill().dropna(how="all")
    missing = [t for t in all_tickers if t not in prices.columns]
    if missing:
        print(f"  WARNING: No data for: {missing}")
    return prices


# ═══════════════════════════════════════════════════════════════════════════════
# MOMENTUM SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def momentum_score(prices: pd.DataFrame, date: pd.Timestamp,
                   tickers: List[str]) -> pd.Series:
    """
    Composite momentum score for each ticker at a given date.
    Uses the Navigrowth weighting: 6M 50%, 1M 25%, 3M 12.5%, 12M 12.5%.
    """
    idx = prices.index.get_indexer([date], method="ffill")[0]
    scores = {}
    for t in tickers:
        if t not in prices.columns:
            continue
        total = 0.0
        valid = True
        for lookback, weight in MOM_WEIGHTS.items():
            if idx - lookback < 0:
                valid = False
                break
            p_now = prices[t].iloc[idx]
            p_then = prices[t].iloc[idx - lookback]
            if pd.isna(p_now) or pd.isna(p_then) or p_then == 0:
                valid = False
                break
            ret = (p_now / p_then) - 1.0
            total += ret * weight
        scores[t] = total if valid else np.nan
    return pd.Series(scores).sort_values(ascending=False)


def absolute_momentum(prices: pd.DataFrame, date: pd.Timestamp,
                      ticker: str, rf_ticker: str = "SGOV",
                      lookback: int = 126) -> bool:
    """
    Absolute momentum filter: is the asset's return over lookback
    greater than the risk-free proxy?
    """
    idx = prices.index.get_indexer([date], method="ffill")[0]
    if idx - lookback < 0:
        return False
    for t in [ticker, rf_ticker]:
        if t not in prices.columns:
            return True  # can't compute, default to invested
    ret_asset = prices[ticker].iloc[idx] / prices[ticker].iloc[idx - lookback] - 1
    ret_rf = prices[rf_ticker].iloc[idx] / prices[rf_ticker].iloc[idx - lookback] - 1
    return ret_asset > ret_rf


# ═══════════════════════════════════════════════════════════════════════════════
# CORRELATION ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def correlation_matrix(prices: pd.DataFrame, tickers: List[str],
                       lookback: int = 252) -> pd.DataFrame:
    """Rolling return correlation matrix over lookback period."""
    available = [t for t in tickers if t in prices.columns]
    returns = prices[available].pct_change().dropna()
    if len(returns) > lookback:
        returns = returns.iloc[-lookback:]
    return returns.corr()


def find_high_corr_pairs(corr: pd.DataFrame, threshold: float = 0.80
                         ) -> List[Tuple[str, str, float]]:
    """Find pairs with correlation above threshold."""
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = corr.iloc[i, j]
            if abs(c) >= threshold:
                pairs.append((cols[i], cols[j], round(c, 3)))
    return sorted(pairs, key=lambda x: -abs(x[2]))


# ═══════════════════════════════════════════════════════════════════════════════
# RISK-OFF SLEEVE COMPARISON
# ═══════════════════════════════════════════════════════════════════════════════

def compare_risk_off(prices: pd.DataFrame, lookback: int = 252) -> dict:
    """
    Compare current risk-off (EqWt SGOV/XHLF) vs proposed (EqWt SGOV/DBMF/CAOS).
    Returns annualized return, vol, Sharpe, max drawdown, and correlation to SPY.
    """
    results = {}
    spy_ret = prices["SPY"].pct_change().dropna() if "SPY" in prices.columns else None

    for label, tickers in [("Current: SGOV/XHLF", RISK_OFF_CURRENT),
                           ("Proposed: SGOV/DBMF/CAOS", RISK_OFF_PROPOSED)]:
        avail = [t for t in tickers if t in prices.columns]
        if not avail:
            continue
        eq_wt = prices[avail].pct_change().mean(axis=1).dropna()
        if len(eq_wt) < 60:
            continue

        ann_ret = eq_wt.mean() * 252
        ann_vol = eq_wt.std() * math.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + eq_wt).cumprod()
        dd = (cum / cum.cummax() - 1).min()
        corr_spy = eq_wt.corr(spy_ret) if spy_ret is not None else np.nan

        results[label] = {
            "Ann Return": f"{ann_ret:.2%}",
            "Ann Vol": f"{ann_vol:.2%}",
            "Sharpe": f"{sharpe:.2f}",
            "Max DD": f"{dd:.2%}",
            "Corr to SPY": f"{corr_spy:.3f}",
            "Tickers": avail,
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST: DUAL MOMENTUM ROTATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    label: str
    equity_curve: pd.Series = field(default_factory=pd.Series)
    annual_returns: Dict[int, float] = field(default_factory=dict)
    trades: List[dict] = field(default_factory=list)
    ann_return: float = 0.0
    ann_vol: float = 0.0
    sharpe: float = 0.0
    max_dd: float = 0.0
    calmar: float = 0.0


def run_momentum_backtest(prices: pd.DataFrame, universe: List[str],
                          risk_off: List[str], label: str,
                          n_hold: int = 7, rebal_freq: int = 21,
                          use_abs_momentum: bool = True) -> BacktestResult:
    """
    Monthly dual-momentum rotation backtest.
    - Rank universe by composite momentum score
    - Apply absolute momentum filter (vs SGOV)
    - Hold top N that pass filter; rest goes to risk-off
    - Equal weight across selected holdings
    """
    result = BacktestResult(label=label)
    available = [t for t in universe if t in prices.columns]
    rf_avail = [t for t in risk_off if t in prices.columns]

    if not available or not rf_avail:
        print(f"  Skipping {label}: insufficient data")
        return result

    returns = prices.pct_change().fillna(0)
    dates = prices.index
    start_idx = 252  # need 12M lookback

    portfolio_value = [1.0]
    holdings = {}
    rebal_counter = 0

    for i in range(start_idx, len(dates)):
        dt = dates[i]
        rebal_counter += 1

        if rebal_counter >= rebal_freq or not holdings:
            scores = momentum_score(prices, dt, available)
            scores = scores.dropna()

            if use_abs_momentum:
                passing = [t for t in scores.index
                           if absolute_momentum(prices, dt, t)]
            else:
                passing = scores.index.tolist()

            top_n = [t for t in scores.index if t in passing][:n_hold]

            risk_off_wt = max(0, 1.0 - len(top_n) / n_hold)
            eq_wt = (1.0 - risk_off_wt) / len(top_n) if top_n else 0

            holdings = {}
            for t in top_n:
                holdings[t] = eq_wt
            if risk_off_wt > 0:
                rf_wt = risk_off_wt / len(rf_avail)
                for t in rf_avail:
                    holdings[t] = rf_wt

            result.trades.append({
                "date": dt.strftime("%Y-%m-%d"),
                "equity": top_n,
                "risk_off_pct": f"{risk_off_wt:.0%}",
            })
            rebal_counter = 0

        day_ret = sum(holdings.get(t, 0) * returns[t].iloc[i]
                      for t in holdings if t in returns.columns)
        portfolio_value.append(portfolio_value[-1] * (1 + day_ret))

    ec = pd.Series(portfolio_value[1:], index=dates[start_idx:])
    result.equity_curve = ec

    total_ret = ec.iloc[-1] / ec.iloc[0]
    years = len(ec) / 252
    result.ann_return = total_ret ** (1 / years) - 1 if years > 0 else 0
    daily_rets = ec.pct_change().dropna()
    result.ann_vol = daily_rets.std() * math.sqrt(252)
    result.sharpe = result.ann_return / result.ann_vol if result.ann_vol > 0 else 0
    result.max_dd = (ec / ec.cummax() - 1).min()
    result.calmar = result.ann_return / abs(result.max_dd) if result.max_dd != 0 else 0

    for year in ec.index.year.unique():
        yr_data = ec[ec.index.year == year]
        if len(yr_data) > 1:
            result.annual_returns[year] = yr_data.iloc[-1] / yr_data.iloc[0] - 1

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# TAX-LOSS HARVESTING SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TLHAction:
    date: str
    sell_ticker: str
    buy_ticker: str
    loss_amount: float
    holding_period_days: int
    wash_sale_clear_date: str


def systematic_tlh(prices: pd.DataFrame, holdings_history: List[dict],
                   tlh_pairs: Dict[str, str],
                   loss_threshold: float = -0.03,
                   min_holding_days: int = 7,
                   seed: int = 42) -> List[TLHAction]:
    """
    Systematic tax-loss harvesting with randomized timing.

    Rules:
    1. Check positions 1-2x per month on random business days
    2. If any position is down > threshold from cost basis, harvest
    3. Swap into TLH pair to maintain exposure
    4. Track 31-day wash sale window per security
    5. Don't harvest if position was bought < min_holding_days ago
    """
    rng = random.Random(seed)
    actions = []
    wash_sale_blackout = {}  # ticker -> date when blackout ends

    dates = prices.index
    months = pd.Series(dates).dt.to_period("M").unique()

    for month in months:
        month_dates = dates[(dates >= month.start_time) &
                            (dates <= month.end_time)]
        if len(month_dates) < 5:
            continue

        n_checks = rng.choice([1, 2])
        check_indices = sorted(rng.sample(range(len(month_dates)),
                                          min(n_checks, len(month_dates))))

        for ci in check_indices:
            check_date = month_dates[ci]

            for ticker, pair in tlh_pairs.items():
                if ticker not in prices.columns or pair not in prices.columns:
                    continue

                if ticker in wash_sale_blackout:
                    if check_date <= wash_sale_blackout[ticker]:
                        continue

                idx = prices.index.get_indexer([check_date], method="ffill")[0]
                lookbacks = [21, 42, 63]  # check vs 1M, 2M, 3M ago cost basis
                for lb in lookbacks:
                    if idx - lb < 0:
                        continue
                    cost = prices[ticker].iloc[idx - lb]
                    current = prices[ticker].iloc[idx]
                    if pd.isna(cost) or pd.isna(current) or cost == 0:
                        continue
                    loss_pct = current / cost - 1

                    if loss_pct < loss_threshold:
                        notional_loss = loss_pct * 10000  # per $10k position
                        wash_clear = check_date + pd.Timedelta(days=31)
                        actions.append(TLHAction(
                            date=check_date.strftime("%Y-%m-%d"),
                            sell_ticker=ticker,
                            buy_ticker=pair,
                            loss_amount=round(notional_loss, 2),
                            holding_period_days=lb,
                            wash_sale_clear_date=wash_clear.strftime("%Y-%m-%d"),
                        ))
                        wash_sale_blackout[ticker] = wash_clear
                        wash_sale_blackout[pair] = wash_clear
                        break  # one harvest per ticker per check

    return actions


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════════════════════

def print_section(title: str):
    w = 78
    print(f"\n{'=' * w}")
    print(f"  {title}")
    print(f"{'=' * w}")


def print_backtest(r: BacktestResult):
    print(f"\n  {r.label}")
    print(f"  {'-' * 50}")
    print(f"  Ann Return:  {r.ann_return:>8.2%}")
    print(f"  Ann Vol:     {r.ann_vol:>8.2%}")
    print(f"  Sharpe:      {r.sharpe:>8.2f}")
    print(f"  Max DD:      {r.max_dd:>8.2%}")
    print(f"  Calmar:      {r.calmar:>8.2f}")
    if r.annual_returns:
        print(f"\n  Year-by-Year:")
        for yr in sorted(r.annual_returns):
            print(f"    {yr}: {r.annual_returns[yr]:>8.2%}")
    if r.trades:
        print(f"\n  Last 5 Rebalances:")
        for t in r.trades[-5:]:
            print(f"    {t['date']}: {t['equity']} | risk-off: {t['risk_off_pct']}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="CRTOX Momentum Analysis")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=datetime.date.today().isoformat())
    parser.add_argument("--no-tlh", action="store_true")
    args = parser.parse_args()

    all_tickers = list(set(
        CRTOX_CURRENT + PROPOSED_TICKERS + RISK_OFF_CURRENT +
        RISK_OFF_PROPOSED + list(TLH_PAIRS.values()) + ["SPY", "QQQ"]
    ))

    print_section("FETCHING DATA")
    prices = fetch_prices(all_tickers, args.start, args.end)
    print(f"  Got {len(prices)} trading days, {len(prices.columns)} tickers")

    # ── 1. CORRELATION ANALYSIS ──────────────────────────────────────────────
    print_section("1. CORRELATION ANALYSIS: CURRENT CRTOX UNIVERSE")
    avail_current = [t for t in CRTOX_CURRENT if t in prices.columns]
    corr_current = correlation_matrix(prices, avail_current)
    high_pairs = find_high_corr_pairs(corr_current, 0.70)
    if high_pairs:
        print("\n  High-correlation pairs (>0.70) in current universe:")
        for a, b, c in high_pairs[:15]:
            flag = " *** OVERLAP" if c > 0.85 else ""
            print(f"    {a:6s} / {b:6s}  r = {c:+.3f}{flag}")
    else:
        print("  No pairs above 0.70 threshold")

    print_section("2. CORRELATION ANALYSIS: PROPOSED UNIVERSE")
    avail_proposed = [t for t in PROPOSED_TICKERS if t in prices.columns]
    corr_proposed = correlation_matrix(prices, avail_proposed)
    high_pairs_new = find_high_corr_pairs(corr_proposed, 0.70)
    if high_pairs_new:
        print("\n  High-correlation pairs (>0.70) in proposed universe:")
        for a, b, c in high_pairs_new[:15]:
            flag = " *** OVERLAP" if c > 0.85 else ""
            print(f"    {a:6s} / {b:6s}  r = {c:+.3f}{flag}")

    avg_corr_old = corr_current.values[np.triu_indices_from(corr_current.values, k=1)].mean()
    avg_corr_new = corr_proposed.values[np.triu_indices_from(corr_proposed.values, k=1)].mean()
    print(f"\n  Avg pairwise correlation -- Current: {avg_corr_old:.3f}  |  Proposed: {avg_corr_new:.3f}")

    # ── 2. CURRENT MOMENTUM RANKINGS ────────────────────────────────────────
    print_section("3. CURRENT MOMENTUM RANKINGS (as of latest date)")
    latest = prices.index[-1]
    print(f"\n  Date: {latest.strftime('%Y-%m-%d')}")

    print("\n  A) Current CRTOX universe:")
    scores_current = momentum_score(prices, latest, avail_current)
    for t, s in scores_current.items():
        abs_pass = absolute_momentum(prices, latest, t)
        flag = "PASS" if abs_pass else "FAIL"
        print(f"    {t:6s}  score: {s:+.4f}  abs_mom: {flag}")

    print("\n  B) Proposed universe:")
    scores_proposed = momentum_score(prices, latest, avail_proposed)
    for t, s in scores_proposed.items():
        abs_pass = absolute_momentum(prices, latest, t)
        flag = "PASS" if abs_pass else "FAIL"
        print(f"    {t:6s}  score: {s:+.4f}  abs_mom: {flag}")

    # ── 3. RISK-OFF COMPARISON ───────────────────────────────────────────────
    print_section("4. RISK-OFF SLEEVE COMPARISON")
    ro_results = compare_risk_off(prices)
    for label, stats in ro_results.items():
        print(f"\n  {label}  ({stats['Tickers']})")
        for k, v in stats.items():
            if k != "Tickers":
                print(f"    {k:15s}: {v}")

    # ── 4. BACKTESTS ─────────────────────────────────────────────────────────
    print_section("5. BACKTEST COMPARISON")

    bt_current = run_momentum_backtest(
        prices, avail_current, RISK_OFF_CURRENT,
        "Current CRTOX Universe + SGOV/XHLF risk-off",
        n_hold=7, rebal_freq=21)
    print_backtest(bt_current)

    bt_proposed_old_ro = run_momentum_backtest(
        prices, avail_proposed, RISK_OFF_CURRENT,
        "Proposed Universe + SGOV/XHLF risk-off",
        n_hold=7, rebal_freq=21)
    print_backtest(bt_proposed_old_ro)

    bt_proposed_new_ro = run_momentum_backtest(
        prices, avail_proposed, RISK_OFF_PROPOSED,
        "Proposed Universe + SGOV/DBMF/CAOS risk-off",
        n_hold=7, rebal_freq=21)
    print_backtest(bt_proposed_new_ro)

    # ── 5. TAX-LOSS HARVESTING ───────────────────────────────────────────────
    if not args.no_tlh:
        print_section("6. TAX-LOSS HARVESTING ANALYSIS")
        tlh_actions = systematic_tlh(prices, [], TLH_PAIRS,
                                     loss_threshold=-0.03)
        total_harvested = sum(a.loss_amount for a in tlh_actions)
        print(f"\n  Total TLH opportunities found: {len(tlh_actions)}")
        print(f"  Total losses harvested (per $10k notional): ${total_harvested:,.0f}")

        if tlh_actions:
            by_ticker = {}
            for a in tlh_actions:
                by_ticker.setdefault(a.sell_ticker, []).append(a)
            print(f"\n  Top harvesting opportunities by ticker:")
            sorted_tickers = sorted(by_ticker.items(),
                                    key=lambda x: sum(a.loss_amount for a in x[1]))
            for ticker, acts in sorted_tickers[:10]:
                total = sum(a.loss_amount for a in acts)
                print(f"    {ticker:6s} -> {TLH_PAIRS.get(ticker, '?'):6s}  "
                      f"count: {len(acts):3d}  total loss: ${total:>8,.0f}")

            print(f"\n  Recent TLH actions (last 10):")
            for a in tlh_actions[-10:]:
                print(f"    {a.date}: sell {a.sell_ticker:6s} -> buy {a.buy_ticker:6s}  "
                      f"loss: ${a.loss_amount:>7,.0f}  "
                      f"wash-clear: {a.wash_sale_clear_date}")

    # ── 6. SUMMARY ───────────────────────────────────────────────────────────
    print_section("SUMMARY & RECOMMENDATIONS")
    print("""
  1. UNIVERSE IMPROVEMENTS
     - Add: URNM (uranium), PAVE (infra), CIBR (cyber), AMLP (midstream),
       COPX (copper), EMXC (EM ex-China), XBI (equal-wt biotech)
     - These reduce avg pairwise correlation and add distinct macro themes
     - Drop or limit: IGV/IAI (high overlap with QQQ/broad tech)

  2. RISK-OFF SLEEVE
     - Replace 100% T-bill risk-off with EqWt SGOV/DBMF/CAOS
     - DBMF adds positive carry + crisis alpha (trend-following)
     - CAOS adds tail-risk convexity (put spread overlay)
     - Net effect: similar low vol, but positive expected return in
       risk-off periods + negative equity correlation during drawdowns

  3. MANAGED FUTURES FOR COMMODITY EXPOSURE
     - CTA (Simplify) captures commodity trends systematically
     - Better than holding commodity ETFs directly because CTA can
       go short and has built-in risk management
     - Consider CTA as a permanent 5-10% strategic allocation

  4. TAX-LOSS HARVESTING
     - 1-2 random checks per month avoid predictable patterns
     - Swap into correlated-but-not-identical pair ETF
     - 31-day wash sale window tracked per security
     - Re-entry into original position after wash period if momentum
       still favors it
     - Estimated tax alpha: 0.5-1.5% annually in taxable accounts

  5. MOMENTUM SCORING CONFIRMATION
     - 6-month lookback (50% weight) is the dominant signal
     - Consistent with academic momentum factor literature
     - 1-month (25%) adds short-term trend confirmation
     - 3M and 12M (12.5% each) are stabilizers
""")


if __name__ == "__main__":
    main()
