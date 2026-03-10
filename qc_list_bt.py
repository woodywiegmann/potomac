"""List backtests for a project to check status."""
import time, hashlib, base64, subprocess, json

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 28686016


def call(endpoint, payload, timeout=30):
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    result = subprocess.run(
        ["curl.exe", "--max-time", str(timeout), "--compressed", "-s",
         "-X", "POST", BASE + endpoint,
         "-H", "Authorization: Basic " + a,
         "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        print(f"  Empty (curl code {result.returncode})")
        return None
    return json.loads(result.stdout)


print("Listing backtests for project", PROJECT_ID, "...")
r = call("/backtests/list", {"projectId": PROJECT_ID, "start": 0, "end": 5, "includeStatistics": True})
if r and r.get("success"):
    backtests = r.get("backtests", [])
    print(f"Found {len(backtests)} backtests:")
    for bt in backtests:
        print(f"  {bt.get('name', '?')}: completed={bt.get('completed')} "
              f"progress={bt.get('progress')} error={bt.get('error')}")
        if bt.get("completed"):
            stats = bt.get("statistics", {})
            if stats:
                print(f"    CAGR={stats.get('Compounding Annual Return')} "
                      f"DD={stats.get('Drawdown')} Sharpe={stats.get('Sharpe Ratio')}")
            btid = bt.get("backtestId", "")
            print(f"    URL: https://www.quantconnect.com/terminal/{PROJECT_ID}#open/{btid}")
elif r:
    print("API error:", json.dumps(r, indent=2)[:500])
else:
    print("No response")
