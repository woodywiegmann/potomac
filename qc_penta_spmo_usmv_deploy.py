"""
QuantConnect Deployment: Penta 5d-Smoothed (SPMO / 60S-30C-10XLU)
===================================================================
Penta rotation with 5-day SMA smoothing on the binary signal:

  Raw Penta ON/OFF computed daily (3+ of 4 core indicators)
  5-day SMA of that binary > 0.5 = smoothed RISK ON
  This cuts transitions from ~60/year to ~20-25/year

  Risk on:   100% SPMO
  Risk off:  60% SGOV + 20% CAOS + 20% XLU

Execution: midday (~noon ET) to approximate avg of open and close price.
Cost: 10bps slippage per side (20bps round-trip).
CAOS fallback: before CAOS data is available, its 30% goes to SGOV.

Usage:
    python qc_penta_spmo_usmv_deploy.py
"""

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


ALGO_CODE = r'''
from AlgorithmImports import *
from datetime import timedelta
from collections import deque
import numpy as np


def compute_rsi(closes, period=14):
    if closes is None or len(closes) < period + 1:
        return 50.0
    c = np.array(closes, dtype=float)
    delta = np.diff(c)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.zeros_like(c)
    avg_loss = np.zeros_like(c)
    avg_gain[1] = gain[0]
    avg_loss[1] = loss[0]
    for i in range(2, len(c)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gain[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + loss[i-1]) / period
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 10.0)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi[-1])


class TenBpsSlippage:
    """10bps slippage per side = 20bps round-trip."""
    def get_slippage_approximation(self, asset, order):
        return asset.price * 0.001


class PentaSPMOBlend(QCAlgorithm):
    """
    Penta rotation with 5d SMA smoothing: SPMO risk-on / 60S+30C+10XLU risk-off.
    The raw binary Penta ON/OFF is smoothed over 5 days to cut whipsaw.
    """

    WARMUP_DAYS = 252
    SMA50 = 50
    SMA5 = 5
    RSI_PERIOD = 14
    RSI_OB = 75
    SMOOTH_WINDOW = 5

    def initialize(self):
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        self.spmo = self.add_equity("SPMO", Resolution.DAILY).symbol
        self.sgov = self.add_equity("SGOV", Resolution.DAILY).symbol
        self.xlu  = self.add_equity("XLU",  Resolution.DAILY).symbol

        self._has_caos = False
        self.caos = None
        try:
            eq = self.add_equity("CAOS", Resolution.DAILY)
            self.caos = eq.symbol
            self._has_caos = True
        except Exception:
            pass

        self.spy_sym = self.add_equity("SPY", Resolution.DAILY).symbol
        self.iyt_sym = self.add_equity("IYT", Resolution.DAILY).symbol
        self.lqd_sym = self.add_equity("LQD", Resolution.DAILY).symbol

        try:
            self.nya_sym = self.add_index("NYA", Resolution.DAILY).symbol
        except Exception:
            self.nya_sym = self.add_equity("VTI", Resolution.DAILY).symbol

        try:
            vix = self.add_index("VIX", Resolution.DAILY)
            self.vix_sym = vix.symbol
            self._has_vix = True
        except Exception:
            self.vix_sym = None
            self._has_vix = False

        self._current_target = None
        self._switch_count = 0
        self._penta_history = deque(maxlen=self.SMOOTH_WINDOW)

        slippage = TenBpsSlippage()
        self.securities[self.spmo].set_slippage_model(slippage)
        self.securities[self.sgov].set_slippage_model(slippage)
        self.securities[self.xlu].set_slippage_model(slippage)
        if self._has_caos:
            self.securities[self.caos].set_slippage_model(slippage)

        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 180),
            self._daily_check,
        )

        self.set_warm_up(timedelta(days=self.WARMUP_DAYS))

    def _get_penta_and_regime(self):
        lookback = max(self.SMA50 + self.SMA5, self.RSI_PERIOD + 5) + 5
        spy_h = self.history(self.spy_sym, lookback, Resolution.DAILY)
        iyt_h = self.history(self.iyt_sym, 15, Resolution.DAILY)
        nya_h = self.history(self.nya_sym, 15, Resolution.DAILY)
        lqd_h = self.history(self.lqd_sym, 15, Resolution.DAILY)

        if spy_h.empty or len(spy_h) < self.SMA50 + self.SMA5:
            return None, None, 0.0
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

        penta_cnt = p1 + p2 + p3 + p4
        penta_val = 1.0 if penta_cnt >= 3 else 0.0
        trend_val = float(p1)

        rsi = compute_rsi(spy_c, self.RSI_PERIOD)
        rsi_val = 1.0 if rsi < self.RSI_OB else 0.0

        if self._has_vix and self.vix_sym is not None:
            vix_h = self.history(self.vix_sym, 10, Resolution.DAILY)
            if not vix_h.empty and len(vix_h) >= 5:
                vix_c = vix_h["close"].values.astype(float)
                vix_val = 1.0 if vix_c[-1] < np.mean(vix_c[-5:]) else 0.0
                vix_level = float(vix_c[-1])
            else:
                vix_val = 1.0
                vix_level = 20.0
        else:
            vix_val = 1.0
            vix_level = 20.0

        raw_on = 1.0 if penta_cnt >= 3 else 0.0
        self._penta_history.append(raw_on)

        if len(self._penta_history) < self.SMOOTH_WINDOW:
            return None, None, 0.0

        smoothed = sum(self._penta_history) / len(self._penta_history)
        penta_on = smoothed > 0.5
        return ("RISK_ON" if penta_on else "RISK_OFF"), ("SPMO" if penta_on else "DEFENSIVE"), smoothed

    def _daily_check(self):
        if self.is_warming_up:
            return

        regime, target, comp = self._get_penta_and_regime()
        if target is None:
            return
        if self._current_target == target:
            return

        old = self._current_target or "NONE"
        self._current_target = target
        self._switch_count += 1
        self.debug(
            f"SWITCH #{self._switch_count}: {old} -> {target} "
            f"| regime={regime} comp={comp:.2f}"
        )

        self.liquidate()
        if target == "SPMO":
            self.set_holdings(self.spmo, 1.0)
        elif target == "DEFENSIVE":
            caos_ok = (self._has_caos and self.caos is not None
                       and self.securities[self.caos].has_data
                       and self.securities[self.caos].price > 0)
            if caos_ok:
                self.set_holdings(self.sgov, 0.60)
                self.set_holdings(self.caos, 0.20)
                self.set_holdings(self.xlu,  0.20)
            else:
                self.set_holdings(self.sgov, 0.80)
                self.set_holdings(self.xlu,  0.20)
                self.debug("  CAOS unavailable -- 90% SGOV + 10% XLU fallback")

    def on_end_of_algorithm(self):
        years = (self.end_date - self.start_date).days / 365.25
        self.debug("=" * 50)
        self.debug("PENTA 5d-SMOOTH: SPMO / 60S-30C-10XLU SUMMARY")
        self.debug("=" * 50)
        self.debug(f"Signal: 5d SMA of binary Penta > 0.5")
        self.debug(f"Risk-on:  100% SPMO")
        self.debug(f"Risk-off: 60% SGOV + 20% CAOS + 20% XLU")
        self.debug(f"Fallback: 80% SGOV + 20% XLU (pre-CAOS)")
        self.debug(f"Execution: midday (~noon ET)")
        self.debug(f"Slippage: 10bps/side (20bps RT)")
        self.debug(f"Regime switches: {self._switch_count}")
        self.debug(f"Switches/year:   {self._switch_count / max(years, 0.1):.1f}")
        self.debug("=" * 50)
'''


