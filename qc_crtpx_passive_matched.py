"""
Run CRTPX Passive from June 2021 to match Enhanced start date.
"""
import json, os, sys, time as t
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE = "https://www.quantconnect.com/api/v2"
UID = 470149
TOK = "7f0ee7b98f85c84c644ae02c788a8f0c3d1060f70e9fdcddea4a69af09575a9a"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def hdr():
    ts = str(int(t.time()))
    h = sha256(f"{TOK}:{ts}".encode()).hexdigest()
    a = b64encode(f"{UID}:{h}".encode()).decode()
    return {"Authorization": f"Basic {a}", "Timestamp": ts}

def api(ep, payload=None):
    r = post(f"{BASE}{ep}", headers=hdr(), json=payload or {}).json()
    if not r.get("success"):
        print(f"  ERR {ep}: {json.dumps(r, indent=2)[:300]}")
    return r

ALGO = r'''
from AlgorithmImports import *
from datetime import timedelta

class CrtpxPassiveMatched(QCAlgorithm):
    EQUITY_RING = ["VOO", "IVV", "SPLG"]
    CASH_RING   = ["SGOV", "BIL", "SHV"]
    TLH_LOSS_PCT = -0.03
    WASH_SALE_DAYS = 31
    CONFIRM_DAYS = 3
    SMA_PERIOD = 50

    def initialize(self):
        self.set_start_date(2021, 6, 1)
        self.set_end_date(2026, 2, 1)
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")
        self.universe_settings.resolution = Resolution.DAILY
        all_t = set(self.EQUITY_RING + self.CASH_RING + ["SPY","DIA"])
        self.symbols = {}
        for tk in all_t:
            try: self.symbols[tk] = self.add_equity(tk, Resolution.DAILY).symbol
            except: pass
        self.signal_tickers = {
            "SP500": self.add_equity("SPY", Resolution.DAILY).symbol,
            "DJT": self.add_equity("IYT", Resolution.DAILY).symbol,
            "NYA": self.add_equity("VTI", Resolution.DAILY).symbol,
            "LQD": self.add_equity("LQD", Resolution.DAILY).symbol,
        }
        self._regime = None
        self._confirm_count = 0
        self._current_equity = "VOO"
        self._current_cash = "SGOV"
        self.wash_sale_until = {}
        self.total_harvested = 0.0
        self.harvest_count = 0
        self.switch_count = 0
        self.schedule.on(self.date_rules.every_day("SPY"),
                         self.time_rules.after_market_open("SPY", 31), self._daily)
        self.set_warm_up(timedelta(days=self.SMA_PERIOD + 30))

    def _penta(self):
        g = 0
        for n, s in self.signal_tickers.items():
            h = self.history(s, self.SMA_PERIOD + 5, Resolution.DAILY)
            if h.empty or len(h) < self.SMA_PERIOD: g += 1; continue
            p = h["close"]
            if p.iloc[-1] > p.rolling(self.SMA_PERIOD).mean().iloc[-1]: g += 1
        return g

    def _daily(self):
        if self.is_warming_up: return
        desired = "ON" if self._penta() >= 3 else "OFF"
        if self._regime is None:
            self._regime = desired; self._confirm_count = self.CONFIRM_DAYS
            self._exec(desired); return
        if desired != self._regime:
            self._confirm_count += 1
            if self._confirm_count >= self.CONFIRM_DAYS:
                self._regime = desired; self._confirm_count = 0
                self.switch_count += 1; self._exec(desired)
        else: self._confirm_count = 0
        self._tlh()

    def _pick(self, ring, pref=0):
        for off in range(len(ring)):
            tk = ring[(pref + off) % len(ring)]
            if tk in self.wash_sale_until and self.time < self.wash_sale_until[tk]: continue
            return tk
        return ring[pref]

    def _exec(self, regime):
        if regime == "ON":
            for tk in self.CASH_RING:
                if tk in self.symbols and self.portfolio[self.symbols[tk]].invested:
                    self._harv(tk); self.liquidate(self.symbols[tk])
            eq = self._pick(self.EQUITY_RING,
                            self.EQUITY_RING.index(self._current_equity) if self._current_equity in self.EQUITY_RING else 0)
            self._current_equity = eq
            if eq in self.symbols: self.set_holdings(self.symbols[eq], 1.0)
        else:
            for tk in self.EQUITY_RING:
                if tk in self.symbols and self.portfolio[self.symbols[tk]].invested:
                    self._harv(tk); self.liquidate(self.symbols[tk])
            cash = self._pick(self.CASH_RING,
                              self.CASH_RING.index(self._current_cash) if self._current_cash in self.CASH_RING else 0)
            self._current_cash = cash
            if cash in self.symbols: self.set_holdings(self.symbols[cash], 1.0)

    def _harv(self, tk):
        if tk not in self.symbols: return
        h = self.portfolio[self.symbols[tk]]
        if h.invested and h.unrealized_profit < 0:
            self.total_harvested += abs(h.unrealized_profit); self.harvest_count += 1

    def _nxt(self, ring, cur):
        i = ring.index(cur) if cur in ring else 0
        return ring[(i+1) % len(ring)]

    def _tlh(self):
        for ring, attr in [(self.EQUITY_RING,"_current_equity"),(self.CASH_RING,"_current_cash")]:
            cur = getattr(self, attr)
            if cur not in self.symbols: continue
            h = self.portfolio[self.symbols[cur]]
            if not h.invested or h.average_price <= 0 or h.price <= 0: continue
            pct = (h.price / h.average_price) - 1.0
            if pct >= self.TLH_LOSS_PCT: continue
            sub = self._nxt(ring, cur)
            if sub in self.wash_sale_until and self.time < self.wash_sale_until[sub]:
                sub = self._nxt(ring, sub)
                if sub == cur: continue
                if sub in self.wash_sale_until and self.time < self.wash_sale_until[sub]: continue
            if sub not in self.symbols: continue
            self.total_harvested += abs(h.unrealized_profit); self.harvest_count += 1
            qty, px = h.quantity, h.price
            self.liquidate(self.symbols[cur])
            sp = self.securities[self.symbols[sub]].price
            if sp > 0:
                sq = int(qty * px / sp)
                if sq > 0: self.market_order(self.symbols[sub], sq)
            self.wash_sale_until[cur] = self.time + timedelta(days=self.WASH_SALE_DAYS)
            setattr(self, attr, sub)

    def on_end_of_algorithm(self):
        yrs = (self.end_date - self.start_date).days / 365.25
        self.debug(f"Switches: {self.switch_count} ({self.switch_count/yrs:.1f}/yr)")
        self.debug(f"TLH: {self.harvest_count} harvests, ${self.total_harvested:,.0f} total")
'''

