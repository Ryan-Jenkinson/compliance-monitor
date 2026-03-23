# CLAUDE.md — Compliance Monitor

## What this project is

An automated regulatory intelligence tool that monitors PFAS, EPR, REACH, and TSCA regulatory developments and delivers weekly email briefings. The system scrapes 17 sources, runs a 3-stage Claude pipeline to filter/summarize/write, then renders and sends an HTML newsletter.

The company context: a US manufacturer dealing with fluoropolymer product coatings and supply chain compliance. Direct product risk (PFAS in coatings) and supply chain risk (suppliers, components) are both tracked.

## Who reads the briefings

A small, expert internal compliance team:
- The developer/compliance lead (me)
- Senior manager (my boss)
- Director (occasionally)

These people have been receiving PFAS and compliance briefings for a long time. They know the regulatory landscape, the active campaigns, the key deadlines, and the company's current strategy. **Do not treat them as beginners.**

## How to write the exec summary and section strategy notes

**Executive summary:** Write as a "here's what changed in the last 7 days" update. The rolling window is the last 7 days ending on the day of generation (Monday briefing = since last Monday, Friday = since last Friday). Do not re-explain background context. Do not restate known major deadlines as if they're breaking news. The person sharing this in a meeting will provide verbal framing — the summary is a tight expert update, not a press release.

**Section notes / company strategy sections (bottom of each topic section):** Same principle. If there are real developments: highlight them and connect to strategic implications concisely. If nothing material changed in the last 7 days: briefly acknowledge it, then restate the most recent version of the suggested plan for that area (e.g. "No major updates this week — continue monitoring X and prepare Y ahead of the Q3 review"). Never leave a strategy section empty; never explain what PFAS is.

**Tone:** Trusted colleague catching up experts who are pressed for time.

## Architecture

```
run.py                        # main entry point
├── scrapers/                 # 17 source scrapers (federal register, EPA, ECHA, state agencies, etc.)
├── processors/               # dedup + keyword pre-filter before Claude
├── ai/
│   ├── claude_client.py      # Anthropic SDK wrapper, per-day caching
│   ├── summarizer.py         # 3-stage pipeline orchestrator
│   └── prompts.py            # system prompt + 3 stage prompts
├── newsletter/
│   ├── renderer.py           # Jinja2 + CSS inlining (premailer)
│   └── templates/            # base.html, exec_summary.html, topic_section.html
├── delivery/
│   ├── gmail_sender.py       # SMTP via Gmail app password
│   └── state_map_generator.py # PFAS state map → GitHub Pages
├── subscribers/              # SQLite-backed subscriber management + CLI
├── config/
│   ├── settings.py           # env vars, typed Config
│   └── topics.yaml           # 4 topics with keywords, search terms, company relevance narratives
└── scheduler/                # cron_setup.py — 6 AM daily cron job
```

## AI pipeline (3 stages)

- **Stage 1 — Haiku:** Fast filter, drops non-regulatory noise
- **Stage 2 — Sonnet:** Per-topic summaries with company impact analysis
- **Stage 3 — Sonnet:** Executive summary across all topics

Cache stored in `data/cache/claude/` by date. Scraper cache TTL: 12 hours.

## Run modes

```bash
python run.py               # full pipeline: scrape → summarize → render → send
python run.py --dry-run     # scrape + summarize, print, no email
python run.py --preview     # render HTML and open in browser
python run.py --force       # override "already sent today" guard
python run.py --test-email addr@example.com   # send to test address only
```

## Rolling article window

Articles tracked in `data/sent_articles.json`. 5-day window: articles older than 5 days are dropped, newer ones carried over to avoid repeat content. Each article marked as "new" or "carried-over" with age.

## Key config

- Topics, keywords, and company relevance narratives: `config/topics.yaml`
- Environment: `.env` (see `.env.example`) — needs `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
- Database: `data/compliance.db` (SQLite) — subscribers, topic preferences, send logs, regulation state tracking

## Subscriber management

```bash
python subscribers/cli.py list
python subscribers/cli.py add email@example.com --first-name Name
python subscribers/cli.py remove email@example.com
```

## Scheduler

```bash
python scheduler/cron_setup.py install   # 6 AM daily cron
python scheduler/cron_setup.py status
python scheduler/cron_setup.py remove
```

macOS note: requires System Settings > Battery > Schedule to wake at 5:55 AM.

## GitHub Pages

The rendered newsletter and PFAS state map are pushed to a GitHub Pages repo at `/tmp/compliance-maps` during each run.

## Dependencies

Key: `anthropic`, `requests`, `beautifulsoup4`, `feedparser`, `jinja2`, `premailer`, `pyyaml`, `python-dotenv`, `schedule`, `playwright` (for JS-heavy state agency sites).
