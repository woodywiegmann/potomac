"""
QuantConnect Deployment: SPMO Replica 50 (No Tactical Overlay)
===============================================================
Always invested in a 50-stock momentum portfolio:
  - Monthly rebalance
  - 6m + 12m risk-adjusted momentum score
  - Cap-aware + momentum-rank-aware weighting
  - No tactical regime overlay

Outputs:
  - qc_spmo_replica_50_results.json
  - qc_spmo_replica_50_daily_returns.csv

Usage:
  python qc_spmo_replica_50_deploy.py
"""

import csv
import json
import os
import sys
import time as time_mod
from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256

from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_headers():
    timestamp = str(int(time_mod.time()))
    hashed = sha256(f"{API_TOKEN}:{timestamp}".encode("utf-8")).hexdigest()
    auth = b64encode(f"{USER_ID}:{hashed}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {auth}", "Timestamp": timestamp}


def api_post(endpoint, payload=None):
    url = f"{BASE_URL}{endpoint}"
    resp = post(url, headers=get_headers(), json=payload or {})
    data = resp.json()
    if not data.get("success"):
        print(f"  API ERROR {endpoint}: {json.dumps(data, indent=2)}")
    return data


ALGO_CODE = r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np


class TenBpsSlippage:
    def get_slippage_approximation(self, asset, order):
        return asset.price * 0.001


class SpmoReplica50(QCAlgorithm):
    """
    SPMO-style 50-stock momentum replica without tactical overlay.
    """
    N = 50
    LB6 = 126
    LB12 = 252
    MIN_CAP = 5e9
    MAX_W = 0.06

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 3, 1)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.coarse_selection, self.fine_selection)

        self.rebalance_flag = True
        self.pending_rebalance = False
        self.target_weights = {}
        self.current_universe = []

        self.schedule.on(
            self.date_rules.month_end("SPY"),
            self.time_rules.before_market_close("SPY", 20),
            self._schedule_rebalance
        )

        self.settings.free_portfolio_value_percentage = 0.01

    def _schedule_rebalance(self):
        self.rebalance_flag = True

    def coarse_selection(self, coarse):
        if not self.rebalance_flag:
            return Universe.UNCHANGED

        c = [
            x for x in coarse
            if x.has_fundamental_data and x.price is not None and x.price > 5
        ]
        c = sorted(c, key=lambda x: x.dollar_volume, reverse=True)[:1200]
        return [x.symbol for x in c]

    def fine_selection(self, fine):
        if not self.rebalance_flag:
            return Universe.UNCHANGED

        filtered = [
            f for f in fine
            if f.market_cap is not None and f.market_cap >= self.MIN_CAP
        ]
        filtered = sorted(filtered, key=lambda f: f.market_cap, reverse=True)[:500]

        rows = []
        for f in filtered:
            sym = f.symbol
            hist = self.history(sym, self.LB12 + 5, Resolution.DAILY)
            if hist.empty or len(hist) < self.LB12:
                continue
            try:
                px = hist["close"].dropna()
                if len(px) < self.LB12:
                    continue
                p_now = float(px.iloc[-1])
                p_6m = float(px.iloc[-self.LB6])
                p_12m = float(px.iloc[-self.LB12])
                if p_now <= 0 or p_6m <= 0 or p_12m <= 0:
                    continue

                r6 = p_now / p_6m - 1.0
                r12 = p_now / p_12m - 1.0
                vol = px.pct_change().iloc[-self.LB12:].std() * np.sqrt(252)
                if vol is None or not np.isfinite(vol) or vol <= 0:
                    continue
                score = 0.5 * (r6 / vol) + 0.5 * (r12 / vol)
                rows.append((sym, float(f.market_cap), float(score)))
            except Exception:
                continue

        if len(rows) < self.N:
            self.debug(f"Insufficient scored names: {len(rows)}")
            self.rebalance_flag = False
            return Universe.UNCHANGED

        rows = sorted(rows, key=lambda x: x[2], reverse=True)[:self.N]
        syms = [x[0] for x in rows]
        caps = np.array([x[1] for x in rows], dtype=float)
        scores = np.array([x[2] for x in rows], dtype=float)

        cap_w = caps / max(caps.sum(), 1e-12)
        ranks = scores.argsort().argsort().astype(float) + 1.0
        rank_w = ranks / max(ranks.sum(), 1e-12)
        w = 0.5 * cap_w + 0.5 * rank_w

        # single-name cap + redistribute
        for _ in range(5):
            over = w > self.MAX_W
            if not np.any(over):
                break
            excess = (w[over] - self.MAX_W).sum()
            w[over] = self.MAX_W
            under = ~over
            if np.any(under) and excess > 0:
                base = w[under].sum()
                if base > 0:
                    w[under] += excess * (w[under] / base)

        w = w / max(w.sum(), 1e-12)
        self.target_weights = {syms[i]: float(w[i]) for i in range(len(syms))}
        self.current_universe = syms
        self.pending_rebalance = True
        self.rebalance_flag = False
        return syms

    def on_data(self, data):
        if not self.pending_rebalance:
            return
        if len(self.target_weights) == 0:
            return

        targets = set(self.target_weights.keys())
        for kv in self.portfolio:
            h = kv.value
            if h.invested and h.symbol not in targets:
                self.liquidate(h.symbol)

        for s, w in self.target_weights.items():
            self.set_holdings(s, w)

        self.pending_rebalance = False
        self.debug(f"Rebalanced {len(self.target_weights)} names.")

    def on_end_of_algorithm(self):
        self.debug("SPMO Replica 50 complete.")
