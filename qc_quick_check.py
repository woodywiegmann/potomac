"""Quick API connectivity check and minimal backtest status."""
import time, hashlib, base64, subprocess, json

USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
PROJECT_ID = 28686016
BACKTEST_ID = "2fc8c491334aa4bf29b8067d88bde293"


def call(endpoint, payload, timeout=30):
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    result = subprocess.run(
        ["curl.exe", "--max-time", str(timeout), "--compressed", "-s",
         "-w", "\n%{http_code}|%{time_total}|%{size_download}",
         "-X", "POST", BASE + endpoint,
         "-H", "Authorization: Basic " + a,
         "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().split("\n")
    meta = lines[-1] if lines else ""
    body = "\n".join(lines[:-1]) if len(lines) > 1 else ""
    print(f"  curl code={result.returncode}  meta={meta}")
    if body:
        return json.loads(body)
    return None


print("1. API connectivity (list projects, limit 1)...")
r = call("/projects/read", {"start": 0, "end": 1}, timeout=15)
if r:
    print(f"   success={r.get('success')}")

print("\n2. Project info...")
r = call("/projects/read", {"projectId": PROJECT_ID}, timeout=15)
if r:
    projects = r.get("projects", [])
    if projects:
        p = projects[0]
        print(f"   name={p.get('name')}  created={p.get('created')}")

print("\n3. Backtest status (short timeout)...")
r = call("/backtests/read", {"projectId": PROJECT_ID, "backtestId": BACKTEST_ID}, timeout=15)
if r:
    bt = r.get("backtest", {})
    print(f"   completed={bt.get('completed')}  progress={bt.get('progress')}")
    if bt.get("completed"):
        stats = bt.get("statistics", {})
        print(f"   CAGR: {stats.get('Compounding Annual Return')}")
        print(f"   Drawdown: {stats.get('Drawdown')}")
        print(f"   Sharpe: {stats.get('Sharpe Ratio')}")
        print(f"   Net Profit: {stats.get('Net Profit')}")
        url = f"https://www.quantconnect.com/terminal/{PROJECT_ID}#open/{BACKTEST_ID}"
        print(f"   URL: {url}")
    elif bt.get("error"):
        print(f"   ERROR: {bt.get('error')}")
else:
    print("   No response (timeout or network issue)")
