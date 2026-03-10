"""
QuantConnect Deployment: Tactical Hard Asset ETF
=================================================
50% COM static + 50% tactical (14-ETF tiered momentum or SHY when COMOD off).
COMOD: DBC > 200d SMA, TLT > 12m avg (real rates proxy), UUP < 200d SMA. 3/3 = risk on.
Monthly rebalance: first trading day of month, before market close.
Slippage: 10 bps per side. Benchmark: PDBC.

Usage:
  python qc_hard_asset_tactical_deploy.py
"""

import json
import os
import sys
import time as time_mod
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = int(os.environ.get("QC_USER_ID", "470149"))
API_TOKEN = os.environ.get("QC_API_TOKEN", "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 14 tactical ETFs by tier (max 2 per tier in selection)
TACTICAL_TIERS = {
    1: ["TILL", "PDBA", "MOO", "LAND"],
    2: ["XLE", "XOP", "OIH"],
    3: ["COPX", "LIT", "PICK", "REMX"],
    4: ["GDX", "SLV", "SIL"],
}
ALL_TACTICAL = []
TICKER_TO_TIER = {}
for tier, tickers in TACTICAL_TIERS.items():
    ALL_TACTICAL.extend(tickers)
    for t in tickers:
        TICKER_TO_TIER[t] = tier

LOOKBACK_9M = 189
SMA_DAYS = 200
TLT_12M_DAYS = 252


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

# 14 tactical by tier; max 2 per tier
TACTICAL_TIERS = {1: ["TILL", "PDBA", "MOO", "LAND"], 2: ["XLE", "XOP", "OIH"],
                  3: ["COPX", "LIT", "PICK", "REMX"], 4: ["GDX", "SLV", "SIL"]}
ALL_TACTICAL = []
TICKER_TO_TIER = {}
for tier, tickers in TACTICAL_TIERS.items():
    ALL_TACTICAL.extend(tickers)
    for t in tickers:
        TICKER_TO_TIER[t] = tier

LOOKBACK_9M = 189
SMA_DAYS = 200
TLT_12M_DAYS = 252


class TenBpsSlippage:
    def get_slippage_approximation(self, asset, order):
        return asset.price * 0.001


class HardAssetTactical(QCAlgorithm):
    """50% COM + 50% tactical (14-ETF tiered momentum) or 50% SHY. COMOD 3/3 = risk on."""

    def initialize(self):
        self.set_start_date(2017, 1, 1)
        self.set_end_date(datetime.now().year, datetime.now().month, datetime.now().day)
        self.set_cash(100_000)
        self.set_benchmark("PDBC")

        self.com_sym = self.add_equity("COM", Resolution.DAILY).symbol
        self.shy_sym = self.add_equity("SHY", Resolution.DAILY).symbol
        self.dbc_sym = self.add_equity("DBC", Resolution.DAILY).symbol
        self.uup_sym = self.add_equity("UUP", Resolution.DAILY).symbol
        self.tlt_sym = self.add_equity("TLT", Resolution.DAILY).symbol

        self.tactical_symbols = {}
        for t in ALL_TACTICAL:
            try:
                self.tactical_symbols[t] = self.add_equity(t, Resolution.DAILY).symbol
            except Exception:
                pass

        slippage = TenBpsSlippage()
        for sym in [self.com_sym, self.shy_sym] + list(self.tactical_symbols.values()):
            if sym in self.securities:
                self.securities[sym].set_slippage_model(slippage)
        for s in [self.dbc_sym, self.uup_sym, self.tlt_sym]:
            if s in self.securities:
                self.securities[s].set_slippage_model(slippage)

        self._prev_risk_on = None
        self.set_warm_up(timedelta(days=400))

        self.schedule.on(
            self.date_rules.month_start("SPY"),
            self.time_rules.before_market_close("SPY", 30),
            self.rebalance,
        )

    def get_sma(self, symbol, period):
        if symbol is None: return None
        h = self.history(symbol, period + 5, Resolution.DAILY)
        if h.empty or len(h) < period: return None
        try:
            return float(h["close"].iloc[-period:].mean())
        except (IndexError, KeyError): return None

    def get_close(self, symbol):
        if symbol is None: return None
        h = self.history(symbol, 1, Resolution.DAILY)
        if h.empty: return None
        try: return float(h["close"].iloc[-1])
        except (IndexError, KeyError): return None

    def get_avg_12m(self, symbol):
        if symbol is None: return None
        h = self.history(symbol, TLT_12M_DAYS + 5, Resolution.DAILY)
        if h.empty or len(h) < 20: return None
        try:
            n = min(TLT_12M_DAYS, len(h))
            return float(h["close"].iloc[-n:].mean())
        except (IndexError, KeyError): return None

    def comod_risk_on(self):
        # 1) DBC above 200d SMA
        dbc_close = self.get_close(self.dbc_sym)
        dbc_sma = self.get_sma(self.dbc_sym, SMA_DAYS)
        c_bull = (dbc_close is not None and dbc_sma is not None and dbc_sma > 0 and dbc_close > dbc_sma)
        if dbc_close is None or dbc_sma is None:
            c_bull = None
        # 2) TLT above 12m avg (real rates proxy: falling long rates = bullish)
        tlt_close = self.get_close(self.tlt_sym)
        tlt_avg = self.get_avg_12m(self.tlt_sym)
        r_bull = (tlt_close is not None and tlt_avg is not None and tlt_close > tlt_avg)
        if tlt_close is None or tlt_avg is None:
            r_bull = None
        # 3) UUP below 200d SMA (weak dollar = bullish)
        uup_close = self.get_close(self.uup_sym)
        uup_sma = self.get_sma(self.uup_sym, SMA_DAYS)
        d_bull = (uup_close is not None and uup_sma is not None and uup_sma > 0 and uup_close < uup_sma)
        if uup_close is None or uup_sma is None:
            d_bull = None
        if c_bull is None or r_bull is None or d_bull is None:
            return self._prev_risk_on if self._prev_risk_on is not None else False
        out = c_bull and r_bull and d_bull
        self._prev_risk_on = out
        return out

    def total_return_9m(self, symbol):
        if symbol is None or symbol not in self.securities: return None
        h = self.history(symbol, LOOKBACK_9M + 5, Resolution.DAILY)
        if h.empty or len(h) <= LOOKBACK_9M: return None
        try:
            start_p = float(h["close"].iloc[-(LOOKBACK_9M + 1)])
            end_p = float(h["close"].iloc[-1])
            if start_p <= 0: return None
            return (end_p / start_p) - 1.0
        except (IndexError, KeyError): return None

    def select_tactical(self):
        candidates = []
        for t, sym in self.tactical_symbols.items():
            tr = self.total_return_9m(sym)
            if tr is not None and tr > 0:
                candidates.append((t, tr))
        if len(candidates) < 2: return []
        candidates.sort(key=lambda x: -x[1])
        selected = []
        tier_count = {1: 0, 2: 0, 3: 0, 4: 0}
        for t, _ in candidates:
            tier = TICKER_TO_TIER.get(t)
            if tier is None or tier_count[tier] >= 2: continue
            selected.append(t)
            tier_count[tier] += 1
            if len(selected) >= 4: break
        return selected

    def rebalance(self):
        if self.is_warming_up:
            return
        risk_on = self.comod_risk_on()
        if not risk_on:
            self.set_holdings(self.com_sym, 0.5)
            self.set_holdings(self.shy_sym, 0.5)
            for t, sym in self.tactical_symbols.items():
                self.set_holdings(sym, 0.0)
            return
        selected = self.select_tactical()
        if len(selected) < 2:
            self.set_holdings(self.com_sym, 0.5)
            self.set_holdings(self.shy_sym, 0.5)
            for t, sym in self.tactical_symbols.items():
                self.set_holdings(sym, 0.0)
            return
        w_tactical = 0.5 / len(selected)
        self.set_holdings(self.com_sym, 0.5)
        self.set_holdings(self.shy_sym, 0.0)
        for t, sym in self.tactical_symbols.items():
            if t in selected:
                self.set_holdings(sym, w_tactical)
            else:
                self.set_holdings(sym, 0.0)
'''


def main():
    print("=" * 70)
    print("QUANTCONNECT: Tactical Hard Asset (50% COM + 50% tactical/SHY)")
    print("=" * 70)

    print("\n1. Authenticating...")
    r = api_post("/authenticate")
    if not r.get("success"):
        print("   Auth failed.")
        sys.exit(1)
    print("   OK")

    print("\n2. Creating project...")
    ts = int(time_mod.time())
    project_name = f"HardAssetTactical_{ts}"
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
    bt_name = f"HardAssetTactical_{ts}"
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
    print("TACTICAL HARD ASSET RESULTS")
    print("=" * 70)
    print(f"  Project:  {project_name}")
    print(f"  Backtest: {bt_name}")
    print("  50% COM + 50% tactical (14 ETF tiered momentum) or 50% SHY")
    print("  COMOD: DBC>200d SMA, TLT>12m avg, UUP<200d SMA. 3/3 = risk on.")
    print("  Rebalance: first trading day of month. Slippage: 10 bps/side.")

    print("\n  KEY METRICS:")
    for key in [
        "Total Orders", "Total Return", "Compounding Annual Return",
        "Drawdown", "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
        "Alpha", "Beta", "Annual Standard Deviation",
        "Total Fees", "Portfolio Turnover",
    ]:
        val = stats.get(key, "N/A")
        print(f"    {key:.<42} {val}")

    out = os.path.join(SCRIPT_DIR, "qc_hard_asset_tactical_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results: {out}")

    url = f"https://www.quantconnect.com/project/{project_id}"
    print(f"\n  View: {url}")
    print("=" * 70)


if __name__ == "__main__":
    main()
