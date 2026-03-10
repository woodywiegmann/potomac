# International Single-Country Dual Momentum Strategy

## Strategy Overview

An international-only dual momentum strategy using liquid single-country ETFs, adapted from Gary Antonacci's Global Equities Momentum (GEM) framework. Instead of toggling between US and international equities, this variant rotates among international single-country ETFs using **relative momentum** to select the strongest country and **absolute momentum** as the go-to-cash filter.

---

## ETF Universe: Liquid International Single-Country ETFs

### Tier 1 — Core Universe (AUM > $5B, Avg Volume > 3M shares/day)

| Ticker | Country        | AUM ($B)  | 30d Avg Vol  | Expense | Spread | Inception |
|--------|----------------|-----------|--------------|---------|--------|-----------|
| EWJ    | Japan          | $20.3B    | 10,665,088   | 0.49%   | 0.01%  | Mar 1996  |
| EWZ    | Brazil         | $9.7B     | 43,156,603   | 0.59%   | 0.03%  | Jul 2000  |
| INDA   | India          | $9.3B     | 9,062,417    | 0.61%   | 0.02%  | Feb 2012  |
| EWT    | Taiwan         | $8.8B     | 5,438,879    | 0.59%   | 0.01%  | Jun 2000  |
| FXI    | China (Lg Cap) | $6.2B     | 36,135,680   | 0.74%   | 0.02%  | Oct 2004  |

### Tier 2 — Strong Liquidity (AUM $1B-$5B, Avg Volume > 500K shares/day)

| Ticker | Country        | AUM ($B)  | Est Avg Vol  | Expense | Inception |
|--------|----------------|-----------|--------------|---------|-----------|
| EWG    | Germany        | $1.8B     | 1,551,076    | 0.49%   | Mar 1996  |
| MCHI   | China (Broad)  | ~$5.5B    | ~8,000,000   | 0.59%   | Mar 2012  |
| EWU    | United Kingdom | ~$3.0B    | ~2,000,000   | 0.49%   | Mar 1996  |
| EWC    | Canada         | ~$3.5B    | ~2,500,000   | 0.49%   | Mar 1996  |
| EWY    | South Korea    | ~$3.5B    | ~3,500,000   | 0.59%   | May 2000  |
| EWA    | Australia      | ~$1.5B    | ~1,500,000   | 0.49%   | Mar 1996  |
| EWW    | Mexico         | ~$1.5B    | ~2,000,000   | 0.49%   | Mar 1996  |
| EWH    | Hong Kong      | ~$1.0B    | ~3,000,000   | 0.49%   | Mar 1996  |

### Tier 3 — Tradeable but Thinner (AUM $300M-$1B)

| Ticker | Country        | AUM ($M)  | Est Avg Vol  | Expense | Notes                    |
|--------|----------------|-----------|--------------|---------|--------------------------|
| EWQ    | France         | ~$385M    | ~500,000     | 0.50%   | Developed market         |
| EWP    | Spain          | ~$500M    | ~500,000     | 0.50%   | Developed market         |
| EWI    | Italy          | ~$350M    | ~500,000     | 0.49%   | Developed market         |
| EWL    | Switzerland    | ~$1.0B    | ~800,000     | 0.49%   | Defensive, quality       |
| EWD    | Sweden         | ~$400M    | ~300,000     | 0.53%   | Export-oriented          |
| EWS    | Singapore      | ~$500M    | ~500,000     | 0.49%   | Financial hub            |
| EWN    | Netherlands    | ~$300M    | ~200,000     | 0.50%   | ASML-heavy               |
| EPOL   | Poland         | ~$300M    | ~200,000     | 0.59%   | Frontier/EM              |
| THD    | Thailand       | ~$500M    | ~300,000     | 0.59%   | ASEAN                    |
| GREK   | Greece         | ~$300M    | ~200,000     | 0.59%   | Frontier play            |
| EWK    | Belgium        | ~$50M     | ~30,000      | 0.50%   | Too illiquid — EXCLUDE   |
| EDEN   | Denmark        | ~$100M    | ~50,000      | 0.53%   | Thin — use with caution  |
| NORW   | Norway         | ~$100M    | ~50,000      | 0.53%   | Thin — use with caution  |
| ECH    | Chile          | ~$300M    | ~200,000     | 0.59%   | Commodity-linked         |
| EZA    | South Africa   | ~$300M    | ~300,000     | 0.59%   | Resource-heavy           |
| TUR    | Turkey         | ~$300M    | ~500,000     | 0.59%   | High vol, high momentum  |
| KWEB   | China Internet | ~$6.0B    | ~15,000,000  | 0.70%   | Sector-specific, not pure country |

---

## Recommended Universe (16 ETFs)

For a dual momentum country rotation, I recommend this core universe of 16 ETFs that balance geographic diversification, liquidity, and breadth across developed and emerging markets:

### Developed Markets (9)
1. **EWJ** — Japan
2. **EWG** — Germany
3. **EWU** — United Kingdom
4. **EWC** — Canada
5. **EWA** — Australia
6. **EWQ** — France
7. **EWL** — Switzerland
8. **EWP** — Spain
9. **EWI** — Italy

