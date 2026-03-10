"""Check defensive and gold digger QC backtests."""
import json, time, hashlib, base64, subprocess, os

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
DIR = os.path.dirname(os.path.abspath(__file__))

checks = [
    ("Defensive", 28700962, "57047b2add985ba7391d605b187c7827", "qc_defensive_raw.json"),
    ("GoldDigger", 28700961, "cf2915affc3aad4ef619e9cf4f965b8e", "qc_golddigger_raw.json"),
]

for label, pid, bid, fname in checks:
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    out = os.path.join(DIR, fname)
    r = subprocess.run(
        ["curl.exe", "--max-time", "300", "--compressed", "-s", "-o", out,
         "-w", "%{http_code}|%{time_total}|%{size_download}",
         "-X", "POST", BASE + "/backtests/read",
         "-H", "Authorization: Basic " + a, "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"projectId": pid, "backtestId": bid})],
        capture_output=True, text=True, timeout=310)
    print(label + ": curl=" + str(r.returncode) + " meta=" + r.stdout)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        with open(out) as f:
            data = json.load(f)
        bt = data.get("backtest", {})
        print("  completed=" + str(bt.get("completed")))
        if bt.get("completed"):
            for k, v in bt.get("statistics", {}).items():
                print("  " + k + ": " + str(v))
        elif bt.get("error"):
            print("  ERROR: " + str(bt["error"]))
    print()
