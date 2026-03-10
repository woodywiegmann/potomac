"""Read backtest logs and orders from QC. Resource: read-only API calls, no backtests."""
import json, os
import time as tm
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
PROJECT_ID = 28547602
BACKTEST_ID = "05bccf17a546d97424108162720848b7"

def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}

def api(endpoint, payload=None):
    return post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload or {}).json()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Read backtest with logs
print("1. Reading backtest logs...")
r = api("/backtests/read", {
    "projectId": PROJECT_ID,
    "backtestId": BACKTEST_ID
})
bt = r.get("backtest", {})
logs = bt.get("logs", "")
log_list = bt.get("logList", [])
print(f"   logs field length: {len(logs)}")
print(f"   logList length: {len(log_list)}")

if log_list:
    print("\n   LOG LIST (last 30):")
    for entry in log_list[-30:]:
        print(f"   {entry}")

# 2. Read orders
print("\n2. Reading orders...")
r2 = api("/backtests/orders/read", {
    "projectId": PROJECT_ID,
    "backtestId": BACKTEST_ID,
    "start": 0,
    "end": 500
})

orders = r2.get("orders", [])
print(f"   Total orders: {len(orders)}")

if orders:
    # Summarize by ticker
    ticker_trades = {}
    for o in orders:
        sym = o.get("symbol", {}).get("value", "?")
        direction = "BUY" if o.get("quantity", 0) > 0 else "SELL"
        dt = o.get("time", "?")
        qty = o.get("quantity", 0)
        price = o.get("price", 0)
        key = sym
        if key not in ticker_trades:
            ticker_trades[key] = {"buys": 0, "sells": 0, "count": 0}
        ticker_trades[key]["count"] += 1
        if qty > 0:
            ticker_trades[key]["buys"] += 1
        else:
            ticker_trades[key]["sells"] += 1

    print("\n   TRADES BY TICKER:")
    for t, v in sorted(ticker_trades.items(), key=lambda x: -x[1]["count"]):
        print(f"     {t:.<10} {v['count']:>4} trades ({v['buys']} buys, {v['sells']} sells)")

    print(f"\n   FIRST 10 ORDERS:")
    for o in orders[:10]:
        sym = o.get("symbol", {}).get("value", "?")
        dt = o.get("time", "?")[:19]
        qty = o.get("quantity", 0)
        price = o.get("price", 0)
        status = o.get("status", "?")
        print(f"     {dt} | {sym:.<8} | qty={qty:>8} | price=${price:>8.2f} | {status}")

    print(f"\n   LAST 10 ORDERS:")
    for o in orders[-10:]:
        sym = o.get("symbol", {}).get("value", "?")
        dt = o.get("time", "?")[:19]
        qty = o.get("quantity", 0)
        price = o.get("price", 0)
        status = o.get("status", "?")
        print(f"     {dt} | {sym:.<8} | qty={qty:>8} | price=${price:>8.2f} | {status}")

# Save orders
out = os.path.join(SCRIPT_DIR, "qc_orders.json")
with open(out, "w") as f:
    json.dump(r2, f, indent=2, default=str)
print(f"\n   Orders saved: {out}")

# 3. Summary
stats = bt.get("statistics", {})
print(f"\n{'=' * 70}")
print("BACKTEST SUMMARY")
print(f"{'=' * 70}")
print(f"  CAGR:             {stats.get('Compounding Annual Return', 'N/A')}")
print(f"  Max Drawdown:     {stats.get('Drawdown', 'N/A')}")
print(f"  Sharpe:           {stats.get('Sharpe Ratio', 'N/A')}")
print(f"  Sortino:          {stats.get('Sortino Ratio', 'N/A')}")
print(f"  Alpha:            {stats.get('Alpha', 'N/A')}")
print(f"  Beta:             {stats.get('Beta', 'N/A')}")
print(f"  Turnover:         {stats.get('Portfolio Turnover', 'N/A')}")
print(f"  Total Fees:       {stats.get('Total Fees', 'N/A')}")
print(f"  Info Ratio:       {stats.get('Information Ratio', 'N/A')}")
print(f"  Tracking Error:   {stats.get('Tracking Error', 'N/A')}")
print(f"  Total orders:     {len(orders)}")
print(f"  Period:           {bt.get('backtestStart', '?')} to {bt.get('backtestEnd', '?')}")
print(f"\n  RESOURCE: Read-only API calls (no backtests run, no credits used)")
