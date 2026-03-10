"""Read v2 backtest results by writing curl output to file."""
import time, hashlib, base64, subprocess, json, os

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 28686016
BACKTEST_ID = "2fc8c491334aa4bf29b8067d88bde293"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(SCRIPT_DIR, "qc_v2_raw_response.json")

ts = str(int(time.time()))
h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
payload = json.dumps({"projectId": PROJECT_ID, "backtestId": BACKTEST_ID})

print("Fetching backtest results (writing to file, 300s timeout)...")
result = subprocess.run(
    ["curl.exe", "--max-time", "300", "--compressed", "-s",
     "-o", OUT_FILE,
     "-w", "%{http_code}|%{time_total}|%{size_download}",
     "-X", "POST", BASE + "/backtests/read",
     "-H", "Authorization: Basic " + a,
     "-H", "Timestamp: " + ts,
     "-H", "Content-Type: application/json",
     "-d", payload],
    capture_output=True, text=True, timeout=310
)
print(f"curl code: {result.returncode}")
print(f"curl meta: {result.stdout}")

if os.path.exists(OUT_FILE) and os.path.getsize(OUT_FILE) > 0:
    with open(OUT_FILE) as f:
        data = json.load(f)
    bt = data.get("backtest", {})
    stats = bt.get("statistics", {})
    rt = bt.get("runtimeStatistics", {})

    print(f"\nCompleted: {bt.get('completed')}")
    print(f"\n--- STATISTICS ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\n--- RUNTIME ---")
    for k, v in rt.items():
        print(f"  {k}: {v}")
    url = f"https://www.quantconnect.com/terminal/{PROJECT_ID}#open/{BACKTEST_ID}"
    print(f"\nURL: {url}")
else:
    print(f"No output file or empty (size: {os.path.getsize(OUT_FILE) if os.path.exists(OUT_FILE) else 0})")
