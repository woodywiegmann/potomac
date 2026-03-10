"""
Fee Analyzer & Swap Recommendation Engine
==========================================
Reads your current holdings and ETFdb screener exports to:
1. Rank your holdings by total fee drag (expense ratio * AUM allocated)
2. Find cheaper ETF alternatives in the same category
3. Calculate exact dollar savings from each swap
4. Generate a prioritized swap recommendation report

Usage:
    python fee_analyzer.py

Input files (place in same folder):
    - our_holdings.csv: Your current book of ETF/fund positions
    - etfdb_*.csv: ETFdb screener exports by category (optional, for swap suggestions)

If you don't have ETFdb exports yet, the script still runs the fee drag
analysis on your holdings alone.
"""

import csv
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Holding:
    ticker: str
    name: str
    total_value: float
    num_accounts: int
    expense_ratio_bps: float
    category: str = ""

    @property
    def expense_ratio_pct(self) -> float:
        return self.expense_ratio_bps / 100.0

    @property
    def annual_fee_drag(self) -> float:
        return self.total_value * (self.expense_ratio_bps / 10000.0)


@dataclass
class ETFCandidate:
    ticker: str
    name: str
    expense_ratio_bps: float
    aum: float
    avg_volume: float
    num_holdings: int
    category: str = ""


@dataclass
class SwapRecommendation:
    current: Holding
    replacement: ETFCandidate
    fee_savings_bps: float
    annual_dollar_savings: float
    notes: str = ""


# ── Category mapping: maps common ETF tickers to broad categories ──
# Extend this as needed for your specific holdings
TICKER_CATEGORY_MAP = {
    # US Large Cap
    "VOO": "US Large Cap", "SPY": "US Large Cap", "IVV": "US Large Cap",
    "SPLG": "US Large Cap", "VTI": "US Total Market", "ITOT": "US Total Market",
    "SCHB": "US Total Market", "SPTM": "US Total Market",
    "VV": "US Large Cap", "SCHX": "US Large Cap", "IWB": "US Large Cap",
    "MGC": "US Mega Cap", "OEF": "US Large Cap",
    # US Large Cap Growth
    "QQQ": "US Large Cap Growth", "QQQM": "US Large Cap Growth",
    "VUG": "US Large Cap Growth", "IWF": "US Large Cap Growth",
    "SCHG": "US Large Cap Growth", "SPYG": "US Large Cap Growth",
    "MGK": "US Large Cap Growth", "VONG": "US Large Cap Growth",
    # US Large Cap Value
    "VTV": "US Large Cap Value", "IWD": "US Large Cap Value",
    "SCHV": "US Large Cap Value", "SPYV": "US Large Cap Value",
    "VONV": "US Large Cap Value",
    # US Mid Cap
    "VO": "US Mid Cap", "IJH": "US Mid Cap", "MDY": "US Mid Cap",
    "SCHM": "US Mid Cap", "SPMD": "US Mid Cap",
    # US Small Cap
    "VB": "US Small Cap", "IJR": "US Small Cap", "IWM": "US Small Cap",
    "SCHA": "US Small Cap", "SPSM": "US Small Cap",
    # US Small/Mid Growth/Innovation
    "QQQJ": "US SMID Growth", "ARKK": "US Thematic/Innovation",
    "ARKW": "US Thematic/Innovation", "ARKG": "US Thematic/Innovation",
    "ARKF": "US Thematic/Innovation", "ARKQ": "US Thematic/Innovation",
    # International Developed
    "VEA": "Intl Developed", "IEFA": "Intl Developed", "EFA": "Intl Developed",
    "SPDW": "Intl Developed", "SCHF": "Intl Developed",
    "IXUS": "Intl Total ex-US", "VXUS": "Intl Total ex-US",
    "VEU": "Intl Total ex-US",
    # Emerging Markets
    "VWO": "Emerging Markets", "IEMG": "Emerging Markets", "EEM": "Emerging Markets",
    "SPEM": "Emerging Markets", "SCHE": "Emerging Markets",
    # US Aggregate Bond
    "AGG": "US Agg Bond", "BND": "US Agg Bond", "SCHZ": "US Agg Bond",
    "SPAB": "US Agg Bond",
    # US Treasury
    "SHV": "US Short Treasury", "SHY": "US Short-Term Bond",
    "IEF": "US Intermediate Treasury", "TLT": "US Long Treasury",
    "GOVT": "US Treasury", "SGOV": "US Ultra-Short Treasury",
    "BIL": "US T-Bill",
    # US Corporate Bond
    "LQD": "US IG Corporate", "VCIT": "US IG Corporate",
    "HYG": "US High Yield", "JNK": "US High Yield",
    "VCSH": "US Short Corp Bond", "IGSB": "US Short Corp Bond",
    # US TIPS
    "TIP": "US TIPS", "SCHP": "US TIPS", "VTIP": "US Short TIPS",
    # US Municipal
    "MUB": "US Muni", "VTEB": "US Muni", "TFI": "US Muni",
    # International Bond
    "BNDX": "Intl Bond", "IAGG": "Intl Bond",
    # Sector
    "VGT": "US Tech", "XLK": "US Tech", "FTEC": "US Tech",
    "VHT": "US Healthcare", "XLV": "US Healthcare",
    "VFH": "US Financials", "XLF": "US Financials",
    "VDE": "US Energy", "XLE": "US Energy",
    "VNQ": "US Real Estate", "IYR": "US Real Estate", "SCHH": "US Real Estate",
    "VPU": "US Utilities", "XLU": "US Utilities",
    "GLD": "Gold", "IAU": "Gold", "GLDM": "Gold",
    "SLV": "Silver",
    # Dividend
    "VYM": "US Dividend", "SCHD": "US Dividend", "DVY": "US Dividend",
    "HDV": "US Dividend", "DGRO": "US Dividend Growth",
    "VIG": "US Dividend Growth", "DGRW": "US Dividend Growth",
}