def main():
    print("CRTPX Passive (matched period Jun 2021 - Feb 2026)")
    r = api("/authenticate")
    ts = int(t.time())
    name = f"CRTPX_Passive_Matched_{ts}"
    r = api("/projects/create", {"name": name, "language": "Py"})
    pid = r["projects"][0]["projectId"]
    api("/files/update", {"projectId": pid, "name": "main.py", "content": ALGO})
    r = api("/compile/create", {"projectId": pid})
    cid = r.get("compileId")
    for _ in range(30):
        t.sleep(3)
        r = api("/compile/read", {"projectId": pid, "compileId": cid})
        if r.get("state") == "BuildSuccess": break
        if r.get("state") == "BuildError": print("BUILD ERROR"); sys.exit(1)
    bn = f"Passive_Matched_{ts}"
    r = api("/backtests/create", {"projectId": pid, "compileId": cid, "backtestName": bn})
    bid = r["backtest"]["backtestId"]
    print(f"  Backtest: {bid}")
    for _ in range(120):
        t.sleep(5)
        r = api("/backtests/read", {"projectId": pid, "backtestId": bid})
        if r.get("backtest", {}).get("completed"): break
    stats = r.get("backtest", {}).get("statistics", {})
    rt = r.get("backtest", {}).get("runtimeStatistics", {})
    print("\n  RESULTS:")
    for k in ["Compounding Annual Return","Drawdown","Sharpe Ratio","Sortino Ratio",
              "Alpha","Beta","Annual Standard Deviation","Win Rate","Average Win","Average Loss","Total Fees"]:
        print(f"    {k}: {stats.get(k,'N/A')}")
    print(f"    Equity: {rt.get('Equity','N/A')}")
    with open(os.path.join(SCRIPT_DIR, "qc_crtpx_passive_matched.json"), "w") as f:
        json.dump(r, f, indent=2, default=str)
    print(f"\n  Project: https://www.quantconnect.com/project/{pid}")

if __name__ == "__main__":
    main()