'''


def extract_daily_returns(backtest_payload, out_csv_path):
    bt = backtest_payload.get("backtest", {})
    charts = bt.get("charts", {})
    strategy_chart = charts.get("Strategy Equity", {})
    series = strategy_chart.get("series", {})
    if not series:
        return 0

    first_series = next(iter(series.values()))
    values = first_series.get("values", [])
    if not values:
        return 0

    rows = []
    prev = None
    for point in values:
        x = point.get("x")
        y = point.get("y")
        if x is None or y is None:
            continue
        dt = datetime.fromtimestamp(int(x), tz=timezone.utc).date().isoformat()
        eq = float(y)
        ret = 0.0 if prev is None else (eq / prev - 1.0 if prev != 0 else 0.0)
        rows.append((dt, eq, ret))
        prev = eq

    with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "equity", "daily_ret"])
        w.writerows(rows)
    return len(rows)


def main():
    print("=" * 72)
    print("QUANTCONNECT: SPMO REPLICA 50 (NO OVERLAY)")
    print("=" * 72)

    print("\n1. Authenticating...")
    r = api_post("/authenticate")
    if not r.get("success"):
        print("   Auth failed.")
        sys.exit(1)
    print("   OK")

    print("\n2. Creating project...")
    ts = int(time_mod.time())
    project_name = f"SPMOReplica50_NoOverlay_{ts}"
    r = api_post("/projects/create", {"name": project_name, "language": "Py"})
    if not r.get("success"):
        print("   Failed.")
        sys.exit(1)
    project_id = r["projects"][0]["projectId"]
    print(f"   Project: {project_name} (ID: {project_id})")

    print("\n3. Uploading algorithm...")
    r = api_post("/files/update", {
        "projectId": project_id,
        "name": "main.py",
        "content": ALGO_CODE,
    })
    if not r.get("success"):
        r = api_post("/files/create", {
            "projectId": project_id,
            "name": "main.py",
            "content": ALGO_CODE,
        })
        if not r.get("success"):
            print("   Upload failed.")
            sys.exit(1)
    print("   Uploaded.")

    print("\n4. Compiling...")
    r = api_post("/compile/create", {"projectId": project_id})
    if not r.get("success"):
        print("   Compile request failed.")
        sys.exit(1)
    compile_id = r.get("compileId")

    for _ in range(40):
        time_mod.sleep(3)
        r = api_post("/compile/read", {"projectId": project_id, "compileId": compile_id})
        state = r.get("state", "")
        print(f"   State: {state}")
        if state == "BuildSuccess":
            break
        if state == "BuildError":
            for log in r.get("logs", []):
                print(f"     {log}")
            sys.exit(1)
    else:
        print("   Compile timed out.")
        sys.exit(1)
    print("   Compiled OK.")

    print("\n5. Starting backtest...")
    bt_name = f"SPMOReplica50_NoOverlay_{ts}"
    r = api_post("/backtests/create", {
        "projectId": project_id,
        "compileId": compile_id,
        "backtestName": bt_name,
    })
    if not r.get("success"):
        print("   Backtest creation failed.")
        print(json.dumps(r, indent=2))
        sys.exit(1)
    backtest_id = r["backtest"]["backtestId"]
    print(f"   Backtest: {bt_name} (ID: {backtest_id})")

    print("\n6. Waiting for completion...")
    for _ in range(480):
        time_mod.sleep(5)
        r = api_post("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = r.get("backtest", {})
        progress = bt.get("progress", 0)
        if bt.get("completed", False):
            print(f"\n   Done at {progress:.0%}.")
            break
        print(f"   {progress:.0%}", end="\r")
    else:
        print("\n   Timed out.")
        sys.exit(1)

    bt = r.get("backtest", {})
    stats = bt.get("statistics", {})

    out_json = os.path.join(SCRIPT_DIR, "qc_spmo_replica_50_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, default=str)

    out_csv = os.path.join(SCRIPT_DIR, "qc_spmo_replica_50_daily_returns.csv")
    n_rows = extract_daily_returns(r, out_csv)

    print("\n" + "=" * 72)
    print("SPMO REPLICA 50 (NO OVERLAY) RESULTS")
    print("=" * 72)
    for key in [
        "Total Return", "Compounding Annual Return", "Drawdown",
        "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
        "Alpha", "Beta", "Annual Standard Deviation",
        "Portfolio Turnover", "Total Fees", "Total Orders"
    ]:
        print(f"  {key:.<40} {stats.get(key, 'N/A')}")
    print(f"  Daily return rows exported............. {n_rows}")
    print(f"  Results JSON........................... {out_json}")
    print(f"  Daily returns CSV...................... {out_csv}")
    print(f"  View................................... https://www.quantconnect.com/project/{project_id}")
    print("=" * 72)


if __name__ == "__main__":
    main()
