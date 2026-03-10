---
name: backtest-strategy
description: End-to-end workflow for researching, backtesting, and deploying trend-based tactical strategies. Use when building a new strategy, running a backtest, deploying to QuantConnect, or validating backtest results.
---

# Backtest Strategy Workflow

## Workflow Steps

```
Task Progress:
- [ ] Step 1: Define the thesis and signals
- [ ] Step 2: Build local backtest
- [ ] Step 3: Evaluate results
- [ ] Step 4: Deploy to QuantConnect
- [ ] Step 5: Validate against Yahoo Finance
- [ ] Step 6: Correlation and portfolio fit analysis
```

## Step 1: Define the Thesis and Signals

Before writing any code, answer:
- What market inefficiency does this strategy exploit?
- What asset class / universe does it trade?
- What signals drive entry/exit? (specify lookbacks, thresholds)
- What is the rebalance frequency?
- Is allocation binary or graduated?

Reference existing signal patterns in `intl_composite_signals.py` and `freeburg_signals.py`.

## Step 2: Build Local Backtest

Use this skeleton:

```python
"""
{Strategy Name} Backtest
========================
{One-line description}

Usage: python {filename}.py
"""
import os
import warnings
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings("ignore")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def fetch_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    raw = yf.download(tickers, start=start, end=end, auto_adjust=False, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Close"].ffill()
    return raw[["Close"]].rename(columns={"Close": tickers[0]}).ffill()

def compute_signals(prices: pd.DataFrame) -> pd.DataFrame:
    # TODO: implement signal logic
    pass

def run_backtest(prices: pd.DataFrame, signals: pd.DataFrame) -> pd.Series:
    # TODO: implement portfolio construction and equity curve
    pass

def evaluate(equity: pd.Series, benchmark: pd.Series) -> dict:
    returns = equity.pct_change().dropna()
    bench_returns = benchmark.pct_change().dropna()
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (252 / len(equity)) - 1
    max_dd = (equity / equity.cummax() - 1).min()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.inf
    beta = returns.cov(bench_returns) / bench_returns.var() if bench_returns.var() != 0 else 0
    return {
        "CAGR": f"{cagr:.2%}", "Max DD": f"{max_dd:.2%}",
        "Calmar": f"{calmar:.2f}", "Sharpe": f"{sharpe:.2f}", "Beta": f"{beta:.2f}",
    }

if __name__ == "__main__":
    # Implement and run
    pass
```

## Step 3: Evaluate Results

Required metrics (print as table):
- Calmar ratio, CAGR, Max DD, Sharpe, Beta
- Win rate, profit factor (for discrete trades)
- Number of trades, avg holding period
- Correlation to each existing sleeve

Red flags:
- Calmar < 0.5 → strategy doesn't manage risk well enough
- > 100 trades/year → check for commission drag
- Correlation > 0.6 to any existing sleeve → marginal diversification benefit
- In-sample only → must walk-forward validate

## Step 4: Deploy to QuantConnect

Follow the deployment pattern in `qc_intl_composite_deploy.py`:

```python
import hashlib, base64, requests, json, time

USER_ID = "YOUR_USER_ID"
API_TOKEN = "YOUR_API_TOKEN"

timestamp = str(int(time.time()))
hash_bytes = hashlib.sha256(f"{API_TOKEN}:{timestamp}".encode()).digest()
auth = base64.b64encode(f"{USER_ID}:{hash_bytes.hex()}:{timestamp}".encode()).decode()
headers = {"Authorization": f"Basic {auth}"}

# 1. Create project
# 2. Upload main.py
# 3. Compile
# 4. Run backtest
# 5. Poll for completion
# 6. Fetch and save results
```

## Step 5: Validate Against Yahoo Finance

Use `validate_composite_risk_overlay_yahoo.py` as reference:
- Pull the same tickers from Yahoo Finance for the backtest period
- Reconstruct the equity curve from QC orders/trades
- Compare monthly returns — flag any discrepancy > 50bps

## Step 6: Portfolio Fit Analysis

Use `combined_portfolio_analysis.py` pattern:
- Compute pairwise correlation matrix with all four existing sleeves
- Run combined portfolio analysis with the new strategy added
- Report: does it improve Calmar? Reduce max DD? Add uncorrelated returns?
