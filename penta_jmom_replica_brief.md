# Project Brief: Penta Overlay on JMOM Single-Stock Replication + Leveraged Risk-On/Off
## John Woodside Inc | From: Will (COO) | To: Jack (The Quant) | March 2026

---

Jack,

New project from Woody. This one has three moving parts so read carefully.

---

## Background

We ran the numbers on every smart beta / factor ETF since Feb 2019. The winner among true factor ETFs is **JMOM (JPM US Momentum Factor)** — 14.74% CAGR, -34.3% max DD, 0.43 Calmar. It beat QVAL, MTUM, VLUE, QUAL, and everything else that isn't just closet mega-cap growth.

Woody wants to replicate JMOM with single stocks, then layer Penta's risk-on/risk-off regime overlay on top, and add leveraged S&P 500 exposure during risk-on using E-mini futures.

---

## Strategy Architecture

### Component 1 — JMOM Single-Stock Replication (The Core)

Reverse-engineer JMOM's methodology and build a monthly-rebalanced stock portfolio:

**Stock selection signals:**
- 12-month price return excluding most recent month (12-1 momentum)
- Risk-adjusted momentum (return / volatility over trailing 12 months)
- Earnings momentum (3-month change in consensus EPS estimates — if available via yfinance, otherwise skip and use price momentum double-weighted)

**Universe:** S&P 500 constituents

**Portfolio construction:**
- Rank all S&P 500 stocks by composite momentum score
- Select top 25 stocks
- Equal weight (4% each)
- Rebalance monthly, last trading day

**Output:** This gives us a standalone equity curve. Measure its beta to SPY. In the backtest data we pulled, JMOM's beta was roughly 1.0-1.05. Your replication will probably land in a similar range. Record the realized beta — we need it for Component 3.

### Component 2 — Penta Risk-On / Risk-Off Overlay

Apply Penta's signal framework to determine the daily regime. I don't have the exact Penta signals spec, so Woody — you'll need to tell Jack the precise rules here, or Jack can stub it out with a proxy.

**Proxy risk-on/risk-off signal (use until Woody provides Penta spec):**
- Composite of: SPY vs 200-day SMA, VIX level vs 20 threshold, 10Y yield trend (50-day ROC), credit spread direction (LQD/HYG vs SHY ratio trend)
- If 3 of 4 signals are bullish → RISK ON
- If 2 or fewer are bullish → RISK OFF
- Evaluate daily at close

**Woody: replace this proxy with Penta's actual signals when you're ready. The architecture stays the same regardless of what generates the risk-on/risk-off flag.**

### Component 3 — Regime-Based Allocation

This is where it all comes together.

**RISK ON allocation:**
- 100% in the JMOM replica portfolio (Component 1)
- PLUS 0.2x notional S&P 500 exposure via E-mini futures
- Total portfolio beta ≈ replica beta + 0.2 ≈ 1.2-1.25x
- The futures overlay costs essentially zero (margin collateral earns T-bill rate)
- This is the Hoffstein return-stacking concept — you're getting equity exposure on top of equity exposure using capital-efficient instruments

**RISK OFF allocation:**
- Liquidate the JMOM replica entirely
- Liquidate the E-mini futures overlay
- Move to: 50% CAOS (Simplify tail-risk ETF) + 50% cash (SGOV proxy or T-bill rate)
- This is the indirect tactics sleeve — you're not just hiding in cash, you're positioned to profit from the conditions that triggered the defensive posture

**Transition mechanics:**
- On risk-on → risk-off signal: sell all stocks at next day's open, sell futures, buy CAOS at next day's open, rest to cash
- On risk-off → risk-on signal: sell CAOS, buy top 25 momentum stocks at next day's open, initiate futures overlay
- Assume 10bps slippage on each transition (conservative for liquid large-caps)

```
RISK ON:
┌─────────────────────────────┐
│  JMOM Replica (25 stocks)   │  ← ~1.0x beta
│  + 0.2x E-mini S&P 500     │  ← +0.2x beta  
│  = ~1.2x total exposure     │
└─────────────────────────────┘

RISK OFF:
┌─────────────────────────────┐
│  50% CAOS (tail-risk puts)  │  ← negative beta, convex
│  50% Cash (SGOV/T-bills)    │  ← zero beta, earns yield
│  = ~negative total exposure │
└─────────────────────────────┘
```

---

## Backtest Specification

**Period:** March 2020 through February 2026 (6 years — CAOS inception was ~Sep 2020, so start there if needed)
**Starting capital:** $100,000
**Benchmark:** SPY buy-and-hold AND JMOM buy-and-hold (two benchmarks)
**Transaction costs:** 10bps per stock trade, $1.40 per E-mini contract
**Futures sizing:** 0.2x portfolio notional value / $50 per point / current ES price = number of contracts (round down)

