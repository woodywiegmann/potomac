"""
QuantConnect Deployment: CRTPX Enhanced (Convex Risk-Off) + TLH
=================================================================
Same Penta signal as the Passive variant, but instead of 100% SGOV
in risk-off, allocates to a paper-informed defensive mix:

  Risk-off blend:
    40% DBMF  (trend-following / managed futures)
    30% CAOS  (tail-risk convexity overlay)
    30% SGOV  (T-bill anchor)

Rationale (Baltussen, Martens & van der Linden, FAJ 2026):
  - Trend-following: highest standalone return among defensive
    strategies (4.8% at 5% vol, 222-year sample), positive in
    BOTH up and down states, best protection in extended drawdowns.
  - Immediate convexity (CAOS as DAR4020 proxy): put-like payoff,
    provides protection at ONSET of drawdown before trend-following
    can position correctly. Paper shows 50/50 trend+DAR is optimal.
  - Cash anchor: stabilizes the blend, ensures no leverage needed.

TLH swap ring:
  Equity: VOO -> IVV -> SPLG
  Cash:   SGOV -> BIL -> SHV
  DBMF:   no swap pair needed (unique exposure, held only in risk-off)
  CAOS:   no swap pair needed (same reason)

Usage:
    python qc_crtpx_enhanced_deploy.py
"""

import json
import os
import sys
import time as time_mod
from base64 import b64encode
from hashlib import sha256
from requests import post, get

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


