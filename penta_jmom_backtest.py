"""
Penta Factor Rotation Backtest: Momentum vs Low-Vol
=====================================================
Always invested. Penta signal rotates between factor portfolios:
  RISK ON  -> JMOM replica (50 highest-momentum S&P 500 stocks)
  RISK OFF -> SPLV replica (50 lowest-volatility S&P 500 stocks)

No leverage. No CAOS. No cash. Just factor rotation.

Variants:
  A (base): Penta rotation (JMOM risk-on / SPLV risk-off)
  B: JMOM only (always momentum, control group)
  C: SPLV only (always low-vol, control group)

Usage: python penta_jmom_backtest.py
"""

import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from jmom_replica import get_sp500_tickers, select_portfolio, N_STOCKS as JMOM_N
from splv_replica import select_low_vol_portfolio, N_STOCKS as SPLV_N
from penta_signals import get_regime, RISK_ON, RISK_OFF, REQUIRED_TICKERS

warnings.filterwarnings("ignore")

START_DATE = "2019-06-01"
END_DATE = "2026-03-01"
BT_START = "2020-09-01"
INITIAL_CAPITAL = 100_000
SLIPPAGE_BPS = 10

CORR_PROXIES = {"CRDBX (SPY)": "SPY", "Defensive (BTAL)": "BTAL",
                "Intl Tactical (ACWX)": "ACWX", "Gold Digger (GLD)": "GLD"}

HTML_OUT = os.path.join(SCRIPT_DIR, "penta_jmom_dashboard.html")

# ── Data ──────────────────────────────────────────────────────────────────────

def fetch_all_data(sp500_tickers):
    extra = list(REQUIRED_TICKERS) + ["JMOM", "SPLV", "BTAL", "ACWX", "GLD"]
    all_t = list(set(sp500_tickers + extra))
    print(f"  Downloading prices for {len(all_t)} tickers...")
    raw = yf.download(all_t, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Close"].ffill()
    return raw[["Close"]].rename(columns={"Close": all_t[0]}).ffill()


def fetch_fundamentals_fast(tickers):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    results = {}
    done = 0
    total = len(tickers)
    t0 = time.time()

    def _f(t):
        try:
            info = yf.Ticker(t).info
            if not info:
                return t, None
            return t, {"roe": info.get("returnOnEquity"),
                       "debt_equity": info.get("debtToEquity"),
                       "trailing_eps": info.get("trailingEps")}
        except Exception:
            return t, None

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_f, t): t for t in tickers}
        for f in as_completed(futures):
            t, data = f.result()
            done += 1
            if data:
                results[t] = data
            if done % 100 == 0 or done == total:
                print(f"    {done}/{total} ({len(results)} valid) [{time.time()-t0:.0f}s]")
    return results

# ── Backtest engine ───────────────────────────────────────────────────────────

