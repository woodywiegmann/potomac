# Research Role Playbook — Actionable Quant Ideas for Fund Ops
**Prepared for: Woody Wiegmann | Reporting to: Dan Russo**

---

## 1. Expense Ratio Optimization (Your ARKK → QQQJ Swap, Scaled Up)

Your instinct on QQQJ is solid. ARKK charges 75bps; QQQJ is ~15bps for similar innovation/growth-tilted exposure with better diversification (100 names vs ARKK's concentrated 30-35). That's 60bps of drag eliminated per dollar allocated.

**Scale this into a systematic process:**

| Action | Detail |
|--------|--------|
| **Full holdings audit** | Pull every position across all custodians. Flag any fund/ETF charging >40bps. For each, identify a comparable replacement at <20bps. |
| **Overlap analysis** | Use tools like ETF Research Center or Morningstar X-Ray to check if multiple holdings in the same account are buying the same underlying stocks. Redundant exposure = wasted fees. |
| **Mutual fund → ETF conversion** | Where possible, swap share-class mutual funds (often 50-100bps+) for equivalent ETFs (often 3-10bps). Example: VFIAX (4bps) vs VOO (3bps) is marginal, but PIMCO Total Return mutual fund (76bps) → AGG (3bps) or BND (3bps) is massive. |
| **Build a "fee budget"** | Create a weighted-average expense ratio for each model portfolio. Track it quarterly. Set a target (e.g., bring blended ER from 35bps to 20bps). This is a tangible, reportable metric Dan can present. |

**Quick-win candidates to investigate:**

- Any actively managed large-cap US equity fund → VOO/IVV/SPLG (3bps)
- Any active international fund → IXUS (7bps) or VEA/IEFA
- Any active bond fund → AGG/BND/SCHZ
- Thematic/story funds (like ARKK) → broader, cheaper alternatives (QQQJ, VGT, FTEC)

---

## 2. Trade Execution Improvements

### A. Block Trading / Model-Based Rebalancing
If you're placing the same trades across dozens of accounts individually, you're leaving money on the table via worse fills and wasted time.

- **Action:** Work with each custodian to enable block/batch trading if not already in use. Schwab, Fidelity, Pershing all support this through their RIA platforms.
- **Impact:** Better average fills, less market impact, massive time savings.

### B. Execution Timing
- Avoid trading in the first and last 15 minutes of the session (widest spreads, most volatility).
- For large rebalances, use VWAP or TWAP execution if custodian allows, or at minimum split large orders.
- **Track slippage:** Compare the price you intended vs. the fill you got. Even a few bps of consistent slippage across thousands of trades is real money.

### C. Rebalancing Triggers (Threshold-Based vs Calendar-Based)
- Calendar-based rebalancing (quarterly) is lazy and leaves drift on the table between periods.
- **Proposal:** Implement drift-based rebalancing triggers. If any asset class drifts more than ±3-5% from target, flag for rebalance. This is more tax-efficient AND keeps risk closer to target.
- Build a simple dashboard (even in Excel/Google Sheets) that pulls allocations and flags drift. Automate with custodian data exports.

---

## 3. Cash Drag Analysis

Uninvested cash sitting in accounts is one of the most underappreciated drags on performance.

- **Action:** Pull cash balances across all accounts. Calculate total AUM in cash. Quantify the drag (cash earning ~4-5% in money market vs. the expected return of the target allocation, say 8-10% for a 60/40).
- **Deliverable:** A report showing total cash drag in dollar terms. If $5M is sitting in cash across accounts earning 4.5% when it should be invested earning 9%, that's ~$225K/year of opportunity cost.
- **Fix:** Set up systematic sweeps or invest cash within 48 hours of receipt. Use ultra-short bond ETFs (SGOV, BIL, SHV) as cash proxies if needed for liquidity.

---

## 4. Tax-Loss Harvesting Protocol

This is the single highest-value activity most RIAs under-execute.

### Build a Systematic TLH Engine:
1. **Daily/weekly screen:** Identify positions with unrealized losses >$1,000 (or whatever threshold makes sense given account size and trading costs).
2. **Swap pairs:** Pre-define tax-loss harvesting swap pairs that are similar but NOT substantially identical (wash sale safe):
   - SPY ↔ IVV ↔ VOO ↔ SPLG (S&P 500 — these are all fine to swap between)
   - VEA ↔ IEFA ↔ SPDW (Developed international)
   - VWO ↔ IEMG ↔ SPEM (Emerging markets)
   - AGG ↔ BND ↔ SCHZ (US aggregate bond)
   - QQQ ↔ QQQM (Nasdaq 100 — note QQQM is cheaper at 15bps vs QQQ's 20bps)
3. **Wash sale tracking:** Build a tracking sheet across accounts. If you sell SPY at a loss in Account A, you cannot buy SPY (or substantially identical) in Account B within 30 days. Cross-account wash sale violations are common audit findings.
4. **Quantify savings:** Track realized losses harvested per quarter. Present as a "tax alpha" metric.

---

## 5. Holdings-Level Intelligence

### A. Factor Exposure Audit
Use a tool like Portfolio Visualizer, Bloomberg PORT, or even Morningstar to decompose factor exposures across your models:
- Are you getting unintended value/growth tilts?
- Is your "diversified" portfolio actually all loading on the same momentum factor?
- Are your international holdings just tracking US megacaps with foreign domicile?

**Action:** Run a factor regression (Market, Size, Value, Momentum, Quality) on each model portfolio. Identify and eliminate uncompensated factor bets.

### B. Sector/Geographic Concentration
- Pull the look-through holdings of all ETFs/funds in each model.
- Aggregate sector weights. You may find you're 35% tech without realizing it because QQQ + VGT + ARKK all overlap heavily in AAPL/MSFT/NVDA.
- Same for geographic: many "international" funds are 50%+ in companies that derive most revenue from the US.

### C. Duration/Credit Quality (Fixed Income)
- Map out the duration and credit quality of every fixed income holding.
- Ensure duration matches client time horizons (don't have 7-year duration bonds for clients who need money in 2 years).
- Identify if you're being paid for credit risk or just taking it for free.

---

## 6. Wire & Operations Process Improvements

### A. Wire Template Library
- Create standardized wire templates for every recurring destination (fund companies, custodian-to-custodian, client banks).
- Pre-populate ABA numbers, account numbers, and beneficiary details.
- Reduces errors and processing time from ~15 min/wire to ~3 min.

### B. Custodian Reconciliation
- Build a weekly reconciliation process: compare your internal records (portfolio management system) to custodian statements.
- Flag discrepancies >$100. Common issues: pending trades, dividend timing, fee debits.
- This catches errors before clients see them.

### C. Process Documentation
- Document every recurring process (wire initiation, rebalancing, new account setup, fee billing) as a step-by-step SOP.
- This makes you indispensable AND makes it possible to delegate to the Junior Research Analyst.

---

## 7. Quantitative Tools to Build

These are things you can build with Python, Excel, or even Google Sheets to add immediate value:

| Tool | Complexity | Impact |
|------|-----------|--------|
| **Expense Ratio Tracker** | Low | Track blended ER across models over time |
| **Drift Monitor** | Low-Med | Flag accounts that have drifted beyond thresholds |
| **Cash Drag Report** | Low | Quantify uninvested cash across all accounts |
| **TLH Scanner** | Medium | Identify harvestable losses daily/weekly |
| **Overlap Analyzer** | Medium | Holdings-level overlap between funds in same portfolio |
| **Trade Execution Log** | Low | Track intended vs. actual fill prices, measure slippage |
| **Factor Attribution Dashboard** | Med-High | Decompose portfolio returns into factor contributions |

---

## 8. High-Impact Ideas to Pitch

### A. Direct Indexing (for larger accounts, $250K+)
Instead of holding SPY/VOO, hold the individual S&P 500 stocks directly. This enables:
- Continuous tax-loss harvesting at the individual stock level (10-20x more harvesting opportunities)
- Custom exclusions (ESG screens, concentrated stock avoidance)
- Zero expense ratio on the equity sleeve
- Platforms: Parametric, Aperio (BlackRock), or Fidelity/Schwab's native direct indexing tools

### B. Fixed Income Ladder vs Fund
For clients with >$500K in bonds, consider building an individual bond ladder instead of using bond funds:
- No management fees
- Known cash flows (maturity dates match spending needs)
- No interest rate risk if held to maturity
- Better tax management (selective lot selling)

### C. Systematic Options Overlay (Advanced)
For appropriate clients (large taxable accounts with concentrated stock):
- Covered call writing on concentrated positions to generate income
- Protective put strategies to manage downside
- Collars to lock in gains while deferring taxes
- This requires compliance sign-off but can be a significant value-add

### D. Securities-Based Lending Awareness
When clients need liquidity, selling positions triggers taxes. Borrowing against the portfolio may be cheaper after tax. Know your custodians' SBL programs and rates.

---

## 9. Metrics to Track & Report

Establish these as your personal KPIs to demonstrate value:

1. **Blended expense ratio** — target reduction in bps, track monthly
2. **Tax losses harvested** — dollar value per quarter
3. **Cash drag reduction** — % of AUM uninvested, target <1%
4. **Rebalancing efficiency** — % of accounts within drift tolerance
5. **Trade execution quality** — average slippage in bps
6. **Wire processing time** — average minutes per wire, error rate
7. **Process documentation** — # of SOPs created/updated

---

## 10. First 30 Days — Priority Actions

| Week | Action |
|------|--------|
| **1** | Get full read access to all custodian platforms. Pull complete holdings across all accounts. |
| **1** | Map every fund/ETF held with its expense ratio, AUM allocated, and identify the top 10 most expensive. |
| **2** | Build the expense ratio tracker. Present first "fee savings" opportunities to Dan. |
| **2** | Document the wire initiation process end-to-end. |
| **3** | Run overlap analysis on the top 3 model portfolios. Present findings. |
| **3** | Build the cash drag report. Quantify the number. |
| **4** | Propose a systematic TLH protocol with swap pairs. Get buy-in. |
| **4** | Build the drift monitor. Set up weekly alerts. |

---

*"The goal isn't to be busy. It's to find the $50,000/year in drag that nobody is looking for, eliminate it, and make it visible."*
