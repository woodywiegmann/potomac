"""
Portfolio Overlap Analyzer
==========================
Analyzes holdings overlap across ETFs in your model portfolios.
Uses ETFdb holdings data (if available) or known top-holdings data
to detect when multiple ETFs in the same portfolio are buying
the same underlying stocks.

Usage:
    python overlap_analyzer.py

Input:
    - our_holdings.csv OR model_portfolios.csv
    - (Optional) ETFdb holdings exports per ETF

Even without ETFdb holdings exports, this script uses a built-in database
of top holdings for ~60 common ETFs to detect overlap.
"""

import csv
import os
import sys
from collections import defaultdict


# ── Built-in top-10 holdings with approximate weights (%) ──
# These are approximate and should be validated against current data.
# The key insight: if the same stock appears in multiple ETFs in your
# portfolio, you have concentration risk you may not intend.

TOP_HOLDINGS = {
    "VOO": [("AAPL", 7.0), ("MSFT", 6.8), ("NVDA", 6.2), ("AMZN", 3.8), ("META", 2.6),
            ("GOOGL", 2.1), ("GOOG", 1.8), ("BRK.B", 1.7), ("LLY", 1.5), ("AVGO", 1.5)],
    "SPY": [("AAPL", 7.0), ("MSFT", 6.8), ("NVDA", 6.2), ("AMZN", 3.8), ("META", 2.6),
            ("GOOGL", 2.1), ("GOOG", 1.8), ("BRK.B", 1.7), ("LLY", 1.5), ("AVGO", 1.5)],
    "IVV": [("AAPL", 7.0), ("MSFT", 6.8), ("NVDA", 6.2), ("AMZN", 3.8), ("META", 2.6),
            ("GOOGL", 2.1), ("GOOG", 1.8), ("BRK.B", 1.7), ("LLY", 1.5), ("AVGO", 1.5)],
    "QQQ": [("AAPL", 8.9), ("MSFT", 8.1), ("NVDA", 7.5), ("AMZN", 5.3), ("META", 4.8),
            ("AVGO", 4.5), ("GOOGL", 2.7), ("GOOG", 2.6), ("COST", 2.5), ("TSLA", 2.4)],
    "QQQM": [("AAPL", 8.9), ("MSFT", 8.1), ("NVDA", 7.5), ("AMZN", 5.3), ("META", 4.8),
             ("AVGO", 4.5), ("GOOGL", 2.7), ("GOOG", 2.6), ("COST", 2.5), ("TSLA", 2.4)],
    "QQQJ": [("MRVL", 1.8), ("DASH", 1.6), ("TEAM", 1.5), ("DDOG", 1.4), ("WDAY", 1.3),
             ("ZS", 1.2), ("ANSS", 1.2), ("ILMN", 1.1), ("OKTA", 1.0), ("TTD", 1.0)],
    "VGT": [("AAPL", 16.5), ("MSFT", 14.2), ("NVDA", 13.0), ("AVGO", 5.0), ("CRM", 2.5),
            ("AMD", 2.0), ("ACN", 2.0), ("ADBE", 1.8), ("CSCO", 1.7), ("ORCL", 1.6)],
    "XLK": [("AAPL", 15.0), ("MSFT", 13.5), ("NVDA", 12.5), ("AVGO", 4.8), ("CRM", 2.6),
            ("AMD", 2.1), ("ACN", 2.0), ("ADBE", 1.9), ("CSCO", 1.8), ("ORCL", 1.6)],
    "ARKK": [("TSLA", 11.0), ("COIN", 8.5), ("ROKU", 7.5), ("SQ", 6.0), ("PATH", 5.5),
             ("RBLX", 5.0), ("SHOP", 4.5), ("TWLO", 4.0), ("ZM", 3.5), ("U", 3.5)],
    "VTI": [("AAPL", 6.5), ("MSFT", 6.3), ("NVDA", 5.8), ("AMZN", 3.5), ("META", 2.4),
            ("GOOGL", 1.9), ("GOOG", 1.6), ("BRK.B", 1.6), ("LLY", 1.4), ("AVGO", 1.4)],
    "VUG": [("AAPL", 12.5), ("MSFT", 11.8), ("NVDA", 10.5), ("AMZN", 6.5), ("META", 4.5),
            ("AVGO", 3.0), ("GOOGL", 2.8), ("GOOG", 2.5), ("TSLA", 2.0), ("LLY", 1.8)],
    "SCHG": [("AAPL", 12.0), ("MSFT", 11.5), ("NVDA", 10.8), ("AMZN", 6.2), ("META", 4.3),
             ("AVGO", 3.2), ("GOOGL", 2.7), ("GOOG", 2.4), ("TSLA", 2.1), ("LLY", 1.7)],
    "VTV": [("BRK.B", 3.5), ("JPM", 3.0), ("UNH", 2.8), ("XOM", 2.5), ("JNJ", 2.3),
            ("PG", 2.2), ("HD", 2.0), ("ABBV", 2.0), ("CVX", 1.8), ("MRK", 1.7)],
    "SCHD": [("ABBV", 4.2), ("HD", 4.0), ("AMGN", 4.0), ("CSCO", 3.8), ("PEP", 3.5),
             ("KO", 3.2), ("VZ", 3.0), ("TXN", 3.0), ("PFE", 2.8), ("BLK", 2.7)],
    "VIG": [("MSFT", 5.0), ("AAPL", 4.5), ("JPM", 3.5), ("UNH", 3.0), ("AVGO", 2.8),
            ("MA", 2.5), ("V", 2.3), ("HD", 2.2), ("PG", 2.0), ("COST", 1.8)],
    "VEA": [("NOVO-B", 2.0), ("ASML", 1.8), ("NESN", 1.2), ("AZN", 1.1), ("SAP", 1.0),
            ("SHEL", 1.0), ("ROG", 0.9), ("MC", 0.9), ("TOYOTA", 0.8), ("NOVARTIS", 0.8)],
    "IEFA": [("NOVO-B", 2.1), ("ASML", 1.9), ("NESN", 1.3), ("AZN", 1.2), ("SAP", 1.1),
             ("SHEL", 1.0), ("ROG", 0.9), ("MC", 0.9), ("TOYOTA", 0.8), ("NOVARTIS", 0.8)],
    "EFA": [("NOVO-B", 2.3), ("ASML", 2.0), ("NESN", 1.4), ("AZN", 1.3), ("SAP", 1.1),
            ("SHEL", 1.1), ("ROG", 1.0), ("MC", 1.0), ("TOYOTA", 0.9), ("NOVARTIS", 0.9)],
    "VWO": [("TSM", 6.5), ("TENCENT", 3.8), ("ALIBABA", 2.5), ("SAMSUNG", 2.0), ("RELIANCE", 1.5),
            ("MEITUAN", 1.2), ("PDD", 1.1), ("INFOSYS", 1.0), ("ICBC", 0.9), ("VALE", 0.8)],
    "IEMG": [("TSM", 7.0), ("TENCENT", 3.5), ("SAMSUNG", 3.0), ("ALIBABA", 2.2), ("RELIANCE", 1.3),
             ("PDD", 1.2), ("MEITUAN", 1.1), ("INFOSYS", 1.0), ("ICBC", 0.9), ("VALE", 0.8)],
    "IWM": [("SMCI", 0.6), ("ONTO", 0.4), ("MSTR", 0.4), ("FNF", 0.3), ("EME", 0.3),
            ("LSCC", 0.3), ("CARG", 0.3), ("DT", 0.3), ("GLPI", 0.3), ("MEDP", 0.3)],
    "VB": [("SMCI", 0.5), ("FNF", 0.4), ("EME", 0.4), ("LSCC", 0.3), ("CARG", 0.3),
           ("DT", 0.3), ("GLPI", 0.3), ("MEDP", 0.3), ("RGEN", 0.3), ("PCTY", 0.3)],
    "LQD": [],  # Bond ETFs don't overlap with equities in a meaningful way
    "AGG": [],
    "BND": [],
    "GLD": [("GOLD_BULLION", 100.0)],
    "VNQ": [("PLD", 8.0), ("AMT", 6.0), ("EQIX", 5.0), ("WELL", 4.5), ("SPG", 4.0),
            ("DLR", 3.5), ("PSA", 3.0), ("O", 3.0), ("CCI", 2.5), ("VICI", 2.5)],
    "HYG": [],
    "TLT": [],
    "VTEB": [],
}


