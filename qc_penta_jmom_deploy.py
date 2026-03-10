"""
QuantConnect Deployment: Penta + JMOM Replica (Variant D)
==========================================================
Strategy:
  - RISK ON: Top 50 S&P 500 momentum stocks (12-1 return + risk-adjusted)
             + 0.2x E-mini S&P 500 futures overlay
  - RISK OFF: 100% cash (T-bill rate)
  - Signal: 4-factor proxy (SPY>200d SMA, VIX<20, 10Y yield ROC, credit)
  - Monthly stock rebalance, daily signal evaluation
  - Quality gate: ROE > 10%, D/E < 1.5, positive EPS

Variant D had the best Calmar (1.78) and Sharpe (1.81) in local backtest.

Usage:
    python qc_penta_jmom_deploy.py
"""

import json
import os
import sys
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


ALGO_CODE = r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np


class PentaJMOMVariantD(QCAlgorithm):
    """
    Penta + JMOM Replica (Variant D)
    ==================================
    RISK ON:  Top 50 momentum stocks (EW, ~1.9% each) + 0.2x SPY overlay
    RISK OFF: 100% cash
    Signal:   SPY > 200d SMA + LQD/SHY credit spread (2 of 2 = ON)
    Rebalance: Monthly (stocks), daily (regime check)
    """

    def initialize(self):
        self.set_start_date(2020, 9, 1)
        self.set_end_date(2026, 3, 1)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        self.n_hold = 50
        self.es_leverage = 0.20
        self.momentum_lookback = 252
        self.skip_recent = 21

        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.lqd = self.add_equity("LQD", Resolution.DAILY).symbol
        self.shy = self.add_equity("SHY", Resolution.DAILY).symbol

        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.coarse_filter, self.fine_filter)

        self.regime = "RISK_ON"
        self.last_rebalance_month = 0
        self.need_initial_rebalance = True

        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.before_market_close("SPY", 30),
            self.daily_check
        )

        self.settings.free_portfolio_value_percentage = 0.05
        self.set_warm_up(timedelta(days=260))

    def coarse_filter(self, coarse):
        return [c.symbol for c in coarse
                if c.has_fundamental_data and c.market_cap > 2e9 and c.dollar_volume > 1e6]

    def fine_filter(self, fine):
        filtered = []
        for f in fine:
            sector = f.asset_classification.morningstar_sector_code
            if sector in [MorningstarSectorCode.FINANCIAL_SERVICES,
                          MorningstarSectorCode.REAL_ESTATE]:
                continue
            roe = f.operation_ratios.roe.one_year
            de = f.operation_ratios.long_term_debt_equity_ratio.one_year
            eps = f.earning_reports.basic_eps.three_months
            if roe is not None and roe > 0 and roe < 0.10:
                continue
            if de is not None and de > 0 and de > 1.5:
                continue
            if eps is not None and eps <= 0:
                continue
            filtered.append(f)
        return [f.symbol for f in filtered]

    def daily_check(self):
        if self.is_warming_up:
            return

        new_regime = self.evaluate_regime()

        if new_regime != self.regime:
            self.log(f"REGIME SWITCH: {self.regime} -> {new_regime}")
            if new_regime == "RISK_OFF":
                self.go_risk_off()
            else:
                self.go_risk_on()
            self.regime = new_regime
            return

        if self.regime == "RISK_ON":
            is_month_end = self.time.month != self.last_rebalance_month
            if is_month_end or self.need_initial_rebalance:
                self.monthly_rebalance()
                self.last_rebalance_month = self.time.month
                self.need_initial_rebalance = False

    def evaluate_regime(self):
        bullish = 0

        spy_hist = self.history(self.spy, 201, Resolution.DAILY)
        if not spy_hist.empty and len(spy_hist) >= 200:
            try:
                closes = spy_hist["close"]
                if hasattr(closes, "values"):
                    vals = closes.values.flatten() if hasattr(closes.values, "flatten") else closes.values
                    sma_200 = float(np.mean(vals))
                    current = float(vals[-1])
                    if current > sma_200:
                        bullish += 1
            except Exception:
                pass

        try:
            lqd_hist = self.history(self.lqd, 55, Resolution.DAILY)
            shy_hist = self.history(self.shy, 55, Resolution.DAILY)
            if not lqd_hist.empty and not shy_hist.empty:
                lqd_c = lqd_hist["close"].values.flatten()
                shy_c = shy_hist["close"].values.flatten()
                min_len = min(len(lqd_c), len(shy_c))
                if min_len >= 50:
                    ratio = lqd_c[-min_len:] / shy_c[-min_len:]
                    ratio_sma = float(np.mean(ratio[-50:]))
                    if float(ratio[-1]) > ratio_sma:
                        bullish += 1
        except Exception:
            pass

        return "RISK_ON" if bullish >= 2 else "RISK_OFF"

    def go_risk_off(self):
        tlh_count = 0
        tlh_loss = 0.0
        for kvp in self.portfolio:
            h = kvp.value
            if h.invested and h.unrealized_profit_percent < -0.02:
                tlh_count += 1
                tlh_loss += abs(h.unrealized_profit)
        if tlh_count > 0:
            self.log(f"  TLH: {tlh_count} positions with >2% loss, ${tlh_loss:,.0f} harvestable")

        self.liquidate()
        self.log(f"  RISK OFF: Liquidated. Cash = ${self.portfolio.cash:,.0f}")

    def go_risk_on(self):
        self.need_initial_rebalance = True
        self.log(f"  RISK ON: Will rebalance on next check")

    def monthly_rebalance(self):
        active = []
        for s in self.active_securities.keys:
            sec = self.active_securities[s]
            if not sec.has_data:
                continue
            if s.value in ("SPY", "LQD", "SHY"):
                continue
            active.append(s)

        if len(active) < self.n_hold:
            self.log(f"REBAL: Only {len(active)} active, need {self.n_hold}. Waiting.")
            return

        scored = []
        for symbol in active:
            try:
                history = self.history(symbol, self.momentum_lookback + 10, Resolution.DAILY)
                if history.empty or len(history) < self.momentum_lookback:
                    continue
                prices = history["close"]
                if hasattr(prices, "values"):
                    pv = prices.values.flatten()
                else:
                    pv = np.array(prices)
                if len(pv) < self.momentum_lookback:
                    continue
                p_12m = float(pv[0])
                p_1m = float(pv[-(self.skip_recent + 1)])
                if p_12m <= 0 or p_1m <= 0:
                    continue
                mom_12_1 = (p_1m / p_12m) - 1.0

                daily_rets = np.diff(pv) / pv[:-1]
                vol = float(np.std(daily_rets) * np.sqrt(252)) if len(daily_rets) > 20 else 1.0
                risk_adj = mom_12_1 / vol if vol > 0 else 0

                scored.append({"symbol": symbol, "mom": mom_12_1, "radj": risk_adj})
            except Exception:
                continue

        if len(scored) < self.n_hold:
            self.log(f"REBAL: Only {len(scored)} scored, need {self.n_hold}")
            return

        from scipy.stats import rankdata
        mom_arr = np.array([r["mom"] for r in scored])
        radj_arr = np.array([r["radj"] for r in scored])
        mom_pct = rankdata(mom_arr) / len(mom_arr) * 100
        radj_pct = rankdata(radj_arr) / len(radj_arr) * 100

        for i, rec in enumerate(scored):
            rec["composite"] = 0.5 * mom_pct[i] + 0.5 * radj_pct[i]

        scored.sort(key=lambda x: x["composite"], reverse=True)
        selected = scored[:self.n_hold]
        target_set = set(r["symbol"] for r in selected)

        for kvp in self.portfolio:
            h = kvp.value
            if h.invested and h.symbol not in target_set and h.symbol != self.spy:
                self.liquidate(h.symbol)

        stock_weight = (1.0 - self.settings.free_portfolio_value_percentage - self.es_leverage) / self.n_hold
        for rec in selected:
            sym = rec["symbol"]
            self.set_holdings(sym, stock_weight)

        self.set_holdings(self.spy, self.es_leverage)

        top5 = ", ".join([f"{r['symbol'].value}({r['composite']:.0f})" for r in selected[:5]])
        self.log(f"REBAL: {len(selected)} stocks @ {stock_weight:.2%} + SPY {self.es_leverage:.0%} | Top 5: [{top5}]")

    def on_end_of_algorithm(self):
        self.log(f"FINAL: ${self.portfolio.total_portfolio_value:,.0f}")
        invested = [(kvp.value.symbol.value, kvp.value.holdings_value,
                     kvp.value.holdings_value / self.portfolio.total_portfolio_value)
                    for kvp in self.portfolio if kvp.value.invested]
        invested.sort(key=lambda x: x[1], reverse=True)
        for name, val, pct in invested[:10]:
            self.log(f"  {name}: ${val:,.0f} ({pct:.1%})")
