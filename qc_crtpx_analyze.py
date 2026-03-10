"""Analyze CRTPX backtest orders to identify TLH swap activity."""

import json
import time as t
from base64 import b64encode
from hashlib import sha256
from requests import post

BASE = "https://www.quantconnect.com/api/v2"
UID = 470149
TOK = "7f0ee7b98f85c84c644ae02c788a8f0c3d1060f70e9fdcddea4a69af09575a9a"
PID = 28548058
BTID = "e49cbc75675ae36a9e76eac40362eec8"


def hdr():
    ts = str(int(t.time()))
    h = sha256(f"{TOK}:{ts}".encode()).hexdigest()
    a = b64encode(f"{UID}:{h}".encode()).decode()
    return {"Authorization": f"Basic {a}", "Timestamp": ts}


def main():
    all_orders = []
    start = 0
    batch = 100
    while True:
        r = post(
            f"{BASE}/backtests/orders/read",
            headers=hdr(),
            json={
                "projectId": PID,
                "backtestId": BTID,
                "start": start,
                "end": start + batch,
            },
        ).json()
        orders = r.get("orders", [])
        if not orders:
            break
        all_orders.extend(orders)
        if len(orders) < batch:
            break
        start += batch

    print(f"Total orders fetched: {len(all_orders)}")

    equity_subs = {"IVV", "SPLG"}
    cash_subs = {"BIL", "SHV"}

    by_ticker = {}
    tlh_swaps = []

    for o in all_orders:
        sym = o.get("symbol", {})
        ticker = sym.get("Value", sym.get("value", "???"))
        if isinstance(ticker, dict):
            ticker = str(ticker)

        by_ticker.setdefault(ticker, []).append(o)

        if ticker in equity_subs or ticker in cash_subs:
            tlh_swaps.append({
                "ticker": ticker,
                "direction": o.get("Direction", o.get("direction", "")),
                "qty": o.get("Quantity", o.get("quantity", 0)),
                "price": o.get("Price", o.get("price", 0)),
                "time": o.get("Time", o.get("time", "")),
            })

    print("\n=== ORDERS BY TICKER ===")
    for tk in sorted(by_ticker.keys()):
        n = len(by_ticker[tk])
        print(f"  {tk:>6}: {n:>3} orders")

    print(f"\n=== TLH SWAP TRADES (substitute tickers) ===")
    print(f"  Total swap orders: {len(tlh_swaps)}")
    for s in tlh_swaps[:30]:
        dt = str(s["time"])[:10]
        print(f"  {dt}  {s['ticker']:>5}  dir={s['direction']}  qty={s['qty']}  px={s['price']}")
    if len(tlh_swaps) > 30:
        print(f"  ... and {len(tlh_swaps) - 30} more")

    regime_switches = 0
    dates_seen = set()
    for o in all_orders:
        ticker = o.get("symbol", {}).get("Value", "")
        dt = str(o.get("Time", ""))[:10]
        key = (ticker, dt)
        if key not in dates_seen:
            dates_seen.add(key)
        if ticker in ("VOO", "SGOV") and dt not in [s["time"][:10] for s in tlh_swaps]:
            regime_switches += 1

    print(f"\n=== REGIME TRANSITIONS ===")
    voo_orders = by_ticker.get("VOO", [])
    sgov_orders = by_ticker.get("SGOV", [])
    print(f"  VOO orders:  {len(voo_orders)}")
    print(f"  SGOV orders: {len(sgov_orders)}")

    print("\n=== TIMELINE (first 40 orders) ===")
    sorted_orders = sorted(all_orders, key=lambda x: str(x.get("Time", x.get("time", ""))))
    for o in sorted_orders[:40]:
        ticker = o.get("symbol", {}).get("Value", "")
        dt = str(o.get("Time", ""))[:19]
        direction = o.get("Direction", o.get("direction", ""))
        qty = o.get("Quantity", o.get("quantity", 0))
        fill = o.get("Price", o.get("price", 0))
        print(f"  {dt}  {ticker:>5}  {direction}  qty={qty}  fill={fill}")


if __name__ == "__main__":
    main()
