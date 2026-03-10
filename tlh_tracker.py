"""
Tax Loss Harvesting (TLH) Tracker
==================================
Tracks positions, unrealized P&L, wash sale windows, and harvest log.
Designed for the low-beta stock basket + international ETF rotation.

Usage:
  python tlh_tracker.py scan       - Scan positions for harvestable losses
  python tlh_tracker.py log        - Show harvest log
  python tlh_tracker.py add TICKER SHARES COST_BASIS  - Add a position
  python tlh_tracker.py harvest TICKER SWAP_TICKER    - Record a harvest
"""

import os
import sys
import json
import csv
from datetime import datetime, timedelta
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSITIONS_FILE = os.path.join(SCRIPT_DIR, "tlh_positions.json")
HARVEST_LOG_FILE = os.path.join(SCRIPT_DIR, "tlh_harvest_log.csv")
WASH_SALE_DAYS = 31
HARVEST_THRESHOLD_PCT = 0.02
HARVEST_THRESHOLD_ABS = 500

TLH_SWAP_PAIRS = {
    "JNJ": ["PG", "ABT"], "PG": ["JNJ", "CL"], "KO": ["PEP", "MDLZ"],
    "PEP": ["KO", "MDLZ"], "WMT": ["COST", "KR"], "COST": ["WMT", "TGT"],
    "DUK": ["SO", "NEE"], "SO": ["DUK", "D"], "NEE": ["AEP", "SRE"],
    "MCD": ["YUM", "SBUX"], "YUM": ["MCD", "CMG"], "HON": ["JCI", "EMR"],
    "JCI": ["HON", "EMR"], "MDLZ": ["HSY", "GIS"], "HSY": ["MDLZ", "HRL"],
    "VZ": ["T", "TMUS"], "T": ["VZ", "TMUS"], "CL": ["PG", "CHD"],
    "ED": ["DUK", "WEC"], "WEC": ["XEL", "CMS"], "XEL": ["WEC", "ED"],
    "GIS": ["CAG", "SJM"], "MRK": ["BMY", "AMGN"], "BMY": ["MRK", "GILD"],
    "LMT": ["GD", "RTX"], "GD": ["LMT", "RTX"], "WM": ["RSG", "WCN"],
    "RSG": ["WM", "WCN"], "CSCO": ["IBM", "JNPR"], "IBM": ["CSCO", "HPE"],
    "TXN": ["ADI", "MCHP"], "ADI": ["TXN", "MCHP"], "ADP": ["PAYX", "CTAS"],
    "PAYX": ["ADP", "CTAS"], "SHW": ["ECL", "APD"], "ECL": ["SHW", "APD"],
    "AMT": ["CCI", "SBAC"], "CCI": ["AMT", "SBAC"], "O": ["NNN", "WPC"],
    "EWJ": ["DXJ", "BBJP"], "EWG": ["HEWG", "DBEF"], "EWQ": ["EWG", "EZU"],
    "EWI": ["EWQ", "EZU"], "EWD": ["NORW", "EWL"], "EWT": ["INDA", "EWY"],
    "EWZ": ["ILF", "FLBR"], "EWY": ["EWT", "FXI"], "EWW": ["ILF", "ECH"],
    "FXI": ["KWEB", "MCHI"], "INDA": ["EPI", "SMIN"],
    "RING": ["GDX", "GDXJ"], "SIL": ["SLV", "SILJ"],
    "COPX": ["PICK", "XME"], "PICK": ["COPX", "GNR"],
    "URA": ["NLR", "URNM"], "REMX": ["LIT", "PICK"],
}


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def load_harvest_log():
    if not os.path.exists(HARVEST_LOG_FILE):
        return []
    rows = []
    with open(HARVEST_LOG_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def save_harvest_entry(entry):
    exists = os.path.exists(HARVEST_LOG_FILE)
    with open(HARVEST_LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "date", "ticker", "shares", "cost_basis", "sale_price",
            "loss_amount", "swap_ticker", "wash_sale_end", "status"
        ])
        if not exists:
            writer.writeheader()
        writer.writerow(entry)


def get_wash_sale_restricted():
    """Return set of tickers currently in wash sale window."""
    log = load_harvest_log()
    today = datetime.now().date()
    restricted = set()
    for row in log:
        try:
            end_date = datetime.strptime(row["wash_sale_end"], "%Y-%m-%d").date()
            if today <= end_date:
                restricted.add(row["ticker"])
        except (ValueError, KeyError):
            pass
    return restricted


