# Trade Concepts for Testing — Brief Memo  
**POTOMAC FUND MANAGEMENT | February 2026**

*Obviously I don't have full transparency into the trading signals, so excuse any ideas that are stupid.*

---

## IDEA 1: Replace ARKK with QQQJ in CRTOX

ARKK's discretionary management adds uncontrolled variance to CRTOX's signal-driven framework. QQQJ (Nasdaq Next Gen 100, passive, 0.15% ER) removes manager drift. Benefits: ~60 bps expense reduction (0.75% → 0.15%), same signals and entry/exit dates, no indicator changes—a cleaner, cheaper, more predictable instrument.

---

## IDEA 2: Risk-Off Convexity Enhancement

Replace 100% SGOV (cash anchor) during risk-off with instruments that profit from the conditions triggering our defensive posture.

- **Alternatives:** CAOS (tail-risk puts) + DBMF (trend-following) + SGOV, or HEQT (hedged equity) + DBMF + SGOV.
- **Rationale:** DBMF adds positive carry and crisis alpha via trend-following. CAOS adds tail-risk convexity through put-spread overlay. Different failure modes provide complementary protection.

**173 Risk-Off Days — Comparative Performance**

| Metric        | SGOV (current) | 50/50 SGOV/CAOS | EqWt 3-Way | 15H/15D/70S |
|---------------|-----------------|-----------------|------------|-------------|
| Annualized    | +5.21%          | +6.74%          | +8.39%     | +7.92%      |
| Geometric     | +3.64%          | +4.71%          | +5.85%     | +5.56%      |
| Volatility    | 0.24%           | 2.56%           | 4.48%      | 2.55%       |
| Beta to S&P   | 0.0005          | 0.002           | 0.07       | 0.10        |
| Incremental   | —               | +1.07%          | +2.21%     | +1.92%      |

*(EqWt 3-Way = CAOS + DBMF + SGOV; 15H/15D/70S = 15% HEQT + 15% DBMF + 70% SGOV.)*

---

## IDEA 3: Systematic Tax-Loss Harvesting on Sector Rotations

On each signal-driven rotation, screen exiting lots for unrealized losses. Sell loss lots first, immediately buy the swap ETF to maintain exposure. Track wash sale windows (30 days) cross-account. Every rotation is a TLH opportunity; significant tax alpha is expected.

**Top harvesting pairs:** ARKK/QQQJ, URNM/URA, SIL/SILJ, COPX/CPER, XME/PICK, SMH/SOXX.  
**Estimated tax alpha:** 0.5–1.5% annually in taxable accounts via 1–2 random monthly checks.

**Example positions (unrealized loss → swap, same sector):** SIL → SILJ/SLVP (silver miners); XME → PICK/GNR (metals & mining); ARKK → QQQJ/QQQ (growth/innovation); ILF → EWZ+EWW (Latin America); SMH → SOXX/XSD (semiconductors); IBB/ITA → XBI/PPA (biotech/aerospace).