def run_variant(prices, sp500_tickers, sector_map, fundamentals,
                mode="rotation", label="A"):
    """
    mode: "rotation" (Penta switches JMOM/SPLV), "jmom_only", "splv_only"
    """
    spy = prices["SPY"] if "SPY" in prices.columns else None
    jmom_etf = prices["JMOM"] if "JMOM" in prices.columns else None
    splv_etf = prices["SPLV"] if "SPLV" in prices.columns else None

    price_dict = {col: prices[col] for col in prices.columns}

    bt_dates = prices.index[prices.index >= pd.Timestamp(BT_START)]
    if len(bt_dates) == 0:
        return None

    month_ends = bt_dates.to_series().groupby([bt_dates.year, bt_dates.month]).last().values
    month_end_set = set(pd.Timestamp(d) for d in month_ends)

    equity = INITIAL_CAPITAL
    holdings = {}
    active_factor = RISK_ON
    entry_prices = {}

    equity_curve = []
    regime_log = []
    transitions = []
    tlh_log = []
    jmom_days = 0
    jmom_return_sum = 0.0
    splv_days = 0
    splv_return_sum = 0.0

    for i, date in enumerate(bt_dates):
        date = pd.Timestamp(date)

        # Determine which factor should be active
        if mode == "jmom_only":
            target_factor = RISK_ON
        elif mode == "splv_only":
            target_factor = RISK_OFF
        else:
            target_factor, signals = get_regime(price_dict, date)

        # Factor switch
        if target_factor != active_factor or (i == 0 and not holdings):
            if holdings and target_factor != active_factor:
                cost = abs(equity * SLIPPAGE_BPS / 10000)
                equity -= cost

                for t in list(holdings.keys()):
                    if t in prices.columns and t in entry_prices:
                        cur_p = prices[t].loc[:date].dropna()
                        if len(cur_p) > 0 and entry_prices.get(t, 0) > 0:
                            ret = cur_p.iloc[-1] / entry_prices[t] - 1.0
                            if ret < -0.02:
                                tlh_log.append({"date": date.strftime("%Y-%m-%d"),
                                                "ticker": t, "return": f"{ret:.1%}",
                                                "sector": sector_map.get(t, "")})

                transitions.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "direction": f"{'MOMENTUM' if active_factor == RISK_ON else 'LOW-VOL'} -> {'MOMENTUM' if target_factor == RISK_ON else 'LOW-VOL'}",
                    "equity": f"${equity:,.0f}",
                })

            active_factor = target_factor

            if active_factor == RISK_ON:
                port, _ = select_portfolio(prices, fundamentals, date, sp500_tickers, JMOM_N)
            else:
                port, _ = select_low_vol_portfolio(prices, date, sp500_tickers, SPLV_N)

            holdings = {t: w for t, w in port}
            entry_prices = {}
            for t in holdings:
                cp = prices[t].loc[:date].dropna()
                if len(cp) > 0:
                    entry_prices[t] = cp.iloc[-1]

        # Monthly rebalance (reconstitute active factor)
        elif date in month_end_set:
            if active_factor == RISK_ON:
                port, _ = select_portfolio(prices, fundamentals, date, sp500_tickers, JMOM_N)
            else:
                port, _ = select_low_vol_portfolio(prices, date, sp500_tickers, SPLV_N)

            old_set = set(holdings.keys())
            new_set = set(t for t, w in port)
            trades = len(old_set - new_set) + len(new_set - old_set)
            cost = trades * (SLIPPAGE_BPS / 10000) * equity * (1.0 / max(len(new_set), 1))
            equity -= cost

            holdings = {t: w for t, w in port}
            for t in holdings:
                if t not in entry_prices:
                    cp = prices[t].loc[:date].dropna()
                    if len(cp) > 0:
                        entry_prices[t] = cp.iloc[-1]

        # Daily return
        if i > 0 and holdings:
            prev_date = bt_dates[i - 1]
            daily_ret = 0.0
            for t, w in holdings.items():
                if t in prices.columns:
                    p0 = prices[t].loc[:prev_date].dropna()
                    p1 = prices[t].loc[:date].dropna()
                    if len(p0) > 0 and len(p1) > 0:
                        daily_ret += w * (p1.iloc[-1] / p0.iloc[-1] - 1.0)

            equity *= (1.0 + daily_ret)

            if active_factor == RISK_ON:
                jmom_days += 1
                jmom_return_sum += daily_ret
            else:
                splv_days += 1
                splv_return_sum += daily_ret

        factor_label = "MOMENTUM" if active_factor == RISK_ON else "LOW-VOL"
        equity_curve.append({"date": date, "equity": equity, "factor": factor_label})

        if mode == "rotation":
            sig_str = "; ".join([f"{k}: {'ON' if v['bullish'] else 'OFF'}" for k, v in signals.items()])
        else:
            sig_str = f"Fixed: {mode}"
        regime_log.append({"date": date.strftime("%Y-%m-%d"), "factor": factor_label,
                           "signals": sig_str, "equity": f"${equity:,.0f}"})

    eq_df = pd.DataFrame(equity_curve).set_index("date")

    # Benchmarks
    for bench_name, bench_series in [("spy", spy), ("jmom_etf", jmom_etf), ("splv_etf", splv_etf)]:
        if bench_series is not None:
            bench_bt = bench_series.reindex(eq_df.index, method="ffill").dropna()
            if len(bench_bt) > 1:
                eq_df[bench_name] = INITIAL_CAPITAL * (bench_bt / bench_bt.iloc[0])

    metrics = compute_metrics(eq_df, spy, transitions, jmom_days, jmom_return_sum,
                              splv_days, splv_return_sum)
    return eq_df, pd.DataFrame(regime_log), pd.DataFrame(transitions), tlh_log, metrics

# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(eq_df, spy_prices, transitions, jmom_days, jmom_ret_sum,
                    splv_days, splv_ret_sum):
    eq = eq_df["equity"]
    years = (eq.index[-1] - eq.index[0]).days / 365.25 if len(eq) > 1 else 1

    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    max_dd = ((eq / eq.cummax()) - 1).min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else float("inf")

    daily_rets = eq.pct_change().dropna()
    sharpe = (daily_rets.mean() / daily_rets.std() * np.sqrt(252)) if len(daily_rets) > 1 and daily_rets.std() > 0 else 0

    if spy_prices is not None:
        spy_daily = spy_prices.reindex(daily_rets.index).pct_change().dropna()
        aligned = pd.concat([daily_rets.rename("strat"), spy_daily.rename("spy")], axis=1).dropna()
        beta = aligned["strat"].cov(aligned["spy"]) / aligned["spy"].var() if len(aligned) > 5 and aligned["spy"].var() > 0 else np.nan
    else:
        beta = np.nan

    n_switches = len(transitions)
    switches_per_year = n_switches / years if years > 0 else 0

    factors = eq_df.get("factor")
    on_durations, off_durations = [], []
    if factors is not None:
        run = 1
        for j in range(1, len(factors)):
            if factors.iloc[j] == factors.iloc[j - 1]:
                run += 1
            else:
                (on_durations if factors.iloc[j - 1] == "MOMENTUM" else off_durations).append(run)
                run = 1

    jmom_ann = (jmom_ret_sum / jmom_days * 252) if jmom_days > 0 else 0
    splv_ann = (splv_ret_sum / splv_days * 252) if splv_days > 0 else 0

    monthly = eq.resample("ME").last().pct_change().dropna()
    win_rate = (monthly > 0).mean() if len(monthly) > 0 else 0

    return {
        "Calmar": calmar, "CAGR": cagr, "Max DD": max_dd, "Sharpe": sharpe,
        "Beta": beta, "Switches/Year": switches_per_year,
        "Avg Momentum Duration (days)": np.mean(on_durations) if on_durations else 0,
        "Avg Low-Vol Duration (days)": np.mean(off_durations) if off_durations else 0,
        "Momentum Sleeve Ann. Return": jmom_ann,
        "Low-Vol Sleeve Ann. Return": splv_ann,
        "Days in Momentum": jmom_days, "Days in Low-Vol": splv_days,
        "Win Rate": win_rate,
        "Total Return": eq.iloc[-1] / eq.iloc[0] - 1, "Final Value": eq.iloc[-1],
    }

# ── Stress tests ──────────────────────────────────────────────────────────────

def stress_tests(eq_df):
    eq = eq_df["equity"]
    periods = {
        "2022 Rate Shock (Jan-Oct)": ("2022-01-01", "2022-10-31"),
        "Aug 2024 VIX Spike": ("2024-07-15", "2024-08-15"),
    }
    results = {}
    for label, (s, e) in periods.items():
        sub = eq.loc[s:e]
        if len(sub) > 1:
            results[label] = {"return": sub.iloc[-1] / sub.iloc[0] - 1,
                              "max_dd": ((sub / sub.cummax()) - 1).min()}
    return results

# ── Output ────────────────────────────────────────────────────────────────────

def print_metrics(metrics, label):
    print(f"\n  {'-' * 55}")
    print(f"  {label}")
    print(f"  {'-' * 55}")
    fmt = {"Calmar": ".2f", "CAGR": ".2%", "Max DD": ".2%", "Sharpe": ".2f",
           "Beta": ".2f", "Switches/Year": ".1f",
           "Avg Momentum Duration (days)": ".0f", "Avg Low-Vol Duration (days)": ".0f",
           "Momentum Sleeve Ann. Return": ".2%", "Low-Vol Sleeve Ann. Return": ".2%",
           "Days in Momentum": ".0f", "Days in Low-Vol": ".0f",
           "Win Rate": ".1%", "Total Return": ".2%", "Final Value": ",.0f"}
    for key, f in fmt.items():
        val = metrics.get(key, 0)
        if key == "Final Value":
            print(f"  {key:<40} ${val:{f}}")
        else:
            print(f"  {key:<40} {val:{f}}")


