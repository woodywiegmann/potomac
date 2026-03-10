"""Quick QC status check and backtest runner."""
import json
import sys
import time as tm
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"

def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}

def api(endpoint, payload=None):
    r = post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload or {})
    return r.json()

# Auth
print("1. Authenticating...")
r = api("/authenticate")
print(f"   Success: {r.get('success')}")
if not r.get("success"):
    print("   FAILED:", r)
    sys.exit(1)

# List projects
print("\n2. Listing projects...")
r = api("/projects/read")
projects = r.get("projects", [])
print(f"   Total projects: {len(projects)}")
for p in projects[-5:]:
    pid = p["projectId"]
    name = p["name"]
    lang = p["language"]
    print(f"   ID:{pid} | {name} | {lang}")

# Use the most recent CRTOX project
target_id = None
for p in reversed(projects):
    if "CRTOX" in p["name"]:
        target_id = p["projectId"]
        break

if not target_id:
    print("No CRTOX project found!")
    sys.exit(1)

print(f"\n3. Using project: {target_id}")

# Compile it
print("   Compiling...")
r = api("/compile/create", {"projectId": target_id})
print(f"   Compile response: success={r.get('success')}, state={r.get('state')}")
if not r.get("success"):
    print("   ERROR:", json.dumps(r, indent=2))
    sys.exit(1)

compile_id = r.get("compileId")
print(f"   Compile ID: {compile_id}")

# Wait for compile
for i in range(20):
    tm.sleep(3)
    r = api("/compile/read", {"projectId": target_id, "compileId": compile_id})
    state = r.get("state", "")
    if state == "BuildSuccess":
        print(f"   Compiled OK!")
        break
    elif state == "BuildError":
        print(f"   BUILD ERROR:")
        for log in r.get("logs", []):
            print(f"     {log}")
        sys.exit(1)
    print(f"   Waiting... ({state})")

# Run backtest (1 backtest only)
print("\n4. Starting backtest (1 run)...")
print("   RESOURCE TRACKING: This is backtest #1")
bt_name = f"CRTOX_TLH_{int(tm.time())}"
r = api("/backtests/create", {
    "projectId": target_id,
    "compileId": compile_id,
    "backtestName": bt_name
})
if not r.get("success"):
    print("   FAILED:", json.dumps(r, indent=2))
    sys.exit(1)

backtest_id = r["backtest"]["backtestId"]
print(f"   Backtest ID: {backtest_id}")
print(f"   Name: {bt_name}")

# Poll for completion
print("\n5. Waiting for backtest...")
for i in range(180):
    tm.sleep(5)
    r = api("/backtests/read", {"projectId": target_id, "backtestId": backtest_id})
    bt = r.get("backtest", {})
    completed = bt.get("completed", False)
    progress = bt.get("progress", 0)
    if i % 6 == 0:
        print(f"   Progress: {progress:.0%}")
    if completed:
        break

if not completed:
    print("   Timed out!")
    sys.exit(1)

print(f"   COMPLETED!")

# Read results
print("\n6. Results:")
stats = bt.get("statistics", {})
runtime = bt.get("runtimeStatistics", {})

print("\n   KEY METRICS:")
for key in ["Total Return", "Compounding Annual Return", "Drawdown",
             "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
             "Alpha", "Beta", "Total Fees", "Portfolio Turnover",
             "Treynor Ratio", "Information Ratio", "Tracking Error",
             "Estimated Strategy Capacity"]:
    val = stats.get(key, "N/A")
    print(f"   {key:.<45} {val}")

print("\n   RUNTIME STATS:")
for key, val in runtime.items():
    print(f"   {key:.<45} {val}")

# Logs (TLH summary)
logs = bt.get("logs", "")
if logs:
    lines = logs.strip().split("\n")
    tlh_lines = [l for l in lines if "TLH" in l or "harvest" in l.lower()]
    print(f"\n   TLH LOG ENTRIES ({len(tlh_lines)} harvest events):")
    for l in tlh_lines[-25:]:
        print(f"   {l}")

# Save full results
import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qc_backtest_results.json")
with open(out, "w") as f:
    json.dump(r, f, indent=2, default=str)
print(f"\n   Full results saved: {out}")

print(f"\n   RESOURCE USAGE SUMMARY:")
print(f"   Backtests run this session: 1")
print(f"   Data used: US Equities (included in plan)")
print(f"   Premium data: None")
print(f"\n   View: https://www.quantconnect.com/terminal/{target_id}#open/{backtest_id}")
