"""Analyze QC backtest orders for TLH activity. Read-only, no credits used."""
import json, os
import time as tm
from base64 import b64encode
from hashlib import sha256
from collections import defaultdict
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
PROJECT_ID = 28547602
BACKTEST_ID = "05bccf17a546d97424108162720848b7"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}

def api(ep, payload=None):
    return post(f"{BASE_URL}{ep}", headers=get_headers(), json=payload or {}).json()

TLH_PAIRS = {
    "SMH": "SOXX", "SOXX": "SMH",
    "IBB": "XBI",  "XBI": "IBB",
    "SIL": "SILJ", "SILJ": "SIL",
    "XME": "PICK",
    "ITA": "XAR",  "XAR": "ITA",
    "IWO": "VBK",
    "ILF": "EWZ",
    "EFV": "FNDF",
    "IGV": "FTEC",
    "IAI": "KCE",
    "SGOV": "BIL",
}

SUBS = set(TLH_PAIRS.values())
UNIVERSE = ["SMH", "IBB", "SIL", "SILJ", "XME", "ITA", "XAR",
            "IWO", "ILF", "EFV", "SOXX", "IGV", "IAI"]

# Fetch all orders (paginated by order ID ranges)
all_orders = []
start = 0
batch = 100
while True:
    r = api("/backtests/read/orders", {
        "projectId": PROJECT_ID,
        "backtestId": BACKTEST_ID,
        "start": start,
        "end": start + batch
    })
    orders = r.get("orders", [])
    total = r.get("length", 0)
    all_orders.extend(orders)
    print(f"Fetched orders {start}-{start+batch} ({len(orders)} returned, {total} total)")
    if len(orders) < batch or start + batch >= total:
        break
    start += batch

print(f"\nTotal orders: {len(all_orders)}")

# Analyze
ticker_stats = defaultdict(lambda: {"buys": 0, "sells": 0, "buy_value": 0, "sell_value": 0})
monthly_trades = defaultdict(int)
tlh_swap_events = []

for o in all_orders:
    ticker = o.get("symbol", {}).get("value", "?")
    qty = o.get("quantity", 0)
    price = o.get("price", 0)
    dt = o.get("time", "")[:10]
    month = dt[:7]
    value = abs(qty * price)

    monthly_trades[month] += 1

    if qty > 0:
        ticker_stats[ticker]["buys"] += 1
        ticker_stats[ticker]["buy_value"] += value
    else:
        ticker_stats[ticker]["sells"] += 1
        ticker_stats[ticker]["sell_value"] += value

    if ticker in SUBS and ticker not in UNIVERSE:
        tlh_swap_events.append({
            "date": dt,
            "ticker": ticker,
            "qty": qty,
            "price": price,
            "value": value,
            "direction": "BUY" if qty > 0 else "SELL"
        })

# Print results
L = []
def p(s=""):
    L.append(s)
    print(s)

W = 100
p("=" * W)
p("CRTOX MOMENTUM + TLH BACKTEST ANALYSIS")
p("QuantConnect Project 28547602")
p("Period: 2021-01-01 to 2026-02-01")
p("=" * W)

p("\nBACKTEST METRICS (from QC):")
p("  CAGR:             20.95%")
p("  Max Drawdown:     -30.90%")
p("  Sharpe:           0.645")
p("  Sortino:          0.758")
p("  Alpha:            4.6% (annualized vs SPY)")
p("  Beta:             1.104")
p("  Turnover:         2.51%")
p("  Total Fees:       $6,044.77")
p("  Info Ratio:       0.461")
p("  Tracking Error:   11.6%")
p("  Final Equity:     $2,629,754 (started $1,000,000)")
p("  Total Return:     163.0%")

p(f"\n{'=' * W}")
p("ORDER ANALYSIS")
p(f"{'=' * W}")
p(f"\n  Total orders: {len(all_orders)}")
p(f"  Total volume: ${sum(abs(o.get('quantity',0)*o.get('price',0)) for o in all_orders):,.0f}")

p(f"\n  TRADES BY TICKER:")
p(f"  {'Ticker':.<10} {'Total':>6} {'Buys':>6} {'Sells':>6} {'Buy$':>14} {'Sell$':>14} {'TLH Swap?'}")
p("  " + "-" * 80)
for t, v in sorted(ticker_stats.items(), key=lambda x: -x[1]["buys"] - x[1]["sells"]):
    total = v["buys"] + v["sells"]
    is_swap = "YES" if t in SUBS and t not in UNIVERSE else ""
    p(f"  {t:.<10} {total:>6} {v['buys']:>6} {v['sells']:>6} ${v['buy_value']:>12,.0f} ${v['sell_value']:>12,.0f} {is_swap}")

p(f"\n  TLH SWAP TICKER ACTIVITY:")
p(f"  (These are substitute tickers -- indicates TLH harvest occurred)")
if tlh_swap_events:
    p(f"  Total TLH swap trades: {len(tlh_swap_events)}")
    p(f"\n  {'Date':.<12} {'Ticker':.<8} {'Direction':.<6} {'Qty':>8} {'Price':>10} {'Value':>14}")
    p("  " + "-" * 70)
    for e in tlh_swap_events:
        p(f"  {e['date']:.<12} {e['ticker']:.<8} {e['direction']:.<6} {e['qty']:>8} ${e['price']:>9.2f} ${e['value']:>13,.0f}")
else:
    p("  No TLH swap trades detected in orders")

p(f"\n  MONTHLY TRADE FREQUENCY:")
for m in sorted(monthly_trades.keys()):
    bar = "#" * min(monthly_trades[m], 50)
    p(f"  {m}  {monthly_trades[m]:>4} trades  {bar}")

# Year-by-year trade count
yearly_trades = defaultdict(int)
for m, c in monthly_trades.items():
    yearly_trades[m[:4]] += c
p(f"\n  ANNUAL TRADE COUNT:")
for y in sorted(yearly_trades.keys()):
    p(f"  {y}: {yearly_trades[y]:>5} trades")

p(f"\n{'=' * W}")
p("RESOURCE USAGE (this analysis):")
p("  API calls: ~3-5 (read-only, order pagination)")
p("  Backtests run: 0 (analysis only)")
p("  Credits used: 0")
p(f"{'=' * W}")

out = os.path.join(SCRIPT_DIR, "qc_analysis_results.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print(f"\nSaved to: {out}")
