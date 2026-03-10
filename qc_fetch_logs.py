"""Fetch signal logs from QC backtest and run analytics."""
import json
import time
import hashlib
import base64
import subprocess
import os

PROJECT_ID = 28685329
BACKTEST_ID = "ccead7cfac4527a584e26e0aa667a1dd"
USER_ID = 470149
API_TOKEN = "0d335ae3e7bc1d4cb9a57f3c1b3d6f87419b1aec369bf085dc44bc5043b9b88a"
BASE = "https://www.quantconnect.com/api/v2"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def call_api(endpoint, payload):
    ts = str(int(time.time()))
    h = hashlib.sha256((API_TOKEN + ":" + ts).encode()).hexdigest()
    a = base64.b64encode((str(USER_ID) + ":" + h).encode()).decode()
    body = json.dumps(payload)
    result = subprocess.run(
        ["curl.exe", "--max-time", "60", "-s", "-X", "POST",
         BASE + endpoint,
         "-H", "Authorization: Basic " + a,
         "-H", "Timestamp: " + ts,
         "-H", "Content-Type: application/json",
         "-d", body],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        print("Empty response for", endpoint)
        return {}
    return json.loads(result.stdout)


def main():
    print("Fetching logs from backtest", BACKTEST_ID, "...")

    signal_lines = []

    for start in range(0, 10000, 500):
        end = start + 500
        r = call_api("/backtests/read/log", {
            "projectId": PROJECT_ID,
            "backtestId": BACKTEST_ID,
            "start": start,
            "end": end,
        })
        logs = r.get("logs", r.get("BacktestLogs", []))
        if not logs and start == 0:
            logs = r.get("log", [])
            if isinstance(logs, str):
                logs = logs.split("\n")

        if not logs:
            # also try the full backtest read for logs
            if start == 0:
                print("No logs from /backtests/read/log, trying /backtests/read ...")
                r2 = call_api("/backtests/read", {
                    "projectId": PROJECT_ID,
                    "backtestId": BACKTEST_ID,
                })
                bt = r2.get("backtest", {})
                logs = bt.get("logs", [])
                if isinstance(logs, str):
                    logs = logs.split("\n")
                if not logs:
                    print("No logs found. Keys:", list(r.keys()), list(r2.keys()) if isinstance(r2, dict) else "")
                    print("First response sample:", json.dumps(r, indent=2)[:1000])
            break

        found_any = False
        if isinstance(logs, list):
            for line in logs:
                txt = line if isinstance(line, str) else str(line)
                if "SIGNALS|" in txt:
                    signal_lines.append(txt)
                    found_any = True
        batch_size = len(logs) if isinstance(logs, list) else 0
        print(f"  Batch {start}-{end}: {batch_size} lines, {len(signal_lines)} signal entries so far")

        if batch_size < 100 and start > 0:
            break

    print(f"\nTotal signal entries found: {len(signal_lines)}")

    if signal_lines:
        out_path = os.path.join(SCRIPT_DIR, "qc_4signal_logs.txt")
        with open(out_path, "w") as f:
            for line in signal_lines:
                f.write(line + "\n")
        print(f"Saved to {out_path}")
        analyze(signal_lines)
    else:
        print("No signal log lines found. The algo logs SIGNALS| each month.")
        print("You can view logs directly at:")
        print(f"  https://www.quantconnect.com/terminal/{PROJECT_ID}#open/{BACKTEST_ID}")


def analyze(lines):
    records = []
    for line in lines:
        parts = line.split("SIGNALS|")[-1].strip()
        vals = {}
        for chunk in parts.split("|"):
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                try:
                    vals[k] = float(v)
                except ValueError:
                    pass
        if vals:
            records.append(vals)

    if not records:
        print("No parseable records")
        return

    n = len(records)
    signals = ["sma_cross", "breadth", "rsi5", "wma_iwma"]

    print(f"\n{'='*66}")
    print(f"  SIGNAL ANALYTICS  ({n} monthly observations, Jan 2016 - Feb 2026)")
    print(f"{'='*66}")

    print(f"\n  --- Trigger Frequency ---")
    print(f"  {'Signal':<14} {'Risk-On%':>10} {'Risk-Off%':>10} {'Mean':>8} {'StdDev':>8}")
    print(f"  {'-'*54}")

    for s in signals:
        vals = [r.get(s, 0.5) for r in records]
        mean_v = sum(vals) / len(vals)
        risk_on = sum(1 for v in vals if v > 0.5)
        risk_on_pct = risk_on / len(vals) * 100
        risk_off_pct = 100 - risk_on_pct
        variance = sum((v - mean_v) ** 2 for v in vals) / len(vals)
        std_dev = variance ** 0.5
        print(f"  {s:<14} {risk_on_pct:>9.1f}% {risk_off_pct:>9.1f}% {mean_v:>8.3f} {std_dev:>8.3f}")

    comp_vals = [r.get("composite", 0.5) for r in records]
    comp_mean = sum(comp_vals) / len(comp_vals)
    eq_vals = [r.get("eq_wt", 0.5) for r in records]
    eq_mean = sum(eq_vals) / len(eq_vals)

    print(f"  {'-'*54}")
    print(f"  {'composite':<14} {'':>10} {'':>10} {comp_mean:>8.3f}")
    print(f"  {'equity_wt':<14} {'':>10} {'':>10} {eq_mean:>8.3f}")

    time_invested = sum(1 for v in eq_vals if v >= 0.5) / len(eq_vals) * 100
    print(f"\n  Time invested (equity_wt >= 50%): {time_invested:.1f}%")
    print(f"  Average equity weight: {eq_mean:.1%}")

    print(f"\n  --- Signal Agreement ---")
    all_on = sum(1 for r in records if all(r.get(s, 0.5) > 0.5 for s in signals))
    all_off = sum(1 for r in records if all(r.get(s, 0.5) <= 0.5 for s in signals))
    mixed = n - all_on - all_off
    print(f"  All 4 risk-on:  {all_on:>4} months ({all_on/n*100:.1f}%)")
    print(f"  All 4 risk-off: {all_off:>4} months ({all_off/n*100:.1f}%)")
    print(f"  Mixed signals:  {mixed:>4} months ({mixed/n*100:.1f}%)")

    print(f"\n  --- Signal Correlation Matrix ---")
    print(f"  (how often pairs agree on direction)")
    print(f"  {'':14}", end="")
    for s in signals:
        print(f" {s[:8]:>8}", end="")
    print()
    for s1 in signals:
        v1 = [r.get(s1, 0.5) for r in records]
        print(f"  {s1:<14}", end="")
        for s2 in signals:
            v2 = [r.get(s2, 0.5) for r in records]
            agree = sum(1 for a, b in zip(v1, v2)
                        if (a > 0.5 and b > 0.5) or (a <= 0.5 and b <= 0.5))
            print(f" {agree/n*100:>7.0f}%", end="")
        print()

    # Estimate signal value: for binary signals, compare composite
    # when signal is on vs off
    print(f"\n  --- Signal Discrimination (composite when ON vs OFF) ---")
    print(f"  {'Signal':<14} {'Comp when ON':>14} {'Comp when OFF':>14} {'Delta':>8}")
    print(f"  {'-'*54}")
    for s in signals:
        on_comps = [r["composite"] for r in records if r.get(s, 0.5) > 0.5 and "composite" in r]
        off_comps = [r["composite"] for r in records if r.get(s, 0.5) <= 0.5 and "composite" in r]
        on_mean = sum(on_comps) / len(on_comps) if on_comps else 0
        off_mean = sum(off_comps) / len(off_comps) if off_comps else 0
        delta = on_mean - off_mean
        print(f"  {s:<14} {on_mean:>14.3f} {off_mean:>14.3f} {delta:>8.3f}")


if __name__ == "__main__":
    main()