def print_comparison(all_metrics):
    print(f"\n{'=' * 110}")
    print("  VARIANT COMPARISON")
    print(f"{'=' * 110}")
    print(f"  {'Variant':<40} {'Calmar':>8} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>8} {'Beta':>6} {'WinRate':>8} {'TotRet':>10}")
    print(f"  {'-' * 106}")
    for label, m in all_metrics.items():
        print(f"  {label:<40} {m['Calmar']:>8.2f} {m['CAGR']:>8.2%} {m['Max DD']:>8.2%} "
              f"{m['Sharpe']:>8.2f} {m['Beta']:>6.2f} {m['Win Rate']:>8.1%} {m['Total Return']:>10.2%}")


def correlation_analysis(eq_df, prices):
    strat_monthly = eq_df["equity"].resample("ME").last().pct_change().dropna()
    results = {}
    for label, ticker in CORR_PROXIES.items():
        if ticker in prices.columns:
            proxy = prices[ticker].resample("ME").last().pct_change().dropna()
            aligned = pd.concat([strat_monthly.rename("strat"), proxy.rename("proxy")], axis=1).dropna()
            results[label] = aligned["strat"].corr(aligned["proxy"]) if len(aligned) > 5 else np.nan
        else:
            results[label] = np.nan
    return results

# ── HTML Dashboard ────────────────────────────────────────────────────────────

