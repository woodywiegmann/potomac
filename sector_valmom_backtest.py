"""
Sector Rotation + Value-Momentum Stock Selection Backtest
==========================================================
Two-layer approach: macro sector momentum on top, micro value-momentum
stock picking underneath. Ride the best sector, own the best stocks inside it.

Layer 1: Rank 11 GICS sector ETFs by composite 3m+6m return relative to SPY.
Layer 2: Within the winning sector(s), rank S&P 500 stocks by value+momentum
         composite with quality gate, select top N equal-weight.

Variants:
  A (base): Top 1 sector, 10 stocks
  B: Top 2 sectors (50/50), 10 stocks each
  C: Top 1 sector, 15 stocks
  D: Top 1 sector, 10 stocks, momentum only (no value)
  E: Top 1 sector, 10 stocks, value only (no momentum)

Usage: python sector_valmom_backtest.py
"""

import io
import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import requests as _requests
import yfinance as yf

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SECTOR_ETFS = {
    "XLK": "Information Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Materials",
    "XLC": "Communication Services",
}

ETF_TO_GICS = {v: k for k, v in SECTOR_ETFS.items()}

START_DATE = "2015-01-01"  # extra lookback for momentum
END_DATE = "2026-03-01"
BT_START = "2016-01-01"
INITIAL_CAPITAL = 100_000
COST_BPS = 5

WIKI_HEADERS = {"User-Agent": "PotomacBacktest/1.0 (woody@potomacfund.com)"}

CORR_PROXIES = {
    "CRDBX Core (SPY)": "SPY",
    "Defensive (BTAL)": "BTAL",
    "Intl Tactical (ACWX)": "ACWX",
    "Gold Digger (GLD)": "GLD",
}

# ── Data fetching ─────────────────────────────────────────────────────────────

def get_sp500_tickers():
    try:
        resp = _requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=WIKI_HEADERS, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        sectors = dict(zip(tickers, df["GICS Sector"]))
        return tickers, sectors
    except Exception as e:
        print(f"  WARNING: S&P 500 fetch failed ({e})")
        return [], {}


def fetch_all_prices(tickers, start, end):
    print(f"  Downloading prices for {len(tickers)} tickers...")
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Close"].ffill()
    return raw[["Close"]].rename(columns={"Close": tickers[0]}).ffill()


