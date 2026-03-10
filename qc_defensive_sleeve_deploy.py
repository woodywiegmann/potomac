"""
QuantConnect Deploy: Defensive Equity Sleeve
=============================================
Equal-weight 20 low-beta large caps, quarterly rebalance.
Simulates put overlay via reduced equity exposure in high-vol months.
"""
import json, os, time, hashlib, base64, subprocess

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def call_api(endpoint, payload):
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    result = subprocess.run(
        ["curl.exe", "--max-time", "60", "-s", "-X", "POST",
         BASE_URL + endpoint,
         "-H", "Authorization: Basic " + a, "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
        capture_output=True, text=True)
    if not result.stdout.strip():
        return {"success": False}
    data = json.loads(result.stdout)
    if not data.get("success"):
        print(f"  API ERROR {endpoint}:", json.dumps(data, indent=2)[:300])
    return data

ALGO = r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np

class DefensiveEquitySleeve(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")

        self.low_beta = [
            "ED", "GIS", "DUK", "EXC", "HSY", "AEP", "CMS", "SO",
            "UNH", "WEC", "MDLZ", "KO", "XEL", "PNW", "JNJ",
            "PG", "T", "CI", "ATO", "EVRG"
        ]
        self.put_proxy_pct = 0.025 / 12.0

        self.symbols = {}
        for t in self.low_beta + ["SPY", "SHV"]:
            s = self.add_equity(t, Resolution.DAILY)
            s.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
            self.symbols[t] = s.symbol

        self.set_warm_up(timedelta(days=30))
        self.schedule.on(
            self.date_rules.month_start(),
            self.time_rules.after_market_open("SPY", 30),
            self.monthly_check)
        self.last_rebal_quarter = -1

    def monthly_check(self):
        if self.is_warming_up:
            return
        q = (self.time.month - 1) // 3
        rebalance = (q != self.last_rebal_quarter)
        if rebalance:
            self.last_rebal_quarter = q

        spy_h = self.history(self.symbols["SPY"], 252, Resolution.DAILY)
        if spy_h.empty or len(spy_h) < 60:
            return
        spy_close = spy_h["close"].astype(float)
        ret_21d = spy_close.iloc[-1] / spy_close.iloc[-22] - 1 if len(spy_close) > 22 else 0
        vol_60 = spy_close.pct_change().iloc[-60:].std() * np.sqrt(252) if len(spy_close) > 60 else 0.15

        put_payoff = 0.0
        if ret_21d < -0.05:
            excess = abs(ret_21d) - 0.05
            put_payoff = excess * 2.0
            if ret_21d < -0.10:
                put_payoff += (abs(ret_21d) - 0.10) * 1.0

        equity_scale = 1.0
        if vol_60 > 0.25:
            equity_scale = 0.85

        n = len(self.low_beta)
        per_stock = (1.0 / n) * equity_scale
        cash_reserve = self.put_proxy_pct

        if rebalance:
            target = {}
            for t in self.low_beta:
                sym = self.symbols.get(t)
                if sym and self.securities[sym].has_data:
                    target[t] = per_stock

            for kvp in self.portfolio:
                h = kvp.value
                if h.invested and h.symbol.value not in target and h.symbol.value != "SHV":
                    self.liquidate(h.symbol)

            for t, w in target.items():
                sym = self.symbols[t]
                cur = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
                if abs(cur - w) > 0.01:
                    self.set_holdings(sym, w)

        self.plot("Defensive", "PutPayoff", put_payoff)
        self.plot("Defensive", "Vol60", vol_60)
'''

def main():
    print("Deploying Defensive Equity Sleeve...")
    r = call_api("/projects/create", {"name": "DefensiveSleeve_" + str(int(time.time())), "language": "Py"})
    if not r.get("success"): return
    pid = r["projects"][0]["projectId"]
    print(f"  Project: {pid}")

    r = call_api("/files/create", {"projectId": pid, "name": "main.py", "content": ALGO})
    if not r.get("success"):
        call_api("/files/update", {"projectId": pid, "name": "main.py", "content": ALGO})

    r = call_api("/compile/create", {"projectId": pid})
    if not r.get("success"): return
    cid = r.get("compileId")
    for i in range(20):
        time.sleep(3)
        r = call_api("/compile/read", {"projectId": pid, "compileId": cid})
        if r.get("state") == "BuildSuccess":
            print("  Compiled!")
            break
        if r.get("state") == "BuildError":
            print("  BUILD ERROR:", r.get("logs"))
            return
    else:
        return

    r = call_api("/backtests/create", {"projectId": pid, "compileId": cid, "backtestName": "Defensive_" + str(int(time.time()))})
    if not r.get("success"): return
    bid = r["backtest"]["backtestId"]
    print(f"  Backtest: {bid}")
    with open(os.path.join(SCRIPT_DIR, "qc_defensive_ids.json"), "w") as f:
        json.dump({"project_id": pid, "backtest_id": bid}, f, indent=2)

if __name__ == "__main__":
    main()