def scan_positions():
    """Scan all positions for harvestable losses."""
    positions = load_positions()
    if not positions:
        print("  No positions tracked. Use 'add' command first.")
        return

    tickers = list(positions.keys())
    restricted = get_wash_sale_restricted()

    print(f"\n  Fetching current prices for {len(tickers)} positions...")
    prices = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            h = tk.history(period="1d")
            if not h.empty:
                prices[t] = h["Close"].iloc[-1]
        except Exception:
            pass

    print(f"\n  {'='*80}")
    print(f"  TLH SCAN ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"  {'='*80}")
    print(f"  {'Ticker':<8} {'Shares':>7} {'Basis':>9} {'Price':>9} {'P&L':>10} {'P&L%':>7} {'Action':<20} {'Swap'}")
    print(f"  {'-'*90}")

    harvestable_total = 0
    for t, pos in sorted(positions.items()):
        shares = pos["shares"]
        basis = pos["cost_basis"]
        price = prices.get(t, basis)
        total_basis = shares * basis
        total_value = shares * price
        pnl = total_value - total_basis
        pnl_pct = (price / basis - 1) * 100 if basis > 0 else 0

        is_loss = pnl < 0
        exceeds_threshold = (abs(pnl_pct) > HARVEST_THRESHOLD_PCT * 100) or (abs(pnl) > HARVEST_THRESHOLD_ABS)
        in_wash = t in restricted

        if is_loss and exceeds_threshold and not in_wash:
            action = "*** HARVEST ***"
            swaps = TLH_SWAP_PAIRS.get(t, ["(sector ETF)"])
            swap_str = " / ".join(swaps[:2])
            harvestable_total += pnl
        elif is_loss and exceeds_threshold and in_wash:
            action = "WASH SALE BLOCK"
            swap_str = ""
        elif is_loss:
            action = "below threshold"
            swap_str = ""
        else:
            action = "gain (hold)"
            swap_str = ""

        print(f"  {t:<8} {shares:>7} ${basis:>8.2f} ${price:>8.2f} ${pnl:>9.2f} {pnl_pct:>6.1f}% {action:<20} {swap_str}")

    print(f"  {'-'*90}")
    if harvestable_total < 0:
        tax_savings = abs(harvestable_total) * 0.30
        print(f"  Total harvestable losses: ${harvestable_total:,.2f}")
        print(f"  Estimated tax savings (30% rate): ${tax_savings:,.2f}")
    else:
        print(f"  No harvestable losses at this time.")

    print(f"\n  Wash sale restricted: {restricted if restricted else 'none'}")


def add_position(ticker, shares, cost_basis):
    positions = load_positions()
    positions[ticker.upper()] = {
        "shares": int(shares),
        "cost_basis": float(cost_basis),
        "date_added": datetime.now().strftime("%Y-%m-%d"),
    }
    save_positions(positions)
    print(f"  Added: {ticker.upper()} {shares} shares @ ${cost_basis:.2f}")


def record_harvest(ticker, swap_ticker):
    positions = load_positions()
    ticker = ticker.upper()
    swap_ticker = swap_ticker.upper()

    if ticker not in positions:
        print(f"  {ticker} not in tracked positions")
        return

    pos = positions[ticker]
    try:
        tk = yf.Ticker(ticker)
        price = tk.history(period="1d")["Close"].iloc[-1]
    except Exception:
        print("  Could not fetch current price")
        return

    loss = (price - pos["cost_basis"]) * pos["shares"]
    if loss >= 0:
        print(f"  {ticker} is not at a loss (P&L: ${loss:,.2f}). No harvest needed.")
        return

    wash_end = (datetime.now() + timedelta(days=WASH_SALE_DAYS)).strftime("%Y-%m-%d")

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ticker": ticker,
        "shares": pos["shares"],
        "cost_basis": pos["cost_basis"],
        "sale_price": round(price, 2),
        "loss_amount": round(loss, 2),
        "swap_ticker": swap_ticker,
        "wash_sale_end": wash_end,
        "status": "harvested",
    }
    save_harvest_entry(entry)

    # Replace position with swap at current price
    try:
        stk = yf.Ticker(swap_ticker)
        swap_price = stk.history(period="1d")["Close"].iloc[-1]
    except Exception:
        swap_price = price

    del positions[ticker]
    positions[swap_ticker] = {
        "shares": pos["shares"],
        "cost_basis": round(swap_price, 2),
        "date_added": datetime.now().strftime("%Y-%m-%d"),
    }
    save_positions(positions)

    tax_savings = abs(loss) * 0.30
    print(f"\n  HARVEST RECORDED:")
    print(f"    Sold: {ticker} {pos['shares']} shares @ ${price:.2f}")
    print(f"    Loss harvested: ${loss:,.2f}")
    print(f"    Est. tax savings (30%): ${tax_savings:,.2f}")
    print(f"    Swap: Bought {swap_ticker} {pos['shares']} shares @ ${swap_price:.2f}")
    print(f"    Wash sale window: do NOT buy {ticker} until {wash_end}")


def show_log():
    log = load_harvest_log()
    if not log:
        print("  No harvests recorded yet.")
        return

    print(f"\n  {'='*80}")
    print(f"  TAX LOSS HARVEST LOG")
    print(f"  {'='*80}")
    print(f"  {'Date':<12} {'Sold':<8} {'Shares':>7} {'Loss':>10} {'Swap':<8} {'Wash Ends':<12} {'Status'}")
    print(f"  {'-'*70}")

    total_harvested = 0
    for row in log:
        loss = float(row.get("loss_amount", 0))
        total_harvested += loss
        print(f"  {row['date']:<12} {row['ticker']:<8} {row['shares']:>7} "
              f"${loss:>9.2f} {row['swap_ticker']:<8} {row['wash_sale_end']:<12} {row['status']}")

    print(f"  {'-'*70}")
    print(f"  Total losses harvested: ${total_harvested:,.2f}")
    print(f"  Estimated cumulative tax savings: ${abs(total_harvested)*0.30:,.2f}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("  Current positions file:", POSITIONS_FILE)
        print("  Harvest log file:", HARVEST_LOG_FILE)
        return

    cmd = sys.argv[1].lower()

    if cmd == "scan":
        scan_positions()
    elif cmd == "log":
        show_log()
    elif cmd == "add" and len(sys.argv) >= 5:
        add_position(sys.argv[2], int(sys.argv[3]), float(sys.argv[4]))
    elif cmd == "harvest" and len(sys.argv) >= 4:
        record_harvest(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
