import json, csv, os, time as time_mod
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"

def get_headers():
    ts = str(int(time_mod.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    auth = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {auth}", "Timestamp": ts}

project_id = 28552769
backtest_id = "f4059b5808096b3fc4a98ae8da4bee11"

all_orders = []
for start in range(0, 300, 100):
    r = post(f"{BASE_URL}/backtests/orders/read", headers=get_headers(), json={
        "projectId": project_id,
        "backtestId": backtest_id,
        "start": start,
        "end": start + 100,
    }).json()
    batch = r.get("orders", [])
    print(f"  Batch {start}-{start+100}: {len(batch)} orders")
    all_orders.extend(batch)
    if len(batch) < 100:
        break

print(f"Total: {len(all_orders)} orders")

rows = []
for o in all_orders:
    sym = o.get("symbol", {})
    ticker = sym.get("value", "") if isinstance(sym, dict) else str(sym)
    ticker = ticker.split(" ")[0]
    rows.append({
        "date": o.get("time", "")[:10],
        "action": "BUY" if o.get("quantity", 0) > 0 else "SELL",
        "ticker": ticker,
        "price": round(o.get("price", 0), 4),
        "shares": abs(int(o.get("quantity", 0))),
        "value": round(abs(o.get("quantity", 0) * o.get("price", 0)), 2),
        "status": o.get("status", ""),
        "tag": o.get("tag", ""),
    })

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crtpx_trades.csv")
with open(out, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"Saved {len(rows)} trades to {out}")