# Cheapest known ETFs per category (for fallback when no ETFdb export available)
CHEAPEST_BY_CATEGORY = {
    "US Large Cap": ("VOO", 3), "US Total Market": ("VTI", 3),
    "US Large Cap Growth": ("SCHG", 4), "US Large Cap Value": ("SCHV", 4),
    "US Mid Cap": ("SPMD", 3), "US Small Cap": ("SPSM", 3),
    "US SMID Growth": ("QQQJ", 15),
    "US Thematic/Innovation": ("QQQJ", 15),
    "Intl Developed": ("SPDW", 4), "Intl Total ex-US": ("IXUS", 7),
    "Emerging Markets": ("SPEM", 7),
    "US Agg Bond": ("SPAB", 3), "US IG Corporate": ("VCIT", 4),
    "US High Yield": ("USHY", 15), "US Treasury": ("GOVT", 5),
    "US Short-Term Bond": ("VGSH", 4), "US Short Treasury": ("SHV", 15),
    "US Long Treasury": ("TLT", 15), "US Intermediate Treasury": ("IEF", 15),
    "US Ultra-Short Treasury": ("SGOV", 9), "US T-Bill": ("BIL", 14),
    "US TIPS": ("SCHP", 5), "US Short TIPS": ("VTIP", 4),
    "US Muni": ("VTEB", 5), "Intl Bond": ("BNDX", 7),
    "US Tech": ("FTEC", 8), "US Healthcare": ("VHT", 10),
    "US Financials": ("VFH", 10), "US Energy": ("VDE", 10),
    "US Real Estate": ("SCHH", 7), "US Utilities": ("VPU", 10),
    "Gold": ("GLDM", 10), "US Dividend": ("SCHD", 6),
    "US Dividend Growth": ("VIG", 6),
    "US Mega Cap": ("MGC", 7),
}

# TLH swap pairs — funds that are similar enough to swap for tax-loss
# harvesting but NOT substantially identical
TLH_SWAP_PAIRS = {
    "VOO": ["IVV", "SPLG"], "IVV": ["VOO", "SPLG"], "SPLG": ["VOO", "IVV"],
    "SPY": ["IVV", "VOO", "SPLG"],
    "VTI": ["ITOT", "SCHB", "SPTM"], "ITOT": ["VTI", "SCHB"],
    "QQQ": ["QQQM"], "QQQM": ["QQQ"],
    "VEA": ["IEFA", "SPDW", "SCHF"], "IEFA": ["VEA", "SPDW"],
    "VWO": ["IEMG", "SPEM", "SCHE"], "IEMG": ["VWO", "SPEM"],
    "AGG": ["BND", "SCHZ", "SPAB"], "BND": ["AGG", "SCHZ"],
    "VUG": ["IWF", "SCHG", "SPYG"], "IWF": ["VUG", "SCHG"],
    "VTV": ["IWD", "SCHV", "SPYV"], "IWD": ["VTV", "SCHV"],
    "VO": ["IJH", "SPMD", "SCHM"], "IJH": ["VO", "SPMD"],
    "VB": ["IJR", "SPSM", "SCHA"], "IJR": ["VB", "SPSM"],
    "IWM": ["VB", "SPSM", "SCHA"],
    "LQD": ["VCIT", "IGIB"], "VCIT": ["LQD", "IGIB"],
    "HYG": ["JNK", "USHY"], "JNK": ["HYG", "USHY"],
    "VNQ": ["IYR", "SCHH"], "IYR": ["VNQ", "SCHH"],
    "GLD": ["IAU", "GLDM"], "IAU": ["GLD", "GLDM"],
    "VYM": ["SCHD", "HDV"], "SCHD": ["VYM", "HDV"],
    "VIG": ["DGRO", "DGRW"], "DGRO": ["VIG", "DGRW"],
    "TLT": ["VGLT", "SPTL"], "SHY": ["VGSH", "SPTS"],
    "TIP": ["SCHP", "GTIP"], "SCHP": ["TIP", "GTIP"],
    "MUB": ["VTEB", "TFI"], "VTEB": ["MUB", "TFI"],
    "BNDX": ["IAGG"], "IAGG": ["BNDX"],
    "VGT": ["FTEC", "XLK"], "XLK": ["VGT", "FTEC"],
    "ARKK": ["QQQJ"],
}


