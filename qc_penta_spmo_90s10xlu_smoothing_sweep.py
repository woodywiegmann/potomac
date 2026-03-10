"""
QuantConnect Deployment: Penta Smoothing Sweep (SPMO / 90% SGOV + 10% XLU)
===========================================================================
Runs a 3-way smoothing sweep on the binary Penta signal:
  - 3-day SMA
  - 5-day SMA
  - 10-day SMA

Risk on:  100% SPMO
Risk off: 90% SGOV + 10% XLU
Execution: midday (~noon ET)
Costs: 10bps slippage per side (20bps round-trip)

Usage:
    python qc_penta_spmo_90s10xlu_smoothing_sweep.py
"""

import csv
import json
import os
import sys
import time as time_mod
from base64 import b64encode
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


ALGO_TEMPLATE = r'''
from AlgorithmImports import *
from datetime import timedelta
from collections import deque
import numpy as np


class TenBpsSlippage:
    """10bps slippage per side = 20bps round-trip."""
    def get_slippage_approximation(self, asset, order):
        return asset.price * 0.001


class PentaSPMOSweep(QCAlgorithm):
    WARMUP_DAYS = 252
    SMA50 = 50
    SMA5 = 5
    SMOOTH_WINDOW = __SMOOTH_WINDOW__

    def initialize(self):
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        self.spmo = self.add_equity("SPMO", Resolution.DAILY).symbol
        self.sgov = self.add_equity("SGOV", Resolution.DAILY).symbol
        self.xlu = self.add_equity("XLU", Resolution.DAILY).symbol

        self.spy_sym = self.add_equity("SPY", Resolution.DAILY).symbol
        self.iyt_sym = self.add_equity("IYT", Resolution.DAILY).symbol
        self.lqd_sym = self.add_equity("LQD", Resolution.DAILY).symbol

        try:
            self.nya_sym = self.add_index("NYA", Resolution.DAILY).symbol
        except Exception:
            self.nya_sym = self.add_equity("VTI", Resolution.DAILY).symbol

        self._current_target = None
        self._switch_count = 0
        self._penta_history = deque(maxlen=self.SMOOTH_WINDOW)

        slippage = TenBpsSlippage()
        self.securities[self.spmo].set_slippage_model(slippage)
        self.securities[self.sgov].set_slippage_model(slippage)
        self.securities[self.xlu].set_slippage_model(slippage)

        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 180),
            self._daily_check,
        )

        self.set_warm_up(timedelta(days=self.WARMUP_DAYS))

    def _get_target(self):
        lookback = self.SMA50 + self.SMA5 + 5
        spy_h = self.history(self.spy_sym, lookback, Resolution.DAILY)
        iyt_h = self.history(self.iyt_sym, 15, Resolution.DAILY)
        nya_h = self.history(self.nya_sym, 15, Resolution.DAILY)
        lqd_h = self.history(self.lqd_sym, 15, Resolution.DAILY)

        if spy_h.empty or len(spy_h) < self.SMA50 + self.SMA5:
            return None, 0.0
        spy_c = spy_h["close"].values.astype(float)
        n = len(spy_c)

        binary_5 = []
        for i in range(5):
            end_idx = n - 1 - i
            start_idx = end_idx - (self.SMA50 - 1)
            if start_idx >= 0 and end_idx >= self.SMA50 - 1:
                sma50_i = np.mean(spy_c[start_idx:end_idx + 1])
                binary_5.append(1.0 if spy_c[end_idx] > sma50_i else 0.0)
            else:
                binary_5.append(0.0)
        trend_smooth = np.mean(binary_5) if binary_5 else 0.0
        p1 = 1 if trend_smooth > 0.5 else 0

        if iyt_h.empty or len(iyt_h) < 5:
            p2 = 1
        else:
            iyt_c = iyt_h["close"].values.astype(float)
            p2 = 1 if iyt_c[-1] > np.mean(iyt_c[-5:]) else 0

        if nya_h.empty or len(nya_h) < 5:
            p3 = 1
        else:
            nya_c = nya_h["close"].values.astype(float)
            p3 = 1 if nya_c[-1] > np.mean(nya_c[-5:]) else 0

        if lqd_h.empty or len(lqd_h) < 5:
            p4 = 1
        else:
            lqd_c = lqd_h["close"].values.astype(float)
            p4 = 1 if lqd_c[-1] > np.mean(lqd_c[-5:]) else 0

        raw_on = 1.0 if (p1 + p2 + p3 + p4) >= 3 else 0.0
        self._penta_history.append(raw_on)
        if len(self._penta_history) < self.SMOOTH_WINDOW:
            return None, 0.0

        smoothed = sum(self._penta_history) / len(self._penta_history)
        return ("SPMO" if smoothed > 0.5 else "DEFENSIVE"), smoothed

    def _daily_check(self):
        if self.is_warming_up:
            return

        target, comp = self._get_target()
        if target is None:
            return
        if self._current_target == target:
            return

        old = self._current_target or "NONE"
        self._current_target = target
        self._switch_count += 1
        self.debug(
            f"SWITCH #{self._switch_count}: {old} -> {target} | smooth={comp:.2f}"
        )

        self.liquidate()
        if target == "SPMO":
            self.set_holdings(self.spmo, 1.0)
        else:
            self.set_holdings(self.sgov, 0.90)
            self.set_holdings(self.xlu, 0.10)

    def on_end_of_algorithm(self):
        years = (self.end_date - self.start_date).days / 365.25
        self.debug("=" * 50)
        self.debug(f"PENTA {self.SMOOTH_WINDOW}d-SMOOTH SUMMARY")
        self.debug(f"Risk-on: 100% SPMO")
        self.debug(f"Risk-off: 90% SGOV + 10% XLU")
        self.debug(f"Regime switches: {self._switch_count}")
        self.debug(f"Switches/year: {self._switch_count / max(years, 0.1):.1f}")
        self.debug("=" * 50)
'''