### Metrics to Report

1. Calmar ratio
2. CAGR
3. Max drawdown
4. Sharpe ratio
5. Beta to SPY
6. Number of regime switches (risk-on → risk-off transitions per year)
7. Average risk-on period duration (days)
8. Average risk-off period duration (days)
9. Risk-off sleeve performance (did CAOS + cash actually make money during defensive periods?)
10. Contribution analysis: how much alpha came from stock selection vs the leverage overlay vs the risk-off timing?

### Stress Test Periods

Print standalone performance for:
- COVID crash (Feb-Mar 2020) — if data available
- 2022 rate shock (Jan-Oct 2022)
- Aug 2024 VIX spike
- Any drawdown > 5% in the backtest

### Variants to Test

| Variant | Leverage | Risk-Off Mix | Notes |
|---------|----------|-------------|-------|
| A (base) | +0.2x ES | 50% CAOS / 50% cash | As specified |
| B | +0.3x ES | 50% CAOS / 50% cash | More aggressive leverage |
| C | +0.2x ES | 50% CAOS / 25% DBMF / 25% cash | Add trend-following to risk-off |
| D | +0.2x ES | 100% cash | Simple risk-off (control group) |
| E | No leverage | 50% CAOS / 50% cash | Isolate signal value without leverage |

Variant C adds DBMF to the risk-off mix — Woody's been watching DBMF outperform SPY YTD by 11 percentage points. If trend-following works when equities chop, having it in the defensive sleeve turns risk-off periods from "waiting" into "earning."

---

## MANDATORY: Honest Backtest Rules (use `honest_backtest.py`)

All backtests MUST use the `honest_backtest` module. No raw pandas backtest logic.

1. **T+1 signal lag**: Penta signals computed on day T drive allocation on day T+1. Use `lag_signals(signals, lag=1)`. This is critical — the graduated_penta.py backtest showed 66% CAGR without lag. Real number is probably 15-25%.
2. **Open-price execution on transition days**: When regime switches, execution happens at next day's open. The close-to-open gap on risk-off days is where alpha leaks. Use `compute_open_execution_returns()`.
3. **Transaction costs**: 20bps round-trip per regime transition for ETF-based strategies. For single-stock JMOM replica: 30bps round-trip (wider spreads on individual names). Apply via `apply_transition_costs()`.
4. **Validation pipeline**: After backtest, run `validate_strategy()` with `naive_cagr` set to the no-lag result. If CAGR drops > 30%, the alpha was timing illusion.
5. **QC reconciliation**: Before presenting any results, use `reconcile_with_qc()` to compare against QuantConnect output. Flag discrepancies > 50bps.

## Data Sources

- `yfinance` for stock prices, fundamentals, VIX, yields
- S&P 500 constituent list (Wikipedia or static)
- CAOS price history from yfinance (ticker: CAOS, inception ~Sep 2020)
- SGOV for cash proxy returns
- DBMF for variant C
- E-mini S&P 500 futures: approximate with SPY returns x leverage factor (no need to model actual contracts for the backtest — we just need the notional exposure math)

## Output Files

- `penta_jmom_backtest.py` — main script
- `penta_jmom_equity.csv` — daily equity curve
- `penta_jmom_monthly.csv` — monthly returns
- `penta_jmom_regime_log.csv` — daily regime (risk-on/risk-off), signal values, allocation
- `penta_jmom_transitions.csv` — every regime switch with date, direction, and P&L impact
- Summary stats to stdout

---

## Important Notes

1. **Woody will provide the real Penta signal spec.** Build the architecture so the risk-on/risk-off flag is a single function call that can be swapped out. Don't hardcode the proxy signals into the backtest logic — keep them in a separate `signals.py` module.

2. **The E-mini leverage is modest.** 0.2x on a ~1.0 beta portfolio means total beta of ~1.2. This isn't cowboy leverage — it's Hoffstein-style capital efficiency. The margin requirement on 0.2x notional is tiny, so the cash drag is near zero.

3. **CAOS in risk-off is the Woody special.** He's been talking about replacing pure SGOV with convexity instruments since the trade concepts memo. 50/50 CAOS/cash outperformed pure SGOV by +1.53% annualized during the 173 risk-off days he already tested. This is baked into the thesis.

4. **TLH opportunity:** Every regime switch that liquidates stocks is a harvest event. Log unrealized gains/losses at each transition.

---

One more thing, Jack — when Woody sees these numbers, the first thing he'll look at is whether the CAOS + cash sleeve actually made money during risk-off periods, not just "lost less." If the indirect tactics are working, that sleeve should be green, not just less red. That's the whole point.

Get after it.

— Will (COO), John Woodside Inc