def load_holdings(filepath: str) -> list[Holding]:
    """Load our_holdings.csv into Holding objects."""
    holdings = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip().upper()
            if not ticker:
                continue
            h = Holding(
                ticker=ticker,
                name=row.get("name", "").strip(),
                total_value=float(row.get("total_value_across_accounts", 0)),
                num_accounts=int(row.get("num_accounts_held_in", 0)),
                expense_ratio_bps=float(row.get("expense_ratio_bps", 0)),
                category=TICKER_CATEGORY_MAP.get(ticker, row.get("category", "Unknown")),
            )
            holdings.append(h)
    return holdings


def load_etfdb_candidates(folder: str) -> dict[str, list[ETFCandidate]]:
    """Load all etfdb_*.csv files and return candidates grouped by filename-derived category."""
    candidates: dict[str, list[ETFCandidate]] = {}
    for filename in os.listdir(folder):
        if not filename.startswith("etfdb_") or not filename.endswith(".csv"):
            continue
        category = filename.replace("etfdb_", "").replace(".csv", "").replace("_", " ").title()
        filepath = os.path.join(folder, filename)
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = ""
                for key in ["Ticker", "Symbol", "ticker", "symbol"]:
                    if key in row:
                        ticker = row[key].strip().upper()
                        break
                if not ticker:
                    continue

                er_raw = row.get("Expense Ratio", row.get("expense_ratio", "0"))
                er_str = str(er_raw).replace("%", "").strip()
                try:
                    er_pct = float(er_str)
                except ValueError:
                    er_pct = 0.0
                er_bps = er_pct * 100 if er_pct < 1 else er_pct

                aum_raw = row.get("AUM", row.get("Total Assets", "0"))
                aum_str = str(aum_raw).replace("$", "").replace(",", "").replace("B", "e9").replace("M", "e6").strip()
                try:
                    aum = float(aum_str)
                except ValueError:
                    aum = 0.0

                vol_raw = row.get("Avg Volume", row.get("Average Volume", "0"))
                vol_str = str(vol_raw).replace(",", "").strip()
                try:
                    vol = float(vol_str)
                except ValueError:
                    vol = 0.0

                holdings_raw = row.get("# Holdings", row.get("Number of Holdings", "0"))
                try:
                    n_holdings = int(str(holdings_raw).replace(",", "").strip())
                except ValueError:
                    n_holdings = 0

                name = row.get("Name", row.get("Fund Name", row.get("name", "")))
                c = ETFCandidate(
                    ticker=ticker, name=name, expense_ratio_bps=er_bps,
                    aum=aum, avg_volume=vol, num_holdings=n_holdings, category=category,
                )
                candidates.setdefault(category, []).append(c)
    return candidates


