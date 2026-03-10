"""Get backtest stats - with verbose debugging."""
import time, hashlib, base64, subprocess, json, sys

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"

# Check both backtests
CHECKS = [
    ("v1 (200d breadth)", 28685329, "ccead7cfac4527a584e26e0aa667a1dd"),
    ("v2 (100d bin@60%)", 28686016, "2fc8c491334aa4bf29b8067d88bde293"),
]

sys.stdout.reconfigure(line_buffering=True)

for label, proj_id, bt_id in CHECKS:
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()

    payload = json.dumps({"projectId": proj_id, "start": 0, "end": 5})

    print(f"\n--- {label} (project {proj_id}) ---")
    result = subprocess.run(
        ["curl.exe", "--max-time", "20", "--compressed", "-s",
         "-X", "POST", BASE + "/backtests/list",
         "-H", "Authorization: Basic " + a,
         "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", payload],
        capture_output=True, text=True
    )
    print(f"  curl code: {result.returncode}")

    if not result.stdout.strip():
        print("  Empty response")
        continue

    r = json.loads(result.stdout)
    bts = r.get("backtests", [])
    print(f"  Found {len(bts)} backtests")

    for bt in bts:
        if bt.get("backtestId") == bt_id:
            print(f"  Name: {bt.get('name')}")
            print(f"  Completed: {bt.get('completed')}")
            rt = bt.get("runtimeStatistics", {})
            for k, v in rt.items():
                print(f"    {k}: {v}")
            st = bt.get("statistics", {})
            if st:
                for k, v in st.items():
                    print(f"    {k}: {v}")
            break
    else:
        print(f"  Backtest {bt_id} not in list")
