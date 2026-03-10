"""
QuantConnect Deploy: Simplified Gold Digger
=============================================
K-Ratio trend filter + SMA crossover on GLD.
Simplified version of the full CGD system for QC validation.
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

class GoldDiggerSimplified(QCAlgorithm):
    """
    Simplified Composite Gold Digger for QC validation.
    Three components (matching CGD parameters from AmiBroker):
      1. K-Ratio: Dual-band Bollinger trend filter (LT 35/1.1, ST 8/1.2)
      2. GolDollar: Gold SMA(9) vs USD Index SMA(8)
      3. Trailing stop: 40-bar
    Long GLD when signals align, otherwise SGOV.
    """

    def initialize(self):
        self.set_start_date(2005, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("GLD")

        self.gld = self.add_equity("GLD", Resolution.DAILY)
        self.gld.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
        self.uup = self.add_equity("UUP", Resolution.DAILY)
        self.uup.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
        self.cash_etf = self.add_equity("SHV", Resolution.DAILY)
        self.cash_etf.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)

        self.kr_lt_period = 35
        self.kr_lt_std = 1.1
        self.kr_st_period = 8
        self.kr_st_std = 1.2
        self.kr_buy_thresh = 0.1
        self.kr_sell_thresh = 0.25

        self.gd_gold_sma = 9
        self.gd_index_sma = 8

        self.triad_lookback = 90
        self.triad_entry = 0.055
        self.triad_exit = 0.045

        self.trailing_stop_bars = 40

        self.in_trade = False
        self.entry_price = 0
        self.highest_since_entry = 0
        self.bars_in_trade = 0

        self.set_warm_up(timedelta(days=100))
        self.schedule.on(
            self.date_rules.every_day("GLD"),
            self.time_rules.before_market_close("GLD", 15),
            self.check_signals)

    def k_ratio_signal(self):
        h = self.history(self.gld.symbol, self.kr_lt_period + 10, Resolution.DAILY)
        if h.empty or len(h) < self.kr_lt_period:
            return 0
        close = h["close"].astype(float)

        lt_sma = close.iloc[-self.kr_lt_period:].mean()
        lt_std = close.iloc[-self.kr_lt_period:].std()
        lt_upper = lt_sma + self.kr_lt_std * lt_std
        lt_lower = lt_sma - self.kr_lt_std * lt_std

        st_sma = close.iloc[-self.kr_st_period:].mean()
        st_std = close.iloc[-self.kr_st_period:].std()
        st_upper = st_sma + self.kr_st_std * st_std
        st_lower = st_sma - self.kr_st_std * st_std

        price = close.iloc[-1]

        lt_pos = (price - lt_lower) / (lt_upper - lt_lower) if (lt_upper - lt_lower) > 0 else 0.5
        st_pos = (price - st_lower) / (st_upper - st_lower) if (st_upper - st_lower) > 0 else 0.5
        k = (lt_pos + st_pos) / 2.0

        if k < self.kr_buy_thresh:
            return -1
        elif k > (1 - self.kr_sell_thresh):
            return 1
        else:
            return 0

    def goldollar_signal(self):
        gh = self.history(self.gld.symbol, self.gd_gold_sma + 5, Resolution.DAILY)
        uh = self.history(self.uup.symbol, self.gd_index_sma + 5, Resolution.DAILY)
        if gh.empty or uh.empty or len(gh) < self.gd_gold_sma or len(uh) < self.gd_index_sma:
            return 0
        gold_close = gh["close"].astype(float)
        usd_close = uh["close"].astype(float)

        gold_sma = gold_close.iloc[-self.gd_gold_sma:].mean()
        usd_sma = usd_close.iloc[-self.gd_index_sma:].mean()

        gold_above = gold_close.iloc[-1] > gold_sma
        usd_below = usd_close.iloc[-1] < usd_sma

        return 1 if (gold_above and usd_below) else 0

    def triad_signal(self):
        h = self.history(self.gld.symbol, self.triad_lookback + 5, Resolution.DAILY)
        if h.empty or len(h) < self.triad_lookback:
            return 0
        close = h["close"].astype(float)
        momentum = close.iloc[-1] / close.iloc[-self.triad_lookback] - 1
        if momentum > self.triad_entry:
            return 1
        elif momentum < self.triad_exit:
            return -1
        return 0

    def check_signals(self):
        if self.is_warming_up:
            return

        kr = self.k_ratio_signal()
        gd = self.goldollar_signal()
        tr = self.triad_signal()

        should_be_long = False
        if kr == -1:
            should_be_long = False
        elif kr == 1:
            should_be_long = True
        else:
            should_be_long = (gd == 1 or tr == 1)

        if self.in_trade:
            self.bars_in_trade += 1
            price = self.securities[self.gld.symbol].price
            if price > self.highest_since_entry:
                self.highest_since_entry = price

            if self.bars_in_trade >= self.trailing_stop_bars:
                drawdown = (price / self.highest_since_entry - 1) if self.highest_since_entry > 0 else 0
                if drawdown < -0.08:
                    should_be_long = False

        if should_be_long and not self.in_trade:
            self.set_holdings(self.gld.symbol, 0.95)
            if self.portfolio[self.cash_etf.symbol].invested:
                self.liquidate(self.cash_etf.symbol)
            self.in_trade = True
            self.entry_price = self.securities[self.gld.symbol].price
            self.highest_since_entry = self.entry_price
            self.bars_in_trade = 0
        elif not should_be_long and self.in_trade:
            self.liquidate(self.gld.symbol)
            self.set_holdings(self.cash_etf.symbol, 0.95)
            self.in_trade = False

        self.plot("CGD", "KRatio", kr)
        self.plot("CGD", "GolDollar", gd)
        self.plot("CGD", "Triad", tr)
        self.plot("CGD", "InTrade", 1 if self.in_trade else 0)
'''

def main():
    print("Deploying Gold Digger Simplified...")
    r = call_api("/projects/create", {"name": "GoldDigger_" + str(int(time.time())), "language": "Py"})
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

    r = call_api("/backtests/create", {"projectId": pid, "compileId": cid, "backtestName": "CGD_" + str(int(time.time()))})
    if not r.get("success"): return
    bid = r["backtest"]["backtestId"]
    print(f"  Backtest: {bid}")
    with open(os.path.join(SCRIPT_DIR, "qc_golddigger_ids.json"), "w") as f:
        json.dump({"project_id": pid, "backtest_id": bid}, f, indent=2)

if __name__ == "__main__":
    main()
