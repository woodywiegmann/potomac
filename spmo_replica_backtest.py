"""
SPMO 50-Stock Replica Backtest (No Tactical Overlay)
====================================================
Builds a monthly-rebalanced 50-stock momentum replica and exports
daily returns versus SPMO since SPMO inception.

Outputs:
  - spmo_replica_daily_returns.csv

Usage:
  python spmo_replica_backtest.py
"""

import io
import os
import time
import warnings
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_HEADERS = {"User-Agent": "PotomacSPMOReplica/1.0"}
OUT_CSV = os.path.join(SCRIPT_DIR, "spmo_replica_daily_returns.csv")
CAPS_CACHE = os.path.join(SCRIPT_DIR, "spmo_replica_market_caps.csv")


@dataclass
class ReplicaConfig:
    n_stocks: int = 50
    lb_6m: int = 126
    lb_12m: int = 252
    warmup_days: int = 380


def get_sp500_tickers() -> list[str]:
    resp = requests.get(SP500_URL, headers=WIKI_HEADERS, timeout=20)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]
    return df["Symbol"].str.replace(".", "-", regex=False).tolist()


def fetch_adjusted_close(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"].copy()
    else:
        px = raw[["Close"]].rename(columns={"Close": tickers[0]})
    return px.ffill()


def fetch_single_adjusted_close(ticker: str, start: str, end: str) -> pd.Series:
    for i in range(6):
        try:
            hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
            if hist.empty:
                return pd.Series(dtype=float, name=ticker)
            hist.index = hist.index.tz_localize(None)
            return hist["Close"].rename(ticker)
        except Exception:
            time.sleep(2 + i * 2)
    return pd.Series(dtype=float, name=ticker)


def fetch_market_caps(tickers: list[str]) -> dict[str, float]:
    if os.path.exists(CAPS_CACHE):
        try:
            cdf = pd.read_csv(CAPS_CACHE)
            cdf = cdf.dropna()
            cached = {
                str(r["ticker"]): float(r["market_cap"])
                for _, r in cdf.iterrows()
                if float(r["market_cap"]) > 0
            }
            if cached:
                return cached
        except Exception:
            pass

    caps: dict[str, float] = {}

    def _one(t: str):
        try:
            info = yf.Ticker(t).info
            cap = info.get("marketCap")
            if cap is not None and cap > 0:
                return t, float(cap)
        except Exception:
            return t, None
        return t, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_one, t) for t in tickers]
        for fut in as_completed(futures):
            t, cap = fut.result()
            if cap is not None:
                caps[t] = cap

    if caps:
        pd.DataFrame({"ticker": list(caps.keys()), "market_cap": list(caps.values())}).to_csv(
            CAPS_CACHE, index=False
        )
    return caps


def score_momentum(prices: pd.DataFrame, asof: pd.Timestamp, cfg: ReplicaConfig) -> pd.DataFrame:
    hist = prices.loc[:asof]
    records = []
    for t in hist.columns:
        s = hist[t].dropna()
        if len(s) < cfg.lb_12m + 1:
            continue
        p_now = s.iloc[-1]
        p_6m = s.iloc[-cfg.lb_6m]
        p_12m = s.iloc[-cfg.lb_12m]
        if p_now <= 0 or p_6m <= 0 or p_12m <= 0:
            continue

        ret_6m = p_now / p_6m - 1.0
        ret_12m = p_now / p_12m - 1.0
        vol_12m = s.pct_change().iloc[-cfg.lb_12m:].std() * np.sqrt(252)
        if not np.isfinite(vol_12m) or vol_12m <= 0:
            continue
        score = 0.5 * (ret_6m / vol_12m) + 0.5 * (ret_12m / vol_12m)
        records.append({"ticker": t, "score": score})

    if not records:
        return pd.DataFrame(columns=["score"]).set_index(pd.Index([], name="ticker"))
    return pd.DataFrame(records).set_index("ticker").sort_values("score", ascending=False)


def build_weights(scores: pd.DataFrame, mkt_caps: dict[str, float], cfg: ReplicaConfig) -> dict[str, float]:
    top = scores.head(cfg.n_stocks).copy()
    if top.empty:
        return {}

    # Cap-aware + momentum-aware blend to better approximate SPMO behavior.
    cap_raw = pd.Series({t: mkt_caps.get(t, 1.0) for t in top.index}, dtype=float)
    cap_w = cap_raw / max(cap_raw.sum(), 1e-12)

    score = top["score"].astype(float)
    score_rank = score.rank(pct=True)
    score_w = score_rank / max(score_rank.sum(), 1e-12)

    w = 0.5 * cap_w + 0.5 * score_w

    # Single-name cap to limit concentration drift.
    max_w = 0.06
    for _ in range(5):
        over = w > max_w
        if not over.any():
            break
        excess = float((w[over] - max_w).sum())
        w[over] = max_w
        under = ~over
        if under.any() and excess > 0:
            w[under] += excess * (w[under] / max(float(w[under].sum()), 1e-12))

    w = w / max(float(w.sum()), 1e-12)
    return {t: float(v) for t, v in w.items()}


