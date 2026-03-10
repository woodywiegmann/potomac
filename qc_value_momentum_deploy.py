"""
QuantConnect Deployment: Value + Momentum 90/10 Long/Short
============================================================
Strategy:
  - Universe: US equities, market cap > $2B, ex-Financials/REITs
  - 90% long (top 50 by composite), 10% short (bottom 20 by composite)
  - Value: EV/EBITDA, P/E, P/B, P/CF (Morningstar)
  - Momentum: 12-1 month return
  - Quality filters on long book only (ROE > 5%, positive EPS, D/E < 3)
  - Quarterly rebalance (last trading day of Mar/Jun/Sep/Dec)
  - Benchmark: SPY

Usage:
    python qc_value_momentum_deploy.py
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


class ValueMomentumLongShort(QCAlgorithm):
    """
    Value + Momentum 90/10 Long/Short (QVAL/QMOM Style)
    ======================================================
    Universe:   US equities, market cap > $2B, ex-Financials/REITs
    Long (90%): Top 50 by composite score from quality-passing stocks
    Short (10%): Bottom 20 by composite score (no quality filter)
    Value:      EV/EBITDA (30%), P/E (25%), P/B (25%), P/CF (20%)
    Momentum:   12-1 month return (skip recent month)
    Quality:    ROE > 5%, positive EPS, D/E < 3.0 (long only)
    Composite:  50% Value + 50% Momentum
    Rebalance:  Quarterly (last trading day of Mar/Jun/Sep/Dec)
    """

    def initialize(self):
        self.set_start_date(2010, 1, 1)
        self.set_end_date(2026, 3, 1)
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")

        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.coarse_selection, self.fine_selection)

        # ── Configurable parameters ───────────────────────────────
        self.value_weight = 0.50
        self.momentum_weight = 0.50
        self.n_long = 50
        self.n_short = 20
        self.long_alloc = 0.90
        self.short_alloc = 0.10
        self.min_market_cap = 2e9
        self.momentum_lookback = 252
        self.skip_recent = 21

        self.rebalance_months = {3, 6, 9, 12}
        self.rebalance_scheduled = False
        self.last_rebalance_month = 0

        self.long_targets = []
        self.short_targets = []

        self.schedule.on(
            self.date_rules.month_end(),
            self.time_rules.before_market_close("SPY", 60),
            self.check_rebalance
        )

        self.settings.free_portfolio_value_percentage = 0.02

    def check_rebalance(self):
        if self.time.month in self.rebalance_months and self.time.month != self.last_rebalance_month:
            self.rebalance_scheduled = True

    def coarse_selection(self, coarse):
        if not self.rebalance_scheduled:
            return Universe.UNCHANGED

        return [c.symbol for c in coarse
                if c.has_fundamental_data and c.market_cap > self.min_market_cap]

    def fine_selection(self, fine):
        filtered = [
            f for f in fine
            if (f.asset_classification.morningstar_sector_code
                not in [MorningstarSectorCode.FINANCIAL_SERVICES,
                        MorningstarSectorCode.REAL_ESTATE])
        ]

        records = []
        for f in filtered:
            ev_ebitda = f.valuation_ratios.ev_to_ebitda
            pe = f.valuation_ratios.pe_ratio
            pb = f.valuation_ratios.pb_ratio
            pcf = f.valuation_ratios.pcf_ratio
            roe = f.operation_ratios.roe.one_year
            de = f.operation_ratios.long_term_debt_equity_ratio.one_year
            eps = f.earning_reports.basic_eps.three_months

            records.append({
                "symbol": f.symbol,
                "ev_ebitda": ev_ebitda if ev_ebitda and ev_ebitda > 0 else None,
                "pe": pe if pe and pe > 0 else None,
                "pb": pb if pb and pb > 0 else None,
                "pcf": pcf if pcf and pcf > 0 else None,
                "roe": roe,
                "de": de,
                "eps": eps if eps else 0,
                "sector": f.asset_classification.morningstar_sector_code,
            })

        if len(records) < self.n_long + self.n_short:
            return Universe.UNCHANGED

        def pctile_asc(vals):
            arr = np.array(vals, dtype=float)
            valid = ~np.isnan(arr)
            ranks = np.full(len(arr), 50.0)
            if valid.sum() > 1:
                from scipy.stats import rankdata
                r = rankdata(arr[valid])
                pct = 100.0 * (1.0 - (r - 1) / max(len(r) - 1, 1))
                ranks[valid] = pct
            return ranks

        def pctile_desc(vals):
            arr = np.array(vals, dtype=float)
            valid = ~np.isnan(arr)
            ranks = np.full(len(arr), 50.0)
            if valid.sum() > 1:
                from scipy.stats import rankdata
                r = rankdata(arr[valid])
                pct = 100.0 * ((r - 1) / max(len(r) - 1, 1))
                ranks[valid] = pct
            return ranks

        ev_vals = [r["ev_ebitda"] if r["ev_ebitda"] else float("nan") for r in records]
        pe_vals = [r["pe"] if r["pe"] else float("nan") for r in records]
        pb_vals = [r["pb"] if r["pb"] else float("nan") for r in records]
        pcf_vals = [r["pcf"] if r["pcf"] else float("nan") for r in records]

        ev_pct = pctile_asc(ev_vals)
        pe_pct = pctile_asc(pe_vals)
        pb_pct = pctile_asc(pb_vals)
        pcf_pct = pctile_asc(pcf_vals)

        for i, rec in enumerate(records):
            rec["value_score"] = 0.30 * ev_pct[i] + 0.25 * pe_pct[i] + 0.25 * pb_pct[i] + 0.20 * pcf_pct[i]

        all_symbols = [r["symbol"] for r in records]

        self.long_targets = []
        self.short_targets = []
        self._all_records = records

        return all_symbols

    def on_data(self, data):
        if self.is_warming_up or not self.rebalance_scheduled:
            return
        self.rebalance_scheduled = False
        self.last_rebalance_month = self.time.month
        self.rebalance(data)

    def rebalance(self, data):
        records = getattr(self, "_all_records", [])
        if not records:
            self.log("REBAL: No records from universe selection")
            return

        scored = []
        for rec in records:
            symbol = rec["symbol"]
            if not self.securities.contains_key(symbol):
                continue
            if not self.securities[symbol].has_data:
                continue

            history = self.history(symbol, self.momentum_lookback + 10, Resolution.DAILY)
            if history.empty or len(history) < self.momentum_lookback:
                continue
            try:
                prices = history["close"]
                p_12m = prices.iloc[0]
                p_1m = prices.iloc[-(self.skip_recent + 1)]
                if p_12m <= 0 or p_1m <= 0:
                    continue
                mom_12_1 = (p_1m / p_12m) - 1.0
            except (IndexError, KeyError):
                continue

            rec["mom_12_1"] = mom_12_1
            scored.append(rec)

        if len(scored) < self.n_long:
            self.log(f"REBAL: Only {len(scored)} scored, need {self.n_long}")
            return

        mom_vals = [r["mom_12_1"] for r in scored]
        arr = np.array(mom_vals, dtype=float)
        valid = ~np.isnan(arr)
        mom_pct = np.full(len(arr), 50.0)
        if valid.sum() > 1:
            from scipy.stats import rankdata
            r = rankdata(arr[valid])
            pct = 100.0 * ((r - 1) / max(len(r) - 1, 1))
            mom_pct[valid] = pct

        for i, rec in enumerate(scored):
            rec["momentum_score"] = mom_pct[i]
            rec["composite"] = self.value_weight * rec["value_score"] + self.momentum_weight * rec["momentum_score"]

        # Long book: quality-filtered, top N
        quality_pass = [
            r for r in scored
            if (r["eps"] > 0
                and (r["roe"] is None or r["roe"] == 0 or r["roe"] > 0.05)
                and (r["de"] is None or r["de"] == 0 or r["de"] < 3.0))
        ]
        quality_pass.sort(key=lambda x: x["composite"], reverse=True)
        long_picks = quality_pass[:self.n_long]

        # Short book: worst composite from all scored (no quality filter)
        scored.sort(key=lambda x: x["composite"])
        short_picks = scored[:self.n_short]

        long_symbols = set(r["symbol"] for r in long_picks)
        short_symbols = set(r["symbol"] for r in short_picks)

        # Remove overlap (stock can't be in both books)
        short_symbols -= long_symbols

        long_weight = self.long_alloc / max(len(long_symbols), 1)
        short_weight = self.short_alloc / max(len(short_symbols), 1)

        # Log
        top5 = ", ".join([f"{r['symbol'].value}(C={r['composite']:.0f})" for r in long_picks[:5]])
        bot5 = ", ".join([f"{r['symbol'].value}(C={r['composite']:.0f})" for r in short_picks[:5]])
        self.log(f"REBAL Q{self.time.month//3}: {len(long_symbols)}L/{len(short_symbols)}S | "
                 f"Top5: [{top5}] | Bot5: [{bot5}]")

        # TLH opportunity logging
        tlh_count = 0
        tlh_loss = 0.0
        for kvp in self.portfolio:
            h = kvp.value
            if h.invested and h.unrealized_profit_percent < -0.02:
                tlh_count += 1
                tlh_loss += abs(h.unrealized_profit)
        if tlh_count > 0:
            self.log(f"  TLH: {tlh_count} positions with >2% loss, ${tlh_loss:,.0f} harvestable")

        # Liquidate positions not in either book
        target_all = long_symbols | short_symbols
        for kvp in self.portfolio:
            h = kvp.value
            if h.invested and h.symbol not in target_all:
                self.liquidate(h.symbol)

        # Set long positions
        for rec in long_picks:
            sym = rec["symbol"]
            if sym in long_symbols:
                current = 0
                if self.portfolio[sym].invested:
                    current = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
                if abs(current - long_weight) > 0.005:
                    self.set_holdings(sym, long_weight)

        # Set short positions
        for rec in short_picks:
            sym = rec["symbol"]
            if sym in short_symbols:
                current = 0
                if self.portfolio[sym].invested:
                    current = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
                target = -short_weight
                if abs(current - target) > 0.003:
                    self.set_holdings(sym, target)

    def on_end_of_algorithm(self):
        self.log(f"FINAL: Portfolio Value = ${self.portfolio.total_portfolio_value:,.0f}")
        longs = []
        shorts = []
        for kvp in self.portfolio:
            h = kvp.value
            if h.invested:
                pct = h.holdings_value / self.portfolio.total_portfolio_value
                if h.quantity > 0:
                    longs.append((h.symbol.value, h.holdings_value, pct))
                else:
                    shorts.append((h.symbol.value, h.holdings_value, pct))
        longs.sort(key=lambda x: x[1], reverse=True)
        shorts.sort(key=lambda x: abs(x[1]), reverse=True)
        self.log(f"  Long positions: {len(longs)}")
        for name, val, pct in longs[:5]:
            self.log(f"    {name}: ${val:,.0f} ({pct:.1%})")
        self.log(f"  Short positions: {len(shorts)}")
        for name, val, pct in shorts[:5]:
            self.log(f"    {name}: ${val:,.0f} ({pct:.1%})")
'''


def main():
    print("=" * 70)
    print("  QC DEPLOY: Value + Momentum 90/10 Long/Short")
    print("  Universe: US equities, mkt cap > $2B, ex-Financials/REITs")
    print("  Long (90%): Top 50 by V+M composite (quality filtered)")
    print("  Short (10%): Bottom 20 by V+M composite")
    print("  Quarterly rebalance (Mar/Jun/Sep/Dec)")
    print("  Backtest: 2010-01-01 to 2026-03-01")
    print("=" * 70)

    # 1. Create project
    print("\n1. Creating project...")
    r = api("/projects/create", {
        "name": f"ValueMom_LongShort_{int(tm.time())}",
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
    bt_name = f"ValueMom_LongShort_{int(tm.time())}"
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
    print("   (16-year US equity L/S with fundamentals -- expect 20-60 min)")
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
        out = os.path.join(SCRIPT_DIR, "qc_value_momentum_results.json")
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
    print("RESULTS: Value + Momentum 90/10 Long/Short")
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
        tlh_lines = [l for l in lines if "TLH" in l]
        print(f"\n  REBALANCE LOG ({len(rebal_lines)} entries, showing last 8):")
        for l in rebal_lines[-8:]:
            print(f"    {l}")
        if tlh_lines:
            print(f"\n  TLH OPPORTUNITIES ({len(tlh_lines)} entries, showing last 8):")
            for l in tlh_lines[-8:]:
                print(f"    {l}")

    out = os.path.join(SCRIPT_DIR, "qc_value_momentum_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results saved to: {out}")
    print(f"  View: https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
