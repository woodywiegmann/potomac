"""Check combined 50/25/25 backtest."""
import json, time, hashlib, base64, subprocess, os
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
PID = 28707844
BID = "68c6e86dcfb28d4e48b285ca8b35549d"
DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "qc_combined_raw.json")

ts = str(int(time.time()))
h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
r = subprocess.run(
    ["curl.exe", "--max-time", "300", "--compressed", "-s", "-o", OUT,
     "-w", "%{http_code}|%{time_total}|%{size_download}",
     "-X", "POST", BASE + "/backtests/read",
     "-H", "Authorization: Basic " + a, "-H", "Timestamp: " + ts,
     "-H", "Content-Type: application/json",
     "-d", json.dumps({"projectId": PID, "backtestId": BID})],
    capture_output=True, text=True, timeout=310)
print("curl:", r.returncode, r.stdout)
if os.path.exists(OUT) and os.path.getsize(OUT) > 0:
    with open(OUT) as f:
        data = json.load(f)
    bt = data.get("backtest", {})
    print("completed:", bt.get("completed"))
    if bt.get("completed"):
        for k, v in bt.get("statistics", {}).items():
            print("  " + k + ": " + str(v))
        for k, v in bt.get("runtimeStatistics", {}).items():
            print("  [RT] " + k + ": " + str(v))
    elif bt.get("error"):
        print("ERROR:", bt["error"])
