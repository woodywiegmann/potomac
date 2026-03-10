# Commission Analysis: Potomac Defensive Bull Fund
## Account #1400 | Feb 1–20, 2026 (20 calendar days)

---

## What's Happening in This Fund

This is a **tactical / defensive bull strategy** that rotates between:
- Full S&P 500 exposure (via Vanguard S&P 500 fund shares, iShares S&P 500, and E-mini futures)
- Treasuries (BBLX 6M UST ETF) as a defensive position

The fund is executing through **3 separate brokers** for the same underlying exposure.

---

## Commission Summary

| Broker | Activity | Commissions | Fees |
|--------|----------|-------------|------|
| **JONES** | 2 BUYs — Vanguard S&P 500 (~$3.77B notional) | $29,764.69 | — |
| **RCM** | 4 futures trades — ESH6 E-mini S&P Mar26 (~$5B+ notional) | $41,043.80 | — |
| **WALLACH** | 1 BUY (UST ETF), 2 SELLs (iShares S&P, Vanguard S&P, ~$3.69B notional) | $28,195.66 | — |
| **TOTAL** | **20 days** | **$99,004.15** | |

### Annualized: ~$1.8M/year in commissions (this fund alone)

---

## Trade-Level Breakdown

### Broker JONES (Buying S&P 500 fund shares)
| Date | Security | Shares | Price | Notional | Commission | Comm/Notional |
|------|----------|--------|-------|----------|------------|---------------|
| 05-Feb | Vanguard S&P 500 | 2,930,060 | 636.27 | $1.86B | $14,650.30 | **0.08 bps** |
| 18-Feb | Vanguard S&P 500 | 3,022,678 | 631.96 | $1.91B | $15,114.39 | **0.08 bps** |

### Broker RCM (S&P 500 E-mini Futures — ESH6)
| Date | Action | Contracts | Price | Commission | Per Contract |
|------|--------|-----------|-------|------------|-------------|
| 04-Feb | Close (sell) | 7,283 | 6,911.50 | $10,196.20 | **$1.40** |
| 05-Feb | Open (buy) | 7,291 | 6,969.37 | $10,207.40 | **$1.40** |
| 11-Feb | Close (sell) | 7,291 | 6,963.39 | $10,207.40 | **$1.40** |
| 19-Feb | Open (buy) | 7,452 | 6,686.87 | $10,432.80 | **$1.40** |

### Broker WALLACH (Mixed — selling S&P, buying UST)
| Date | Security | Shares | Action | Notional | Commission |
|------|----------|--------|--------|----------|------------|
| 04-Feb | iShares S&P 500 | 2,646,955 | SELL | $1.83B | $13,234.78 |
| 10-Feb | Vanguard S&P 500 | 2,930,060 | SELL | $1.85B | $14,650.30 |
| 18-Feb | BBLX 6M UST ETF | 82,118 | BUY | $3.13M | $310.58 |

---

## Key Observations & Opportunities

### 1. Three Brokers for One Exposure — Why?

The fund is buying Vanguard S&P 500 through JONES, selling it through WALLACH, and
trading S&P futures through RCM. The same underlying position (S&P 500) is being
managed through 3 separate pipes.

**Questions to investigate:**
- Is there a best-execution reason for this split?
- Are the brokers offering different services (custody vs. execution vs. clearing)?
- Could consolidating execution reduce friction and improve fills?
- What does the reconciliation burden look like across 3 brokers?

### 2. The Futures Rotation Pattern

The RCM trades show a clear pattern: the fund is rapidly opening and closing
~7,300 E-mini S&P contracts. At $50/point × ~6,900 points, each contract
represents ~$345K of notional. 7,300 contracts ≈ **$2.5B notional per leg**.

The fund appears to be:
- Closing futures → buying fund shares (shifting from synthetic to physical S&P exposure)
- Selling fund shares → opening futures (shifting from physical to synthetic)

**Why this matters:** Each rotation generates commissions on BOTH the futures side
AND the fund share side. If the strategy requires this rotation, the question is
whether the timing and execution are optimal.

### 3. Commission Rates Are Reasonable Individually, But Volume Drives Cost

- Fund shares: ~0.08 bps on notional — very competitive
- Futures: $1.40/contract — industry standard for institutional

The issue isn't the per-trade rate, it's the **turnover**. The fund appears to be
doing full portfolio rotations multiple times per month. At this pace:
- ~$99K/month × 12 = **~$1.2M/year in commissions**
- That's on top of whatever management fee the fund charges

### 4. The BBLX Position Is Tiny Relative to the Fund

The $3.1M BBLX UST ETF buy is a rounding error compared to the $1.8B+ S&P positions.
If this is the "defensive" allocation, it's currently minimal — the fund is almost
entirely in S&P 500 exposure (hence "Bull" mode).

---

## Actionable Ideas for Your Role

### A. Build a Commission Tracker
Track monthly commissions by broker, by fund, by security. Turn this PDF report into
a time series. Show Dan the run rate and identify if certain months (rebalancing periods)
spike disproportionately.

### B. Execution Quality Analysis
For trades that happen on the same day across brokers (like the Feb 4-5 cluster):
- Compare fills to VWAP for that day
- Calculate implementation shortfall (decision price vs. execution price)
- Determine if splitting across brokers helped or hurt execution

### C. Futures vs. Physical Cost-Benefit
When the fund rotates between futures and fund shares, there are costs beyond commissions:
- Futures roll costs (basis, carry)
- Fund share bid-ask spreads (though NAV-based trades avoid this)
- Margin requirements on futures
Build a model showing the all-in cost of each exposure method.

### D. IBKR Paper Trading Tie-In
This is where your IBKR idea gets powerful. You could:
- Replicate this strategy in paper trading
- Test whether executing through a single broker (IBKR) with their algo suite
  (VWAP, TWAP, adaptive) produces better fills than the current 3-broker split
- Model the commission savings of consolidation
- Test alternative defensive instruments (e.g., S&P put spreads vs. going to cash/UST)

### E. Turnover Cost Reporting
Calculate total turnover cost as a drag on fund performance:
- Commissions: ~$1.2M/year (from this data)
- Market impact: estimate 1-3 bps per leg on $2B+ trades = potentially $400K-$1.2M/year
- Spread costs on futures rolls: varies, but 0.25-0.5 index points × 7,300 contracts × $50 = $91K-$183K per roll
- **Total execution drag could be $1.7M-$2.6M/year**
Present this as a % of fund AUM for context.
