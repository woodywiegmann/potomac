"""Quick check of backtest status using curl to avoid requests hanging."""
import time, hashlib, base64, subprocess, json, sys

PROJECT_ID = 28686016
BACKTEST_ID = "2fc8c491334aa4bf29b8067d88bde293"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"


def call_api(endpoint, payload):
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    body = json.dumps(payload)
    result = subprocess.run(
        ["curl.exe", "--max-time", "120", "--compressed", "-s", "-X", "POST",
         BASE + endpoint,
         "-H", "Authorization: Basic " + a,
         "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", body],
        capture_output=True, text=True
    )
    print("curl returncode:", result.returncode)
    print("curl stdout[:500]:", result.stdout[:500])
    print("curl stderr[:500]:", result.stderr[:500])
    if not result.stdout.strip():
        print("Empty response from curl")
        return None
    return json.loads(result.stdout)


def main():
    print("Checking backtest", BACKTEST_ID, "...")
    r = call_api("/backtests/read", {
        "projectId": PROJECT_ID,
        "backtestId": BACKTEST_ID
    })
    if r is None:
        print("API call failed")
        return

    print("success:", r.get("success"))
    bt = r.get("backtest", {})
    print("completed:", bt.get("completed"))
    print("progress:", bt.get("progress"))

    if bt.get("completed"):
        stats = bt.get("statistics", {})
        print("\n--- RESULTS ---")
        for k, v in stats.items():
            print("  " + k + ": " + str(v))
        rt = bt.get("runtimeStatistics", {})
        if rt:
            print("\n--- RUNTIME ---")
            for k, v in rt.items():
                print("  " + k + ": " + str(v))
        url = "https://www.quantconnect.com/terminal/" + str(PROJECT_ID) + "#open/" + BACKTEST_ID
        print("\nURL:", url)
    else:
        print("Backtest still running. Try again later.")
        err = bt.get("error", "")
        if err:
            print("Error:", err)
        stack = bt.get("stacktrace", "")
        if stack:
            print("Stack:", stack[:500])


if __name__ == "__main__":
    main()
