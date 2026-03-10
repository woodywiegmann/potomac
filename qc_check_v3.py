"""Check v3 CAOS/SGOV backtest status."""
import time, hashlib, base64, subprocess, json, os

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 28698715
BACKTEST_ID = "4438cfa21ac5d56e334e637123d26e4f"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "qc_v3_raw.json")

ts = str(int(time.time()))
h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()

result = subprocess.run(
    ["curl.exe", "--max-time", "300", "--compressed", "-s",
     "-o", OUT, "-w", "%{http_code}|%{time_total}|%{size_download}",
     "-X", "POST", BASE + "/backtests/read",
     "-H", "Authorization: Basic " + a, "-H", "Timestamp: " + ts,
     "-H", "Content-Type: application/json",
     "-d", json.dumps({"projectId": PROJECT_ID, "backtestId": BACKTEST_ID})],
    capture_output=True, text=True, timeout=310)

print(f"curl: code={result.returncode} meta={result.stdout}")
if os.path.exists(OUT) and os.path.getsize(OUT) > 0:
    with open(OUT) as f:
        data = json.load(f)
    bt = data.get("backtest", {})
    print(f"completed: {bt.get('completed')}")
    if bt.get("completed"):
        for k, v in bt.get("statistics", {}).items():
            print(f"  {k}: {v}")
    elif bt.get("error"):
        print(f"ERROR: {bt['error']}")
