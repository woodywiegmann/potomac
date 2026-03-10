# John Woodside Inc — Potomac Research Codebase

AI agent swarm for quantitative research and fund management at Potomac Fund Management. This repo contains **all agents (employees)**, scripts, configs, and instructions to run everything on a new machine.

---

## Quick setup (new computer)

1. **Clone or download** this repo into a folder (e.g. `Potomac`).
2. **Python 3.10+** and pip:
   ```powershell
   pip install -r requirements.txt
   ```
3. **Environment variables** (create a `.env` or set in shell; never commit secrets):
   - `GITHUB_TOKEN` — for pulling/storing from GitHub ([create token](https://github.com/settings/tokens), scope: `repo`)
   - `OPENAI_API_KEY` — for Daily Wrap and podcast transcription
   - `ANTHROPIC_API_KEY` — optional, if using Claude for wraps
   - `ELEVENLABS_API_KEY` — optional, for voice clone
   - `QUANTCONNECT_API_KEY` / `QUANTCONNECT_ORGANIZATION_ID` — for backtest deploy (see QuantConnect)
4. **Optional**: Install [Git](https://git-scm.com/download/win) and [FFmpeg](https://ffmpeg.org/) (for transcribing long audio).

---

## Employees (agents) — who runs what

Each “employee” is a Cursor rule or skill (invoked in chat) or a standalone script/service. Use this table to know **who to ask** and **what to run**.

| Employee | Type | Where | How to use |
|----------|------|--------|------------|
| **COO** | Cursor (this AI) | — | Ask for architecture, workflows, agent coordination, and “what do I run for X?” |
| **Woody's Brain** | Cursor rule | `.cursor/rules/woodys-brain.mdc` | Always applied; defines voice, tone, and style for all written output. |
| **The Quant (Jack)** | Cursor rule + skill | `.cursor/rules/quant-researcher.mdc`, `.cursor/skills/backtest-strategy/SKILL.md` | In Cursor: “@quant-researcher” or “use backtest-strategy skill.” Build backtests, deploy to QuantConnect, use `honest_backtest.py`. |
| **The ETF Wizard** | Cursor rule + skill | `.cursor/rules/etf-wizard.mdc`, `.cursor/skills/etf-screen/SKILL.md` | In Cursor: “@etf-wizard” or “screen ETFs / TLH.” CLI: `low_beta_screener.py`, `overlap_analyzer.py`, `tlh_tracker.py`, `fee_analyzer.py`. |
| **The Presenter** | Cursor rule | `.cursor/rules/presentation-wizard.mdc` | In Cursor: “@presentation-wizard” for slides, one-pagers, Word docs, Potomac branding. |
| **The Memo Writer** | Cursor rule | `.cursor/rules/memo-writer.mdc` | In Cursor: “@memo-writer” for trade concept memos and research specs. |
| **Daily Wrap** | Standalone service | `agents/daily_wrap/` | Run `python agents/daily_wrap/daily_wrap_service.py` (needs `OPENAI_API_KEY`). See [Daily Wrap](#daily-wrap) below. |
| **Voice Clone** | Standalone service | `agents/voice_clone/` | Run `python agents/voice_clone/voice_service.py` (needs ElevenLabs). See [Voice Clone](#voice-clone) below. |
| **Transcriber** | Script | `agents/transcribe_podcasts.py` | Run `python agents/transcribe_podcasts.py` to transcribe audio in `agents/style_corpus/samples/audio/` (needs `OPENAI_API_KEY`, FFmpeg for long files). |

**Org context** (roster, sleeves, tech stack) is in `.cursor/rules/john-woodside-inc.mdc` — load that in Cursor so any new chat has full context.

---

## How to use each piece

### Daily Wrap

- **Purpose:** Generate daily market commentary in Woody’s voice with Potomac’s lens.
- **Run:**
  ```bash
  cd agents/daily_wrap
  python daily_wrap_service.py
  ```
- **Options:** `--date 2026-03-05`, `--voice` (add audio), `--dry-run` (data only, no LLM).
- **Config:** `agents/daily_wrap/config.yaml` (LLM provider, tickers, output dir).
- **Needs:** `OPENAI_API_KEY` (or Anthropic if configured).

### Voice Clone

- **Purpose:** Text-to-speech in Woody’s voice via ElevenLabs.
- **Run:**
  ```bash
  cd agents/voice_clone
  python voice_service.py tts "Your script here"
  ```
- **Config:** `agents/voice_clone/config.yaml` (voice_id, API key via env).
- **Needs:** `ELEVENLABS_API_KEY`; upload audio samples to ElevenLabs to get `voice_id`.

### Transcriber (podcasts → text)

- **Purpose:** Transcribe audio files for the style corpus (and voice training).
- **Run:**
  ```bash
  python agents/transcribe_podcasts.py
  ```
- **Input:** Audio in `agents/style_corpus/samples/audio/`. Output: `agents/style_corpus/samples/podcast_*.txt`.
- **Needs:** `OPENAI_API_KEY`, FFmpeg for files &gt; 25 MB.

### The Quant (Jack) — backtests and QuantConnect

- **Purpose:** Strategy research, local backtests, deploy to QuantConnect.
- **In Cursor:** Invoke “backtest-strategy” skill or quant-researcher rule; reference `honest_backtest.py` for realistic assumptions (T+1 lag, open execution, costs).
- **Key scripts:**
  - `honest_backtest.py` — reusable honest backtest module (use this for all new strategies).
  - `graduated_penta_honest.py` — Penta regime example using honest backtest.
  - `sector_valmom_project_brief.md`, `penta_jmom_replica_brief.md` — project briefs for Jack.
- **Deploy to QC:** Use `qc_*.py` deploy scripts; set `QUANTCONNECT_API_KEY` and org ID.

### ETF Wizard — screening and TLH

- **In Cursor:** Use etf-wizard rule or etf-screen skill.
- **CLI:**
  - `python low_beta_screener.py` — low-beta candidates + TLH pairs.
  - `python overlap_analyzer.py ETF1 ETF2` — overlap.
  - `python tlh_tracker.py scan` / `harvest` / `log`.
  - `python fee_analyzer.py` — fee analysis.

### Excel price feed

- **Purpose:** Download market data for all Potomac-relevant tickers to one Excel file.
- **Run:**
  ```bash
  python download_excel_price_feed.py
  ```
- **Options:** `--tickers SPY,QQQ,...`, `--start`, `--end`, `--ohlc`. See `Excel_Price_Feed_COO_Briefing.md`.

### GitHub pull / store

- **Purpose:** Pull repo/file data from GitHub or store data (Gists, repo files) without Git CLI.
- **Run:**
  ```bash
  # List repos (set GITHUB_TOKEN first)
  python github_pull_data.py
  python github_pull_data.py --repo owner/name --out repo.json
  # Store a file into a repo
  python github_pull_data.py --store-file owner/repo path/in/repo.txt --in localfile.txt -m "Update"
  # Create a Gist
  python github_pull_data.py --store-gist notes.txt --in data.txt
  ```
- See `GitHub_Connect_COO_Briefing.md`.

---

## Key folders and files

| Path | Contents |
|------|----------|
| `.cursor/rules/*.mdc` | Cursor rules: woodys-brain, quant-researcher, etf-wizard, presentation-wizard, memo-writer, john-woodside-inc |
| `.cursor/skills/*/SKILL.md` | Skills: backtest-strategy, daily-wrap, etf-screen |
| `agents/daily_wrap/` | Daily Wrap service, config, templates |
| `agents/voice_clone/` | Voice clone service and config |
| `agents/style_corpus/` | Podcast transcripts and samples for voice/style |
| `agents/transcribe_podcasts.py` | Whisper transcription script |
| `honest_backtest.py` | Shared honest backtest module (T+1, costs, open execution) |
| `download_excel_price_feed.py` | Excel price feed for full ticker set |
| `github_pull_data.py` | GitHub API pull/store (no Git required) |
| `requirements.txt` | Python dependencies |
| `sector_valmom_project_brief.md`, `penta_jmom_replica_brief.md` | Strategy briefs for The Quant |
| `penta_signals_indicator.pine` | TradingView Penta indicator (reference for backtests) |

---

## Four sleeves (Systematic Alpha)

- **CRDBX Core** — 1114-driven sector rotation.
- **Defensive Equity** — low-beta stocks + LEAP puts (`low_beta_screener.py`, `put_options_calculator.py`).
- **International Tactical** — 40-ETF dual momentum + composite risk (`intl_composite_signals.py`, `qc_intl_composite_deploy.py`).
- **Gold Digger** — gold trend (`qc_golddigger_deploy.py`).

---

## After you return

1. Clone or re-download this repo on your main machine.
2. Set env vars again (token, OpenAI, etc.).
3. In Cursor, open this folder and ensure `.cursor/rules/john-woodside-inc.mdc` is applied so the COO and all employees are in context.
4. Run any script or agent from the table and sections above.

For upload instructions (pushing this codebase to GitHub from a machine that has the files), see **UPLOAD_TO_GITHUB.md**.
