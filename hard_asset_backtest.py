"""
Tactical Hard Asset ETF — Local Python Backtest
================================================
50% COM static + 50% tactical (14-ETF tiered momentum or SHY when COMOD off / <2 qualify).
Monthly rebalance: first trading day of month. COMOD 3/3 bullish = risk on.
Output: equity curve, metrics, optional CSV. Optional benchmark comparison (e.g. PDBC).

  python hard_asset_backtest.py
  python hard_asset_backtest.py --start 2017-01-01 --benchmark PDBC
"""

import argparse
import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("pip install yfinance")

try:
    import pandas_datareader.data as web
    HAS_PDR = True
except Exception:
    HAS_PDR = False

from hard_asset_universe import (
    COM,
    SHY,
    ALL_TACTICAL,
    TACTICAL_TIERS,
    TICKER_TO_TIER,
    COMOD_TICKERS,
)
from comod_signals import comod_risk_on

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(SCRIPT_DIR, "hard_asset_daily_returns.csv")

# Backtest config (overridden by --start / --end when provided)
DEFAULT_START = "2012-01-01"
DEFAULT_END = datetime.now().strftime("%Y-%m-%d")
WARMUP_DAYS = 400
REBAL_LOOKBACK_9M = 189   # ~9 months trading days


def fetch_prices(tickers: list, start: str, end: str) -> pd.DataFrame:
    """Adjusted close for all tickers; columns = tickers, index = date."""
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False, group_by="ticker", threads=True)
    if raw.empty:
        return pd.DataFrame()
    # group_by='ticker' → columns (Ticker, OHLCV); get Close per ticker
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(1):
            close = raw.xs("Close", axis=1, level=1).copy()
        else:
            close = raw.xs(raw.columns.get_level_values(1).unique()[0], axis=1, level=1).copy()
        if len(tickers) == 1:
            close = close.rename(columns={close.columns[0]: tickers[0]})
    else:
        col = "Close" if "Close" in raw.columns else "Adj Close"
        close = raw[[col]].rename(columns={col: tickers[0]})
    close.index = close.index.tz_localize(None) if getattr(close.index, "tz", None) else close.index
    return close.ffill()


def fetch_fred_via_api(series_id: str, start: str, end: str) -> pd.Series | None:
    """Fetch FRED series via REST API. Set FRED_API_KEY in env (free at fred.stlouisfed.org/docs/api)."""
    import urllib.parse
    import urllib.request
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return None
    try:
        params = urllib.parse.urlencode({
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "observation_start": start,
            "observation_end": end,
        })
        url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "PotomacBacktest/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = __import__("json").loads(resp.read().decode("utf-8"))
        obs = data.get("observations", [])
        if not obs:
            return None
        rows = []
        for o in obs:
            v = o.get("value")
            if v is None or v == ".":
                continue
            try:
                rows.append((pd.to_datetime(o["date"]), float(v)))
            except (ValueError, TypeError, KeyError):
                continue
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "value"]).set_index("date").sort_index()
        return df["value"]
    except Exception:
        return None


def fetch_fred_series(series_id: str, start: str, end: str) -> pd.Series | None:
    """Fetch FRED series: try pandas_datareader, then FRED API if FRED_API_KEY is set."""
    if HAS_PDR:
        try:
            df = web.get_data_fred(series_id, start=start, end=end)
            if df is not None and not df.empty:
                s = df.iloc[:, 0] if isinstance(df, pd.DataFrame) else df
                s.index = pd.to_datetime(s.index)
                if getattr(s.index, "tz", None):
                    s.index = s.index.tz_localize(None)
                return s
        except Exception:
            pass
    s = fetch_fred_via_api(series_id, start, end)
    return s


def metrics_from_equity(equity: pd.Series) -> dict:
    """CAGR, max_dd, sharpe, sortino from an equity curve (index = date)."""
    daily_ret = equity.pct_change().dropna()
    if daily_ret.empty:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0, "sortino": 0.0}
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    n_years = max(n_years, 1 / 252)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax
    max_dd = float(dd.min())
    ann = 252
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(ann)) if daily_ret.std() > 0 else 0.0
    downside = daily_ret[daily_ret < 0]
    sortino = (daily_ret.mean() / downside.std() * np.sqrt(ann)) if len(downside) and downside.std() > 0 else 0.0
    return {"cagr": cagr, "max_dd": max_dd, "sharpe": float(sharpe), "sortino": float(sortino), "n_years": n_years}


