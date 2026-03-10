"""
QuantConnect Deployment: International 40-ETF Dual Momentum
=============================================================
Strategy:
  - Universe: 40 international ETFs (24 developed, 16 EM)
  - Ranking: Blended momentum (avg of 1m, 3m, 6m, 12m trailing returns)
  - Absolute momentum: Composite score > 0 to stay invested
  - Top 7 holdings, equal-weight (~14.3% each)
  - Risk-off: BIL (T-bills)
  - Monthly rebalance (last trading day)

Usage:
    python qc_intl_40etf_deploy.py
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


ALGO_CODE = r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np


class Intl40ETFDualMomentum(QCAlgorithm):
    """
    International 40-ETF Blended-Lookback Dual Momentum
    =====================================================
    Universe: 40 international ETFs optimized for low pairwise correlation
              24 developed (10 country, 1 factor, 13 thematic)
              16 EM (14 country, 2 broad/thematic)
    Signal:   Blended momentum = avg of 1m, 3m, 6m, 12m trailing returns
    Filter:   Absolute momentum -- composite score must be > 0
    Holding:  Top 7, equal-weight (~14.3% each)
    Cash:     BIL when absolute momentum fails
    Rebal:    Monthly (last trading day of month)
    """

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("EFA")

        # --- DEVELOPED COUNTRY (10) ---
        self.dev_country = {
            "EWJ":  "Japan",
            "EWG":  "Germany",
            "EWQ":  "France",
            "EWI":  "Italy",
            "EWD":  "Sweden",
            "EWL":  "Switzerland",
            "EWP":  "Spain",
            "EWH":  "Hong Kong",
            "EWS":  "Singapore",
            "EDEN": "Denmark",
        }

        # --- DEVELOPED FACTOR (1) ---
        self.dev_factor = {
            "IHDG": "Intl Hedged Qual Div Growth",
        }

        # --- DEVELOPED THEMATIC (13) ---
        self.dev_thematic = {
            "RING": "Global Gold Miners",
            "SIL":  "Silver Miners",
            "URA":  "Uranium",
            "KXI":  "Global Consumer Staples",
            "LIT":  "Lithium & Battery Tech",
            "REMX": "Rare Earth & Strategic Metals",
            "COPX": "Copper Miners",
            "PICK": "Global Metals & Mining",
            "GNR":  "S&P Global Natural Resources",
            "CGW":  "Global Water",
            "GII":  "Global Infrastructure",
            "INFL": "Inflation Beneficiaries",
            "MOO":  "Agribusiness",
        }

        # --- EM COUNTRY (14) ---
        self.em_country = {
            "EWT":  "Taiwan",
            "EWZ":  "Brazil",
            "INDA": "India",
            "FXI":  "China Large-Cap",
            "EWY":  "South Korea",
            "EWW":  "Mexico",
            "ILF":  "Latin America 40",
            "ECH":  "Chile",
            "TUR":  "Turkey",
            "ARGT": "Argentina",
            "VNM":  "Vietnam",
            "THD":  "Thailand",
            "EWM":  "Malaysia",
            "EIDO": "Indonesia",
        }

        # --- EM BROAD/THEMATIC (2) ---
        self.em_broad = {
            "KSA":  "Saudi Arabia",
            "KWEB": "China Internet",
        }

        self.all_etfs = {}
        self.all_etfs.update(self.dev_country)
        self.all_etfs.update(self.dev_factor)
        self.all_etfs.update(self.dev_thematic)
        self.all_etfs.update(self.em_country)
        self.all_etfs.update(self.em_broad)

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
                    self.log(f"  SELL {ticker}")

        for ticker, w in target.items():
            sym = self.symbols[ticker]
            current = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
            if abs(current - w) > 0.02:
                self.set_holdings(sym, w)
                self.log(f"  BUY {ticker} -> {w:.1%}")

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


def main():
    print("=" * 70)
    print("  QC DEPLOY: International 40-ETF Dual Momentum")
    print("  Universe: 24 Dev + 16 EM (optimized pairwise correlation)")
    print("  Signal: Blended (avg 1/3/6/12m) for ranking + abs momentum")
    print("  Top 7 EW, monthly rebal, BIL risk-off")
    print("=" * 70)

    # 1. Create project
    print("\n1. Creating project...")
    r = api("/projects/create", {
        "name": f"Intl_40ETF_DualMom_{int(tm.time())}",
        "language": "Py",
    })
    if not r.get("success"):
        print("   Failed to create project")
        sys.exit(1)
    project_id = r["projects"][0]["projectId"]
    print(f"   Project ID: {project_id}")

    # 2. Upload algorithm
    print("\n2. Uploading algorithm...")
    r = api("/files/create", {
        "projectId": project_id,
        "name": "main.py",
        "content": ALGO_CODE,
    })
    if r.get("success"):
        print("   Uploaded main.py")
    else:
        r = api("/files/update", {
            "projectId": project_id,
            "name": "main.py",
            "content": ALGO_CODE,
        })
        if not r.get("success"):
            print("   FAILED to upload code")
            sys.exit(1)
        print("   Updated main.py")

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
    bt_name = f"Intl40ETF_DualMom_{int(tm.time())}"
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
        try:
            r = api("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        except Exception as e:
            print(f"   Network error: {e}, retrying...")
            continue
        bt = r.get("backtest", {})
        completed_flag = bt.get("completed", False)
        progress = bt.get("progress", 0)
        if i % 12 == 0:
            print(f"   {progress:.0%} complete...")
        if completed_flag:
            completed = True
            break

    if not completed:
        print("   Timed out after 30 min!")
        print(f"   Check: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")
        # Save what we have
        out = os.path.join(SCRIPT_DIR, "qc_intl_40etf_results.json")
        with open(out, "w") as f:
            json.dump({"project_id": project_id, "backtest_id": backtest_id,
                        "status": "timeout", "last_response": r}, f, indent=2, default=str)
        print(f"   Partial results saved to: {out}")
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

    logs = bt.get("logs", "")
    if logs:
        lines = logs.strip().split("\n")
        rebal_lines = [l for l in lines if "REBAL" in l]
        print(f"\n  REBALANCE LOG ({len(rebal_lines)} entries, showing last 15):")
        for l in rebal_lines[-15:]:
            print(f"    {l}")

    out = os.path.join(SCRIPT_DIR, "qc_intl_40etf_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results saved to: {out}")
    print(f"  View: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