def run_replica(prices: pd.DataFrame, mkt_caps: dict[str, float], cfg: ReplicaConfig) -> pd.Series:
    rets = prices.pct_change().fillna(0.0)
    dates = rets.index
    month_ends = dates.to_series().groupby([dates.year, dates.month]).last().tolist()
    month_ends = [d for d in month_ends if d in dates]

    current_w = {}
    out = []
    for i, dt in enumerate(dates):
        if i == 0:
            out.append(0.0)
            continue

        if dt in month_ends:
            scores = score_momentum(prices, dt, cfg)
            current_w = build_weights(scores, mkt_caps, cfg)

        if not current_w:
            out.append(0.0)
            continue

        daily = 0.0
        day_rets = rets.loc[dt]
        for t, w in current_w.items():
            if t in day_rets.index and np.isfinite(day_rets[t]):
                daily += w * float(day_rets[t])
        out.append(daily)

    return pd.Series(out, index=dates, name="replica_ret")


def main():
    cfg = ReplicaConfig()
    print("=" * 70)
    print("SPMO REPLICA (NO OVERLAY): BUILD DAILY RETURN CSV")
    print("=" * 70)

    print("\n1) Loading S&P 500 universe...")
    sp500 = get_sp500_tickers()
    print(f"   Loaded {len(sp500)} tickers.")

    print("\n2) Getting SPMO history...")
    spmo_hist = pd.DataFrame()
    for i in range(6):
        try:
            spmo_hist = yf.Ticker("SPMO").history(period="max", auto_adjust=True)
            if not spmo_hist.empty:
                break
        except Exception:
            time.sleep(2 + i * 2)
    if spmo_hist.empty:
        raise RuntimeError("No SPMO history available from Yahoo.")
    spmo_hist.index = spmo_hist.index.tz_localize(None)
    spmo_start = spmo_hist.index.min().date()
    print(f"   SPMO start date: {spmo_start}")

    start = (spmo_hist.index.min() - pd.Timedelta(days=cfg.warmup_days)).strftime("%Y-%m-%d")
    end = (spmo_hist.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    print("\n3) Downloading stock prices + standalone SPMO...")
    stock_tickers = sorted(set(sp500))
    stock_px = fetch_adjusted_close(stock_tickers, start, end)
    spmo_close = fetch_single_adjusted_close("SPMO", start, end)
    if stock_px.empty or spmo_close.empty:
        raise RuntimeError("Price download failed for stocks or SPMO.")
    print(f"   Stock price matrix shape: {stock_px.shape}")
    print(f"   SPMO close rows: {len(spmo_close)}")

    print("\n4) Fetching market caps for weighting approximation...")
    caps = fetch_market_caps(sp500)
    print(f"   Market caps fetched: {len(caps)}")

    print("\n5) Running monthly 50-stock momentum replica...")
    replica_ret = run_replica(stock_px, caps, cfg)

    print("\n6) Aligning with SPMO since inception and exporting CSV...")
    spmo_ret = spmo_close.pct_change().rename("spmo_ret")
    aligned = pd.concat([replica_ret, spmo_ret], axis=1).dropna()
    aligned = aligned[aligned.index >= spmo_hist.index.min()]
    aligned["active_spread_ret"] = aligned["replica_ret"] - aligned["spmo_ret"]
    aligned = aligned.reset_index().rename(columns={"Date": "date", "index": "date"})
    aligned["date"] = pd.to_datetime(aligned["date"]).dt.date.astype(str)
    aligned.to_csv(OUT_CSV, index=False)

    # Validation summary
    rep = pd.to_numeric(aligned["replica_ret"], errors="coerce")
    spm = pd.to_numeric(aligned["spmo_ret"], errors="coerce")
    act = pd.to_numeric(aligned["active_spread_ret"], errors="coerce")
    corr = rep.corr(spm)
    te_ann = act.std() * np.sqrt(252)
    active_cum = ((1 + rep).prod() / (1 + spm).prod()) - 1.0

    print("\n" + "=" * 70)
    print("TRACKING SUMMARY")
    print("=" * 70)
    print(f"Rows exported:           {len(aligned)}")
    print(f"First output date:       {aligned['date'].iloc[0]}")
    print(f"Replica/SPMO corr:       {corr:.4f}")
    print(f"Tracking error (ann):    {te_ann:.2%}")
    print(f"Cumulative active return:{active_cum:.2%}")
    print(f"Output CSV:              {OUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    main()
