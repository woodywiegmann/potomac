---
name: daily-wrap
description: Generate daily market commentary wraps in Woody's voice with Potomac's lens. Use when the user asks for a market wrap, daily commentary, market recap, or wants to run the daily wrap agent.
---

# The Daily Wrap — Market Commentary Workflow

## Quick Start

Run the daily wrap service:

```bash
cd agents/daily_wrap
python daily_wrap_service.py
```

Options:
- `--date 2026-03-05` — generate for a specific date
- `--voice` — also produce audio via voice clone
- `--dry-run` — fetch data only, skip LLM

## Configuration

Edit `agents/daily_wrap/config.yaml` to:
- Switch LLM provider (OpenAI or Anthropic)
- Add/remove tickers from any category
- Enable voice clone integration
- Change output directory

## Manual Wrap Workflow

If writing a wrap manually instead of using the service:

1. Pull data: indices, VIX, yields, gold, sectors, international
2. Assess regime: risk-on or risk-off? Which Freeburg/composite signals are flashing?
3. Check each sleeve: CRDBX, Defensive, International Tactical, Gold Digger
4. Identify sector leadership rotation and what it implies
5. Write in Woody's voice (see `.cursor/rules/woodys-brain.mdc`):
   - Lead with a thesis, not a data dump
   - Be opinionated — "courage over convention"
   - Close with a punchy Bottom Line

## Existing Signal Scripts (for deeper context)

Reference these scripts in the Potomac folder for signal data:
- `intl_composite_signals.py` — 40-ETF composite risk signals
- `freeburg_signals.py` — Freeburg-Nelson regime identification
- `riskoff_daily.py`, `riskoff_full.py` — risk-off signal analysis
- `intl_risk_dashboard.py` — international risk dashboard