def run_one_backtest(smooth_window: int):
    ts = int(time_mod.time())
    project_name = f"PentaSmooth{smooth_window}d_SPMO_90S10U_{ts}"
    bt_name = project_name
    algo_code = ALGO_TEMPLATE.replace("__SMOOTH_WINDOW__", str(smooth_window))

    print("\n" + "=" * 72)
    print(f"RUNNING SMOOTH WINDOW = {smooth_window}")
    print("=" * 72)

    r = api_post("/projects/create", {"name": project_name, "language": "Py"})
    if not r.get("success"):
        raise RuntimeError("Project creation failed.")
    project_id = r["projects"][0]["projectId"]
    print(f"Project: {project_name} (ID: {project_id})")

    r = api_post("/files/update", {"projectId": project_id, "name": "main.py", "content": algo_code})
    if not r.get("success"):
        r = api_post("/files/create", {"projectId": project_id, "name": "main.py", "content": algo_code})
        if not r.get("success"):
            raise RuntimeError("File upload failed.")

    r = api_post("/compile/create", {"projectId": project_id})
    if not r.get("success"):
        raise RuntimeError("Compile request failed.")
    compile_id = r.get("compileId")

    for _ in range(30):
        time_mod.sleep(3)
        c = api_post("/compile/read", {"projectId": project_id, "compileId": compile_id})
        state = c.get("state", "")
        print(f"Compile state: {state}")
        if state == "BuildSuccess":
            break
        if state == "BuildError":
            logs = c.get("logs", [])
            raise RuntimeError(f"Compile failed: {' | '.join(logs)}")
    else:
        raise RuntimeError("Compile timed out.")

    r = api_post("/backtests/create", {"projectId": project_id, "compileId": compile_id, "backtestName": bt_name})
    if not r.get("success"):
        raise RuntimeError(f"Backtest creation failed: {json.dumps(r)}")
    backtest_id = r["backtest"]["backtestId"]
    print(f"Backtest: {bt_name} (ID: {backtest_id})")

    for _ in range(220):
        time_mod.sleep(5)
        read = api_post("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = read.get("backtest", {})
        progress = bt.get("progress", 0)
        if bt.get("completed", False):
            print(f"Completed at {progress:.0%}.")
            stats = bt.get("statistics", {})
            out_json = os.path.join(
                SCRIPT_DIR, f"qc_penta_spmo_90s10xlu_{smooth_window}dsmooth_results.json"
            )
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(read, f, indent=2, default=str)
            return {
                "smooth_window": smooth_window,
                "project_id": project_id,
                "backtest_id": backtest_id,
                "project_name": project_name,
                "total_return": stats.get("Total Return", "N/A"),
                "cagr": stats.get("Compounding Annual Return", "N/A"),
                "drawdown": stats.get("Drawdown", "N/A"),
                "sharpe": stats.get("Sharpe Ratio", "N/A"),
                "sortino": stats.get("Sortino Ratio", "N/A"),
                "calmar": stats.get("Calmar Ratio", "N/A"),
                "beta": stats.get("Beta", "N/A"),
                "std_ann": stats.get("Annual Standard Deviation", "N/A"),
                "turnover": stats.get("Portfolio Turnover", "N/A"),
                "orders": stats.get("Total Orders", "N/A"),
                "fees": stats.get("Total Fees", "N/A"),
                "url": f"https://www.quantconnect.com/project/{project_id}",
                "json_path": out_json,
            }
        print(f"Progress: {progress:.0%}", end="\r")

    raise RuntimeError("Backtest timed out.")


def main():
    print("=" * 72)
    print("QUANTCONNECT SWEEP: SPMO vs 90% SGOV + 10% XLU")
    print("Smoothing windows: 3, 5, 10")
    print("=" * 72)

    print("\nAuthenticating...")
    auth = api_post("/authenticate")
    if not auth.get("success"):
        print("Auth failed.")
        sys.exit(1)
    print("Auth OK.")

    windows = [3, 5, 10]
    results = []
    for w in windows:
        res = run_one_backtest(w)
        results.append(res)

    out_csv = os.path.join(SCRIPT_DIR, "qc_penta_spmo_90s10xlu_smoothing_sweep_summary.csv")
    fields = [
        "smooth_window",
        "total_return",
        "cagr",
        "drawdown",
        "sharpe",
        "sortino",
        "calmar",
        "beta",
        "std_ann",
        "turnover",
        "orders",
        "fees",
        "project_name",
        "project_id",
        "backtest_id",
        "url",
        "json_path",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print("\n" + "=" * 72)
    print("SWEEP COMPLETE")
    print("=" * 72)
    print(f"{'SMA':>5s} {'Total Return':>14s} {'CAGR':>10s} {'DD':>8s} {'Sharpe':>8s} {'Turnover':>10s} {'Orders':>8s}")
    print("-" * 72)
    for r in results:
        print(
            f"{str(r['smooth_window'])+'d':>5s} {str(r['total_return']):>14s} "
            f"{str(r['cagr']):>10s} {str(r['drawdown']):>8s} "
            f"{str(r['sharpe']):>8s} {str(r['turnover']):>10s} {str(r['orders']):>8s}"
        )
    print(f"\nSummary CSV: {out_csv}")


if __name__ == "__main__":
    main()