def find_swap_recommendations(holdings: list[Holding], candidates: dict[str, list[ETFCandidate]]) -> list[SwapRecommendation]:
    """For each holding, find cheaper alternatives either from ETFdb data or built-in knowledge."""
    recommendations = []

    for h in holdings:
        best_replacement = None
        best_savings_bps = 0
        notes = ""

        # Check built-in cheapest-by-category first
        if h.category in CHEAPEST_BY_CATEGORY:
            cheap_ticker, cheap_er = CHEAPEST_BY_CATEGORY[h.category]
            if cheap_ticker != h.ticker and cheap_er < h.expense_ratio_bps:
                savings = h.expense_ratio_bps - cheap_er
                if savings > best_savings_bps:
                    best_savings_bps = savings
                    best_replacement = ETFCandidate(
                        ticker=cheap_ticker, name=f"(built-in) cheapest in {h.category}",
                        expense_ratio_bps=cheap_er, aum=0, avg_volume=0, num_holdings=0,
                        category=h.category,
                    )
                    notes = "From built-in category data"

        # Check ETFdb exports for even better options
        for cat_name, cat_candidates in candidates.items():
            for c in cat_candidates:
                if c.ticker == h.ticker:
                    continue
                if c.aum < 100_000_000:  # skip tiny funds
                    continue
                savings = h.expense_ratio_bps - c.expense_ratio_bps
                if savings > best_savings_bps:
                    best_savings_bps = savings
                    best_replacement = c
                    notes = f"From ETFdb export: {cat_name}"

        if best_replacement and best_savings_bps >= 2:
            rec = SwapRecommendation(
                current=h,
                replacement=best_replacement,
                fee_savings_bps=best_savings_bps,
                annual_dollar_savings=h.total_value * (best_savings_bps / 10000.0),
                notes=notes,
            )
            recommendations.append(rec)

    recommendations.sort(key=lambda r: r.annual_dollar_savings, reverse=True)
    return recommendations


def generate_report(holdings: list[Holding], recommendations: list[SwapRecommendation]):
    """Print a formatted report to console and write to CSV."""
    total_aum = sum(h.total_value for h in holdings)
    total_fee_drag = sum(h.annual_fee_drag for h in holdings)
    blended_er_bps = (total_fee_drag / total_aum * 10000) if total_aum > 0 else 0

    print("=" * 80)
    print("FEE ANALYSIS REPORT")
    print("=" * 80)
    print(f"\nTotal AUM Analyzed:       ${total_aum:>15,.0f}")
    print(f"Total Annual Fee Drag:    ${total_fee_drag:>15,.0f}")
    print(f"Blended Expense Ratio:    {blended_er_bps:>14.1f} bps")
    print(f"Number of Holdings:       {len(holdings):>15d}")

    # Top fee drags
    print("\n" + "-" * 80)
    print("TOP 15 FEE DRAGS (sorted by annual dollar cost)")
    print("-" * 80)
    print(f"{'Ticker':<8} {'ER(bps)':>8} {'AUM Allocated':>16} {'Annual Fee':>14} {'Category':<25}")
    print("-" * 80)
    sorted_holdings = sorted(holdings, key=lambda h: h.annual_fee_drag, reverse=True)
    for h in sorted_holdings[:15]:
        print(f"{h.ticker:<8} {h.expense_ratio_bps:>7.0f}  ${h.total_value:>14,.0f} ${h.annual_fee_drag:>12,.0f}  {h.category:<25}")

    # Swap recommendations
    if recommendations:
        total_potential_savings = sum(r.annual_dollar_savings for r in recommendations)
        print("\n" + "=" * 80)
        print(f"SWAP RECOMMENDATIONS  (Total potential savings: ${total_potential_savings:,.0f}/year)")
        print("=" * 80)
        print(f"{'#':<4} {'Current':<8} {'ER':>5} {'→':^3} {'Replace':<8} {'ER':>5} {'Save(bps)':>9} {'Annual $Save':>13} {'Category':<20}")
        print("-" * 80)
        for i, r in enumerate(recommendations, 1):
            print(
                f"{i:<4} {r.current.ticker:<8} {r.current.expense_ratio_bps:>4.0f}  {'→':^3} "
                f"{r.replacement.ticker:<8} {r.replacement.expense_ratio_bps:>4.0f}  "
                f"{r.fee_savings_bps:>8.0f}  ${r.annual_dollar_savings:>11,.0f}  {r.current.category:<20}"
            )

        new_fee_drag = total_fee_drag - total_potential_savings
        new_blended = (new_fee_drag / total_aum * 10000) if total_aum > 0 else 0
        print(f"\n  Current blended ER:  {blended_er_bps:.1f} bps  (${total_fee_drag:,.0f}/yr)")
        print(f"  Post-swap blended ER: {new_blended:.1f} bps  (${new_fee_drag:,.0f}/yr)")
        print(f"  Improvement:          {blended_er_bps - new_blended:.1f} bps  (${total_potential_savings:,.0f}/yr saved)")
    else:
        print("\nNo swap recommendations — your holdings are already optimally cheap.")

    # TLH pairs
    print("\n" + "=" * 80)
    print("TAX-LOSS HARVESTING SWAP PAIRS FOR YOUR HOLDINGS")
    print("=" * 80)
    for h in holdings:
        if h.ticker in TLH_SWAP_PAIRS:
            pairs = ", ".join(TLH_SWAP_PAIRS[h.ticker])
            print(f"  {h.ticker:<8} ↔  {pairs}")

    # Write CSV report
    report_path = os.path.join(os.path.dirname(__file__) or ".", "fee_report.csv")
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Section", "Current Ticker", "Current ER (bps)", "AUM Allocated",
                         "Annual Fee Drag", "Replacement Ticker", "Replacement ER (bps)",
                         "Savings (bps)", "Annual $ Savings", "Category", "TLH Pairs"])
        for h in sorted_holdings:
            tlh = ", ".join(TLH_SWAP_PAIRS.get(h.ticker, []))
            writer.writerow(["Holding", h.ticker, h.expense_ratio_bps, h.total_value,
                             f"{h.annual_fee_drag:.0f}", "", "", "", "", h.category, tlh])
        for r in recommendations:
            writer.writerow(["Swap", r.current.ticker, r.current.expense_ratio_bps,
                             r.current.total_value, f"{r.current.annual_fee_drag:.0f}",
                             r.replacement.ticker, r.replacement.expense_ratio_bps,
                             r.fee_savings_bps, f"{r.annual_dollar_savings:.0f}",
                             r.current.category, ""])
        writer.writerow([])
        writer.writerow(["Summary", "Total AUM", total_aum, "Total Fee Drag", f"{total_fee_drag:.0f}",
                         "Blended ER (bps)", f"{blended_er_bps:.1f}", "", "", "", ""])

    print(f"\nCSV report saved to: {report_path}")


