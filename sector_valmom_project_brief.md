# Project Brief: Sector Rotation + Value-Momentum Stock Selection
## John Woodside Inc | From: COO | To: Jack (The Quant) | March 2026

---

Jack,

Woody has a strategy idea he wants built and backtested. It's a two-layer approach — macro sector momentum on top, micro value-momentum stock picking underneath. The thesis is simple: ride the best sector, own the best stocks inside it.

Here's what you need to build.

---

## Strategy Architecture

### Layer 1 — Sector Rotation

Rank the 11 GICS sectors monthly by momentum. Use the S&P sector ETFs as proxies:

XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLRE, XLB, XLC

**Ranking signal**: Composite of 3-month and 6-month total return relative to SPY. Equal weight both lookbacks. The top 1 sector gets the full allocation. Run a variant with top 2 sectors (50/50 split) for comparison.

**Rebalance**: Monthly, at close on last trading day.

### Layer 2 — Stock Selection Within Winning Sector

Once the top sector is identified, screen all S&P 500 constituents in that sector. Rank each stock on a composite of two factors:

**Momentum (50% weight)**:
- 12-month return excluding the most recent month (the "12-1" convention)
- The last month is excluded because short-term returns tend to mean-revert

**Value (50% weight)**:
- Composite rank of: trailing P/E, price-to-free-cash-flow, EV/EBITDA
- Lower multiple = higher score
- Rank on each metric separately, then average the ranks

**Quality gate (pass/fail, not scored)**:
- ROE > 10%
- Debt/Equity < 1.5
- Positive trailing twelve-month earnings
- Stocks that fail any of these are excluded before ranking

**Portfolio construction**:
- Select top 10 stocks by combined momentum + value rank
- Equal weight (10% each)
- Rebalance monthly alongside the sector rotation check

---

## Backtest Specification

**Universe**: S&P 500 constituents, GICS sector classification
**Period**: January 2016 through February 2026 (10 years)
**Benchmark**: SPY (buy and hold)
**Starting capital**: $100,000
**Rebalance**: Monthly, last trading day

### MANDATORY: Honest Backtest Rules (use `honest_backtest.py`)

All backtests MUST use the `honest_backtest` module. No raw pandas backtest logic.

1. **T+1 signal lag**: Signals computed on day T drive allocation on day T+1. Use `lag_signals(signals, lag=1)`.
2. **Open-price execution on transition days**: When the sector rotation or stock selection changes, execution happens at next day's open, not close. Download both Open and Close from yfinance.
3. **Transaction costs**: 20bps round-trip per monthly rebalance (covers spread + slippage + market impact for 10-25 stock trades). Apply via `apply_transition_costs()`.
4. **Validation pipeline**: After backtest, run `validate_strategy()` to check for timing illusion, cost survival, and transition frequency.
5. **No victory laps until QC confirms**: Local results are hypotheses. QuantConnect results are evidence.

### Metrics to Report

In this order — you know the drill:

1. Calmar ratio (CAGR / Max DD)
2. CAGR
3. Max drawdown
4. Sharpe ratio
5. Beta to SPY
6. Average monthly turnover (% of portfolio)
7. Number of sector rotations per year
8. Average holding period per stock
9. Win rate (% of months positive)

### Variants to Test

| Variant | Sectors Held | Stocks per Sector | Notes |
|---------|-------------|-------------------|-------|
| A (base) | Top 1 | 10 | Concentrated |
| B | Top 2 | 10 each (20 total) | Diversified |
| C | Top 1 | 15 | Wider net |
| D | Top 1 | 10, but momentum only (no value) | Isolate momentum contribution |
| E | Top 1 | 10, but value only (no momentum) | Isolate value contribution |

This lets us see whether the factor combination adds value over either factor alone, and whether 1 sector vs 2 changes the risk profile meaningfully.

### Correlation Analysis

Once the base case equity curve is built, compute monthly return correlations against each of the four existing Systematic Alpha sleeves:
- CRDBX Core (use SPY as proxy)
- Defensive Equity (use BTAL as proxy)
- International Tactical (use ACWX as proxy)
- Gold Digger (use GLD as proxy)

If correlation to CRDBX is above 0.6, this strategy is redundant. Below 0.4, it's a candidate for a fifth sleeve or a replacement.

---

## Data Sources

- `yfinance` for price data and fundamentals (P/E, P/FCF, EV/EBITDA, ROE, D/E)
- Wikipedia or a static list for S&P 500 constituents and GICS sector mapping
- Survivorship bias note: yfinance only shows current S&P 500 members. This will introduce some bias. Acceptable for a first pass. If the numbers look promising, we rebuild with point-in-time constituents on QuantConnect.

## Output

- Python script: `sector_valmom_backtest.py` in the Potomac directory
- Equity curve CSV: `sector_valmom_equity.csv`
- Summary stats printed to stdout in table format
- Monthly returns CSV: `sector_valmom_monthly.csv`
- Sector rotation log: which sector was selected each month and why

---

## TLH Considerations

Every monthly rebalance where a stock drops out of the top 10 is a potential harvest. Track the stocks exiting the portfolio with unrealized losses. Swap pairs within the same sector are inherently available since you're replacing one energy stock with another energy stock. Flag these in the output.

---

## What Woody Wants to See

He's going to look at Calmar first. If it's below 0.5, the risk management isn't tight enough and we need to add a risk-off overlay (composite signal or VIX-based). If Calmar is above 1.0, this has real legs.

He'll also want to see how it performed during 2020 (COVID crash), 2022 (rate shock), and any other major drawdown periods. Print a worst-5-months table.

After the local backtest, if it looks good, the next step is deploying to QuantConnect for proper walk-forward validation with point-in-time data. But don't jump ahead — local first.

---

Get after it, Jack.

— COO, John Woodside Inc
