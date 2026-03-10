"""
QuantConnect Deploy: 4-Signal Composite (Equal Weight) on Antonacci Dual Momentum
==================================================================================
Signals (25% each):
  1. ACWX 50/200 SMA crossover (golden cross = risk-on)
  2. Breadth (% MSCI country ETFs > 200d SMA)
  3. RSI(5) on ACWX (>0.50 = risk-on)
  4. WMA/IWMA on ACWX mean price (WMA > IWMA = risk-on)

Equity weight = max(composite, 0.25 floor)
Logs each signal value monthly for post-hoc analytics.

Uses curl.exe for API calls (requests library hangs on this machine).
"""

import json
import os
import time
import hashlib
import base64
import subprocess
import sys

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def call_api(endpoint, payload):
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    body = json.dumps(payload)
    result = subprocess.run(
        ["curl.exe", "--max-time", "30", "-s", "-X", "POST",
         BASE_URL + endpoint,
         "-H", "Authorization: Basic " + a,
         "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", body],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        print("  Empty API response for", endpoint)
        print("  stderr:", result.stderr[:300])
        return {"success": False}
    data = json.loads(result.stdout)
    if not data.get("success"):
        print("  API ERROR on", endpoint + ":", json.dumps(data, indent=2)[:500])
    return data


ALGO_CODE = r'''
from AlgorithmImports import *
from datetime import timedelta
import numpy as np
import pandas as pd


class Intl40ETF_4Signal(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2026, 2, 28)
        self.set_cash(1_000_000)
        self.set_benchmark("EFA")

        self.composite_floor = 0.25

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
        self.sma_short = 50
        self.sma_long = 200

        self.symbols = {}
        for t in list(self.all_etfs.keys()) + [self.cash_ticker, self.trend_ticker]:
            sym = self.add_equity(t, Resolution.DAILY)
            sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
            self.symbols[t] = sym.symbol

        self.breadth_symbols = {}
        for t in self.breadth_tickers:
            if t not in self.symbols:
                sym = self.add_equity(t, Resolution.DAILY)
                sym.set_data_normalization_mode(DataNormalizationMode.TOTAL_RETURN)
                self.breadth_symbols[t] = sym.symbol
            else:
                self.breadth_symbols[t] = self.symbols[t]

        self.set_warm_up(timedelta(days=260))
        self.rebalance_scheduled = False
        self.schedule.on(
            self.date_rules.month_end(),
            self.time_rules.before_market_close("EFA", 30),
            self.flag_rebalance
        )
        self.settings.free_portfolio_value_percentage = 0.02

    def flag_rebalance(self):
        self.rebalance_scheduled = True

    def on_data(self, data):
        if self.is_warming_up or not self.rebalance_scheduled:
            return
        self.rebalance_scheduled = False
        self.rebalance(data)

    # ---- helpers ----
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

    # ---- 4 signals ----
    def signal_sma_crossover(self):
        """ACWX 50d SMA vs 200d SMA. Golden cross = 1, death cross = 0."""
        sym = self.symbols.get(self.trend_ticker)
        if sym is None:
            return 0.5
        sma50 = self.get_sma(sym, self.sma_short)
        sma200 = self.get_sma(sym, self.sma_long)
        if sma50 is None or sma200 is None:
            return 0.5
        return 1.0 if sma50 > sma200 else 0.0

    def signal_breadth(self):
        """% of 31 MSCI country ETFs above 200d SMA."""
        above, total = 0, 0
        for t in self.breadth_tickers:
            sym = self.breadth_symbols.get(t) or self.symbols.get(t)
            if sym is None:
                continue
            if not self.securities[sym].has_data:
                continue
            price = self.get_price(sym)
            sma = self.get_sma(sym, self.sma_long)
            if price is not None and sma is not None and sma > 0:
                total += 1
                if price > sma:
                    above += 1
        return (above / total) if total > 0 else 0.5

    def signal_rsi5(self):
        """RSI(5) on ACWX, scaled to [0, 1]."""
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
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        if np.isnan(val):
            return 0.5
        return float(np.clip(val / 100.0, 0.0, 1.0))

    def signal_wma_iwma(self):
        """WMA(7) vs IWMA(7) on ACWX mean price. WMA > IWMA = 1."""
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
        wma = mean_p.rolling(period).apply(
            lambda x: np.dot(x, w) / w.sum() if len(x) == period else np.nan, raw=True)
        iw = np.arange(period, 0, -1, dtype=float)
        iwma = mean_p.rolling(period).apply(
            lambda x: np.dot(x, iw) / iw.sum() if len(x) == period else np.nan, raw=True)
        if pd.isna(wma.iloc[-1]) or pd.isna(iwma.iloc[-1]):
            return 0.5
        return 1.0 if wma.iloc[-1] > iwma.iloc[-1] else 0.0

    # ---- composite ----
    def compute_composite(self):
        sma_x = self.signal_sma_crossover()
        breadth = self.signal_breadth()
        rsi = self.signal_rsi5()
        wma = self.signal_wma_iwma()

        composite = 0.25 * sma_x + 0.25 * breadth + 0.25 * rsi + 0.25 * wma

        self.plot("Signals", "SMA_Cross", sma_x)
        self.plot("Signals", "Breadth", breadth)
        self.plot("Signals", "RSI5", rsi)
        self.plot("Signals", "WMA_IWMA", wma)
        self.plot("Composite", "Score", composite)

        eq_w = max(composite, self.composite_floor)
        self.plot("Composite", "EquityWt", eq_w)

        self.log(f"SIGNALS|sma_cross={sma_x:.3f}|breadth={breadth:.3f}|rsi5={rsi:.3f}|wma_iwma={wma:.3f}|composite={composite:.3f}|eq_wt={eq_w:.3f}")

        return eq_w, {"sma_cross": sma_x, "breadth": breadth, "rsi5": rsi, "wma_iwma": wma}

    # ---- rebalance ----
    def rebalance(self, data):
        eq_w, signals = self.compute_composite()

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
            bil_sym = self.symbols[self.cash_ticker]
            self.set_holdings(bil_sym, 0.98)
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


def main():
    print("=" * 70)
    print("  4-SIGNAL COMPOSITE (Equal Weight) on Antonacci Dual Momentum")
    print("  Signals: ACWX 50/200 SMA crossover, Breadth, RSI(5), WMA/IWMA")
    print("  Each 25% weight, equity_wt = max(composite, 0.25)")
    print("=" * 70)

    print("\n1. Creating project...")
    r = call_api("/projects/create", {
        "name": "Intl40_4Signal_" + str(int(time.time())),
        "language": "Py",
    })
    if not r.get("success"):
        print("   Failed to create project")
        return
    project_id = r["projects"][0]["projectId"]
    print("   Project ID:", project_id)

    print("2. Uploading algorithm...")
    r = call_api("/files/create", {
        "projectId": project_id,
        "name": "main.py",
        "content": ALGO_CODE,
    })
    if not r.get("success"):
        call_api("/files/update", {
            "projectId": project_id,
            "name": "main.py",
            "content": ALGO_CODE,
        })
    print("   Uploaded main.py")

    print("3. Compiling...")
    r = call_api("/compile/create", {"projectId": project_id})
    if not r.get("success"):
        print("   COMPILE FAILED")
        return
    compile_id = r.get("compileId")
    print("   Compile ID:", compile_id)

    for i in range(30):
        time.sleep(3)
        r = call_api("/compile/read", {"projectId": project_id, "compileId": compile_id})
        state = r.get("state", "")
        print(f"   Poll {i+1}: state={state}")
        if state == "BuildSuccess":
            print("   Compiled OK!")
            break
        if state == "BuildError":
            print("   BUILD ERROR:")
            for log in r.get("logs", []):
                print("    ", log)
            return
    else:
        print("   Compile timed out")
        return

    print("4. Starting backtest...")
    bt_name = "4Signal_" + str(int(time.time()))
    r = call_api("/backtests/create", {
        "projectId": project_id,
        "compileId": compile_id,
        "backtestName": bt_name,
    })
    if not r.get("success"):
        print("   FAILED to start backtest")
        return
    backtest_id = r["backtest"]["backtestId"]
    print("   Backtest:", bt_name, "ID:", backtest_id)

    print("5. Waiting for completion...")
    for i in range(360):
        time.sleep(5)
        r = call_api("/backtests/read", {"projectId": project_id, "backtestId": backtest_id})
        bt = r.get("backtest", {})
        if bt.get("completed"):
            print("   DONE!")
            break
        if i % 6 == 0:
            print(f"   Poll {i+1}: progress={bt.get('progress', '?')}")
    else:
        url = f"https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}"
        print("   Timed out. Check:", url)
        save_result(project_id, backtest_id, {}, url)
        return

    stats = bt.get("statistics", {})
    runtime = bt.get("runtimeStatistics", {})
    url = f"https://www.quantconnect.com/terminal/{project_id}#open/{backtest_id}"

    print("\n  RESULTS:")
    for k in ["Compounding Annual Return", "Drawdown", "Sharpe Ratio",
              "Sortino Ratio", "Net Profit", "Total Orders"]:
        print(f"    {k}: {stats.get(k, 'N/A')}")
    print(f"    URL: {url}")

    save_result(project_id, backtest_id, stats, url)

    print("\n6. Fetching logs for signal analytics...")
    r = call_api("/backtests/read/log", {
        "projectId": project_id,
        "backtestId": backtest_id,
        "start": 0,
        "end": 5000,
    })
    logs = r.get("logs", r.get("LiveLogs", r.get("BacktestLogs", [])))
    if not logs:
        logs = r.get("log", [])

    signal_lines = []
    if isinstance(logs, list):
        for line in logs:
            txt = line if isinstance(line, str) else str(line)
            if "SIGNALS|" in txt:
                signal_lines.append(txt)
    elif isinstance(logs, str):
        for line in logs.split("\n"):
            if "SIGNALS|" in line:
                signal_lines.append(line)

    if signal_lines:
        print(f"   Found {len(signal_lines)} signal log entries")
        out_path = os.path.join(SCRIPT_DIR, "qc_4signal_logs.txt")
        with open(out_path, "w") as f:
            for line in signal_lines:
                f.write(line + "\n")
        print(f"   Saved to {out_path}")
        analyze_signals(signal_lines)
    else:
        print("   No SIGNALS| log lines found in first batch. Check QC terminal for logs.")
        print("   Raw log keys:", list(r.keys()) if isinstance(r, dict) else "not dict")


def save_result(project_id, backtest_id, stats, url):
    out = os.path.join(SCRIPT_DIR, "qc_4signal_result.json")
    with open(out, "w") as f:
        json.dump({
            "project_id": project_id,
            "backtest_id": backtest_id,
            "statistics": stats,
            "url": url,
        }, f, indent=2)
    print(f"   Saved to {out}")


def analyze_signals(lines):
    """Parse logged signal values and compute analytics."""
    records = []
    for line in lines:
        parts = line.split("SIGNALS|")[-1].strip()
        vals = {}
        for chunk in parts.split("|"):
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                try:
                    vals[k] = float(v)
                except ValueError:
                    pass
        if vals:
            records.append(vals)

    if not records:
        print("   No parseable signal records")
        return

    n = len(records)
    signals = ["sma_cross", "breadth", "rsi5", "wma_iwma"]

    print(f"\n  SIGNAL ANALYTICS ({n} monthly observations)")
    print("  " + "-" * 60)
    print(f"  {'Signal':<14} {'Risk-On%':>10} {'Risk-Off%':>10} {'Mean':>8} {'StdDev':>8}")
    print("  " + "-" * 60)

    for s in signals:
        vals = [r.get(s, 0.5) for r in records]
        mean_v = sum(vals) / len(vals)
        risk_on_pct = sum(1 for v in vals if v > 0.5) / len(vals) * 100
        risk_off_pct = 100 - risk_on_pct
        variance = sum((v - mean_v) ** 2 for v in vals) / len(vals)
        std_dev = variance ** 0.5
        print(f"  {s:<14} {risk_on_pct:>9.1f}% {risk_off_pct:>9.1f}% {mean_v:>8.3f} {std_dev:>8.3f}")

    print("  " + "-" * 60)

    comp_vals = [r.get("composite", 0.5) for r in records]
    comp_mean = sum(comp_vals) / len(comp_vals)
    eq_vals = [r.get("eq_wt", 0.5) for r in records]
    eq_mean = sum(eq_vals) / len(eq_vals)
    print(f"  {'composite':<14} {'':>10} {'':>10} {comp_mean:>8.3f}")
    print(f"  {'equity_wt':<14} {'':>10} {'':>10} {eq_mean:>8.3f}")

    time_invested = sum(1 for v in eq_vals if v >= 0.5) / len(eq_vals) * 100
    print(f"\n  Time invested (equity_wt >= 50%): {time_invested:.1f}%")
    print(f"  Average equity weight: {eq_mean:.1%}")


if __name__ == "__main__":
    main()
