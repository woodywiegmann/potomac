"""
The Daily Wrap — Automated Market Commentary Agent
===================================================
Generates a Potomac-flavored daily market wrap with Woody's personal spin.

Usage:
    python daily_wrap_service.py                # Generate today's wrap
    python daily_wrap_service.py --date 2026-03-05  # Specific date
    python daily_wrap_service.py --voice         # Also generate audio via voice clone

Requires:
    pip install yfinance pandas numpy pyyaml openai
    Set OPENAI_API_KEY (or ANTHROPIC_API_KEY) environment variable.
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import yfinance as yf

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
TEMPLATE_PATH = SCRIPT_DIR / "templates" / "market_wrap_template.md"
POTOMAC_DIR = SCRIPT_DIR.parent.parent

STYLE_PROMPT = """You are Woody Wiegmann (@RuleByPowerLaw), quant research analyst at Potomac Fund
Management and host of the Courage Over Convention podcast.

VOICE RULES:
- NEVER be alarmist about single-day moves. A VIX spike is a symptom, not a revelation.
  Don't write "this is what separates" anything. One day doesn't make a regime. Observe,
  contextualize, ask what it means structurally — or say it's noise and move on.
- Use sports and pop culture metaphors naturally (Mighty Ducks, basketball, Arnold movies).
  These aren't decorations — they're how you explain complex ideas accessibly.
- Be irreverent. "That dog don't hunt." "Dude's clearly an idiot." Real person energy, not
  a compliance-approved newsletter. Humor is mandatory.
- Think in systems, not narratives. "People think about everything in linear narratives unless
  they deliberately avoid it. This is why people disregard systematic trend."
- Trend following is religion. Convexity, positive skew, indirect tactics. #winbylosingless.
- Question what the consensus is missing. Don't just report what happened — ask why the crowd
  might be wrong about what it means.
- Reference the four sleeves (CRDBX Core, Defensive Equity, International Tactical, Gold Digger)
  but only when they're actually relevant to today's tape.
- Cite real thinkers: Parker, Hoffstein, McCullough, Freeburg, Taleb, Sun Tzu, Epsilon Theory.
- End with something to THINK about, not a summary. A question, a structural observation, or
  a thesis that challenges the reader.

NEVER DO:
- Generic "markets were mixed today" filler
- Breathless alarm about single-day VIX moves or index drops
- Corporate hedge-speak ("we remain cautiously optimistic")
- Sound like Bloomberg terminal prose or CNBC anchor copy
- Attribute causation to single events without structural context"""


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_market_data(config: dict, target_date: str) -> dict:
    """Fetch price data for all configured tickers."""
    end = pd.Timestamp(target_date) + timedelta(days=1)
    start = pd.Timestamp(target_date) - timedelta(days=10)

    all_tickers = []
    for category in ["indices", "risk_gauges", "commodities", "international", "sectors", "sleeve_proxies"]:
        for item in config["market_data"].get(category, []):
            all_tickers.append(item["ticker"])

    raw = yf.download(
        tickers=all_tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=False,
        progress=False,
        threads=True,
    )

    if raw.empty:
        raise RuntimeError("Yahoo Finance returned no data. Markets may be closed.")

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": all_tickers[0]})

    closes = closes.ffill()

    results = {}
    for category in ["indices", "risk_gauges", "commodities", "international", "sectors", "sleeve_proxies"]:
        results[category] = {}
        for item in config["market_data"].get(category, []):
            ticker = item["ticker"]
            name = item["name"]
            if ticker in closes.columns and len(closes[ticker].dropna()) >= 2:
                last = closes[ticker].dropna().iloc[-1]
                prev = closes[ticker].dropna().iloc[-2]
                pct_change = ((last - prev) / prev) * 100
                results[category][name] = {
                    "ticker": ticker,
                    "last": round(float(last), 2),
                    "prev_close": round(float(prev), 2),
                    "change_pct": round(float(pct_change), 2),
                }

    return results


def format_market_table(data: dict, title: str) -> str:
    """Format a category of market data into a markdown table."""
    lines = [f"| {title} | Last | Change |", "|---|---|---|"]
    for name, vals in data.items():
        chg = vals["change_pct"]
        arrow = "+" if chg >= 0 else ""
        lines.append(f"| {name} | {vals['last']:,.2f} | {arrow}{chg:.2f}% |")
    return "\n".join(lines)


def build_data_summary(market_data: dict) -> str:
    """Build the full data context string for the LLM."""
    sections = []

    sections.append("## Index Performance")
    sections.append(format_market_table(market_data.get("indices", {}), "Index"))

    sections.append("\n## Risk Gauges")
    sections.append(format_market_table(market_data.get("risk_gauges", {}), "Gauge"))

    sections.append("\n## Commodities")
    sections.append(format_market_table(market_data.get("commodities", {}), "Commodity"))

    sections.append("\n## International")
    sections.append(format_market_table(market_data.get("international", {}), "Region"))

    sections.append("\n## Sectors")
    sections.append(format_market_table(market_data.get("sectors", {}), "Sector"))

    sections.append("\n## Sleeve Proxies")
    sections.append(format_market_table(market_data.get("sleeve_proxies", {}), "Sleeve"))

    # Derive risk-on/risk-off heuristic
    vix_data = market_data.get("risk_gauges", {}).get("VIX", {})
    sp_data = market_data.get("indices", {}).get("S&P 500", {})
    gold_data = market_data.get("commodities", {}).get("Gold", {})

    regime_signals = []
    if vix_data:
        vix_level = vix_data.get("last", 20)
        if vix_level > 25:
            regime_signals.append(f"VIX elevated at {vix_level:.1f} (risk-off signal)")
        elif vix_level < 15:
            regime_signals.append(f"VIX complacent at {vix_level:.1f} (risk-on, but watch for vol compression snap)")
        else:
            regime_signals.append(f"VIX neutral at {vix_level:.1f}")

    if sp_data:
        sp_chg = sp_data.get("change_pct", 0)
        if abs(sp_chg) > 1.5:
            regime_signals.append(f"S&P moved {sp_chg:+.2f}% — meaningful single-day move")

    if gold_data:
        gold_chg = gold_data.get("change_pct", 0)
        if gold_chg > 1.0:
            regime_signals.append(f"Gold up {gold_chg:+.2f}% — hard-asset bid, potential risk-off")

    if regime_signals:
        sections.append("\n## Regime Signals")
        for sig in regime_signals:
            sections.append(f"- {sig}")

    return "\n".join(sections)


def generate_wrap_with_llm(data_summary: str, target_date: str, config: dict) -> str:
    """Send data to the LLM and get back a Woody-style market wrap."""
    provider = config["llm"]["provider"]
    model = config["llm"]["model"]
    temperature = config["llm"]["temperature"]
    max_tokens = config["llm"]["max_tokens"]

    user_prompt = f"""Write today's Daily Market Wrap for {target_date}.

