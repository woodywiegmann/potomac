# ETFdb Data Workflow — What to Pull, How to Use It

## Step 1: Data Exports from ETFdb Pro

### Export A: "The Universe" — All ETFs by Category
Run the ETFdb screener with these separate filter sets and export each as CSV:

| Screener Run | Filters | Filename |
|---|---|---|
| US Large Cap Equity | Asset Class: Equity, Market Cap: Large | `etfdb_us_largecap.csv` |
| US Mid/Small Cap | Asset Class: Equity, Market Cap: Mid + Small | `etfdb_us_smid.csv` |
| International Developed | Asset Class: Equity, Region: Developed ex-US | `etfdb_intl_dev.csv` |
| Emerging Markets | Asset Class: Equity, Region: Emerging Markets | `etfdb_em.csv` |
| US Aggregate Bond | Asset Class: Bond, Type: Aggregate | `etfdb_bond_agg.csv` |
| Corporate Bond | Asset Class: Bond, Type: Corporate | `etfdb_bond_corp.csv` |
| Treasury / Gov't | Asset Class: Bond, Type: Government | `etfdb_bond_govt.csv` |
| Thematic / Innovation | Investment Style: Growth / Thematic | `etfdb_thematic.csv` |

**Columns to include in each export:** Ticker, Name, Issuer, Expense Ratio, AUM, Avg Volume, YTD Return, 1Y Return, 3Y Return, 5Y Return, # Holdings, Inception Date

### Export B: "Our Holdings" — Your Current Book
From your custodian(s), export or manually compile a CSV of every unique ETF/fund held across all accounts:

```
ticker,name,total_value_across_accounts,num_accounts_held_in,expense_ratio_bps
VOO,Vanguard S&P 500,15000000,120,3
ARKK,ARK Innovation,2500000,45,75
AGG,iShares Core US Agg Bond,8000000,95,3
...
```

Save as `our_holdings.csv` in this folder.

## Step 2: Free Supplementary Data Sources

| Source | URL | What It Gives You |
|---|---|---|
| **ETFRC Overlap Tool** | etfrc.com/funds/overlap.php | Holdings overlap % between any 2 ETFs |
| **ETFRC Portfolio Builder** | etfrc.com/portfolios/builder.php | Overlap matrix for entire portfolios |
| **Portfolio Visualizer** | portfoliovisualizer.com | Factor regressions, backtests, drawdowns |
| **ETF.com** | etf.com | Independent expense ratio + structure data |

## Step 3: Run the Analysis Scripts

Place your CSVs in this folder, then run:
- `python fee_analyzer.py` — Expense ratio audit + swap recommendations
- `python overlap_analyzer.py` — Holdings overlap detection across your models
