---
name: etf-screen
description: ETF screening, comparison, and TLH swap pair identification workflow. Use when screening ETFs, comparing expense ratios, analyzing fund overlap, or identifying tax loss harvesting opportunities.
---

# ETF Screening & Analysis Workflow

## Quick Workflows

### Screen for Low-Beta Candidates

```bash
python low_beta_screener.py
```

Outputs `low_beta_candidates.csv` with beta, market cap, earnings, and sector TLH pairs.

### Run Correlation Screen

```bash
python crtox_correlation_screen.py
```

Outputs `crtox_corr_screen_results.csv` with pairwise correlations.

### Analyze Holdings Overlap

```bash
python overlap_analyzer.py [ETF1] [ETF2]
```

### Scan for TLH Opportunities

```bash
python tlh_tracker.py scan
python tlh_tracker.py harvest    # Execute harvests
python tlh_tracker.py log        # View harvest history
```

### Analyze Fees

```bash
python fee_analyzer.py
```

## Manual ETF Comparison Workflow

1. **Define the question**: replacement candidate, new sleeve addition, or TLH swap?
2. **Pull data**: `yf.Ticker(symbol).info` for expense ratio, AUM, holdings count
3. **Compare metrics**:

```python
import yfinance as yf
import pandas as pd

tickers = ["VOO", "IVV", "SPLG", "SPY"]
for t in tickers:
    info = yf.Ticker(t).info
    print(f"{t}: ER={info.get('annualReportExpenseRatio','N/A')}, "
          f"AUM=${info.get('totalAssets',0)/1e9:.1f}B")
```

4. **Check overlap**: do the ETFs hold the same underlying stocks?
5. **Verify TLH safety**: are they "substantially identical" for wash sale purposes?
6. **Report**: table with ticker, ER, AUM, tracking error, and recommendation

## Key Decision Framework

| Question | Tool |
|----------|------|
| Is this ETF too expensive? | Fee analyzer — flag if > 40bps |
| Does this overlap with existing holdings? | Overlap analyzer |
| Can I use this for TLH? | Check swap pair tables in `.cursor/rules/etf-wizard.mdc` |
| Does this add diversification? | Correlation screen |
| Is the beta low enough for Defensive sleeve? | Low-beta screener (threshold: 0.70) |