def first_trading_days_of_month(price_index: pd.DatetimeIndex, start_ts: pd.Timestamp):
    """First trading day in each month on or after start_ts."""
    mask = price_index >= start_ts
    filtered = price_index[mask]
    if len(filtered) == 0:
        return []
    first_per_month = filtered.to_series().groupby([filtered.year, filtered.month]).first()
    return [pd.Timestamp(d) for d in first_per_month.values]


def total_return_9m(prices: pd.DataFrame, ticker: str, as_of: pd.Timestamp) -> float | None:
    """9-month total return for ticker as of date. Uses REBAL_LOOKBACK_9M trading days."""
    if ticker not in prices.columns:
        return None
    s = prices[ticker].loc[:as_of].dropna()
    if len(s) <= REBAL_LOOKBACK_9M:
        return None
    start_price = float(s.iloc[-1 - REBAL_LOOKBACK_9M])
    end_price = float(s.iloc[-1])
    if start_price <= 0:
        return None
    return end_price / start_price - 1


def select_tactical_top4_max2_per_tier(prices: pd.DataFrame, as_of: pd.Timestamp) -> list[str]:
    """
    Rank 14 ETFs by 9m TR; keep only TR > 0; select up to 4 with max 2 per tier (greedy).
    Returns list of tickers (0–4). If <2 qualify, returns [] so caller uses 50% COM / 50% SHY.
    """
    candidates = []
    for t in ALL_TACTICAL:
        tr = total_return_9m(prices, t, as_of)
        if tr is not None and tr > 0:
            candidates.append((t, tr))
    if len(candidates) < 2:
        return []
    candidates.sort(key=lambda x: -x[1])
    selected = []
    tier_count = {1: 0, 2: 0, 3: 0, 4: 0}
    for t, _ in candidates:
        tier = TICKER_TO_TIER.get(t)
        if tier is None or tier_count[tier] >= 2:
            continue
        selected.append(t)
        tier_count[tier] += 1
        if len(selected) >= 4:
            break
    return selected