def load_portfolio(filepath: str) -> dict[str, float]:
    """Load portfolio tickers and their dollar values."""
    portfolio = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip().upper()
            value = float(row.get("total_value_across_accounts", row.get("value", 0)))
            if ticker and value > 0:
                portfolio[ticker] = value
    return portfolio


def compute_overlap_matrix(portfolio: dict[str, float]) -> dict[tuple[str, str], dict]:
    """Compute pairwise overlap between all ETFs in the portfolio."""
    overlaps = {}
    tickers = [t for t in portfolio if t in TOP_HOLDINGS and TOP_HOLDINGS[t]]

    for i, t1 in enumerate(tickers):
        h1 = {stock: weight for stock, weight in TOP_HOLDINGS[t1]}
        for t2 in tickers[i + 1:]:
            h2 = {stock: weight for stock, weight in TOP_HOLDINGS[t2]}
            common = set(h1.keys()) & set(h2.keys())
            if common:
                overlap_weight_1 = sum(h1[s] for s in common)
                overlap_weight_2 = sum(h2[s] for s in common)
                overlaps[(t1, t2)] = {
                    "common_stocks": sorted(common),
                    "num_common": len(common),
                    "overlap_weight_fund1": overlap_weight_1,
                    "overlap_weight_fund2": overlap_weight_2,
                    "fund1_value": portfolio[t1],
                    "fund2_value": portfolio[t2],
                }
    return overlaps