def fetch_fundamentals_batch(tickers):
    """Fetch fundamentals for all tickers. Returns dict of ticker -> metrics."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    print(f"  Fetching fundamentals for {len(tickers)} stocks...")
    results = {}
    done = 0
    total = len(tickers)
    t0 = time.time()

    def _fetch_one(t):
        try:
            info = yf.Ticker(t).info
            if not info:
                return t, None
            return t, {
                "pe": info.get("trailingPE"),
                "p_fcf": (info.get("marketCap") or 0) / info.get("freeCashflow", 1)
                         if info.get("freeCashflow") and info.get("freeCashflow") > 0 else None,
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "roe": info.get("returnOnEquity"),
                "debt_equity": info.get("debtToEquity"),
                "trailing_eps": info.get("trailingEps"),
            }
        except Exception:
            return t, None

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        for f in as_completed(futures):
            t, data = f.result()
            done += 1
            if data:
                results[t] = data
            if done % 100 == 0 or done == total:
                elapsed = time.time() - t0
                print(f"    {done}/{total} ({len(results)} valid) [{elapsed:.0f}s]")

    return results

# ── Sector ranking ────────────────────────────────────────────────────────────

def rank_sectors(sector_prices, spy_prices, date, lookbacks_months=(3, 6)):
    """Rank sectors by average relative return over lookback periods."""
    scores = {}
    for etf in SECTOR_ETFS:
        if etf not in sector_prices.columns:
            continue
        rets = []
        for lb_m in lookbacks_months:
            lb_days = lb_m * 21
            hist = sector_prices[etf].loc[:date].dropna()
            spy_hist = spy_prices.loc[:date].dropna()
            if len(hist) < lb_days + 1 or len(spy_hist) < lb_days + 1:
                continue
            etf_ret = hist.iloc[-1] / hist.iloc[-lb_days] - 1.0
            spy_ret = spy_hist.iloc[-1] / spy_hist.iloc[-lb_days] - 1.0
            rets.append(etf_ret - spy_ret)
        if rets:
            scores[etf] = np.mean(rets)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked

# ── Stock selection ───────────────────────────────────────────────────────────

def select_stocks(sector_name, stock_prices, sector_map, fundamentals, date,
                  n_stocks=10, mom_weight=0.5, val_weight=0.5):
    """Select top N stocks from a sector by value+momentum composite."""
    candidates = [t for t, s in sector_map.items()
                  if s == sector_name and t in stock_prices.columns]

    if not candidates:
        return []

    hist = stock_prices[candidates].loc[:date].dropna(how="all")
    if len(hist) < 252:
        return []

    records = []
    for t in candidates:
        series = hist[t].dropna()
        if len(series) < 252:
            continue

        # Quality gate
        fund = fundamentals.get(t, {})
        roe = fund.get("roe")
        de = fund.get("debt_equity")
        eps = fund.get("trailing_eps")

        if roe is not None and roe < 0.10:
            continue
        if de is not None and de > 150:  # yfinance reports D/E as percentage
            continue
        if eps is not None and eps <= 0:
            continue

        # Momentum: 12-1 month return
        if len(series) >= 252 and len(series) >= 21:
            p_12m = series.iloc[-252]
            p_1m = series.iloc[-21]
            if p_12m > 0 and p_1m > 0:
                mom_12_1 = (p_1m / p_12m) - 1.0
            else:
                continue
        else:
            continue

        # Value: composite of P/E, P/FCF, EV/EBITDA (lower = better)
        pe = fund.get("pe")
        p_fcf = fund.get("p_fcf")
        ev_ebitda = fund.get("ev_ebitda")

        records.append({
            "ticker": t,
            "mom_12_1": mom_12_1,
            "pe": pe if pe and pe > 0 else None,
            "p_fcf": p_fcf if p_fcf and p_fcf > 0 else None,
            "ev_ebitda": ev_ebitda if ev_ebitda and ev_ebitda > 0 else None,
        })

    if len(records) < 3:
        return []

    df = pd.DataFrame(records).set_index("ticker")

    # Momentum percentile (higher return = higher rank)
    df["mom_pctile"] = df["mom_12_1"].rank(pct=True) * 100

    # Value percentile for each metric (lower value = higher rank)
    val_pctiles = []
    for col in ["pe", "p_fcf", "ev_ebitda"]:
        valid = df[col].dropna()
        if len(valid) > 0:
            pctile = 100 - valid.rank(pct=True) * 100
            val_pctiles.append(pctile)

    if val_pctiles:
        val_avg = pd.concat(val_pctiles, axis=1).mean(axis=1)
    else:
        val_avg = pd.Series(50, index=df.index)

    df["val_pctile"] = val_avg.reindex(df.index).fillna(50)
    df["composite"] = mom_weight * df["mom_pctile"] + val_weight * df["val_pctile"]

    top = df.sort_values("composite", ascending=False).head(n_stocks)
    return top.index.tolist()

# ── Backtest engine ───────────────────────────────────────────────────────────

def run_backtest(sector_prices, spy_prices, stock_prices, sector_map, fundamentals,
                 n_sectors=1, n_stocks=10, mom_weight=0.5, val_weight=0.5,
                 label="Variant"):
    """Run the full backtest. Returns equity curve, monthly returns, and rotation log."""

    spy_series = spy_prices.copy()
    all_dates = stock_prices.index
    month_ends = all_dates.to_series().groupby([all_dates.year, all_dates.month]).last()
    month_ends = month_ends[month_ends >= pd.Timestamp(BT_START)]

    equity = INITIAL_CAPITAL
    equity_curve = []
    monthly_returns = []
    rotation_log = []
    holdings = {}
    prev_equity = INITIAL_CAPITAL
    total_trades = 0
    total_months = 0
    positive_months = 0
    holding_periods = []
    entry_dates = {}
    tlh_exits = []

    for i, (_, rebal_date) in enumerate(month_ends.items()):
        rebal_date = pd.Timestamp(rebal_date)

        # Layer 1: Rank sectors
        ranked = rank_sectors(sector_prices, spy_series, rebal_date)
        if not ranked:
            equity_curve.append({"date": rebal_date, "equity": equity})
            continue

        top_sectors = ranked[:n_sectors]
        selected_sectors = [(SECTOR_ETFS[etf], score) for etf, score in top_sectors]

        # Layer 2: Select stocks from each sector
        new_holdings = {}
        weight_per_sector = 1.0 / n_sectors

        for sector_name, _ in selected_sectors:
            picks = select_stocks(
                sector_name, stock_prices, sector_map, fundamentals,
                rebal_date, n_stocks=n_stocks,
                mom_weight=mom_weight, val_weight=val_weight
            )
            stock_weight = weight_per_sector / max(len(picks), 1)
            for t in picks:
                new_holdings[t] = stock_weight

        # Track TLH exits (stocks leaving portfolio at a loss)
        for t, w in holdings.items():
            if t not in new_holdings and t in stock_prices.columns:
                price_hist = stock_prices[t].loc[:rebal_date].dropna()
                if len(price_hist) >= 2 and t in entry_dates:
                    entry_price = price_hist.loc[entry_dates[t]] if entry_dates[t] in price_hist.index else price_hist.iloc[-21] if len(price_hist) > 21 else price_hist.iloc[0]
                    exit_price = price_hist.iloc[-1]
                    if isinstance(entry_price, pd.Series):
                        entry_price = entry_price.iloc[0]
                    ret = exit_price / entry_price - 1.0 if entry_price > 0 else 0
                    if ret < -0.02:
                        tlh_exits.append({
                            "date": rebal_date.strftime("%Y-%m-%d"),
                            "ticker": t,
                            "return": f"{ret:.1%}",
                            "sector": sector_map.get(t, ""),
                        })

        # Compute returns for the month
        if i > 0 and holdings:
            prev_date = month_ends.iloc[i - 1]
            port_return = 0.0
            for t, w in holdings.items():
                if t in stock_prices.columns:
                    prices = stock_prices[t]
                    p0 = prices.loc[:prev_date].dropna()
                    p1 = prices.loc[:rebal_date].dropna()
                    if len(p0) > 0 and len(p1) > 0:
                        ret = p1.iloc[-1] / p0.iloc[-1] - 1.0
                        port_return += w * ret
            equity *= (1.0 + port_return)

            # Transaction costs
            trades_this_month = 0
            old_set = set(holdings.keys())
            new_set = set(new_holdings.keys())
            trades_this_month = len(old_set - new_set) + len(new_set - old_set)
            total_trades += trades_this_month
            cost = trades_this_month * (COST_BPS / 10000) * equity
            equity -= cost

            month_ret = equity / prev_equity - 1.0
            monthly_returns.append({"date": rebal_date, "return": month_ret})
            total_months += 1
            if month_ret > 0:
                positive_months += 1
        elif i == 0:
            monthly_returns.append({"date": rebal_date, "return": 0.0})
            total_months += 1

        # Track holding periods
        for t in holdings:
            if t not in new_holdings and t in entry_dates:
                days_held = (rebal_date - entry_dates[t]).days
                holding_periods.append(days_held)
                del entry_dates[t]
        for t in new_holdings:
            if t not in holdings:
                entry_dates[t] = rebal_date

        prev_equity = equity
        holdings = new_holdings

        equity_curve.append({"date": rebal_date, "equity": equity})

        sector_strs = [f"{s}({sc:+.2%})" for s, sc in selected_sectors]
        stock_strs = list(new_holdings.keys())[:5]
        rotation_log.append({
            "date": rebal_date.strftime("%Y-%m-%d"),
            "sectors": ", ".join(sector_strs),
            "n_stocks": len(new_holdings),
            "top_stocks": ", ".join(stock_strs),
            "equity": f"${equity:,.0f}",
        })

    eq_df = pd.DataFrame(equity_curve)
    eq_df.set_index("date", inplace=True)
    mr_df = pd.DataFrame(monthly_returns)
    if not mr_df.empty:
        mr_df.set_index("date", inplace=True)

    # SPY benchmark
    spy_month_ends = spy_series.reindex(eq_df.index, method="ffill").dropna()
    if len(spy_month_ends) > 1:
        spy_start = spy_series.loc[:pd.Timestamp(BT_START)].dropna().iloc[-1]
        spy_equity = [INITIAL_CAPITAL * (p / spy_start) for p in spy_month_ends.values]
        eq_df["spy"] = spy_equity

    # Metrics
    metrics = compute_metrics(eq_df, mr_df, spy_series, total_trades, total_months,
                              positive_months, holding_periods, rotation_log)

    return eq_df, mr_df, pd.DataFrame(rotation_log), metrics, tlh_exits

# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(eq_df, mr_df, spy_prices, total_trades, total_months,
                    positive_months, holding_periods, rotation_log):
    eq = eq_df["equity"]
    years = (eq.index[-1] - eq.index[0]).days / 365.25

    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    max_dd = ((eq / eq.cummax()) - 1).min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else float("inf")

    rets = mr_df["return"] if not mr_df.empty else pd.Series(dtype=float)
    sharpe = (rets.mean() / rets.std() * np.sqrt(12)) if len(rets) > 1 and rets.std() > 0 else 0

    # Beta vs SPY
    spy_monthly = spy_prices.resample("ME").last().pct_change().dropna()
    aligned = pd.concat([rets, spy_monthly.rename("spy")], axis=1).dropna()
    if len(aligned) > 5 and aligned["spy"].var() > 0:
        beta = aligned["return"].cov(aligned["spy"]) / aligned["spy"].var()
    else:
        beta = np.nan

    avg_turnover = total_trades / max(total_months, 1)

    # Sector rotations per year
    sectors_seen = []
    for entry in rotation_log:
        sectors_seen.append(entry["sectors"].split("(")[0].strip())
    rotations = sum(1 for i in range(1, len(sectors_seen)) if sectors_seen[i] != sectors_seen[i - 1])
    rotations_per_year = rotations / years if years > 0 else 0

    avg_holding = np.mean(holding_periods) if holding_periods else 0
    win_rate = positive_months / max(total_months, 1)

    return {
        "Calmar": calmar,
        "CAGR": cagr,
        "Max DD": max_dd,
        "Sharpe": sharpe,
        "Beta": beta,
        "Avg Monthly Turnover (trades)": avg_turnover,
        "Sector Rotations/Year": rotations_per_year,
        "Avg Holding Period (days)": avg_holding,
        "Win Rate": win_rate,
        "Total Return": eq.iloc[-1] / eq.iloc[0] - 1,
        "Final Value": eq.iloc[-1],
    }

# ── Correlation analysis ─────────────────────────────────────────────────────

def correlation_analysis(mr_df, proxy_prices):
    """Compute monthly return correlations vs sleeve proxies."""
    results = {}
    strat_rets = mr_df["return"]

    for label, ticker in CORR_PROXIES.items():
        if ticker not in proxy_prices.columns:
            results[label] = np.nan
            continue
        proxy_monthly = proxy_prices[ticker].resample("ME").last().pct_change().dropna()
        aligned = pd.concat([strat_rets, proxy_monthly.rename("proxy")], axis=1).dropna()
        if len(aligned) > 5:
            results[label] = aligned["return"].corr(aligned["proxy"])
        else:
            results[label] = np.nan

    return results

# ── Output ────────────────────────────────────────────────────────────────────

def print_metrics(metrics, label):
    print(f"\n  {'-' * 50}")
    print(f"  {label}")
    print(f"  {'-' * 50}")
    print(f"  {'Calmar Ratio':<35} {metrics['Calmar']:.2f}")
    print(f"  {'CAGR':<35} {metrics['CAGR']:.2%}")
    print(f"  {'Max Drawdown':<35} {metrics['Max DD']:.2%}")
    print(f"  {'Sharpe Ratio':<35} {metrics['Sharpe']:.2f}")
    print(f"  {'Beta to SPY':<35} {metrics['Beta']:.2f}")
    print(f"  {'Avg Monthly Turnover (trades)':<35} {metrics['Avg Monthly Turnover (trades)']:.1f}")
    print(f"  {'Sector Rotations/Year':<35} {metrics['Sector Rotations/Year']:.1f}")
    print(f"  {'Avg Holding Period (days)':<35} {metrics['Avg Holding Period (days)']:.0f}")
    print(f"  {'Win Rate':<35} {metrics['Win Rate']:.1%}")
    print(f"  {'Total Return':<35} {metrics['Total Return']:.2%}")
    print(f"  {'Final Value':<35} ${metrics['Final Value']:,.0f}")


def print_worst_months(mr_df, n=5):
    if mr_df.empty:
        return
    worst = mr_df.sort_values("return").head(n)
    print(f"\n  WORST {n} MONTHS:")
    print(f"  {'Date':<12} {'Return':>10}")
    print(f"  {'-' * 22}")
    for date, row in worst.iterrows():
        print(f"  {date.strftime('%Y-%m'):<12} {row['return']:>10.2%}")


def print_comparison_table(all_results):
    print(f"\n{'=' * 100}")
    print("  VARIANT COMPARISON")
    print(f"{'=' * 100}")
    print(f"  {'Variant':<30} {'Calmar':>8} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>8} {'Beta':>6} {'WinRate':>8} {'TotRet':>10}")
    print(f"  {'-' * 96}")
    for label, metrics in all_results.items():
        print(f"  {label:<30} {metrics['Calmar']:>8.2f} {metrics['CAGR']:>8.2%} {metrics['Max DD']:>8.2%} "
              f"{metrics['Sharpe']:>8.2f} {metrics['Beta']:>6.2f} {metrics['Win Rate']:>8.1%} {metrics['Total Return']:>10.2%}")


def print_correlations(corr_results):
    print(f"\n  CORRELATION VS EXISTING SLEEVES:")
    print(f"  {'-' * 45}")
    for label, corr in corr_results.items():
        flag = ""
        if not np.isnan(corr):
            if corr > 0.6:
                flag = " *** REDUNDANT"
            elif corr < 0.4:
                flag = " (diversifying)"
        print(f"  {label:<30} {corr:>6.3f}{flag}")


def print_rotation_log(log_df, n=20):
    print(f"\n  SECTOR ROTATION LOG (last {n} months):")
    print(f"  {'Date':<12} {'Sector(s)':<40} {'Stocks':>6} {'Equity':>12}")
    print(f"  {'-' * 72}")
    for _, row in log_df.tail(n).iterrows():
        print(f"  {row['date']:<12} {row['sectors']:<40} {row['n_stocks']:>6} {row['equity']:>12}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  SECTOR ROTATION + VALUE-MOMENTUM STOCK SELECTION")
    print("  Backtest: Jan 2016 — Feb 2026 | $100K | 5bps costs")
    print("=" * 70)

    # 1. Fetch S&P 500 constituents
    print("\n[1/4] Building universe...")
    sp500_tickers, sector_map = get_sp500_tickers()
    if not sp500_tickers:
        print("  ERROR: Could not fetch S&P 500 tickers")
        return
    print(f"    {len(sp500_tickers)} S&P 500 tickers")

    # 2. Download all prices
    print("\n[2/4] Downloading price data...")
    all_tickers = list(set(
        sp500_tickers +
        list(SECTOR_ETFS.keys()) +
        ["SPY"] +
        list(CORR_PROXIES.values())
    ))
    all_prices = fetch_all_prices(all_tickers, START_DATE, END_DATE)
    if all_prices.empty:
        print("  ERROR: No price data")
        return

    sector_prices = all_prices[[c for c in SECTOR_ETFS.keys() if c in all_prices.columns]]
    spy_prices = all_prices["SPY"] if "SPY" in all_prices.columns else pd.Series(dtype=float)
    stock_prices = all_prices[[c for c in sp500_tickers if c in all_prices.columns]]

    print(f"    {len(stock_prices.columns)} stocks, {len(sector_prices.columns)} sector ETFs, {len(all_prices)} trading days")

    # 3. Fetch fundamentals (current snapshot — survivorship bias acknowledged)
    print("\n[3/4] Fetching fundamentals...")
    fundamentals = fetch_fundamentals_batch(list(stock_prices.columns))

    # 4. Run all variants
    print("\n[4/4] Running backtests...")

    variants = {
        "A: Top1 sector, 10 stocks (base)": {"n_sectors": 1, "n_stocks": 10, "mom_weight": 0.5, "val_weight": 0.5},
        "B: Top2 sectors, 10 each": {"n_sectors": 2, "n_stocks": 10, "mom_weight": 0.5, "val_weight": 0.5},
        "C: Top1 sector, 15 stocks": {"n_sectors": 1, "n_stocks": 15, "mom_weight": 0.5, "val_weight": 0.5},
        "D: Top1, mom only (no value)": {"n_sectors": 1, "n_stocks": 10, "mom_weight": 1.0, "val_weight": 0.0},
        "E: Top1, value only (no mom)": {"n_sectors": 1, "n_stocks": 10, "mom_weight": 0.0, "val_weight": 1.0},
    }

    all_metrics = {}
    base_mr = None
    base_eq = None
    base_log = None
    base_tlh = None

    for label, params in variants.items():
        print(f"\n  Running {label}...")
        eq_df, mr_df, log_df, metrics, tlh_exits = run_backtest(
            sector_prices, spy_prices, stock_prices, sector_map, fundamentals,
            **params, label=label
        )
        all_metrics[label] = metrics
        print_metrics(metrics, label)

        if "base" in label.lower():
            base_mr = mr_df
            base_eq = eq_df
            base_log = log_df
            base_tlh = tlh_exits

    # Comparison table
    print_comparison_table(all_metrics)

    # Worst months (base case)
    if base_mr is not None and not base_mr.empty:
        print_worst_months(base_mr)

    # Rotation log
    if base_log is not None:
        print_rotation_log(base_log)

    # Correlation analysis
    if base_mr is not None and not base_mr.empty:
        proxy_prices = all_prices[[c for c in CORR_PROXIES.values() if c in all_prices.columns]]
        corr = correlation_analysis(base_mr, proxy_prices)
        print_correlations(corr)

    # TLH exits
    if base_tlh:
        print(f"\n  TLH HARVEST OPPORTUNITIES ({len(base_tlh)} exits with >2% loss):")
        print(f"  {'Date':<12} {'Ticker':<8} {'Return':>8} {'Sector'}")
        print(f"  {'-' * 50}")
        for entry in base_tlh[-15:]:
            print(f"  {entry['date']:<12} {entry['ticker']:<8} {entry['return']:>8} {entry['sector']}")
        if len(base_tlh) > 15:
            print(f"  ... and {len(base_tlh) - 15} more")

    # Save outputs
    if base_eq is not None:
        eq_path = os.path.join(SCRIPT_DIR, "sector_valmom_equity.csv")
        base_eq.to_csv(eq_path)
        print(f"\n  Equity curve saved to: {eq_path}")

    if base_mr is not None and not base_mr.empty:
        mr_path = os.path.join(SCRIPT_DIR, "sector_valmom_monthly.csv")
        base_mr.to_csv(mr_path)
        print(f"  Monthly returns saved to: {mr_path}")

    if base_log is not None:
        log_path = os.path.join(SCRIPT_DIR, "sector_valmom_rotation_log.csv")
        base_log.to_csv(log_path, index=False)
        print(f"  Rotation log saved to: {log_path}")

    print(f"\n{'=' * 70}")
    print("  DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