def create_sample_holdings():
    """Generate a sample our_holdings.csv so you can see the format."""
    sample_path = os.path.join(os.path.dirname(__file__) or ".", "our_holdings_SAMPLE.csv")
    with open(sample_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "name", "total_value_across_accounts", "num_accounts_held_in", "expense_ratio_bps"])
        sample_data = [
            ("VOO", "Vanguard S&P 500 ETF", 25000000, 200, 3),
            ("ARKK", "ARK Innovation ETF", 3000000, 45, 75),
            ("AGG", "iShares Core US Aggregate Bond", 12000000, 150, 3),
            ("QQQ", "Invesco QQQ Trust", 8000000, 100, 20),
            ("EFA", "iShares MSCI EAFE", 5000000, 80, 32),
            ("VWO", "Vanguard FTSE Emerging Markets", 3000000, 60, 8),
            ("LQD", "iShares iBoxx IG Corporate Bond", 4000000, 70, 14),
            ("IWM", "iShares Russell 2000", 2500000, 50, 19),
            ("VNQ", "Vanguard Real Estate ETF", 1500000, 30, 12),
            ("GLD", "SPDR Gold Shares", 2000000, 40, 40),
            ("HYG", "iShares iBoxx High Yield Corp Bond", 1800000, 35, 49),
            ("TLT", "iShares 20+ Year Treasury Bond", 3000000, 55, 15),
            ("SCHD", "Schwab US Dividend Equity", 4000000, 65, 6),
            ("VGT", "Vanguard Information Technology", 2000000, 30, 10),
            ("VTEB", "Vanguard Tax-Exempt Bond", 3500000, 45, 5),
        ]
        for row in sample_data:
            writer.writerow(row)
    print(f"Sample holdings file created: {sample_path}")
    print("Edit this with your actual data, rename to our_holdings.csv, then re-run.")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    holdings_path = os.path.join(script_dir, "our_holdings.csv")

    if not os.path.exists(holdings_path):
        print("our_holdings.csv not found. Creating a sample file...\n")
        create_sample_holdings()
        print("\nRe-running with SAMPLE data to show you the output format:\n")
        holdings_path = os.path.join(script_dir, "our_holdings_SAMPLE.csv")

    holdings = load_holdings(holdings_path)
    if not holdings:
        print("ERROR: No holdings loaded. Check your CSV format.")
        sys.exit(1)

    candidates = load_etfdb_candidates(script_dir)
    if candidates:
        total_etfs = sum(len(v) for v in candidates.values())
        print(f"Loaded {total_etfs} ETF candidates from {len(candidates)} ETFdb export(s).\n")
    else:
        print("No etfdb_*.csv files found. Using built-in category data for swap suggestions.\n")

    recommendations = find_swap_recommendations(holdings, candidates)
    generate_report(holdings, recommendations)


if __name__ == "__main__":
    main()
