"""
Download price feed and save to Excel.
Uses yfinance; outputs Adjusted Close (and optional OHLC) to .xlsx.

Usage:
  python download_excel_price_feed.py
  python download_excel_price_feed.py --tickers SPY,QQQ,COM,SHY --start 2020-01-01
  python download_excel_price_feed.py --tickers SPY --end 2026-03-01 --ohlc
"""

import argparse
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("pip install yfinance")

try:
    import openpyxl
except ImportError:
    raise SystemExit("pip install openpyxl")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Full universe: indices, sectors, bonds, commodities, hard-asset, intl, factor, signals, TLH pairs
DEFAULT_TICKERS = (
    # US indices + benchmarks
    "SPY,QQQ,IWM,DIA,VOO,^GSPC,^NDX,^RUT,^DJI,"
    # GICS sectors
    "XLK,XLF,XLE,XLV,XLI,XLY,XLP,XLU,XLRE,XLB,XLC,"
    # Bonds / rates / credit
    "AGG,BND,TLT,SHY,SGOV,LQD,HYG,BNDX,BIL,SHV,SPTS,VGIT,VGLT,SPTL,SCHZ,"
    # Commodities / gold / GoldDigger instruments
    "GLD,SLV,IAU,DBC,PDBC,COM,UUP,PHYS,RING,GDXJ,SILJ,GC=F,SI=F,CL=F,"
    # Hard-asset tactical
    "TILL,PDBA,MOO,LAND,XOP,OIH,COPX,LIT,PICK,REMX,GDX,SIL,"
    # International broad
    "EFA,EEM,ACWX,VWO,VEA,IEMG,IEFA,SPDW,SPEM,"
    # International single-country (tactical 40-ETF universe subset)
    "EWJ,EWG,EWU,EWA,EWC,EWY,EWH,EWT,EWS,EWZ,EWW,ILF,"
    # Factor / smart beta (comprehensive)
    "MTUM,SPMO,JMOM,USMV,QUAL,VTV,VUG,"
    "QVAL,QMOM,VFMO,RPV,RPG,SPYV,SPYG,AVUV,AVLV,JVAL,PDP,IWD,IWF,DFLV,DFAC,"
    # Volatility
    "VIXY,VXX,^VIX,"
    # Penta signal inputs
    "^DJT,^NYA,^TNX,^TYX,"
    # Sleeve proxies + defensive instruments
    "CRDBX,CAOS,DBMF,HEQT,BTAL,"
    # TLH swap pairs + thematic
    "QQQJ,QQQM,URNM,URA,CPER,XME,SMH,SOXX,XBI,IBB,ITA,PPA,XSD"
)
DEFAULT_START = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
DEFAULT_END = datetime.now().strftime("%Y-%m-%d")
OUT_EXCEL = "price_feed.xlsx"


def fetch_prices(tickers: list[str], start: str, end: str, ohlc: bool = False) -> pd.DataFrame | dict:
    """Fetch Adjusted Close (or OHLC) for tickers. Returns DataFrame (close) or dict of DataFrames (ohlc)."""
    raw = yf.download(
        tickers, start=start, end=end, auto_adjust=True, progress=True,
        group_by="ticker", threads=True, interval="1d"
    )
    if raw.empty:
        return pd.DataFrame() if not ohlc else {}

    if isinstance(raw.columns, pd.MultiIndex):
        level1 = raw.columns.get_level_values(1).unique()
        close_col = "Close" if "Close" in level1 else level1[0]
        close = raw.xs(close_col, axis=1, level=1).copy()
        if len(tickers) == 1:
            close = close.rename(columns={close.columns[0]: tickers[0]})
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})

    close.index = close.index.tz_localize(None) if getattr(close.index, "tz", None) else close.index
    close = close.ffill()

    if not ohlc:
        return close

    out = {"Close": close}
    for col in ["Open", "High", "Low"]:
        if col in level1 if isinstance(raw.columns, pd.MultiIndex) else col in raw.columns:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw.xs(col, axis=1, level=1).copy()
            else:
                df = raw[[col]].rename(columns={col: tickers[0]})
            df.index = df.index.tz_localize(None) if getattr(df.index, "tz", None) else df.index
            out[col] = df.ffill()
    return out


def main():
    parser = argparse.ArgumentParser(description="Download price feed to Excel")
    parser.add_argument("--tickers", default=DEFAULT_TICKERS, help="Comma-separated tickers (default: expanded universe)")
    parser.add_argument("--start", default=DEFAULT_START, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_END, help="End date YYYY-MM-DD")
    parser.add_argument("--ohlc", action="store_true", help="Include Open, High, Low sheets")
    parser.add_argument("--out", default=OUT_EXCEL, help="Output Excel filename")
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        raise SystemExit("Provide at least one ticker via --tickers")

    print(f"Downloading {tickers} from {args.start} to {args.end}...")
    data = fetch_prices(tickers, args.start, args.end, ohlc=args.ohlc)

    out_path = os.path.join(SCRIPT_DIR, args.out)
    if args.ohlc and isinstance(data, dict):
        with pd.ExcelWriter(out_path, engine="openpyxl") as w:
            for sheet_name, df in data.items():
                df.to_excel(w, sheet_name=sheet_name)
        print(f"Wrote sheets: {list(data.keys())} -> {out_path}")
    elif isinstance(data, pd.DataFrame) and not data.empty:
        data.to_excel(out_path, sheet_name="Close")
        print(f"Wrote {out_path}")
    else:
        raise SystemExit("No data returned; check tickers and date range.")


if __name__ == "__main__":
    main()