def compute_stock_concentration(portfolio: dict[str, float]) -> dict[str, float]:
    """Calculate effective dollar exposure to each underlying stock across all ETFs."""
    total_aum = sum(portfolio.values())
    stock_exposure = defaultdict(float)

    for etf_ticker, etf_value in portfolio.items():
        if etf_ticker not in TOP_HOLDINGS:
            continue
        for stock, weight_pct in TOP_HOLDINGS[etf_ticker]:
            dollar_exposure = etf_value * (weight_pct / 100.0)
            stock_exposure[stock] += dollar_exposure

    return dict(sorted(stock_exposure.items(), key=lambda x: x[1], reverse=True))


def generate_overlap_report(portfolio: dict[str, float]):
    """Generate overlap analysis report."""
    total_aum = sum(portfolio.values())
    equity_etfs = [t for t in portfolio if t in TOP_HOLDINGS and TOP_HOLDINGS[t]]

    print("=" * 80)
    print("PORTFOLIO OVERLAP ANALYSIS")
    print("=" * 80)
    print(f"\nTotal AUM:        ${total_aum:>15,.0f}")
    print(f"Equity ETFs:      {len(equity_etfs):>15d}")
    print(f"(Bond/commodity ETFs excluded from equity overlap analysis)")

    # Pairwise overlap
    overlaps = compute_overlap_matrix(portfolio)
    if overlaps:
        print("\n" + "-" * 80)
        print("PAIRWISE ETF OVERLAP (by number of shared top-10 holdings)")
        print("-" * 80)
        sorted_overlaps = sorted(overlaps.items(), key=lambda x: x[1]["num_common"], reverse=True)
        print(f"{'ETF Pair':<20} {'# Shared':>8} {'Overlap %1':>10} {'Overlap %2':>10} {'Shared Stocks'}")
        print("-" * 80)
        for (t1, t2), data in sorted_overlaps:
            overlap_str = ", ".join(data["common_stocks"][:6])
            if len(data["common_stocks"]) > 6:
                overlap_str += f" +{len(data['common_stocks']) - 6} more"
            print(f"{t1 + ' / ' + t2:<20} {data['num_common']:>8} "
                  f"{data['overlap_weight_fund1']:>9.1f}% {data['overlap_weight_fund2']:>9.1f}%  "
                  f"{overlap_str}")

        # Flag high-overlap pairs
        high_overlap = [(pair, data) for pair, data in sorted_overlaps if data["num_common"] >= 5]
        if high_overlap:
            print(f"\n  WARNING: {len(high_overlap)} ETF pair(s) share 5+ of their top 10 holdings.")
            print("  Consider whether you need both, or if one provides sufficient exposure.\n")
            for (t1, t2), data in high_overlap:
                combined = data["fund1_value"] + data["fund2_value"]
                print(f"    {t1} (${data['fund1_value']:,.0f}) + {t2} (${data['fund2_value']:,.0f}) "
                      f"= ${combined:,.0f} with ~{data['num_common']*10}% stock-level overlap")

    # Stock concentration
    stock_exposure = compute_stock_concentration(portfolio)
    if stock_exposure:
        print("\n" + "=" * 80)
        print("UNDERLYING STOCK CONCENTRATION (look-through across all ETFs)")
        print("=" * 80)
        print(f"{'Stock':<12} {'$ Exposure':>14} {'% of Total AUM':>14}  {'Contributing ETFs'}")
        print("-" * 80)
        top_stocks = list(stock_exposure.items())[:20]
        for stock, exposure in top_stocks:
            pct = (exposure / total_aum) * 100
            contributors = []
            for etf_ticker in equity_etfs:
                for s, w in TOP_HOLDINGS.get(etf_ticker, []):
                    if s == stock:
                        contributors.append(f"{etf_ticker}({w:.1f}%)")
            print(f"{stock:<12} ${exposure:>13,.0f} {pct:>13.2f}%  {', '.join(contributors)}")

        mega_stocks = [(s, e) for s, e in stock_exposure.items() if (e / total_aum) > 0.03]
        if mega_stocks:
            print(f"\n  WARNING: {len(mega_stocks)} stock(s) represent >3% of total AUM through ETF overlap:")
            for stock, exposure in mega_stocks:
                pct = (exposure / total_aum) * 100
                print(f"    {stock}: ${exposure:,.0f} ({pct:.1f}% of AUM)")
            print("\n  This concentration may be intentional, but verify it aligns with the investment thesis.")

    # Write CSV
    report_path = os.path.join(os.path.dirname(__file__) or ".", "overlap_report.csv")
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Section", "Item1", "Item2", "Metric", "Value", "Detail"])
        for (t1, t2), data in overlaps.items():
            writer.writerow(["Overlap", t1, t2, "Shared Holdings",
                             data["num_common"], "; ".join(data["common_stocks"])])
        for stock, exposure in list(stock_exposure.items())[:30]:
            pct = (exposure / total_aum) * 100
            writer.writerow(["Concentration", stock, "", "Dollar Exposure",
                             f"{exposure:.0f}", f"{pct:.2f}%"])

    print(f"\nCSV report saved to: {report_path}")

    # ETFRC recommendation
    print("\n" + "=" * 80)
    print("NEXT STEP: VALIDATE WITH FULL HOLDINGS DATA")
    print("=" * 80)
    print("This analysis uses top-10 holdings only. For full precision:")
    print("  1. Go to etfrc.com/funds/overlap.php")
    print("  2. Compare these high-overlap pairs with full holdings data:")
    for (t1, t2), data in sorted(overlaps.items(), key=lambda x: x[1]["num_common"], reverse=True)[:5]:
        print(f"     → {t1} vs {t2}  (etfrc.com/funds/overlap.php?f1={t1}&f2={t2})")
    print("  3. Use etfrc.com/portfolios/builder.php to input your full model portfolio\n")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    holdings_path = os.path.join(script_dir, "our_holdings.csv")
    sample_path = os.path.join(script_dir, "our_holdings_SAMPLE.csv")

    target = holdings_path if os.path.exists(holdings_path) else sample_path
    if not os.path.exists(target):
        print("ERROR: No holdings file found. Run fee_analyzer.py first to generate sample data.")
        sys.exit(1)

    print(f"Loading portfolio from: {os.path.basename(target)}\n")
    portfolio = load_portfolio(target)
    if not portfolio:
        print("ERROR: No holdings loaded.")
        sys.exit(1)

    generate_overlap_report(portfolio)


if __name__ == "__main__":
    main()