### Emerging Markets (7)
10. **EWT** — Taiwan
11. **EWZ** — Brazil
12. **INDA** — India
13. **FXI** — China
14. **EWY** — South Korea
15. **EWW** — Mexico
16. **EWH** — Hong Kong

**Why these 16?** All have AUM > $300M, are iShares MSCI-based (consistent methodology), have existed since at least 2012 (sufficient backtest history), and trade with reasonable bid/ask spreads. This gives you 9 developed + 7 emerging = good diversification without illiquidity risk.

---

## Dual Momentum Rules (Antonacci-Adapted)

### Step 1: Calculate 12-Month Total Returns (Monthly, End of Month)

For each of the 16 country ETFs, compute the trailing 12-month total return (price + dividends).

### Step 2: Relative Momentum — Rank Countries

Rank all 16 country ETFs by their 12-month total return from highest to lowest. Select the **top N** (see variants below).

### Step 3: Absolute Momentum — Go-to-Cash Filter

This is the critical risk management layer. Compare the selected country ETF(s) against the **absolute momentum benchmark**:

> **If the 12-month total return of the selected ETF > 12-month return of BIL (3-month T-bills), INVEST.**
>
> **If the 12-month total return of the selected ETF < 12-month return of BIL, GO TO CASH.**

### Step 4: Cash Position

When in cash, allocate to one of:
- **SGOV** (iShares 0-3 Month Treasury Bond ETF) — your current preferred cash vehicle
- **BIL** (SPDR 1-3 Month T-Bill ETF) — Antonacci's original benchmark
- **SHV** (iShares Short Treasury Bond ETF) — alternative

### Step 5: Rebalance Monthly

On the last trading day of each month, repeat steps 1-4.

---

## Go-to-Cash Trigger Options (Classic Antonacci + Variants)

### Option A: Classic Antonacci Absolute Momentum (Recommended)

**Trigger:** Selected country ETF's 12-month return < BIL's 12-month return

This is the purest implementation. The logic: if the best international country can't even beat T-bills over the trailing year, the risk/reward is unfavorable — go to cash.

**Pros:** Simple, historically effective, well-researched
**Cons:** Can be late to exit in fast crashes (12-month lookback is slow)

### Option B: Dual Lookback Absolute Momentum

**Trigger:** Selected country ETF's return is negative on BOTH a 12-month AND 6-month basis

Uses two lookback periods. Requires both to confirm before going to cash. This reduces whipsaws but slightly increases drawdown risk.

### Option C: Composite Absolute Momentum (Antonacci's CDM Variant)

**Trigger:** Average of 1-month, 3-month, 6-month, and 12-month returns < 0

Gary Antonacci explored this in his Composite Dual Momentum work. Instead of a single 12-month lookback, you average multiple timeframes. This is faster to react but slightly more prone to whipsaws.

### Option D: Aggregate International Absolute Momentum

**Trigger:** EFA (MSCI EAFE) or ACWX (MSCI ACWI ex-US) 12-month return < BIL 12-month return

Instead of using the individual country ETF as the trigger, use the broad international index. When the overall international market is below T-bills, go to cash for ALL positions. This is a "regime filter" approach.

**Pros:** Avoids being in a strong country during a global bear market
**Cons:** Could force you out of a strong country that's bucking the trend

### Option E: Majority Rules (Best for Multi-Country Portfolios)

**Trigger:** If >50% of the 16 country ETFs have 12-month returns below BIL, go to cash

This is a breadth-based signal. When the majority of countries are underperforming cash, the global environment is hostile.

---

## Strategy Configuration: Top 7 Countries, Equal-Weight

### Why Top 7?
- **Diversification:** 7 countries out of 16 means ~44% of the universe, enough to capture the momentum effect without diluting into mediocre performers
- **Capacity:** Each sleeve is ~14.3% of the portfolio — large enough to matter, small enough that any single country blowup is contained
- **Robustness:** Country momentum research (Asness, Moskowitz, Pedersen) shows the top tercile captures most of the premium. Top 7 of 16 is approximately the top 44% — right in that sweet spot

### Why Equal-Weight?
Antonacci's entire philosophy is that the **signal** (which countries to own) is where the alpha comes from, not the sizing. Equal-weight is:
- **Robust:** No optimization, no curve-fitting, no parameter sensitivity
- **Simple:** 1/7 = ~14.3% per slot. If a slot fails absolute momentum, that 14.3% goes to SGOV
- **Anti-fragile:** You don't overweight a country just because it had the best momentum — the gap between #1 and #7 in any given month could be noise
- **Consistent with Antonacci's research:** His GEM model is 100% in one asset at a time (equal-weight with N=1). Scaling to N=7 with equal-weight is the natural extension