Here is the raw market data:

{data_summary}

Write a complete market wrap using this structure:
1. **The Tape** — Lead with the headline narrative. What happened and WHY it matters through Potomac's lens.
2. **Risk Gauges** — VIX, yields, credit. What the fear/greed gauges are telling us.
3. **Sleeve Check** — Brief status on each of the four Systematic Alpha sleeves (CRDBX Core, Defensive Equity, International Tactical, Gold Digger). Which sleeves are earning their keep today?
4. **Sector Leadership** — Who's leading, who's lagging, and what it implies for regime.
5. **International Pulse** — Developed vs EM, any notable divergences.
6. **The Bottom Line** — One punchy paragraph. Give the reader a thesis, not a summary.

Keep it under 800 words. Be opinionated. Have a point of view."""

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": STYLE_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=STYLE_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def send_to_voice_clone(text: str, config: dict, output_path: Path) -> None:
    """Send the wrap text to the voice clone service for audio generation."""
    import requests

    url = config["voice_clone"]["service_url"]
    audio_path = output_path.with_suffix(".mp3")

    try:
        resp = requests.post(url, json={"text": text, "output_format": "mp3"}, timeout=120)
        resp.raise_for_status()
        audio_path.write_bytes(resp.content)
        print(f"Audio saved: {audio_path}")
    except Exception as e:
        print(f"Voice clone failed (non-fatal): {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="The Daily Wrap — Market Commentary Agent")
    parser.add_argument("--date", default=None, help="Target date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--voice", action="store_true", help="Also generate audio via voice clone service")
    parser.add_argument("--dry-run", action="store_true", help="Fetch data only, skip LLM generation")
    args = parser.parse_args()

    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    config = load_config()

    print(f"=== The Daily Wrap — {target_date} ===")
    print("Fetching market data...")

    market_data = fetch_market_data(config, target_date)
    data_summary = build_data_summary(market_data)

    if args.dry_run:
        print("\n--- DATA SUMMARY (dry run) ---")
        print(data_summary)
        return

    print("Generating wrap with LLM...")
    wrap_text = generate_wrap_with_llm(data_summary, target_date, config)

    output_dir = SCRIPT_DIR / config["output"]["directory"]
    output_dir.mkdir(exist_ok=True)

    filename = config["output"]["filename_format"].format(date=target_date)
    output_path = output_dir / filename

    header = f"# Daily Market Wrap — {target_date}\n## Potomac Fund Management | Woody Wiegmann\n\n---\n\n"
    footer = f"\n\n---\n\n*Generated by The Daily Wrap agent | Data: Yahoo Finance | {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"

    output_path.write_text(header + wrap_text + footer, encoding="utf-8")
    print(f"Wrap saved: {output_path}")

    if args.voice and config["voice_clone"]["enabled"]:
        print("Sending to voice clone service...")
        send_to_voice_clone(wrap_text, config, output_path)
    elif args.voice:
        print("Voice clone is disabled in config. Enable it in config.yaml to generate audio.")

    print("Done.")


if __name__ == "__main__":
    main()
