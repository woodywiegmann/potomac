"""Try reading orders and logs from different QC endpoints."""
import json
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

def api(ep, payload=None):
    return post(f"{BASE_URL}{ep}", headers=get_headers(), json=payload or {}).json()

# Try orders
for ep in ["/backtests/read/orders"]:
    r = api(ep, {
        "projectId": PROJECT_ID,
        "backtestId": BACKTEST_ID,
        "start": 0,
        "end": 100
    })
    success = r.get("success")
    keys = list(r.keys())
    orders = r.get("orders", [])
    print(f"Endpoint {ep}:")
    print(f"  success={success}, keys={keys}, orders={len(orders)}")
    if orders:
        for o in orders[:3]:
            print(f"  {json.dumps(o)[:200]}")

# Try logs
r = api("/backtests/read/logs", {
    "projectId": PROJECT_ID,
    "backtestId": BACKTEST_ID,
    "start": 0,
    "end": 100
})
success = r.get("success")
logs = r.get("logs", [])
print(f"\nLogs endpoint: success={success}, count={len(logs)}")
if logs:
    for l in logs[:10]:
        print(f"  {l}")