class CrtpxEnhancedConvex(QCAlgorithm):
    """
    CRTPX Enhanced -- Convex Risk-Off
    ===================================
    Same Penta signal architecture as the Passive variant.
    Difference: risk-off allocation uses a paper-informed defensive mix
    instead of 100% T-bills.

    Signal (identical to Passive):
      Penta 4 indicators, 50-day SMA, 3/4 = ON, 3-day confirmation.

    Risk-on:  100% VOO
    Risk-off: 40% DBMF + 30% CAOS + 30% SGOV

    TLH: equity ring (VOO/IVV/SPLG), cash ring (SGOV/BIL/SHV).
    DBMF and CAOS are only held in risk-off and have no TLH pairs
    (unique exposures, short holding periods).
    """

    EQUITY_RING = ["VOO", "IVV", "SPLG"]
    CASH_RING   = ["SGOV", "BIL", "SHV"]

    RISKOFF_BLEND = {
        "DBMF": 0.40,
        "CAOS": 0.30,
    }
    RISKOFF_CASH_WT = 0.30

    TLH_LOSS_PCT   = -0.03
    WASH_SALE_DAYS = 31
    CONFIRM_DAYS   = 3
    SMA_PERIOD     = 50

    def initialize(self):
        self.set_start_date(2021, 6, 1)
        self.set_end_date(2026, 2, 1)
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")
        self.universe_settings.resolution = Resolution.DAILY

        all_tickers = set(self.EQUITY_RING + self.CASH_RING)
        all_tickers.update(self.RISKOFF_BLEND.keys())
        all_tickers.update(["SPY", "DIA"])

        self.symbols = {}
        for t in all_tickers:
            try:
                sym = self.add_equity(t, Resolution.DAILY).symbol
                self.symbols[t] = sym
            except Exception:
                self.debug(f"Could not add {t}")

        self.signal_tickers = {
            "SP500": self.add_equity("SPY", Resolution.DAILY).symbol,
            "DJT":   self.add_equity("IYT", Resolution.DAILY).symbol,
            "NYA":   self.add_equity("VTI", Resolution.DAILY).symbol,
            "LQD":   self.add_equity("LQD", Resolution.DAILY).symbol,
        }

        self._regime = None
        self._confirm_count = 0
        self._current_equity = "VOO"
        self._current_cash = "SGOV"

        self.wash_sale_until = {}
        self.total_harvested = 0.0
        self.harvest_count = 0
        self.switch_count = 0

        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 31),
            self._daily_check,
        )

        self.set_warm_up(timedelta(days=self.SMA_PERIOD + 30))

    def _penta_score(self):
        greens = 0
        for name, sym in self.signal_tickers.items():
            hist = self.history(sym, self.SMA_PERIOD + 5, Resolution.DAILY)
            if hist.empty or len(hist) < self.SMA_PERIOD:
                greens += 1
                continue
            prices = hist["close"]
            sma = prices.rolling(self.SMA_PERIOD).mean()
            if prices.iloc[-1] > sma.iloc[-1]:
                greens += 1
        return greens

    def _desired_regime(self):
        return "ON" if self._penta_score() >= 3 else "OFF"

    def _daily_check(self):
        if self.is_warming_up:
            return

        desired = self._desired_regime()

        if self._regime is None:
            self._regime = desired
            self._confirm_count = self.CONFIRM_DAYS
            self._execute_regime(desired)
            return

        if desired != self._regime:
            self._confirm_count += 1
            if self._confirm_count >= self.CONFIRM_DAYS:
                old = self._regime
                self._regime = desired
                self._confirm_count = 0
                self.switch_count += 1
                self.debug(
                    f"REGIME SWITCH #{self.switch_count}: {old} -> {desired} "
                    f"| Penta={self._penta_score()}/4"
                )
                self._execute_regime(desired)
        else:
            self._confirm_count = 0

        self._check_tlh()

    def _pick_ticker(self, ring, preferred_idx=0):
        for offset in range(len(ring)):
            t = ring[(preferred_idx + offset) % len(ring)]
            if t in self.wash_sale_until and self.time < self.wash_sale_until[t]:
                continue
            return t
        return ring[preferred_idx]

    def _execute_regime(self, regime):
        if regime == "ON":
            for t in list(self.RISKOFF_BLEND.keys()) + self.CASH_RING:
                if t in self.symbols and self.portfolio[self.symbols[t]].invested:
                    self._harvest_if_loss(t)
                    self.liquidate(self.symbols[t])

            ticker = self._pick_ticker(
                self.EQUITY_RING,
                self.EQUITY_RING.index(self._current_equity)
                if self._current_equity in self.EQUITY_RING else 0,
            )
            self._current_equity = ticker
            if ticker in self.symbols:
                self.set_holdings(self.symbols[ticker], 1.0)
            self.debug(f"  -> RISK-ON: 100% {ticker}")

        else:
            for t in self.EQUITY_RING:
                if t in self.symbols and self.portfolio[self.symbols[t]].invested:
                    self._harvest_if_loss(t)
                    self.liquidate(self.symbols[t])

            for blend_ticker, wt in self.RISKOFF_BLEND.items():
                if blend_ticker in self.symbols:
                    self.set_holdings(self.symbols[blend_ticker], wt)

            cash_ticker = self._pick_ticker(
                self.CASH_RING,
                self.CASH_RING.index(self._current_cash)
                if self._current_cash in self.CASH_RING else 0,
            )
            self._current_cash = cash_ticker
            if cash_ticker in self.symbols:
                self.set_holdings(self.symbols[cash_ticker], self.RISKOFF_CASH_WT)

            blend_str = " + ".join(
                f"{int(w*100)}% {t}" for t, w in self.RISKOFF_BLEND.items()
            )
            self.debug(
                f"  -> RISK-OFF: {blend_str} + "
                f"{int(self.RISKOFF_CASH_WT*100)}% {cash_ticker}"
            )

    def _harvest_if_loss(self, ticker):
        if ticker not in self.symbols:
            return
        h = self.portfolio[self.symbols[ticker]]
        if h.invested and h.unrealized_profit < 0:
            loss = h.unrealized_profit
            self.total_harvested += abs(loss)
            self.harvest_count += 1
            self.debug(f"  TLH HARVEST: {ticker} loss=${loss:,.2f}")

    def _next_in_ring(self, ring, current):
        idx = ring.index(current) if current in ring else 0
        return ring[(idx + 1) % len(ring)]

    def _check_tlh(self):
        for ring, current_attr in [
            (self.EQUITY_RING, "_current_equity"),
            (self.CASH_RING, "_current_cash"),
        ]:
            current = getattr(self, current_attr)
            if current not in self.symbols:
                continue
            h = self.portfolio[self.symbols[current]]
            if not h.invested:
                continue
            if h.average_price <= 0 or h.price <= 0:
                continue

            pct = (h.price / h.average_price) - 1.0
            if pct >= self.TLH_LOSS_PCT:
                continue

            substitute = self._next_in_ring(ring, current)
            if substitute in self.wash_sale_until:
                if self.time < self.wash_sale_until[substitute]:
                    substitute = self._next_in_ring(ring, substitute)
                    if substitute == current:
                        continue
                    if substitute in self.wash_sale_until:
                        if self.time < self.wash_sale_until[substitute]:
                            continue

            if substitute not in self.symbols:
                continue

            loss = h.unrealized_profit
            self.total_harvested += abs(loss)
            self.harvest_count += 1

            qty = h.quantity
            price_now = h.price
            self.liquidate(self.symbols[current])

            target_val = qty * price_now
            sub_price = self.securities[self.symbols[substitute]].price
            if sub_price > 0:
                sub_qty = int(target_val / sub_price)
                if sub_qty > 0:
                    self.market_order(self.symbols[substitute], sub_qty)

            self.wash_sale_until[current] = (
                self.time + timedelta(days=self.WASH_SALE_DAYS)
            )
            self.debug(
                f"  TLH SWAP: {current} -> {substitute} | "
                f"loss=${loss:,.2f} ({pct:.1%}) | "
                f"cumulative=${self.total_harvested:,.2f}"
            )
            setattr(self, current_attr, substitute)

    def on_end_of_algorithm(self):
        years = (self.end_date - self.start_date).days / 365.25
        self.debug("=" * 50)
        self.debug("CRTPX ENHANCED BACKTEST SUMMARY")
        self.debug("=" * 50)
        self.debug(f"Regime switches: {self.switch_count}")
        self.debug(f"Switches/year:   {self.switch_count / years:.1f}")
        self.debug(f"TLH harvests:    {self.harvest_count}")
        self.debug(f"Total harvested: ${self.total_harvested:,.2f}")
        self.debug(f"Annual harvest:  ${self.total_harvested / years:,.2f}")
        self.debug(
            f"Harvest rate:    "
            f"{self.total_harvested / 1_000_000 * 100:.2f}% of capital"
        )
        self.debug("=" * 50)
