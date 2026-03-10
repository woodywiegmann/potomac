"""Quick poll for QC backtest result."""
import json, time as tm, os
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
PROJECT_ID = 28622875
BACKTEST_ID = "4caadb4bab05d180fa0486d4e8bbe49f"

def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}

r = post(f"{BASE_URL}/backtests/read",
         headers=get_headers(),
         json={"projectId": PROJECT_ID, "backtestId": BACKTEST_ID},
         timeout=30).json()

bt = r.get("backtest", {})
stats = bt.get("statistics", {})
rt = bt.get("runtimeStatistics", {})

print(f"Status: {bt.get('status')}")
print(f"Completed: {bt.get('completed')}")
print(f"Period: {bt.get('backtestStart')} to {bt.get('backtestEnd')}")
print()
print("KEY METRICS:")
for k, v in stats.items():
    print(f"  {k:.<45} {v}")
print()
print("RUNTIME:")
for k, v in rt.items():
    print(f"  {k:.<45} {v}")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qc_intl_momentum_results.json")
with open(out, "w") as f:
    json.dump(r, f, indent=2, default=str)
print(f"\nSaved to: {out}")
print(f"View: https://www.quantconnect.com/terminal/{PROJECT_ID}#open/{BACKTEST_ID}")
