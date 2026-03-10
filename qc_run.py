"""
QC Backtest Runner - uses project 28547602 (has our uploaded code)
Resource tracking: Backtest #2 this session.
"""
import json, sys, os
import time as tm
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE_URL = "https://www.quantconnect.com/api/v2"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
PROJECT_ID = 28547602

def get_headers():
    ts = str(int(tm.time()))
    h = sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    a = b64encode(f"{USER_ID}:{h}".encode()).decode("ascii")
    return {"Authorization": f"Basic {a}", "Timestamp": ts}

def api(endpoint, payload=None):
    r = post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload or {})
    return r.json()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Step 1: Verify project and read files
print("=" * 70)
print("QC BACKTEST: CRTOX Momentum + TLH")
print("Resource tracking: Backtest #2 (session total)")
print("Data: US Equities only (included in plan, no extra cost)")
print("=" * 70)

print("\n1. Reading project files...")
r = api("/files/read", {"projectId": PROJECT_ID})
if r.get("success"):
    files = r.get("files", [])
    for f in files:
        name = f.get("name", "")
        content = f.get("content", "")
        print(f"   File: {name} ({len(content)} chars)")
        if "CrtoxMomentumTLH" in content:
            print("   -> Contains our TLH algorithm")
        elif "BasicTemplate" in content or len(content) < 100:
            print("   -> DEFAULT TEMPLATE - needs update!")
else:
    print("   Could not read files:", r)

# Step 2: Verify main.py has our code, update if needed
print("\n2. Verifying algorithm code...")
needs_update = True
for f in r.get("files", []):
    if f.get("name") == "main.py" and "CrtoxMomentumTLH" in f.get("content", ""):
        needs_update = False
        print("   Code verified - CrtoxMomentumTLH present")

if needs_update:
    print("   Code needs update, uploading...")
    algo_path = os.path.join(SCRIPT_DIR, "crtox_tlh_quantconnect.py")
    with open(algo_path, "r") as af:
        algo_code = af.read()
    r = api("/files/update", {
        "projectId": PROJECT_ID,
        "name": "main.py",
        "content": algo_code
    })
    if r.get("success"):
        print("   Updated successfully")
    else:
        print("   Update failed:", r)
        sys.exit(1)

# Step 3: Compile
print("\n3. Compiling...")
r = api("/compile/create", {"projectId": PROJECT_ID})
if not r.get("success"):
    print("   FAILED:", json.dumps(r, indent=2))
    sys.exit(1)
compile_id = r.get("compileId")
print(f"   Compile ID: {compile_id}")

for i in range(20):
    tm.sleep(3)
    r = api("/compile/read", {"projectId": PROJECT_ID, "compileId": compile_id})
    state = r.get("state", "")
    if state == "BuildSuccess":
        print("   Compiled OK!")
        break
    elif state == "BuildError":
        print("   BUILD ERROR:")
        for log in r.get("logs", []):
            print(f"     {log}")
        sys.exit(1)

# Step 4: Run backtest
print("\n4. Starting backtest...")
bt_name = f"CRTOX_TLH_v2_{int(tm.time())}"
r = api("/backtests/create", {
    "projectId": PROJECT_ID,
    "compileId": compile_id,
    "backtestName": bt_name
})
if not r.get("success"):
    print("   FAILED:", json.dumps(r, indent=2))
    sys.exit(1)

backtest_id = r["backtest"]["backtestId"]
print(f"   Backtest: {bt_name}")
print(f"   ID: {backtest_id}")

# Step 5: Poll
print("\n5. Waiting for completion...")
completed = False
for i in range(240):
    tm.sleep(5)
    r = api("/backtests/read", {"projectId": PROJECT_ID, "backtestId": backtest_id})
    bt = r.get("backtest", {})
    completed = bt.get("completed", False)
    progress = bt.get("progress", 0)
    if i % 12 == 0:
        print(f"   {progress:.0%} complete...")
    if completed:
        break

if not completed:
    print("   Timed out!")
    sys.exit(1)

print("   DONE!")

# Step 6: Results
bt = r.get("backtest", {})
stats = bt.get("statistics", {})
runtime = bt.get("runtimeStatistics", {})

print(f"\n{'=' * 70}")
print("RESULTS")
print(f"{'=' * 70}")
print(f"  Period: {bt.get('backtestStart', '?')} to {bt.get('backtestEnd', '?')}")
print(f"  Trading days: {bt.get('tradeableDates', '?')}")

print("\n  KEY METRICS:")
for key in ["Total Return", "Compounding Annual Return", "Drawdown",
             "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
             "Alpha", "Beta", "Total Fees", "Portfolio Turnover",
             "Treynor Ratio", "Information Ratio", "Tracking Error",
             "Estimated Strategy Capacity", "Lowest Capacity Asset"]:
    val = stats.get(key, "N/A")
    print(f"    {key:.<45} {val}")

print("\n  RUNTIME STATS:")
for key, val in runtime.items():
    print(f"    {key:.<45} {val}")

# TLH logs
logs = bt.get("logs", "")
if logs:
    lines = logs.strip().split("\n")
    tlh_lines = [l for l in lines if "TLH" in l or "harvest" in l.lower() or "REBAL" in l]
    print(f"\n  TLH + REBALANCE LOG ({len(tlh_lines)} entries, showing last 30):")
    for l in tlh_lines[-30:]:
        print(f"    {l}")

out = os.path.join(SCRIPT_DIR, "qc_backtest_results_v2.json")
with open(out, "w") as f:
    json.dump(r, f, indent=2, default=str)
print(f"\n  Full results: {out}")

print(f"\n  RESOURCE USAGE (this session):")
print(f"    Backtests run: 2 (this is #2)")
print(f"    Data: US Equities (standard, included)")
print(f"    Premium data: None")
print(f"    Estimated node time: ~2-5 min")
print(f"\n  View: https://www.quantconnect.com/terminal/{PROJECT_ID}#open/{backtest_id}")