def build_html_dashboard(prices, sp500_tickers, sector_map, fundamentals,
                         base_metrics, base_eq, corr_results):
    as_of = datetime.now().strftime("%Y-%m-%d %H:%M")
    price_dict = {col: prices[col] for col in prices.columns}
    today = prices.index[-1]

    regime, signals = get_regime(price_dict, today)
    factor_label = "MOMENTUM" if regime == RISK_ON else "LOW-VOL"
    factor_class = "momentum" if regime == RISK_ON else "lowvol"

    if regime == RISK_ON:
        port, scores = select_portfolio(prices, fundamentals, today, sp500_tickers, JMOM_N)
        score_col = "composite_score"
        extra_col_header = "Mom 12-1"
        extra_col_key = "mom_12_1"
    else:
        port, scores = select_low_vol_portfolio(prices, today, sp500_tickers, SPLV_N)
        score_col = "vol_pctile"
        extra_col_header = "Vol (ann.)"
        extra_col_key = "vol_252d"

    signal_rows = ""
    for name, s in signals.items():
        cls = "score-high" if s["bullish"] else "score-low"
        val_str = f"{s['value']:.3f}" if isinstance(s['value'], float) else str(s['value'])
        bull_str = "BULLISH" if s["bullish"] else "BEARISH"
        signal_rows += f'    <tr><td>{name}</td><td>{val_str}</td><td class="{cls}"><b>{bull_str}</b></td></tr>\n'

    holdings_rows = ""
    for i, (ticker, weight) in enumerate(port):
        sector = sector_map.get(ticker, "")
        score = ""
        extra = ""
        if not scores.empty and ticker in scores.index:
            sc = scores.loc[ticker]
            score = f"{sc[score_col]:.1f}" if score_col in sc.index else ""
            extra = f"{sc[extra_col_key]:.1%}" if extra_col_key in sc.index else ""
        holdings_rows += (f'    <tr><td>{i+1}</td><td class="ticker"><b>{ticker}</b></td>'
                          f'<td>{sector}</td><td>{extra}</td><td>{score}</td><td>{weight:.1%}</td></tr>\n')

    tv_tickers = ", ".join([t for t, w in port])
    m = base_metrics
    calmar_cls = "score-high" if m["Calmar"] >= 1.0 else "score-mid" if m["Calmar"] >= 0.5 else "score-low"

    corr_rows = ""
    for label, c in corr_results.items():
        flag, cls = "", ""
        if not np.isnan(c):
            if c > 0.6: flag, cls = "REDUNDANT", "score-low"
            elif c < 0.4: flag, cls = "Diversifying", "score-high"
            else: cls = "score-mid"
        corr_rows += f'    <tr><td>{label}</td><td class="{cls}">{c:.3f}</td><td>{flag}</td></tr>\n'

    bench_rows = ""
    for bname, bcol in [("SPY", "spy"), ("JMOM ETF", "jmom_etf"), ("SPLV ETF", "splv_etf")]:
        if bcol in base_eq.columns:
            bval = base_eq[bcol].iloc[-1]
            bret = bval / INITIAL_CAPITAL - 1
            bench_rows += f'      <tr><td>{bname}</td><td>${bval:,.0f} ({bret:.1%})</td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Penta Factor Rotation | Momentum vs Low-Vol</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e1e4e8; padding: 20px; }}
    .header {{ background: linear-gradient(135deg, #1f4e79 0%, #2c6e49 100%); padding: 24px 32px; border-radius: 12px; margin-bottom: 20px; }}
    .header h1 {{ color: #fff; font-size: 1.7em; margin-bottom: 4px; }}
    .header .sub {{ color: #b0d4c8; font-size: 0.92em; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; margin-bottom: 18px; }}
    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px; text-align: center; }}
    .card .label {{ color: #8b949e; font-size: 0.73em; text-transform: uppercase; letter-spacing: 0.5px; }}
    .card .value {{ font-size: 1.35em; font-weight: 700; color: #58a6ff; margin-top: 4px; }}
    .card .value.green {{ color: #3fb950; }}
    .card .value.red {{ color: #f85149; }}
    .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 18px; margin-bottom: 16px; }}
    .section h2 {{ color: #58a6ff; font-size: 1.05em; margin-bottom: 10px; border-bottom: 1px solid #30363d; padding-bottom: 7px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.83em; }}
    th {{ background: #1f2937; color: #8b949e; padding: 7px 9px; text-align: left; font-weight: 600;
         text-transform: uppercase; font-size: 0.7em; letter-spacing: 0.5px; position: sticky; top: 0; }}
    td {{ padding: 5px 9px; border-bottom: 1px solid #21262d; }}
    tr:hover {{ background: #1c2333; }}
    .ticker {{ color: #58a6ff; }}
    .score-high {{ color: #3fb950; font-weight: 600; }}
    .score-mid {{ color: #d29922; }}
    .score-low {{ color: #f85149; }}
    .tv-box {{ background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px 14px;
               font-family: 'Consolas', monospace; font-size: 0.8em; color: #8b949e;
               word-break: break-all; line-height: 1.5; margin-top: 6px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }}
    @media (max-width: 1000px) {{ .grid-2, .grid-3 {{ grid-template-columns: 1fr; }} }}
    .meta {{ color: #484f58; font-size: 0.76em; text-align: center; margin-top: 14px; }}
    .scroll-table {{ max-height: 55vh; overflow-y: auto; }}
    .factor-badge {{ display: inline-block; padding: 8px 20px; border-radius: 8px; font-size: 1.2em; font-weight: 700; }}
    .factor-badge.momentum {{ background: #1a2a3a; border: 2px solid #58a6ff; color: #58a6ff; }}
    .factor-badge.lowvol {{ background: #2a1a3a; border: 2px solid #a371f7; color: #a371f7; }}
  </style>
</head>
<body>

<div class="header">
  <h1>Penta Factor Rotation: Momentum vs Low-Vol</h1>
  <div class="sub">Always invested | JMOM replica (risk-on) / SPLV replica (risk-off) | 1114x Stocks Sleeve | As of {as_of}</div>
</div>

<div class="cards">
  <div class="card"><div class="label">Active Factor</div><div class="factor-badge {factor_class}">{factor_label}</div></div>
  <div class="card"><div class="label">Calmar</div><div class="value {calmar_cls}">{m['Calmar']:.2f}</div></div>
  <div class="card"><div class="label">CAGR</div><div class="value green">{m['CAGR']:.1%}</div></div>
  <div class="card"><div class="label">Max DD</div><div class="value red">{m['Max DD']:.1%}</div></div>
  <div class="card"><div class="label">Sharpe</div><div class="value">{m['Sharpe']:.2f}</div></div>
  <div class="card"><div class="label">Beta</div><div class="value">{m['Beta']:.2f}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value">{m['Win Rate']:.0%}</div></div>
  <div class="card"><div class="label">$100K Becomes</div><div class="value green">${m['Final Value']:,.0f}</div></div>
</div>

<div class="grid-2">
  <div class="section">
    <h2>Penta Signal (determines factor)</h2>
    <table><thead><tr><th>Signal</th><th>Value</th><th>Status</th></tr></thead><tbody>
{signal_rows}    </tbody></table>
    <p style="color:#484f58; margin-top:6px; font-size:0.75em;">3/4 bullish = MOMENTUM | 2 or fewer = LOW-VOL</p>
  </div>
  <div class="section">
    <h2>Factor Rotation Rules</h2>
    <table><tbody>
      <tr><td style="color:#58a6ff; font-weight:600;">RISK ON (Momentum)</td><td>Top 50 S&P 500 by 12-1 momentum + risk-adj, 2% each</td></tr>
      <tr><td style="color:#a371f7; font-weight:600;">RISK OFF (Low-Vol)</td><td>50 lowest-vol S&P 500 stocks (252d), 2% each</td></tr>
      <tr><td>Transition Cost</td><td>10bps slippage per switch</td></tr>
      <tr><td>Rebalance</td><td>Monthly (active factor reconstituted)</td></tr>
      <tr><td>Leverage</td><td>None</td></tr>
      <tr><td>Cash Position</td><td>Never -- always fully invested</td></tr>
    </tbody></table>
  </div>
</div>

<div class="section">
  <h2>Current Holdings: {factor_label} Portfolio (50 stocks)</h2>
  <div class="scroll-table">
  <table>
    <thead><tr><th>#</th><th>Ticker</th><th>Sector</th><th>{extra_col_header}</th><th>Score</th><th>Weight</th></tr></thead>
    <tbody>
{holdings_rows}    </tbody>
  </table>
  </div>
</div>

<div class="grid-3">
  <div class="section">
    <h2>Correlation vs Sleeves</h2>
    <table><thead><tr><th>Sleeve</th><th>Corr</th><th></th></tr></thead><tbody>
{corr_rows}    </tbody></table>
  </div>
  <div class="section">
    <h2>Factor Contribution</h2>
    <table><tbody>
      <tr><td>Days in Momentum</td><td>{m['Days in Momentum']:.0f}</td></tr>
      <tr><td>Days in Low-Vol</td><td>{m['Days in Low-Vol']:.0f}</td></tr>
      <tr><td>Momentum Ann. Return</td><td class="score-high">{m['Momentum Sleeve Ann. Return']:.2%}</td></tr>
      <tr><td>Low-Vol Ann. Return</td><td>{m['Low-Vol Sleeve Ann. Return']:.2%}</td></tr>
      <tr><td>Switches/Year</td><td>{m['Switches/Year']:.1f}</td></tr>
    </tbody></table>
  </div>
  <div class="section">
    <h2>vs Benchmarks</h2>
    <table><tbody>
      <tr><td style="font-weight:600;">Strategy</td><td class="score-high">${m['Final Value']:,.0f} ({m['Total Return']:.1%})</td></tr>
{bench_rows}    </tbody></table>
  </div>
</div>

<div class="section">
  <h2>TradingView Paste ({factor_label} portfolio)</h2>
  <div class="tv-box">{tv_tickers}</div>
</div>

<div class="meta">
  Penta Factor Rotation (Momentum / Low-Vol) | 1114x Stocks Sleeve | Potomac Fund Management | {as_of}
</div>

</body>
</html>"""

    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  HTML dashboard saved to: {HTML_OUT}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  PENTA FACTOR ROTATION: MOMENTUM vs LOW-VOL")
    print("  Always invested | JMOM (risk-on) / SPLV (risk-off)")
    print("  Sep 2020 - Feb 2026 | $100K | No leverage | 10bps slippage")
    print("=" * 70)

    print("\n[1/4] Building universe...")
    sp500_tickers, sector_map = get_sp500_tickers()
    print(f"    {len(sp500_tickers)} S&P 500 tickers")

    print("\n[2/4] Downloading price data...")
    prices = fetch_all_data(sp500_tickers)
    if prices.empty:
        print("  ERROR: No price data")
        return
    print(f"    {len(prices)} trading days, {len(prices.columns)} tickers")

    print("\n[3/4] Fetching fundamentals (for JMOM quality gate)...")
    stock_cols = [c for c in sp500_tickers if c in prices.columns]
    fundamentals = fetch_fundamentals_fast(stock_cols)

    print("\n[4/4] Running backtests...")

    variants = {
        "A: Penta Rotation (JMOM/SPLV)": "rotation",
        "B: JMOM Only (always momentum)": "jmom_only",
        "C: SPLV Only (always low-vol)": "splv_only",
    }

    all_metrics = {}
    base_result = None

    for label, mode in variants.items():
        print(f"\n  Running {label}...")
        result = run_variant(prices, sp500_tickers, sector_map, fundamentals, mode=mode, label=label)
        if result is None:
            print(f"    SKIPPED")
            continue
        eq_df, regime_df, trans_df, tlh_log, metrics = result
        all_metrics[label] = metrics
        print_metrics(metrics, label)

        if "A:" in label:
            base_result = (eq_df, regime_df, trans_df, tlh_log, metrics)

    if all_metrics:
        print_comparison(all_metrics)

    if base_result:
        eq_df, regime_df, trans_df, tlh_log, metrics = base_result

        monthly = eq_df["equity"].resample("ME").last().pct_change().dropna()
        worst = monthly.sort_values().head(5)
        print(f"\n  WORST 5 MONTHS (Rotation):")
        print(f"  {'-' * 22}")
        for date, ret in worst.items():
            print(f"  {date.strftime('%Y-%m'):<12} {ret:>10.2%}")

        stress = stress_tests(eq_df)
        if stress:
            print(f"\n  STRESS TESTS:")
            for label, r in stress.items():
                print(f"  {label:<35} Return: {r['return']:>8.2%}  MaxDD: {r['max_dd']:>8.2%}")

        corr = correlation_analysis(eq_df, prices)
        print(f"\n  CORRELATION VS EXISTING SLEEVES:")
        print(f"  {'-' * 50}")
        for label, c in corr.items():
            flag = ""
            if not np.isnan(c):
                if c > 0.6: flag = " *** REDUNDANT"
                elif c < 0.4: flag = " (diversifying)"
            print(f"  {label:<30} {c:>8.3f}{flag}")

        if tlh_log:
            print(f"\n  TLH OPPORTUNITIES ({len(tlh_log)} exits with >2% loss):")
            for entry in tlh_log[-10:]:
                print(f"  {entry['date']:<12} {entry['ticker']:<8} {entry['return']:>8} {entry['sector']}")

        # Benchmarks
        print(f"\n  BENCHMARK COMPARISON:")
        print(f"  {'Strategy (Rotation)':<30} ${eq_df['equity'].iloc[-1]:>12,.0f}  ({metrics['Total Return']:>8.2%})")
        for bname, bcol in [("SPY", "spy"), ("JMOM ETF", "jmom_etf"), ("SPLV ETF", "splv_etf")]:
            if bcol in eq_df.columns:
                bval = eq_df[bcol].iloc[-1]
                print(f"  {bname:<30} ${bval:>12,.0f}  ({bval/INITIAL_CAPITAL - 1:>8.2%})")

        # Save CSVs
        for fname, data in [("penta_jmom_equity.csv", eq_df),
                            ("penta_jmom_monthly.csv", monthly),
                            ("penta_jmom_regime_log.csv", regime_df),
                            ("penta_jmom_transitions.csv", trans_df)]:
            path = os.path.join(SCRIPT_DIR, fname)
            if isinstance(data, pd.DataFrame):
                data.to_csv(path, index="date" not in data.columns)
            else:
                data.to_csv(path)
            print(f"  Saved: {path}")

        build_html_dashboard(prices, sp500_tickers, sector_map, fundamentals, metrics, eq_df, corr)

    print(f"\n{'=' * 70}")
    print("  DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