'''


def main():
    print("=" * 70)
    print("QUANTCONNECT: CRTPX Enhanced (Convex Risk-Off) + TLH")
    print("=" * 70)

    print("\n1. Authenticating...")
    r = api_post("/authenticate")
    if not r.get("success"):
        print("   Auth failed.")
        sys.exit(1)
    print("   OK")

    print("\n2. Creating project...")
    ts = int(time_mod.time())
    project_name = f"CRTPX_Enhanced_TLH_{ts}"
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
    bt_name = f"CRTPX_Enhanced_{ts}"
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
    runtime = bt.get("runtimeStatistics", {})

    print("\n" + "=" * 70)
    print("CRTPX ENHANCED BACKTEST RESULTS")
    print("=" * 70)
    print(f"  Project:  {project_name}")
    print(f"  Backtest: {bt_name}")
    print(f"  Risk-off: 40% DBMF + 30% CAOS + 30% SGOV")

    print("\n  KEY METRICS:")
    for key in [
        "Total Orders", "Total Return", "Compounding Annual Return",
        "Drawdown", "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
        "Alpha", "Beta", "Annual Standard Deviation",
        "Total Fees", "Portfolio Turnover",
        "Treynor Ratio", "Information Ratio", "Tracking Error",
        "Win Rate", "Loss Rate", "Average Win", "Average Loss",
    ]:
        val = stats.get(key, "N/A")
        print(f"    {key:.<42} {val}")

    print("\n  RUNTIME:")
    for key, val in runtime.items():
        print(f"    {key:.<42} {val}")

    out = os.path.join(SCRIPT_DIR, "qc_crtpx_enhanced_results.json")
    with open(out, "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Full results: {out}")

    url = f"https://www.quantconnect.com/project/{project_id}"
    print(f"\n  View: {url}")
    print("=" * 70)


if __name__ == "__main__":
    main()
