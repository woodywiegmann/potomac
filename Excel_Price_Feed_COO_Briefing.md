# Briefing: Excel Price Feed — COO Run Instructions
## Potomac Fund Management | For: COO | From: Research | March 2026

---

## Purpose

We maintain a **daily price feed** exported to Excel for reporting, ad‑hoc analysis, and strategy monitoring. The feed is produced by a small Python script that pulls adjusted closing prices (and optionally OHLC) from Yahoo Finance and writes a single workbook: **`price_feed.xlsx`**. This briefing gives you everything needed to **run the script yourself** and refresh the file whenever you need updated ticker data.

---

## What You Get

- **File:** `price_feed.xlsx` (saved in the same Potomac folder as the script).
- **Content:** One sheet named **Close** — rows = trading dates, columns = ticker symbols. Values = **adjusted close** (split/dividend adjusted). Optional: extra sheets **Open**, **High**, **Low** if you run with the `--ohlc` flag.
- **Default date range:** Last **2 years** through today (configurable; see below).
- **Default ticker set:** **Expanded universe** (~60+ symbols) so the file is useful across sleeves and projects.

---

## Default Ticker Universe (No Changes Needed)

If you run the script with no arguments, it downloads all of the following:

| Category | Tickers |
|----------|---------|
| **US indices** | SPY, QQQ, IWM, DIA |
| **Sectors (GICS)** | XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLRE, XLB, XLC |
| **Bonds / rates** | AGG, BND, TLT, SHY, SGOV, LQD, HYG, BNDX |
| **Commodities / gold** | GLD, SLV, IAU, DBC, PDBC, COM, UUP |
| **Hard-asset tactical** | TILL, PDBA, MOO, LAND, XOP, OIH, COPX, LIT, PICK, REMX, GDX, SIL |
| **International** | EFA, EEM, ACWX, VWO, VEA, IEMG |
| **Factor / smart beta** | MTUM, SPMO, JMOM, USMV, QUAL, VTV, VUG |
| **Volatility** | VIXY, VXX |

You do **not** need to type these; they are built in. To use a **different** list (e.g. only SPY and QQQ), use the `--tickers` option below.

---

## How to Run It (Your Machine)

### Prerequisites (one-time)

1. **Python 3** installed (e.g. from python.org or your existing Potomac setup).
2. **Dependencies** in the same environment you use for other Potomac scripts:
   ```bash
   pip install yfinance pandas openpyxl
   ```

### Standard run (recommended)

1. Open **Command Prompt** or **PowerShell**.
2. Go to the Potomac folder where the script lives:
   ```bash
   cd "C:\Users\WoodyWiegmann\OneDrive - PFM\Desktop\Potomac"
   ```
   *(Adjust the path if your Potomac folder is elsewhere.)*
3. Run:
   ```bash
   python download_excel_price_feed.py
   ```
4. Wait for the progress bar to finish (with the full ticker list, the first run may take 1–2 minutes).
5. Open **`price_feed.xlsx`** in the same folder. Sheet **Close** has dates × tickers.

That’s it. No need to change anything unless you want custom dates or tickers.

---

## Optional: Custom Dates or Tickers

- **Different date range:**
  ```bash
  python download_excel_price_feed.py --start 2020-01-01 --end 2026-03-01
  ```
- **Your own ticker list** (comma-separated, no spaces):
  ```bash
  python download_excel_price_feed.py --tickers SPY,QQQ,GLD,TLT
  ```
- **Include Open, High, Low** (extra sheets in the same workbook):
  ```bash
  python download_excel_price_feed.py --ohlc
  ```
- **Different output file name:**
  ```bash
  python download_excel_price_feed.py --out my_price_feed.xlsx
  ```

You can combine options, e.g.:
```bash
python download_excel_price_feed.py --start 2022-01-01 --ohlc --out weekly_feed.xlsx
```

---

## How Often to Run

- **Ad hoc:** Run whenever you need a fresh Excel snapshot (e.g. before a meeting or report).
- **Routine:** e.g. weekly or after market close if you use the file for recurring reporting. There is no scheduler; you run it manually.

---

## If Something Fails

- **“No module named 'yfinance'”** (or pandas/openpyxl): run `pip install yfinance pandas openpyxl` in the same Python environment.
- **“No data returned”:** check that tickers are valid Yahoo symbols and the date range contains trading days. A few symbols (e.g. some volatility products) may be delisted or renamed; drop them from the list if they error.
- **Script runs but Excel is empty or partial:** Yahoo can throttle or miss data for a few symbols. Re-run; if it persists, remove the problematic ticker with `--tickers` and a shorter list.

---

## Summary

| Item | Detail |
|------|--------|
| **Script** | `download_excel_price_feed.py` (Potomac folder) |
| **Output** | `price_feed.xlsx` in the same folder |
| **Default** | ~60+ tickers, last 2 years, Close only |
| **Your action** | `cd` to Potomac, then `python download_excel_price_feed.py` |
| **Refresh** | Run whenever you need updated data |

If you want more tickers added to the default list or a different default date range, tell Research and we’ll update the script and this briefing.
