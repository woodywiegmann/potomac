"""
QuantConnect Deployment: 40-ETF Dual Momentum + COMPOSITE Risk-On/Risk-Off
=========================================================================
Single backtest using the composite overlay (breadth, ACWX trend/momentum,
VIX, BNDX, relative strength, RSI(5), WMA/IWMA, Turtle Donchian) with
graduated equity weight to target 60-90% time invested and maximize Calmar.

Usage:
  python qc_intl_composite_deploy.py
"""

import json
import os
import time as tm
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

COMPOSITE_FLOOR = 0.25  # min equity weight (graduated)


def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}


def api(endpoint, payload=None):
    r = post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload or {})
    data = r.json()
    if not data.get("success"):
        print(f"  API ERROR on {endpoint}: {json.dumps(data, indent=2)}")
    return data


def build_composite_algo_code(floor=0.25):
    """Generate LEAN algorithm code for composite risk-on/risk-off."""
    return r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np
import pandas as pd


class Intl40ETFCompositeRisk(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("EFA")

        self.composite_floor = ''' + str(floor) + r'''

        self.all_etfs = {
            "EWJ": "Japan", "EWG": "Germany", "EWQ": "France",
            "EWI": "Italy", "EWD": "Sweden", "EWL": "Switzerland",
            "EWP": "Spain", "EWH": "Hong Kong", "EWS": "Singapore",
            "EDEN": "Denmark",
            "IHDG": "Intl Hedged Qual Div Growth",
            "RING": "Global Gold Miners", "SIL": "Silver Miners",
            "URA": "Uranium", "KXI": "Global Consumer Staples",
            "LIT": "Lithium & Battery Tech", "REMX": "Rare Earth Metals",
            "COPX": "Copper Miners", "PICK": "Global Metals Mining",
            "GNR": "S&P Global NatRes", "CGW": "Global Water",
            "GII": "Global Infrastructure", "INFL": "Inflation Beneficiaries",
            "MOO": "Agribusiness",
            "EWT": "Taiwan", "EWZ": "Brazil", "INDA": "India",
            "FXI": "China", "EWY": "South Korea", "EWW": "Mexico",
            "ILF": "LatAm 40", "ECH": "Chile", "TUR": "Turkey",
            "ARGT": "Argentina", "VNM": "Vietnam", "THD": "Thailand",
            "EWM": "Malaysia", "EIDO": "Indonesia",
            "KSA": "Saudi Arabia", "KWEB": "China Internet",
        }
        self.breadth_tickers = [
            "EWJ", "EWG", "EWU", "EWC", "EWA", "EWQ", "EWL", "EWP",
            "EWI", "EWD", "EWH", "EWS", "EWN", "EDEN", "EWK", "EWO",
            "EWT", "EWZ", "INDA", "FXI", "EWY", "EWW", "EWM", "ECH",
            "TUR", "THD", "EIDO", "EPHE", "KSA", "ARGT", "VNM",
        ]
        self.trend_ticker = "ACWX"
        self.cash_ticker = "BIL"
        self.n_hold = 7
        self.lookback_months = [1, 3, 6, 12]
        self.sma_period = 200
        self.weights = {
            "breadth": 0.18, "acwx_trend": 0.15, "acwx_mom": 0.12,
            "vol_ok": 0.12, "credit_ok": 0.08, "rel_strength": 0.05,
            "rsi5": 0.12, "wma_iwma": 0.10, "turtle": 0.08,
        }

        self.symbols = {}
        for t in list(self.all_etfs.keys()) + [self.cash_ticker, self.trend_ticker, "SPY", "BNDX"]:
            sym = self.add_equity(t, Resolution.DAILY)
            sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
            self.symbols[t] = sym.symbol
        # VIX: try AddIndex (backtest); if unavailable, vol_ok defaults to 0.5
        self.vix = None
        try:
            self.vix = self.add_index("VIX", Resolution.DAILY)
        except Exception:
            pass
        self.breadth_symbols = {}
        for t in self.breadth_tickers:
            if t not in self.symbols:
                sym = self.add_equity(t, Resolution.DAILY)
                sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
                self.breadth_symbols[t] = sym.symbol
            else:
                self.breadth_symbols[t] = self.symbols[t]
        for t in self.breadth_tickers:
            if t not in self.symbols and t not in self.breadth_symbols:
                sym = self.add_equity(t, Resolution.DAILY)
                sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
                self.breadth_symbols[t] = sym.symbol

        self.set_warm_up(timedelta(days=260))
        self.rebalance_scheduled = False
        self.schedule.on(
            self.date_rules.month_end(),
            self.time_rules.before_market_close("EFA", 30),
            self.flag_rebalance
        )
        self.settings.free_portfolio_value_percentage = 0.02
        self.turtle_in_s1 = False
        self.turtle_in_s2 = False

    def flag_rebalance(self):
        self.rebalance_scheduled = True

    def on_data(self, data):
        if self.is_warming_up or not self.rebalance_scheduled:
            return
        self.rebalance_scheduled = False
        self.rebalance(data)

    def get_sma(self, symbol, period):
        h = self.history(symbol, period + 5, Resolution.DAILY)
        if h.empty or len(h) < period:
            return None
        try:
            return float(h["close"].iloc[-period:].mean())
        except (IndexError, KeyError):
            return None

    def get_price(self, symbol):
        h = self.history(symbol, 1, Resolution.DAILY)
        if h.empty:
            return None
        try:
            return float(h["close"].iloc[-1])
        except (IndexError, KeyError):
            return None

    def trailing_return(self, symbol, months):
        days = int(months * 21)
        h = self.history(symbol, days + 5, Resolution.DAILY)
        if h.empty or len(h) < days:
            return None
        try:
            cur = h["close"].iloc[-1]
            past = h["close"].iloc[-(days + 1)]
            if past == 0:
                return None
            return (cur / past) - 1.0
        except (IndexError, KeyError):
            return None

    def blended_momentum(self, symbol):
        rets = []
        for m in self.lookback_months:
            r = self.trailing_return(symbol, m)
            if r is not None:
                rets.append(r)
        return (sum(rets) / len(rets)) if rets else None

    def breadth_pct(self):
        above, total = 0, 0
        for t in self.breadth_tickers:
            sym = self.breadth_symbols.get(t) or self.symbols.get(t)
            if sym is None:
                continue
            if not self.securities[sym].has_data:
                continue
            price = self.get_price(sym)
            sma = self.get_sma(sym, self.sma_period)
            if price is not None and sma is not None and sma > 0:
                total += 1
                if price > sma:
                    above += 1
        return (above / total) if total > 0 else 0.5

    def acwx_trend_signal(self):
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return 0.5
        price = self.get_price(sym)
        sma = self.get_sma(sym, self.sma_period)
        if price is None or sma is None or sma == 0:
            return 0.5
        return 1.0 if price > sma else 0.0

    def acwx_mom_norm(self):
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return 0.5
        mom = self.blended_momentum(sym)
        if mom is None:
            return 0.5
        x = np.clip(mom, -0.2, 0.2)
        return float((x + 0.2) / 0.4)

    def vol_ok_signal(self):
        if self.vix is None:
            return 0.5
        try:
            h = self.history(self.vix.symbol, 1, Resolution.DAILY)
            if h.empty:
                return 0.5
            v = float(h["close"].iloc[-1])
            return 1.0 - min(1.0, v / 30.0)
        except Exception:
            return 0.5

    def credit_ok_signal(self):
        sym = self.symbols.get("BNDX")
        if sym is None:
            return 0.5
        price = self.get_price(sym)
        sma = self.get_sma(sym, self.sma_period)
        if price is None or sma is None or sma == 0:
            return 0.5
        return 1.0 if price > sma else 0.0

    def rel_strength_signal(self):
        acwx_sym = self.symbols.get(self.trend_ticker)
        spy_sym = self.symbols.get("SPY")
        if acwx_sym is None or spy_sym is None:
            return 0.5
        r_acwx = self.trailing_return(acwx_sym, 12)
        r_spy = self.trailing_return(spy_sym, 12)
        if r_acwx is None or r_spy is None:
            return 0.5
        diff = np.clip(r_acwx - r_spy, -0.2, 0.2)
        return float((diff + 0.2) / 0.4)

    def rsi5_signal(self):
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return 0.5
        h = self.history(sym, 60, Resolution.DAILY)
        if h.empty or len(h) < 10:
            return 0.5
        close = h["close"].astype(float)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        period = 5
        avg_gain = gain.ewm(alpha=1.0/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1.0/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        if np.isnan(val):
            return 0.5
        return float(np.clip(val / 100.0, 0.0, 1.0))

    def wma_iwma_signal(self):
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return 0.5
        h = self.history(sym, 50, Resolution.DAILY)
        if h.empty or len(h) < 15:
            return 0.5
        if "high" in h.columns and "low" in h.columns:
            mean_p = (h["high"].astype(float) + h["low"].astype(float)) / 2
        else:
            mean_p = h["close"].astype(float)
        period = 7
        w = np.arange(1, period + 1, dtype=float)
        wma = mean_p.rolling(period).apply(lambda x: np.dot(x, w) / w.sum() if len(x) == period else np.nan, raw=True)
        iw = np.arange(period, 0, -1, dtype=float)
        iwma = mean_p.rolling(period).apply(lambda x: np.dot(x, iw) / iw.sum() if len(x) == period else np.nan, raw=True)
        if pd.isna(wma.iloc[-1]) or pd.isna(iwma.iloc[-1]):
            return 0.5
        return 1.0 if wma.iloc[-1] > iwma.iloc[-1] else 0.0

    def turtle_signal(self):
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return 0.5
        h = self.history(sym, 60, Resolution.DAILY)
        if h.empty or len(h) < 60:
            return 0.5
        close = h["close"].astype(float)
        r20h = close.rolling(20).max()
        r10l = close.rolling(10).min()
        r55h = close.rolling(55).max()
        r20l = close.rolling(20).min()
        in_s1, in_s2 = self.turtle_in_s1, self.turtle_in_s2
        c = close.iloc[-1]
        a20h = r20h.iloc[-1]
        a10l = r10l.iloc[-1]
        a55h = r55h.iloc[-1]
        a20l = r20l.iloc[-1]
        if np.isnan(c) or np.isnan(a20h) or np.isnan(a10l) or np.isnan(a55h) or np.isnan(a20l):
            return 1.0 if (in_s1 or in_s2) else 0.0
        if in_s1 and c < a10l:
            in_s1 = False
        if in_s2 and c < a20l:
            in_s2 = False
        if c > a20h:
            in_s1 = True
        if c > a55h:
            in_s2 = True
        self.turtle_in_s1, self.turtle_in_s2 = in_s1, in_s2
        return 1.0 if (in_s1 or in_s2) else 0.0

    def compute_composite(self):
        sig = {
            "breadth": self.breadth_pct(),
            "acwx_trend": self.acwx_trend_signal(),
            "acwx_mom": self.acwx_mom_norm(),
            "vol_ok": self.vol_ok_signal(),
            "credit_ok": self.credit_ok_signal(),
            "rel_strength": self.rel_strength_signal(),
            "rsi5": self.rsi5_signal(),
            "wma_iwma": self.wma_iwma_signal(),
            "turtle": self.turtle_signal(),
        }
        total = 0.0
        wsum = 0.0
        for k, w in self.weights.items():
            if k in sig and w > 0:
                total += w * sig[k]
                wsum += w
        comp = (total / wsum) if wsum > 0 else 0.5
        comp = max(0.0, min(1.0, comp))
        return comp, sig

    def go_to_cash(self, equity_weight):
        for kvp in self.portfolio:
            holding = kvp.value
            if holding.invested:
                t = holding.symbol.value
                if t != self.cash_ticker:
                    self.liquidate(holding.symbol)
        bil_sym = self.symbols[self.cash_ticker]
        self.set_holdings(bil_sym, 0.98)

    def rebalance(self, data):
        comp, sig = self.compute_composite()
        eq_w = max(comp, self.composite_floor)
        eq_w = max(0.0, min(1.0, eq_w))

        self.plot("Composite", "Score", comp)
        self.plot("Composite", "EquityWeight", eq_w)

        scores = {}
        for t in self.all_etfs:
            sym = self.symbols.get(t)
            if sym is None:
                continue
            if not self.securities[sym].has_data:
                continue
            s = self.blended_momentum(sym)
            if s is not None:
                scores[t] = s

        if len(scores) == 0:
            self.go_to_cash(eq_w)
            return

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = ranked[:self.n_hold]
        slot_w = 1.0 / self.n_hold
        target = {}
        for t, s in top_n:
            if s > 0:
                target[t] = eq_w * slot_w
        cash_w = 1.0 - sum(target.values())
        if cash_w > 0.001:
            target[self.cash_ticker] = target.get(self.cash_ticker, 0) + cash_w

        for kvp in self.portfolio:
            holding = kvp.value
            if holding.invested:
                t = holding.symbol.value
                if t not in target and t != self.cash_ticker:
                    self.liquidate(holding.symbol)

        for t, w in target.items():
            if t == self.cash_ticker:
                continue
            sym = self.symbols[t]
            cur = self.portfolio[sym].holdings_value / self.portfolio.total_portfolio_value
            if abs(cur - w) > 0.02:
                self.set_holdings(sym, w)

        bil_sym = self.symbols[self.cash_ticker]
        bil_target = target.get(self.cash_ticker, 0)
        if bil_target > 0.02:
            self.set_holdings(bil_sym, bil_target)
        elif self.portfolio[bil_sym].invested:
            self.liquidate(bil_sym)
'''


def run_backtest(floor=0.25):
    algo_code = build_composite_algo_code(floor)
    print("\n" + "=" * 70)
    print("  INTL 40-ETF COMPOSITE RISK-ON/RISK-OFF")
    print("  Signals: breadth, ACWX trend/mom, VIX, BNDX, rel strength, RSI(5), WMA/IWMA, Turtle")
    print("  Equity weight = max(composite, floor=" + str(floor) + ")")
    print("=" * 70)

    print("  1. Creating project...")
    r = api("/projects/create", {
        "name": "Intl40_CompositeRisk_" + str(int(tm.time())),
        "language": "Py",
    })
    if not r.get("success"):
        print("     Failed to create project")
        return None
    project_id = r["projects"][0]["projectId"]
    print("     Project ID:", project_id)

    print("  2. Uploading algorithm...")
    r = api("/files/create", {
        "projectId": project_id,
        "name": "main.py",
        "content": algo_code,
    })
    if not r.get("success"):
        r = api("/files/update", {
            "projectId": project_id,
            "name": "main.py",
            "content": algo_code,
        })
    print("     Uploaded main.py")

    print("  3. Compiling...")
    r = api("/compile/create", {"projectId": project_id})
    if not r.get("success"):
        print("     COMPILE FAILED:", json.dumps(r, indent=2))
        return None
    compile_id = r.get("compileId")
    print("     Compile ID:", compile_id)
    for i in range(30):
        tm.sleep(3)
        r = api("/compile/read", {"projectId": project_id, "compileId": compile_id})
        state = r.get("state", "")
        print(f"     Poll {i+1}: state={state}")
        if state == "BuildSuccess":
            print("     Compiled OK!")
            break
        if state == "BuildError":
            print("     BUILD ERROR:")
            for log in r.get("logs", []):
                print("      ", log)
            return None
    else:
        print("     Compile timed out")
        return None

    print("  4. Starting backtest...")
    bt_name = "Composite_" + str(int(tm.time()))
    r = api("/backtests/create", {
        "projectId": project_id,
        "compileId": compile_id,
        "backtestName": bt_name,
    })
    if not r.get("success"):
        print("     FAILED:", json.dumps(r, indent=2))
        return None
    backtest_id = r["backtest"]["backtestId"]
    print("     Backtest:", bt_name, "ID:", backtest_id)

    print("  5. Waiting for completion...")
    for i in range(360):
        tm.sleep(5)
        try:
            r = api("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        except Exception as e:
            print("     Error:", e)
            continue
        bt = r.get("backtest", {})
        if bt.get("completed", False):
            print("     DONE!")
            break
        progress = bt.get("progress", "")
        if i % 6 == 0:
            print(f"     Poll {i+1}: progress={progress}")
    else:
        url = f"https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}"
        print("     Timed out. Check:", url)
        return {"project_id": project_id, "backtest_id": backtest_id, "url": url}

    stats = bt.get("statistics", {})
    runtime = bt.get("runtimeStatistics", {})
    url = f"https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}"
    print("\n  RESULTS:")
    print("    CAGR:    ", stats.get("Compounding Annual Return", "N/A"))
    print("    Return:  ", stats.get("Net Profit", "N/A"))
    print("    Drawdown:", stats.get("Drawdown", "N/A"))
    print("    Sharpe:  ", stats.get("Sharpe Ratio", "N/A"))
    print("    URL:     ", url)

    out = os.path.join(SCRIPT_DIR, "qc_composite_backtest_result.json")
    with open(out, "w") as f:
        json.dump({
            "project_id": project_id,
            "backtest_id": backtest_id,
            "statistics": stats,
            "runtimeStatistics": runtime,
            "url": url,
        }, f, indent=2, default=str)
    print("\n  Result saved to:", out)
    return {"project_id": project_id, "backtest_id": backtest_id, "url": url}


def main():
    run_backtest(floor=COMPOSITE_FLOOR)


if __name__ == "__main__":
    main()
