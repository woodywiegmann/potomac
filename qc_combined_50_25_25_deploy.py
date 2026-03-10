"""
QuantConnect Deploy: Combined 3-Sleeve Portfolio
=================================================
50% CRDBX (buy and hold, includes fees)
25% Defensive Equity (20 low-beta stocks, quarterly rebalance)
25% International Tactical (4-signal composite, CAOS/SGOV risk-off)

Period: Jan 2021 - Feb 2026 (constrained by CAOS inception)
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
import pandas as pd


class CombinedThreeSleeve(QCAlgorithm):
    """
    50% CRDBX | 25% Defensive Equity | 25% International Tactical
    """

    def initialize(self):
        self.set_start_date(2021, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("SPY")

        # --- Weights ---
        self.w_crdbx = 0.50
        self.w_defensive = 0.25
        self.w_intl = 0.25
        self.composite_floor = 0.25
        self.breadth_sma_period = 100
        self.breadth_threshold = 0.60

        # --- CRDBX ---
        self.crdbx = self.add_equity("CRDBX", Resolution.DAILY)
        self.crdbx.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)

        # --- Defensive basket ---
        self.low_beta = [
            "ED", "GIS", "DUK", "EXC", "HSY", "AEP", "CMS", "SO",
            "UNH", "WEC", "MDLZ", "KO", "XEL", "PNW", "JNJ",
            "PG", "T", "CI", "ATO", "EVRG"
        ]

        # --- International Tactical ETFs ---
        self.all_etfs = [
            "EWJ", "EWG", "EWQ", "EWI", "EWD", "EWL", "EWP", "EWH", "EWS",
            "EDEN", "IHDG", "RING", "SIL", "URA", "KXI", "LIT", "REMX",
            "COPX", "PICK", "GNR", "CGW", "GII", "INFL", "MOO",
            "EWT", "EWZ", "INDA", "FXI", "EWY", "EWW", "ILF", "ECH",
            "TUR", "ARGT", "VNM", "THD", "EWM", "EIDO", "KSA", "KWEB"
        ]
        self.breadth_tickers = [
            "EWJ", "EWG", "EWU", "EWC", "EWA", "EWQ", "EWL", "EWP",
            "EWI", "EWD", "EWH", "EWS", "EWN", "EDEN", "EWK", "EWO",
            "EWT", "EWZ", "INDA", "FXI", "EWY", "EWW", "EWM", "ECH",
            "TUR", "THD", "EIDO", "EPHE", "KSA", "ARGT", "VNM"
        ]
        self.trend_ticker = "ACWX"
        self.n_hold = 7

        # --- Add all securities ---
        self.symbols = {}
        all_tickers = list(set(
            self.low_beta + self.all_etfs + self.breadth_tickers +
            ["ACWX", "CAOS", "SGOV", "SPY"]
        ))
        for t in all_tickers:
            try:
                s = self.add_equity(t, Resolution.DAILY)
                s.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
                self.symbols[t] = s.symbol
            except:
                pass

        self.set_warm_up(timedelta(days=260))
        self.rebalance_scheduled = False
        self.last_quarter = -1

        self.schedule.on(
            self.date_rules.month_end(),
            self.time_rules.before_market_close("SPY", 30),
            self.flag_rebalance)
        self.settings.free_portfolio_value_percentage = 0.02

    def flag_rebalance(self):
        self.rebalance_scheduled = True

    def on_data(self, data):
        if self.is_warming_up or not self.rebalance_scheduled:
            return
        self.rebalance_scheduled = False
        self.rebalance()

    # --- Helpers ---
    def get_sma(self, symbol, period):
        h = self.history(symbol, period + 5, Resolution.DAILY)
        if h.empty or len(h) < period:
            return None
        try:
            return float(h["close"].iloc[-period:].mean())
        except:
            return None

    def get_price(self, symbol):
        h = self.history(symbol, 1, Resolution.DAILY)
        if h.empty:
            return None
        try:
            return float(h["close"].iloc[-1])
        except:
            return None

    def trailing_return(self, symbol, months):
        days = int(months * 21)
        h = self.history(symbol, days + 5, Resolution.DAILY)
        if h.empty or len(h) < days:
            return None
        try:
            cur = h["close"].iloc[-1]
            past = h["close"].iloc[-(days + 1)]
            return (cur / past) - 1.0 if past != 0 else None
        except:
            return None

    def blended_momentum(self, symbol):
        rets = [self.trailing_return(symbol, m) for m in [1, 3, 6, 12]]
        rets = [r for r in rets if r is not None]
        return (sum(rets) / len(rets)) if rets else None

    # --- 4 Signals for International Tactical ---
    def signal_sma_crossover(self):
        sym = self.symbols.get(self.trend_ticker)
        if not sym: return 0.5
        s50 = self.get_sma(sym, 50)
        s200 = self.get_sma(sym, 200)
        if s50 is None or s200 is None: return 0.5
        return 1.0 if s50 > s200 else 0.0

    def signal_breadth(self):
        above, total = 0, 0
        for t in self.breadth_tickers:
            sym = self.symbols.get(t)
            if not sym or not self.securities[sym].has_data: continue
            p = self.get_price(sym)
            s = self.get_sma(sym, self.breadth_sma_period)
            if p and s and s > 0:
                total += 1
                if p > s: above += 1
        if total == 0: return 0.5
        return 1.0 if (above / total) >= self.breadth_threshold else 0.0

    def signal_rsi5(self):
        sym = self.symbols.get(self.trend_ticker)
        if not sym: return 0.5
        h = self.history(sym, 60, Resolution.DAILY)
        if h.empty or len(h) < 10: return 0.5
        close = h["close"].astype(float)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        ag = gain.ewm(alpha=0.2, min_periods=5).mean()
        al = loss.ewm(alpha=0.2, min_periods=5).mean()
        rs = ag / al
        rsi = 100 - (100 / (1 + rs))
        v = rsi.iloc[-1]
        return float(np.clip(v / 100.0, 0, 1)) if not np.isnan(v) else 0.5

    def signal_wma_iwma(self):
        sym = self.symbols.get(self.trend_ticker)
        if not sym: return 0.5
        h = self.history(sym, 50, Resolution.DAILY)
        if h.empty or len(h) < 15: return 0.5
        mp = ((h["high"].astype(float) + h["low"].astype(float)) / 2
              if "high" in h.columns else h["close"].astype(float))
        p = 7
        w = np.arange(1, p+1, dtype=float)
        iw = np.arange(p, 0, -1, dtype=float)
        wma = mp.rolling(p).apply(lambda x: np.dot(x,w)/w.sum() if len(x)==p else np.nan, raw=True)
        iwma = mp.rolling(p).apply(lambda x: np.dot(x,iw)/iw.sum() if len(x)==p else np.nan, raw=True)
        if pd.isna(wma.iloc[-1]) or pd.isna(iwma.iloc[-1]): return 0.5
        return 1.0 if wma.iloc[-1] > iwma.iloc[-1] else 0.0

    def compute_intl_equity_weight(self):
        comp = 0.25 * (self.signal_sma_crossover() + self.signal_breadth() +
                       self.signal_rsi5() + self.signal_wma_iwma())
        return max(comp, self.composite_floor)

    # --- Main Rebalance ---
    def rebalance(self):
        target = {}

        # 1) CRDBX: 50% buy-and-hold
        target["CRDBX"] = self.w_crdbx

        # 2) Defensive: 25% across 20 low-beta stocks
        q = (self.time.month - 1) // 3
        n_def = len(self.low_beta)
        for t in self.low_beta:
            sym = self.symbols.get(t)
            if sym and self.securities[sym].has_data:
                target[t] = self.w_defensive / n_def

        # 3) International Tactical: 25% with composite overlay
        eq_w = self.compute_intl_equity_weight()
        intl_equity = self.w_intl * eq_w
        intl_cash = self.w_intl * (1 - eq_w)

        scores = {}
        for t in self.all_etfs:
            sym = self.symbols.get(t)
            if not sym or not self.securities[sym].has_data: continue
            s = self.blended_momentum(sym)
            if s is not None:
                scores[t] = s

        if scores:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:self.n_hold]
            slot = intl_equity / self.n_hold
            for t, s in ranked:
                if s > 0:
                    target[t] = target.get(t, 0) + slot
                else:
                    intl_cash += slot

        if intl_cash > 0.005:
            target["SGOV"] = target.get("SGOV", 0) + intl_cash * 0.5
            target["CAOS"] = target.get("CAOS", 0) + intl_cash * 0.5

        # Plot
        self.plot("Allocation", "CRDBX", self.w_crdbx * 100)
        self.plot("Allocation", "Defensive", self.w_defensive * 100)
        self.plot("Allocation", "IntlEquity", intl_equity * 100)
        self.plot("Allocation", "IntlCash", intl_cash * 100)
        self.plot("Composite", "IntlEqWt", eq_w)

        # Execute
        to_liq = []
        for kvp in self.portfolio:
            h = kvp.value
            if h.invested and h.symbol.value not in target:
                to_liq.append(h.symbol)
        for sym in to_liq:
            self.liquidate(sym)

        for t, w in target.items():
            sym = self.symbols.get(t) or (self.crdbx.symbol if t == "CRDBX" else None)
            if not sym: continue
            cur = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
            if abs(cur - w) > 0.015:
                self.set_holdings(sym, w)
'''

def main():
    print("=" * 60)
    print("  COMBINED 3-SLEEVE: 50% CRDBX | 25% Defensive | 25% Intl")
    print("=" * 60)

    r = call_api("/projects/create", {"name": "Combined_50_25_25_" + str(int(time.time())), "language": "Py"})
    if not r.get("success"): return
    pid = r["projects"][0]["projectId"]
    print(f"  Project: {pid}")

    r = call_api("/files/create", {"projectId": pid, "name": "main.py", "content": ALGO})
    if not r.get("success"):
        call_api("/files/update", {"projectId": pid, "name": "main.py", "content": ALGO})

    r = call_api("/compile/create", {"projectId": pid})
    if not r.get("success"): return
    cid = r.get("compileId")
    for i in range(25):
        time.sleep(3)
        r = call_api("/compile/read", {"projectId": pid, "compileId": cid})
        st = r.get("state", "")
        print(f"  Compile {i+1}: {st}")
        if st == "BuildSuccess": break
        if st == "BuildError":
            print("  ERROR:", r.get("logs"))
            return
    else:
        print("  Timed out")
        return

    r = call_api("/backtests/create", {"projectId": pid, "compileId": cid,
                 "backtestName": "Combined_" + str(int(time.time()))})
    if not r.get("success"): return
    bid = r["backtest"]["backtestId"]
    print(f"  Backtest: {bid}")

    ids = {"project_id": pid, "backtest_id": bid}
    with open(os.path.join(SCRIPT_DIR, "qc_combined_ids.json"), "w") as f:
        json.dump(ids, f, indent=2)
    print(f"  IDs saved. Backtest running on QuantConnect.")

if __name__ == "__main__":
    main()
