"""Analyze CRTPX backtest orders -- improved date/ticker extraction."""

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

    print(f"Total orders: {len(all_orders)}")

    if all_orders:
        print("\nSample order keys:", list(all_orders[0].keys()))
        print("Sample order:", json.dumps(all_orders[0], indent=2, default=str)[:800])

    by_ticker = {}
    for o in all_orders:
        sym = o.get("symbol", o.get("Symbol", {}))
        if isinstance(sym, str):
            ticker = sym
        elif isinstance(sym, dict):
            ticker = sym.get("Value", sym.get("value", sym.get("Ticker", "???")))
        else:
            ticker = str(sym)

        dt = o.get("time", o.get("Time", o.get("CreatedTime", "???")))
        direction = o.get("direction", o.get("Direction", ""))
        qty = o.get("quantity", o.get("Quantity", 0))
        price = o.get("price", o.get("Price", 0))

        by_ticker.setdefault(ticker, []).append({
            "date": str(dt)[:10],
            "dir": direction,
            "qty": qty,
            "price": price,
        })

    print("\n=== ORDERS BY TICKER ===")
    for tk in sorted(by_ticker.keys()):
        orders = by_ticker[tk]
        buys = sum(1 for o in orders if o["dir"] in (0, "Buy"))
        sells = sum(1 for o in orders if o["dir"] in (1, "Sell"))
        print(f"  {tk:>6}: {len(orders):>3} total  ({buys} buys, {sells} sells)")

    print("\n=== FULL TRADE LOG (chronological) ===")
    all_flat = []
    for tk, orders in by_ticker.items():
        for o in orders:
            all_flat.append((o["date"], tk, o["dir"], o["qty"], o["price"]))
    all_flat.sort(key=lambda x: x[0])

    prev_date = ""
    for date, tk, d, qty, px in all_flat:
        dir_str = "BUY " if d in (0, "Buy") else "SELL"
        if date != prev_date:
            print(f"\n  {date}")
            prev_date = date
        print(f"    {dir_str}  {tk:>5}  qty={abs(qty):>8.0f}  px=${px:>10.2f}")

    equity_subs = {"IVV", "SPLG"}
    cash_subs = {"BIL", "SHV"}

    eq_swaps = sum(len(by_ticker.get(t, [])) for t in equity_subs)
    cash_swps = sum(len(by_ticker.get(t, [])) for t in cash_subs)
    print(f"\n=== TLH SUMMARY ===")
    print(f"  Equity substitute orders (IVV/SPLG): {eq_swaps}")
    print(f"  Cash substitute orders (BIL/SHV):    {cash_swps}")
    print(f"  Total substitute orders:             {eq_swaps + cash_swps}")
    print(f"  TLH swap events (pairs):             {(eq_swaps + cash_swps) // 2}")

    voo_n = len(by_ticker.get("VOO", []))
    sgov_n = len(by_ticker.get("SGOV", []))
    spym_n = len(by_ticker.get("SPYM", []))
    print(f"\n  VOO orders:  {voo_n}")
    print(f"  SGOV orders: {sgov_n}")
    print(f"  SPYM orders: {spym_n} (likely SPY benchmark mapping)")

    total_orders = len(all_flat)
    years = 6.67
    switches = (voo_n + sgov_n) // 2
    print(f"\n  Est. regime switches: ~{switches}")
    print(f"  Switches/year:        ~{switches/years:.1f}")


if __name__ == "__main__":
    main()
