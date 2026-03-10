"""
QuantConnect Deployment: International Blended-Lookback Momentum
================================================================
Creates project, uploads LEAN algorithm, compiles, runs backtest.

Strategy:
  - Universe: 16 single-country ETFs + 7 factor/broad ETFs (23 total)
  - Ranking: Blended momentum (avg of 1m, 3m, 6m, 12m trailing returns)
  - Absolute momentum: Composite score > 0 to stay invested
  - Top 7 holdings, equal-weight
  - Risk-off: BIL (T-bills)
  - Monthly rebalance (last trading day)

Usage:
    python qc_intl_momentum_deploy.py
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


def api(endpoint, payload=None, method="post"):
    r = post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload or {})
    data = r.json()
    if not data.get("success"):
        print(f"  API ERROR on {endpoint}: {json.dumps(data, indent=2)}")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# LEAN ALGORITHM
# ═══════════════════════════════════════════════════════════════════════════════

ALGO_CODE = r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np


class IntlBlendedMomentum(QCAlgorithm):
    """
    International Blended-Lookback Momentum Rotation
    ==================================================
    Universe: 23 international ETFs (16 single-country + 7 factor/broad)
    Signal:   Blended momentum = average of 1m, 3m, 6m, 12m trailing returns
    Filter:   Absolute momentum -- composite score must be > 0
    Holding:  Top 7, equal-weight (~14.3% each)
    Cash:     BIL when absolute momentum fails
    Rebal:    Monthly (last trading day of month)

    Adapted from Gary Antonacci's GEM framework.
    """

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("EFA")

        # Single-country ETFs (iShares MSCI)
        self.country_etfs = {
            "EWJ":  "Japan",
            "EWG":  "Germany",
            "EWU":  "United Kingdom",
            "EWC":  "Canada",
            "EWA":  "Australia",
            "EWQ":  "France",
            "EWL":  "Switzerland",
            "EWP":  "Spain",
            "EWI":  "Italy",
            "EWT":  "Taiwan",
            "EWZ":  "Brazil",
            "INDA": "India",
            "FXI":  "China",
            "EWY":  "South Korea",
            "EWW":  "Mexico",
            "EWH":  "Hong Kong",
        }

        # Factor / broad international ETFs
        self.factor_etfs = {
            "GVAL": "Cambria Global Value",
            "GMOM": "Cambria Global Momentum",
            "IVAL": "Alpha Architect Intl Value",
            "IMOM": "Alpha Architect Intl Momentum",
            "EFA":  "MSCI EAFE",
            "VWO":  "Vanguard EM",
            "DLS":  "WisdomTree Intl SmallCap Div",
        }

        self.all_etfs = {}
        self.all_etfs.update(self.country_etfs)
        self.all_etfs.update(self.factor_etfs)

        self.cash_ticker = "BIL"
        self.n_hold = 7
        self.lookback_months = [1, 3, 6, 12]
        self.max_lookback_days = 260

        self.symbols = {}
        for ticker in list(self.all_etfs.keys()) + [self.cash_ticker]:
            sym = self.add_equity(ticker, Resolution.DAILY)
            sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
            self.symbols[ticker] = sym.symbol

        self.set_warm_up(timedelta(days=self.max_lookback_days + 30))

        self.rebalance_scheduled = False
        self.schedule.on(
            self.date_rules.month_end(),
            self.time_rules.before_market_close("EFA", 30),
            self.flag_rebalance
        )

        self.settings.free_portfolio_value_percentage = 0.02

    def flag_rebalance(self):
        self.rebalance_scheduled = True

    def on_data(self, data):
        if self.is_warming_up:
            return
        if not self.rebalance_scheduled:
            return
        self.rebalance_scheduled = False
        self.rebalance(data)

    def trailing_return(self, symbol, months):
        """Trailing total return over N months using daily close."""
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
        """Average of 1m, 3m, 6m, 12m trailing returns."""
        rets = []
        for m in self.lookback_months:
            r = self.trailing_return(symbol, m)
            if r is not None:
                rets.append(r)
        if len(rets) == 0:
            return None
        return sum(rets) / len(rets)

    def rebalance(self, data):
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

        # Absolute momentum filter: composite score must be > 0
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

        # Liquidate positions not in target
        for kvp in self.portfolio:
            holding = kvp.value
            if holding.invested:
                ticker = holding.symbol.value
                if ticker not in target and ticker != self.cash_ticker:
                    self.liquidate(holding.symbol)
                    self.log(f"  SELL {ticker}")

        # Set target weights
        for ticker, w in target.items():
            sym = self.symbols[ticker]
            current = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
            if abs(current - w) > 0.02:
                self.set_holdings(sym, w)
                self.log(f"  BUY {ticker} -> {w:.1%}")

        # Cash portion to BIL
        if cash_slots > 0:
            cash_weight = cash_slots * weight
            bil_sym = self.symbols[self.cash_ticker]
            self.set_holdings(bil_sym, cash_weight)
            self.log(f"  CASH -> BIL {cash_weight:.1%}")
        else:
            bil_sym = self.symbols[self.cash_ticker]
            if self.portfolio[bil_sym].invested:
                self.liquidate(bil_sym)

    def on_end_of_algorithm(self):
        self.log(f"FINAL: Portfolio Value = ${self.portfolio.total_portfolio_value:,.0f}")
        for kvp in self.portfolio:
            h = kvp.value
            if h.invested:
                self.log(f"  {h.symbol.value}: ${h.holdings_value:,.0f} "
                         f"({h.holdings_value/self.portfolio.total_portfolio_value:.1%})")
'''


# ═══════════════════════════════════════════════════════════════════════════════
# DEPLOY
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  QC DEPLOY: International Blended-Lookback Momentum")
    print("  Universe: 16 country ETFs + GVAL, GMOM, IVAL, IMOM, EFA, VWO, DLS")
    print("  Signal: Composite (avg 1/3/6/12m) for ranking + abs momentum")
    print("  Top 7 EW, monthly rebal, BIL risk-off")
    print("=" * 70)

    # 1. Reuse existing project or create new one
    project_id = 28622875  # Created in first run
    print(f"\n1. Using project ID: {project_id}")

    # 2. Upload algorithm
    print("\n2. Uploading algorithm...")
    r = api("/files/update", {
        "projectId": project_id,
        "name": "main.py",
        "content": ALGO_CODE,
    })
    if r.get("success"):
        print("   Uploaded main.py")
    else:
        print("   Upload failed, trying create...")
        r = api("/files/create", {
            "projectId": project_id,
            "name": "main.py",
            "content": ALGO_CODE,
        })
        if not r.get("success"):
            print("   FAILED to upload code")
            sys.exit(1)
        print("   Created main.py")

    # 3. Compile
    print("\n3. Compiling...")
    r = api("/compile/create", {"projectId": project_id})
    if not r.get("success"):
        print("   COMPILE FAILED:", json.dumps(r, indent=2))
        sys.exit(1)
    compile_id = r.get("compileId")
    print(f"   Compile ID: {compile_id}")

    compiled = False
    for i in range(30):
        tm.sleep(3)
        r = api("/compile/read", {"projectId": project_id, "compileId": compile_id})
        state = r.get("state", "")
        if state == "BuildSuccess":
            print("   Compiled OK!")
            compiled = True
            break
        elif state == "BuildError":
            print("   BUILD ERROR:")
            for log in r.get("logs", []):
                print(f"     {log}")
            sys.exit(1)
        elif i % 5 == 0:
            print(f"   Waiting... ({state})")

    if not compiled:
        print("   Compile timed out")
        sys.exit(1)

    # 4. Run backtest
    print("\n4. Starting backtest...")
    bt_name = f"IntlMom_Blended_{int(tm.time())}"
    r = api("/backtests/create", {
        "projectId": project_id,
        "compileId": compile_id,
        "backtestName": bt_name,
    })
    if not r.get("success"):
        print("   FAILED:", json.dumps(r, indent=2))
        sys.exit(1)

    backtest_id = r["backtest"]["backtestId"]
    print(f"   Backtest: {bt_name}")
    print(f"   ID: {backtest_id}")

    # 5. Poll for completion
    print("\n5. Waiting for completion...")
    completed = False
    for i in range(360):
        tm.sleep(5)
        r = api("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = r.get("backtest", {})
        completed = bt.get("completed", False)
        progress = bt.get("progress", 0)
        if i % 12 == 0:
            print(f"   {progress:.0%} complete...")
        if completed:
            break

    if not completed:
        print("   Timed out after 30 min!")
        print(f"   Check manually: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")
        sys.exit(1)

    print("   DONE!")

    # 6. Results
    bt = r.get("backtest", {})
    stats = bt.get("statistics", {})
    runtime = bt.get("runtimeStatistics", {})

    print(f"\n{'=' * 70}")
    print("RESULTS")
    print(f"{'=' * 70}")
    print(f"  Period: {bt.get('backtestStart', '?')} to {bt.get('backtestEnd', '?')}")

    print("\n  KEY METRICS:")
    for key in ["Total Return", "Compounding Annual Return", "Drawdown",
                 "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
                 "Alpha", "Beta", "Total Fees", "Portfolio Turnover",
                 "Treynor Ratio", "Information Ratio", "Tracking Error",
                 "Estimated Strategy Capacity", "Lowest Capacity Asset"]:
        val = stats.get(key, "N/A")
        print(f"    {key:.<45} {val}")

    print("\n  RUNTIME STATS:")
    for key, val in runtime.items():
        print(f"    {key:.<45} {val}")

    # Log analysis
    logs = bt.get("logs", "")
    if logs:
        lines = logs.strip().split("\n")
        rebal_lines = [l for l in lines if "REBAL" in l]
        print(f"\n  REBALANCE LOG ({len(rebal_lines)} entries, showing last 15):")
        for l in rebal_lines[-15:]:
            print(f"    {l}")

    # Save results
    out = os.path.join(SCRIPT_DIR, "qc_intl_momentum_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results saved to: {out}")
    print(f"  View: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