def run_backtest(start: str | None = None, end: str | None = None, benchmark: str | None = None):
    start = start or DEFAULT_START
    end = end or DEFAULT_END
    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")
    all_tickers = [COM, SHY] + ALL_TACTICAL + ["DBC", "DX-Y.NYB"]
    print("Fetching prices (yfinance)...")
    prices = fetch_prices(all_tickers, fetch_start, end)
    if prices.empty or COM not in prices.columns:
        raise SystemExit("No price data for COM; check start date and tickers.")

    # FRED DFII10 (real rates). Use FRED_API_KEY env var, or pandas-datareader, for full COMOD.
    print("Fetching FRED DFII10...")
    dfii10 = fetch_fred_series("DFII10", fetch_start, end)
    if dfii10 is None or dfii10.empty:
        print("DFII10 unavailable (set FRED_API_KEY or install pandas-datareader); COMOD will carry forward or risk off.")

    # COMOD data container
    comod_data = {
        "dbc": prices[["DBC"]].copy() if "DBC" in prices.columns else None,
        "dfii10": dfii10,
        "dxy": prices[["DX-Y.NYB"]].copy() if "DX-Y.NYB" in prices.columns else None,
    }
    # Align to single calendar
    common = prices.index
    if dfii10 is not None and not dfii10.empty:
        common = common.union(dfii10.index).sort_values()

    start_ts = pd.Timestamp(start)
    rebal_dates = first_trading_days_of_month(prices.index, start_ts)
    rebal_dates = [d for d in rebal_dates if d in prices.index]
    if not rebal_dates:
        raise SystemExit("No rebalance dates in range.")

    # Build weight schedule: for each rebal date, store target weights
    weights_by_date = {}
    prev_risk_on = None
    months_risk_off = 0
    months_tactical = 0

    for rb in rebal_dates:
        risk_on = comod_risk_on(rb, comod_data, prev_risk_on)
        prev_risk_on = risk_on

        if not risk_on:
            weights_by_date[rb] = {COM: 0.5, SHY: 0.5}
            months_risk_off += 1
            continue

        selected = select_tactical_top4_max2_per_tier(prices, rb)
        if len(selected) < 2:
            weights_by_date[rb] = {COM: 0.5, SHY: 0.5}
            months_risk_off += 1
            continue

        months_tactical += 1
        tactical_w = 0.5 / len(selected)
        w = {COM: 0.5}
        for t in selected:
            w[t] = tactical_w
        weights_by_date[rb] = w

    # Daily equity curve: from first rebal to last date; then slice to [start, end] for reporting
    first_rb = min(weights_by_date.keys())
    end_ts = pd.Timestamp(end)
    idx = prices.index[(prices.index >= first_rb) & (prices.index <= end_ts)]
    if idx.empty:
        raise SystemExit("No trading days after first rebalance in range.")
    ret = prices.loc[idx].pct_change().dropna(how="all")
    # Align rebal dates to ret index (use previous close for same-day rebal)
    rebal_list = sorted(weights_by_date.keys())

    equity = pd.Series(index=idx, dtype=float)
    equity.iloc[0] = 1.0
    current_weights = None
    for i in range(1, len(idx)):
        d = idx[i]
        # Update weights on rebalance date (weights apply to close-to-close from this day)
        if d in rebal_list:
            current_weights = weights_by_date[d].copy()
        if current_weights is None:
            current_weights = weights_by_date[rebal_list[0]].copy()

        day_ret = 0.0
        for ticker, w in current_weights.items():
            if ticker in ret.columns and not pd.isna(ret.loc[d, ticker]):
                day_ret += w * ret.loc[d, ticker]
        equity.iloc[i] = equity.iloc[i - 1] * (1 + day_ret)

    # Fill any NaN in equity
    equity = equity.ffill().fillna(1.0)

    # Metrics (strategy)
    m = metrics_from_equity(equity)
    daily_ret = equity.pct_change().dropna()

    print("\n--- Tactical Hard Asset Backtest ---")
    print(f"Start: {equity.index[0].date()}  End: {equity.index[-1].date()}  Years: {m['n_years']:.2f}")
    print(f"CAGR:        {m['cagr']*100:.2f}%")
    print(f"Max Drawdown: {m['max_dd']*100:.2f}%")
    print(f"Sharpe:      {m['sharpe']:.2f}")
    print(f"Sortino:     {m['sortino']:.2f}")
    print(f"Months risk-off (COM+SHY): {months_risk_off}  Months tactical: {months_tactical}")

    # Benchmark comparison (e.g. PDBC) over same period
    if benchmark:
        bench_ticker = benchmark.upper()
        print(f"\nFetching benchmark {bench_ticker}...")
        bench_start = equity.index[0].strftime("%Y-%m-%d")
        bench_end = equity.index[-1].strftime("%Y-%m-%d")
        bench_px = fetch_prices([bench_ticker], bench_start, bench_end)
        if not bench_px.empty and bench_ticker in bench_px.columns:
            # Align to strategy calendar: reindex to strategy index, ffill then bfill so no NaNs
            bench_ret = bench_px[bench_ticker].reindex(equity.index).ffill().bfill().pct_change()
            bench_ret = bench_ret.fillna(0.0)
            bench_ret.iloc[0] = 0.0
            bench_equity = (1 + bench_ret).cumprod()
            bm = metrics_from_equity(bench_equity)
            print(f"\n--- Benchmark: {bench_ticker} (same period) ---")
            print(f"Start: {bench_equity.index[0].date()}  End: {bench_equity.index[-1].date()}  Years: {bm['n_years']:.2f}")
            print(f"CAGR:        {bm['cagr']*100:.2f}%")
            print(f"Max Drawdown: {bm['max_dd']*100:.2f}%")
            print(f"Sharpe:      {bm['sharpe']:.2f}")
            print(f"Sortino:     {bm['sortino']:.2f}")
            print("\n--- Comparison ---")
            print(f"                Strategy   {bench_ticker}")
            print(f"CAGR:           {m['cagr']*100:>6.2f}%    {bm['cagr']*100:>6.2f}%")
            print(f"Max Drawdown:   {m['max_dd']*100:>6.2f}%    {bm['max_dd']*100:>6.2f}%")
            print(f"Sharpe:         {m['sharpe']:>6.2f}     {bm['sharpe']:>6.2f}")
            print(f"Sortino:        {m['sortino']:>6.2f}     {bm['sortino']:>6.2f}")
        else:
            print(f"  Could not load {bench_ticker}; skip benchmark.")

    # CSV: date, portfolio_ret
    out_df = pd.DataFrame({"date": daily_ret.index, "portfolio_ret": daily_ret.values})
    out_df.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")

    return equity, weights_by_date


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tactical Hard Asset ETF backtest")
    parser.add_argument("--start", default=DEFAULT_START, help=f"Backtest start (default {DEFAULT_START})")
    parser.add_argument("--end", default=DEFAULT_END, help="Backtest end (default today)")
    parser.add_argument("--benchmark", default=None, help="Benchmark ticker to compare (e.g. PDBC)")
    args = parser.parse_args()
    run_backtest(start=args.start, end=args.end, benchmark=args.benchmark)