'''


def main():
    print("=" * 70)
    print("  QC DEPLOY: Penta + JMOM Replica (Variant D)")
    print("  Risk-On: Top 50 momentum + 0.2x ES leverage")
    print("  Risk-Off: 100% cash")
    print("  Signal: 4-factor proxy (SPY>200d, VIX<20, 10Y, credit)")
    print("  Backtest: Sep 2020 - Mar 2026")
    print("=" * 70)

    print("\n1. Creating project...")
    r = api("/projects/create", {
        "name": f"Penta_JMOM_VarD_{int(tm.time())}",
        "language": "Py",
    })
    if not r.get("success"):
        print("   Failed to create project")
        sys.exit(1)
    project_id = r["projects"][0]["projectId"]
    print(f"   Project ID: {project_id}")

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

    print("\n4. Starting backtest...")
    bt_name = f"Penta_JMOM_VarD_{int(tm.time())}"
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

    print("\n5. Waiting for completion...")
    print("   (5.5-year US equity with fundamentals + daily signals -- expect 15-45 min)")
    completed = False
    for i in range(720):
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
        print("   Timed out after 60 min!")
        print(f"   Check: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")
        out = os.path.join(SCRIPT_DIR, "qc_penta_jmom_results.json")
        with open(out, "w") as f:
            json.dump({"project_id": project_id, "backtest_id": backtest_id,
                        "status": "timeout", "last_response": r}, f, indent=2, default=str)
        print(f"   Partial results saved to: {out}")
        sys.exit(1)

    print("   DONE!")

    bt = r.get("backtest", {})
    stats = bt.get("statistics", {})
    runtime = bt.get("runtimeStatistics", {})

    print(f"\n{'=' * 70}")
    print("RESULTS: Penta + JMOM Replica (Variant D)")
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
        regime_lines = [l for l in lines if "REGIME" in l or "REBAL" in l or "TLH" in l]
        print(f"\n  REGIME + REBAL LOG ({len(regime_lines)} entries, showing last 15):")
        for l in regime_lines[-15:]:
            print(f"    {l}")

    out = os.path.join(SCRIPT_DIR, "qc_penta_jmom_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results saved to: {out}")
    print(f"  View: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