def main():
    print("=" * 70)
    print("QUANTCONNECT: Penta 5d-Smooth (SPMO / 60S-30C-10XLU)")
    print("=" * 70)

    print("\n1. Authenticating...")
    r = api_post("/authenticate")
    if not r.get("success"):
        print("   Auth failed.")
        sys.exit(1)
    print("   OK")

    print("\n2. Creating project...")
    ts = int(time_mod.time())
    project_name = f"Penta5dSmooth_SPMO_60S30C10XLU_{ts}"
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

    for _ in range(30):
        time_mod.sleep(3)
        r = api_post("/compile/read", {
            "projectId": project_id,
            "compileId": compile_id,
        })
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
    bt_name = f"Penta5dSmooth_SPMO_60S30C10XLU_{ts}"
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
    for _ in range(180):
        time_mod.sleep(5)
        r = api_post("/backtests/read", {
            "projectId": project_id,
            "backtestId": backtest_id,
        })
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

    print("\n" + "=" * 70)
    print("PENTA 5d-SMOOTH SPMO / 60S-30C-10XLU RESULTS")
    print("=" * 70)
    print(f"  Project:  {project_name}")
    print(f"  Backtest: {bt_name}")
    print("  Signal:     5d SMA of binary Penta > 0.5 (smoothed)")
    print("  Risk on:    100% SPMO")
    print("  Risk off:   60% SGOV + 20% CAOS + 20% XLU")
    print("  Fallback:   80% SGOV + 20% XLU (pre-CAOS data)")
    print("  Execution:  Midday (~noon ET, open+close avg proxy)")
    print("  Costs:      10bps slippage/side (20bps RT)")

    print("\n  KEY METRICS:")
    for key in [
        "Total Orders", "Total Return", "Compounding Annual Return",
        "Drawdown", "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
        "Alpha", "Beta", "Annual Standard Deviation",
        "Total Fees", "Portfolio Turnover",
    ]:
        val = stats.get(key, "N/A")
        print(f"    {key:.<42} {val}")

    out = os.path.join(SCRIPT_DIR, "qc_penta_5dsmooth_spmo_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results: {out}")

    url = f"https://www.quantconnect.com/project/{project_id}"
    print(f"\n  View: {url}")
    print("=" * 70)


if __name__ == "__main__":
    main()