### Weighting Alternatives Considered (and rejected)
| Method | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Equal-weight** | Simple, robust, no overfitting | Treats #1 same as #7 | **SELECTED** |
| Momentum-ranked tilt | Overweights strongest signal | Adds parameter (decay rate), marginal benefit | Reject |
| Inverse volatility | Risk-parity-lite, smoother | Penalizes EM momentum winners, adds complexity | Reject |
| Full risk-parity | Equal risk contribution | Requires covariance estimation, overkill | Reject |
| Market-cap weight | "Natural" weighting | Defeats purpose — just buy EFA | Reject |

### Portfolio Mechanics
- **7 equal slots** of ~14.3% each
- Each slot independently subject to absolute momentum filter
- Slots that fail → SGOV (cash)
- Possible states range from **100% invested** (all 7 pass) to **100% cash** (all 7 fail)
- Typical state in bull markets: 5-7 slots invested, 0-2 in cash
- Typical state in bear markets: 0-3 slots invested, 4-7 in cash

---

## Implementation Details

### Rebalancing Schedule
- **Frequency:** Monthly (last trading day of month)
- **Lookback:** 12-month total return (Antonacci's researched optimal)
- **Execution:** Market-on-close or next-day open

### Cash Benchmark
- **BIL** (SPDR Bloomberg 1-3 Month T-Bill ETF) — Antonacci's canonical benchmark
- You already use **SGOV** — functionally equivalent and arguably better

### Position Sizing
- **7 equal-weight slots** of ~14.3% each
- Each slot independently subject to absolute momentum filter
- Slots that fail absolute momentum → SGOV
- No leverage, no short positions

### Transaction Cost Considerations
- Tier 1 ETFs: negligible impact (0.01-0.03% spreads)
- Tier 2 ETFs: minimal impact
- Tier 3 ETFs: consider using limit orders, especially EWK/EDEN/NORW

---

## Backtest Considerations & Historical Context

### Antonacci's Research Findings
- 12-month lookback outperformed 1, 3, 6, and 9-month variants
- Absolute momentum reduced max drawdown from -60% to ~-20%
- The strategy was out of equities during most of 2008 and 2001-2002
- Annual turnover: ~200-400% (monthly decisions, but often stays put)

### Key Advantages of International-Only
- International markets are less correlated with each other than US sectors
- Country momentum has been documented as a robust factor (Asness, Moskowitz, Pedersen 2013)
- Emerging markets offer higher dispersion = more momentum alpha
- Avoids US concentration risk you may already have elsewhere

### Key Risks
- Currency risk embedded in all these ETFs (USD-denominated but foreign-currency exposed)
- Country-specific political/regulatory risk (e.g., China VIE structure, Turkey lira crises)
- Momentum crashes can be severe (2009 snap-back, 2020 COVID rotation)
- Absolute momentum trigger can lag in fast waterfall declines

---

## Final Strategy: Top 7, Equal-Weight, Classic Absolute Momentum

**Monthly process:**

1. On the last trading day of each month, calculate trailing 12-month total return for all 16 country ETFs and BIL
2. Rank all 16 by 12-month return, select the **Top 7**
3. For each of the 7 selected countries:
   - If its 12-month return > BIL's 12-month return → allocate **14.3%** to that country ETF
   - If its 12-month return ≤ BIL's 12-month return → allocate that **14.3%** to SGOV
4. Execute trades (sell any countries that dropped out of the top 7 or failed absolute momentum; buy new entries)
5. Repeat next month

**What this gives you:**
- 7 countries = enough diversification to avoid single-country catastrophe
- Equal-weight = no optimization risk, pure signal-driven
- Individual absolute momentum filters = graceful de-risking (you don't go 0-to-100% cash overnight; you bleed out of equities one sleeve at a time as countries fail)
- SGOV as cash = consistent with your existing infrastructure

---

## Quick Reference: Go-to-Cash Decision Tree

```
Month-End (Last Trading Day):
│
├─ Calculate 12-month total return for all 16 country ETFs + BIL
│
├─ Rank countries #1 through #16 by 12-month return
│
├─ Select Top 7
│
├─ For EACH of the 7 selected countries:
│   │
│   ├─ 12m return > BIL 12m return?
│   │   ├─ YES → Allocate 14.3% (1/7) to that country ETF
│   │   └─ NO  → Allocate 14.3% (1/7) to SGOV
│   │
│
├─ Countries ranked #8-#16: No allocation (sell if previously held)
│
└─ Execute: Sell dropped countries, buy new top-7 entries, flip
    failed abs-momentum slots to SGOV
```

---

## Data Sources for Live Implementation

- **Returns data:** Yahoo Finance, Bloomberg, or portfolio analytics platform
- **BIL returns:** FRED (3-month T-bill rate) or BIL ETF total return
- **ETF screener:** etfdb.com (your login: woody.wiegmann@potomac.com)
- **Country rankings:** etfdb.com/etfs/country/ has AUM and return leaderboards
- **Rebalancing tool:** Consider building a simple spreadsheet or Python script

---

*Strategy framework adapted from Gary Antonacci's "Dual Momentum Investing" (2014) and his Global Equities Momentum (GEM) research at optimalmomentum.com*
