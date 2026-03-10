"""Quick status check via list endpoint."""
import json, time, hashlib, base64, subprocess

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
PID = 28707844

ts = str(int(time.time()))
h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
r = subprocess.run(
    ["curl.exe", "--max-time", "20", "--compressed", "-s", "-X", "POST",
     BASE + "/backtests/list",
     "-H", "Authorization: Basic " + a, "-H", "Timestamp: " + ts,
     "-H", "Content-Type: application/json",
     "-d", json.dumps({"projectId": PID, "start": 0, "end": 5})],
    capture_output=True, text=True)
if r.stdout.strip():
    data = json.loads(r.stdout)
    for bt in data.get("backtests", []):
        print("Name:", bt.get("name"))
        print("Completed:", bt.get("completed"))
        print("Progress:", bt.get("progress"))
        print("Error:", bt.get("error"))
