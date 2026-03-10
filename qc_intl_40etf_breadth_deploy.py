"""
QuantConnect Deployment: 40-ETF Dual Momentum + Breadth/Trend Overlay
======================================================================
Runs 4 backtests with different breadth thresholds (30%, 40%, 50%, 60%).

Risk-off logic (OR gate for staying invested):
  - Signal A: % of MSCI single-country ETFs above 200-day SMA >= threshold
  - Signal B: ACWX above its 200-day SMA
  - STAY INVESTED if Signal A positive OR Signal B positive
  - GO TO 100% CASH (BIL) only if BOTH are negative

Usage:
    python qc_intl_40etf_breadth_deploy.py
"""

import json, sys, os
import time as tm
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}


def api(endpoint, payload=None):
    r = post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload or {})
    data = r.json()
    if not data.get("success"):
        print(f"  API ERROR on {endpoint}: {json.dumps(data, indent=2)}")
    return data


def build_algo_code(breadth_threshold_pct):
    """Generate LEAN algorithm code with a specific breadth threshold."""
    return r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np


class Intl40ETFBreadthMomentum(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("EFA")

        self.breadth_threshold = ''' + str(breadth_threshold_pct / 100.0) + r'''

        # === INVESTMENT UNIVERSE (40 ETFs) ===
        self.all_etfs = {
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

        # === BREADTH UNIVERSE -- all MSCI single-country iShares ETFs ===
        # Separate from investment universe; used only for breadth signal
        self.breadth_tickers = [
            "EWJ", "EWG", "EWU", "EWC", "EWA", "EWQ", "EWL", "EWP",
            "EWI", "EWD", "EWH", "EWS", "EWN", "EDEN", "EWK", "EWO",
            "EWT", "EWZ", "INDA", "FXI", "EWY", "EWW", "EWM", "ECH",
            "TUR", "THD", "EIDO", "EPHE", "KSA", "ARGT", "VNM",
        ]

        self.trend_ticker = "ACWX"
        self.cash_ticker = "BIL"
        self.n_hold = 7
        self.lookback_months = [1, 3, 6, 12]
        self.max_lookback_days = 260
        self.sma_period = 200

        # Register all investment universe symbols
        self.symbols = {}
        for ticker in list(self.all_etfs.keys()) + [self.cash_ticker]:
            sym = self.add_equity(ticker, Resolution.DAILY)
            sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
            self.symbols[ticker] = sym.symbol

        # Register breadth-only symbols (not in investment universe)
        self.breadth_symbols = {}
        for ticker in self.breadth_tickers:
            if ticker not in self.symbols:
                sym = self.add_equity(ticker, Resolution.DAILY)
                sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
                self.breadth_symbols[ticker] = sym.symbol
            else:
                self.breadth_symbols[ticker] = self.symbols[ticker]

        # Register ACWX for trend signal
        if self.trend_ticker not in self.symbols:
            sym = self.add_equity(self.trend_ticker, Resolution.DAILY)
            sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
            self.symbols[self.trend_ticker] = sym.symbol

        self.set_warm_up(timedelta(days=self.sma_period + 30))

        self.rebalance_scheduled = False
        self.schedule.on(
            self.date_rules.month_end(),
            self.time_rules.before_market_close("EFA", 30),
            self.flag_rebalance
        )

        self.settings.free_portfolio_value_percentage = 0.02
        self.months_in_cash = 0
        self.months_total = 0

    def flag_rebalance(self):
        self.rebalance_scheduled = True

    def on_data(self, data):
        if self.is_warming_up:
            return
        if not self.rebalance_scheduled:
            return
        self.rebalance_scheduled = False
        self.rebalance(data)

    def get_sma(self, symbol, period):
        history = self.history(symbol, period + 5, Resolution.DAILY)
        if history.empty or len(history) < period:
            return None
        try:
            return float(history["close"].iloc[-period:].mean())
        except (IndexError, KeyError):
            return None

    def get_current_price(self, symbol):
        history = self.history(symbol, 1, Resolution.DAILY)
        if history.empty:
            return None
        try:
            return float(history["close"].iloc[-1])
        except (IndexError, KeyError):
            return None

    def breadth_pct(self):
        above = 0
        total = 0
        for ticker in self.breadth_tickers:
            sym = self.breadth_symbols.get(ticker)
            if sym is None:
                continue
            if not self.securities[sym].has_data:
                continue
            price = self.get_current_price(sym)
            sma = self.get_sma(sym, self.sma_period)
            if price is not None and sma is not None and sma > 0:
                total += 1
                if price > sma:
                    above += 1
        if total == 0:
            return 0.0
        return above / total

    def trend_positive(self):
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return False
        if not self.securities[sym].has_data:
            return False
        price = self.get_current_price(sym)
        sma = self.get_sma(sym, self.sma_period)
        if price is None or sma is None or sma == 0:
            return False
        return price > sma

    def trailing_return(self, symbol, months):
        days = int(months * 21)
        history = self.history(symbol, days + 5, Resolution.DAILY)
        if history.empty or len(history) < days:
            return None
        try:
            current = history["close"].iloc[-1]
            past = history["close"].iloc[-(days + 1)]
            if past == 0:
                return None
            return (current / past) - 1.0
        except (IndexError, KeyError):
            return None

    def blended_momentum(self, symbol):
        rets = []
        for m in self.lookback_months:
            r = self.trailing_return(symbol, m)
            if r is not None:
                rets.append(r)
        if len(rets) == 0:
            return None
        return sum(rets) / len(rets)

    def go_to_cash(self):
        for kvp in self.portfolio:
            holding = kvp.value
            if holding.invested:
                ticker = holding.symbol.value
                if ticker != self.cash_ticker:
                    self.liquidate(holding.symbol)
        bil_sym = self.symbols[self.cash_ticker]
        self.set_holdings(bil_sym, 0.98)

    def rebalance(self, data):
        self.months_total += 1

        # --- MACRO OVERLAY: OR gate for staying invested ---
        breadth = self.breadth_pct()
        trend = self.trend_positive()
        breadth_pass = breadth >= self.breadth_threshold
        trend_pass = trend

        self.plot("Macro", "Breadth_Pct", breadth * 100)
        self.plot("Macro", "Threshold", self.breadth_threshold * 100)
        self.plot("Macro", "ACWX_Trend", 1 if trend_pass else 0)
        self.plot("Macro", "Risk_On", 1 if (breadth_pass or trend_pass) else 0)

        # OR gate: stay invested if EITHER is positive
        # Go to cash ONLY if BOTH are negative
        if not breadth_pass and not trend_pass:
            self.months_in_cash += 1
            self.log(f"MACRO RISK-OFF: Breadth={breadth:.1%} (thresh={self.breadth_threshold:.0%}), "
                     f"ACWX_trend={'UP' if trend_pass else 'DOWN'} -> 100% BIL "
                     f"[Cash {self.months_in_cash}/{self.months_total} months]")
            self.go_to_cash()
            return

        self.log(f"MACRO RISK-ON: Breadth={breadth:.1%} (thresh={self.breadth_threshold:.0%}), "
                 f"ACWX_trend={'UP' if trend_pass else 'DOWN'} -> Running momentum")

        # --- MOMENTUM RANKING (unchanged from baseline) ---
        scores = {}
        for ticker in self.all_etfs:
            sym = self.symbols.get(ticker)
            if sym is None:
                continue
            if not self.securities[sym].has_data:
                continue
            score = self.blended_momentum(sym)
            if score is not None:
                scores[ticker] = score

        if len(scores) == 0:
            self.log("REBAL: No scores available, skipping")
            return

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = ranked[:self.n_hold]

        invest = [(t, s) for t, s in top_n if s > 0]
        cash_slots = self.n_hold - len(invest)

        weight = 1.0 / self.n_hold
        target = {}
        for ticker, score in invest:
            target[ticker] = weight

        invested_str = ", ".join([f"{t}({s:+.2%})" for t, s in invest])
        failed = [(t, s) for t, s in top_n if s <= 0]
        failed_str = ", ".join([f"{t}({s:+.2%})" for t, s in failed])
        cash_pct = cash_slots * weight * 100

        self.log(f"REBAL: Invested=[{invested_str}] | "
                 f"Failed=[{failed_str}] | Cash={cash_pct:.0f}%")

        for kvp in self.portfolio:
            holding = kvp.value
            if holding.invested:
                ticker = holding.symbol.value
                if ticker not in target and ticker != self.cash_ticker:
                    self.liquidate(holding.symbol)

        for ticker, w in target.items():
            sym = self.symbols[ticker]
            current = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
            if abs(current - w) > 0.02:
                self.set_holdings(sym, w)

        if cash_slots > 0:
            cash_weight = cash_slots * weight
            bil_sym = self.symbols[self.cash_ticker]
            self.set_holdings(bil_sym, cash_weight)
        else:
            bil_sym = self.symbols[self.cash_ticker]
            if self.portfolio[bil_sym].invested:
                self.liquidate(bil_sym)

    def on_end_of_algorithm(self):
        cash_pct = (self.months_in_cash / self.months_total * 100) if self.months_total > 0 else 0
        self.log(f"FINAL: Portfolio Value = ${self.portfolio.total_portfolio_value:,.0f}")
        self.log(f"FINAL: Months in cash (macro risk-off) = {self.months_in_cash}/{self.months_total} ({cash_pct:.1f}%)")
        self.log(f"FINAL: Breadth threshold = {self.breadth_threshold:.0%}")
'''


THRESHOLDS = [30, 40, 50, 60]


def run_backtest(threshold):
    """Create project, upload, compile, run backtest for one threshold."""
    algo_code = build_algo_code(threshold)

    print(f"\n{'='*70}")
    print(f"  BREADTH THRESHOLD: {threshold}%")
    print(f"{'='*70}")

    # 1. Create project
    print("  1. Creating project...")
    r = api("/projects/create", {
        "name": f"Intl40_Breadth{threshold}pct_{int(tm.time())}",
        "language": "Py",
    })
    if not r.get("success"):
        print("     Failed to create project")
        return None
    project_id = r["projects"][0]["projectId"]
    print(f"     Project ID: {project_id}")

    # 2. Upload
    print("  2. Uploading algorithm...")
    r = api("/files/create", {
        "projectId": project_id,
        "name": "main.py",
        "content": algo_code,
    })
    if not r.get("success"):
        r = api("/files/update", {
            "projectId": project_id,
            "name": "main.py",
            "content": algo_code,
        })
    print("     Uploaded main.py")

    # 3. Compile
    print("  3. Compiling...")
    r = api("/compile/create", {"projectId": project_id})
    if not r.get("success"):
        print("     COMPILE FAILED:", json.dumps(r, indent=2))
        return None
    compile_id = r.get("compileId")

    compiled = False
    for i in range(30):
        tm.sleep(3)
        r = api("/compile/read", {"projectId": project_id, "compileId": compile_id})
        state = r.get("state", "")
        if state == "BuildSuccess":
            print("     Compiled OK!")
            compiled = True
            break
        elif state == "BuildError":
            print("     BUILD ERROR:")
            for log in r.get("logs", []):
                print(f"       {log}")
            return None

    if not compiled:
        print("     Compile timed out")
        return None

    # 4. Backtest
    print("  4. Starting backtest...")
    bt_name = f"Breadth{threshold}pct_{int(tm.time())}"
    r = api("/backtests/create", {
        "projectId": project_id,
        "compileId": compile_id,
        "backtestName": bt_name,
    })
    if not r.get("success"):
        print("     FAILED:", json.dumps(r, indent=2))
        return None

    backtest_id = r["backtest"]["backtestId"]
    print(f"     Backtest: {bt_name}")
    print(f"     ID: {backtest_id}")

    # 5. Poll
    print("  5. Waiting...")
    completed = False
    for i in range(360):
        tm.sleep(5)
        try:
            r = api("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        except Exception as e:
            print(f"     Network error: {e}, retrying...")
            continue
        bt = r.get("backtest", {})
        if bt.get("completed", False):
            completed = True
            break
        if i % 12 == 0:
            progress = bt.get("progress", 0)
            print(f"     {progress:.0%} complete...")

    if not completed:
        print(f"     Timed out! Check: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")
        return {"threshold": threshold, "status": "timeout",
                "project_id": project_id, "backtest_id": backtest_id}

    print("     DONE!")

    bt = r.get("backtest", {})
    stats = bt.get("statistics", {})
    runtime = bt.get("runtimeStatistics", {})

    result = {
        "threshold": threshold,
        "status": "completed",
        "project_id": project_id,
        "backtest_id": backtest_id,
        "cagr": stats.get("Compounding Annual Return", "N/A"),
        "total_return": stats.get("Net Profit", "N/A"),
        "drawdown": stats.get("Drawdown", "N/A"),
        "sharpe": stats.get("Sharpe Ratio", "N/A"),
        "sortino": stats.get("Sortino Ratio", "N/A"),
        "alpha": stats.get("Alpha", "N/A"),
        "beta": stats.get("Beta", "N/A"),
        "ann_vol": stats.get("Annual Standard Deviation", "N/A"),
        "win_rate": stats.get("Win Rate", "N/A"),
        "fees": stats.get("Total Fees", "N/A"),
        "orders": stats.get("Total Orders", "N/A"),
        "turnover": stats.get("Portfolio Turnover", "N/A"),
        "end_equity": runtime.get("Equity", "N/A"),
        "capacity": stats.get("Estimated Strategy Capacity", "N/A"),
        "url": f"https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}",
        "full_stats": stats,
        "full_runtime": runtime,
    }

    print(f"\n  RESULTS ({threshold}% threshold):")
    print(f"    CAGR:     {result['cagr']}")
    print(f"    Return:   {result['total_return']}")
    print(f"    Drawdown: {result['drawdown']}")
    print(f"    Sharpe:   {result['sharpe']}")
    print(f"    Alpha:    {result['alpha']}")
    print(f"    Equity:   {result['end_equity']}")

    return result


def main():
    print("=" * 70)
    print("  BREADTH + TREND OVERLAY BACKTEST SWEEP")
    print("  40-ETF International Dual Momentum")
    print("  Signal A: % MSCI country indices > 200d SMA")
    print("  Signal B: ACWX > 200d SMA")
    print("  Logic: OR gate (cash ONLY if both negative)")
    print("  Thresholds: 30%, 40%, 50%, 60%")
    print("=" * 70)

    results = []
    for threshold in THRESHOLDS:
        result = run_backtest(threshold)
        if result:
            results.append(result)
        tm.sleep(2)

    # Save all results
    out = os.path.join(SCRIPT_DIR, "qc_breadth_sweep_results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nAll results saved to: {out}")

    # Comparison table
    print(f"\n\n{'='*90}")
    print("COMPARISON TABLE")
    print(f"{'='*90}")
    print(f"  {'Variant':<15} {'CAGR':>10} {'Return':>10} {'MaxDD':>10} {'Sharpe':>8} "
          f"{'Sortino':>8} {'Alpha':>8} {'Equity':>15}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*15}")

    # Baseline
    print(f"  {'Baseline':<15} {'14.30%':>10} {'289.0%':>10} {'39.8%':>10} {'0.508':>8} "
          f"{'0.541':>8} {'0.049':>8} {'$3,890,450':>15}")

    for r in results:
        if r["status"] == "completed":
            print(f"  {'Breadth '+str(r['threshold'])+'%':<15} {r['cagr']:>10} {r['total_return']:>10} "
                  f"{r['drawdown']:>10} {r['sharpe']:>8} {r['sortino']:>8} {r['alpha']:>8} "
                  f"{r['end_equity']:>15}")
        else:
            print(f"  {'Breadth '+str(r['threshold'])+'%':<15} {'TIMEOUT':>10}")

    print(f"\n{'='*90}")
    print("DONE")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
