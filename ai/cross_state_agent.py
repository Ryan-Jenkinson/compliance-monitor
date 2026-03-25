"""
Cross-State Pattern Agent.

Weekly analysis of bill clusters across states. Identifies:
  - Coordinated legislative campaigns (same bill language, same advocacy network)
  - Next-mover predictions (states that haven't acted where neighbors have)
  - Stage-advance clusters (multiple states advancing simultaneously)
  - Dominant sponsors / model-legislation sources

Runs weekly (Mondays). Output saved to DB + data/cross_state_report.html.
Run via: python run.py --cross-state  (or auto on Mondays in full pipeline)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .claude_client import ClaudeClient
from config.settings import Config
from subscribers.db import get_connection

logger = logging.getLogger(__name__)

_DB_PATH = Config.DB_PATH

# ── DB migration ────────────────────────────────────────────────────────────

def _ensure_table() -> None:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cross_state_reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date  TEXT NOT NULL,
            topic        TEXT NOT NULL,
            raw_json     TEXT NOT NULL DEFAULT '{}',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(report_date, topic)
        )
    """)
    conn.commit()
    conn.close()


# ── Data extraction ─────────────────────────────────────────────────────────

def _load_bill_data(topic: str) -> dict:
    """
    Pull structured bill data for a topic from the DB.
    Returns summary stats ready to feed to Claude.
    """
    conn = get_connection()

    # Bills by state + stage
    rows = conn.execute("""
        SELECT state, stage, status_label, COUNT(*) as cnt,
               GROUP_CONCAT(title, ' | ') as sample_titles,
               MAX(last_action_date) as latest_action
        FROM legiscan_bills
        WHERE topic = ? AND is_active = 1
        GROUP BY state, stage
        ORDER BY cnt DESC
    """, (topic,)).fetchall()

    by_state: dict = defaultdict(lambda: {"stages": {}, "total": 0, "latest_action": ""})
    for row in rows:
        state = row["state"]
        stage = row["stage"] or "unknown"
        by_state[state]["stages"][stage] = row["cnt"]
        by_state[state]["total"] += row["cnt"]
        if row["latest_action"] and row["latest_action"] > by_state[state]["latest_action"]:
            by_state[state]["latest_action"] = row["latest_action"]

    # Advanced bills (passed_one / advanced / enacted_watching)
    advanced = conn.execute("""
        SELECT state, stage, title, last_action, last_action_date, url
        FROM legiscan_bills
        WHERE topic = ? AND is_active = 1
          AND stage IN ('passed_one', 'advanced', 'enacted_watching')
        ORDER BY last_action_date DESC
        LIMIT 30
    """, (topic,)).fetchall()

    # Recent stage changes (last 14 days)
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    recent = conn.execute("""
        SELECT state, stage, title, last_action, last_action_date
        FROM legiscan_bills
        WHERE topic = ? AND is_active = 1
          AND last_action_date >= ?
          AND stage NOT IN ('introduced', 'unknown')
        ORDER BY last_action_date DESC
        LIMIT 20
    """, (topic, cutoff)).fetchall()

    conn.close()

    return {
        "topic": topic,
        "total_bills": sum(s["total"] for s in by_state.values()),
        "total_states": len(by_state),
        "by_state": {k: dict(v) for k, v in by_state.items()},
        "advanced_bills": [dict(r) for r in advanced],
        "recent_changes": [dict(r) for r in recent],
    }


# ── Claude prompt ────────────────────────────────────────────────────────────

_SYSTEM = """You are a legislative intelligence analyst specializing in state regulatory campaigns.
You understand how model legislation spreads, how advocacy networks coordinate across states,
and how to predict which states are likely to act next based on adoption patterns.
Your analysis is used by a compliance team at a US windows/doors manufacturer.
Be specific, data-driven, and actionable. Reference actual state names and bill counts."""

_PROMPT = """Analyze these {topic} legislative bill patterns across US states.

## Bill Data as of {today}

Total bills tracked: {total_bills} across {total_states} states

### Bills by State (stage breakdown)
{state_breakdown}

### Bills at Advanced Stages (passed one chamber, advanced, or enacted)
{advanced_bills}

### Recent Stage Changes (last 14 days)
{recent_changes}

---

Identify patterns and produce a JSON analysis:

{{
  "coordinated_campaigns": [
    {{
      "description": "Pattern description — what states are doing similar things",
      "states": ["XX", "YY", "ZZ"],
      "evidence": "Why this looks coordinated (similar timing, text, advocacy)",
      "company_relevance": "What this means for a US windows/doors manufacturer"
    }}
  ],
  "next_mover_predictions": [
    {{
      "state": "XX",
      "prediction": "Why this state is likely to act next",
      "trigger": "What would cause action (session timing, neighbor passing bill, etc.)",
      "urgency": "HIGH|MEDIUM|LOW"
    }}
  ],
  "stage_clusters": [
    {{
      "stage": "committee|passed_one|advanced",
      "states": ["XX", "YY"],
      "significance": "Why these states advancing simultaneously matters"
    }}
  ],
  "watch_list": [
    {{
      "state": "XX",
      "reason": "Why to watch closely right now",
      "action_needed": "What the company should do"
    }}
  ],
  "summary": "2-3 sentence overall assessment of the {topic} legislative landscape"
}}

Return JSON only. Be specific — use actual state names and bill counts from the data."""


def _build_prompt(topic: str, data: dict) -> str:
    state_lines = []
    for state, info in sorted(data["by_state"].items(),
                              key=lambda x: x[1]["total"], reverse=True)[:25]:
        stages_str = ", ".join(f"{s}:{c}" for s, c in info["stages"].items())
        state_lines.append(f"  {state}: {info['total']} bills ({stages_str})")

    advanced_lines = []
    for bill in data["advanced_bills"][:15]:
        advanced_lines.append(
            f"  [{bill['state']} / {bill['stage']}] {bill['title'][:70]} "
            f"({bill['last_action_date']})"
        )

    recent_lines = []
    for bill in data["recent_changes"][:10]:
        recent_lines.append(
            f"  [{bill['state']} → {bill['stage']}] {bill['title'][:60]} "
            f"({bill['last_action_date']})"
        )

    return _PROMPT.format(
        topic=topic,
        today=date.today().isoformat(),
        total_bills=data["total_bills"],
        total_states=data["total_states"],
        state_breakdown="\n".join(state_lines) or "  No data",
        advanced_bills="\n".join(advanced_lines) or "  None",
        recent_changes="\n".join(recent_lines) or "  None in last 14 days",
    )


# ── Persistence ─────────────────────────────────────────────────────────────

def _save_report(topic: str, analysis: dict, today: str) -> None:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        INSERT OR REPLACE INTO cross_state_reports (report_date, topic, raw_json)
        VALUES (?, ?, ?)
    """, (today, topic, json.dumps(analysis)))
    conn.commit()
    conn.close()


def get_latest_cross_state_report(topic: Optional[str] = None) -> list[dict]:
    """Return the most recent cross-state report(s), newest first."""
    _ensure_table()
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    if topic:
        rows = conn.execute(
            "SELECT * FROM cross_state_reports WHERE topic = ? "
            "ORDER BY report_date DESC LIMIT 1", (topic,)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM cross_state_reports
               WHERE report_date = (SELECT MAX(report_date) FROM cross_state_reports)
               ORDER BY topic"""
        ).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        try:
            d["analysis"] = json.loads(d["raw_json"])
        except Exception:
            d["analysis"] = {}
        results.append(d)
    return results


def _already_ran_this_week() -> bool:
    _ensure_table()
    # "This week" = last 6 days
    cutoff = (date.today() - timedelta(days=6)).isoformat()
    conn = sqlite3.connect(str(_DB_PATH))
    row = conn.execute(
        "SELECT report_date FROM cross_state_reports WHERE report_date >= ? LIMIT 1",
        (cutoff,)
    ).fetchone()
    conn.close()
    return bool(row)


# ── Main entry ───────────────────────────────────────────────────────────────

def run_cross_state_analysis(
    topics: Optional[list[str]] = None,
    force: bool = False,
) -> list[dict]:
    """
    Run cross-state pattern analysis for each topic.
    Skips if already ran this week (unless force=True).
    Returns list of {topic, analysis} dicts.
    """
    _ensure_table()

    if not force and _already_ran_this_week():
        logger.info("Cross-state analysis: already ran this week, skipping")
        return get_latest_cross_state_report()

    if topics is None:
        topics = ["PFAS", "EPR", "TSCA", "ForcedLabor", "ConflictMinerals"]

    client = ClaudeClient()
    today = date.today().isoformat()
    results = []

    for topic in topics:
        logger.info(f"Cross-state analysis: running for {topic}…")
        data = _load_bill_data(topic)

        if data["total_bills"] < 3:
            logger.info(f"  {topic}: too few bills ({data['total_bills']}), skipping")
            continue

        prompt = _build_prompt(topic, data)
        cache_key = f"cross_state_{topic}_{today}"

        try:
            response = client.complete_sonnet(
                prompt, system=_SYSTEM, cache_key=cache_key
            )
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            analysis = json.loads(text.strip())
        except Exception as e:
            logger.warning(f"  {topic}: Claude call failed: {e}")
            continue

        _save_report(topic, analysis, today)
        results.append({"topic": topic, "analysis": analysis})

        summary = analysis.get("summary", "")
        watch = analysis.get("watch_list", [])
        logger.info(f"  {topic}: {len(watch)} states on watch list")
        if summary:
            logger.info(f"  Summary: {summary[:120]}")

    _write_html_report(results, today)
    return results


# ── HTML report ─────────────────────────────────────────────────────────────

_TOPIC_COLORS = {
    "PFAS": "#C0392B",
    "EPR": "#0F766E",
    "TSCA": "#1565C0",
    "ForcedLabor": "#7C3AED",
    "ConflictMinerals": "#B45309",
}

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #F0F1F4; --surface: #FFFFFF; --border: #D8DBE0; --border-light: #E8EAED;
  --text-primary: #111318; --text-secondary: #4A4F5C; --text-muted: #7A8194;
  --red: #D63031; --red-bg: #FEF0F0; --red-border: #FACACA;
  --amber: #CB7B0A; --amber-bg: #FEF6E8; --amber-border: #F5DFA6;
  --green: #0F7B3F; --green-bg: #EEFAF3; --green-border: #B2E0C7;
  --blue: #1565C0; --blue-bg: #EBF3FD; --blue-border: #C0D5F0;
  --surface-dark: #1A1D23;
  --sans: 'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --mono: 'IBM Plex Mono', 'Consolas', monospace;
  --radius: 6px;
  --nav-width: 200px;
  --topbar-h: 55px;
  --statsbar-h: 38px;
}
html { font-size: 14px; scroll-behavior: smooth; }
body { background: var(--bg); font-family: var(--sans); color: var(--text-primary);
       line-height: 1.5; -webkit-font-smoothing: antialiased; }
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Topbar ── */
.cs-topbar {
  position: fixed; top: 0; left: 0; right: 0; height: var(--topbar-h);
  background: var(--surface-dark); display: flex; align-items: center; gap: 14px;
  padding: 0 24px; z-index: 300; border-bottom: 3px solid var(--amber);
}
.cs-topbar-back {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.85);
  border: 1px solid rgba(255,255,255,0.30); border-radius: 4px;
  padding: 4px 10px; text-decoration: none; transition: color 0.15s, border-color 0.15s, background 0.15s;
  white-space: nowrap;
}
.cs-topbar-back:hover { color: #fff; border-color: rgba(255,255,255,0.55); background: rgba(255,255,255,0.08); text-decoration: none; }
.cs-topbar-sep { width: 1px; height: 18px; background: rgba(255,255,255,0.20); flex-shrink: 0; }
.cs-topbar-title { font-weight: 700; font-size: 14px; color: #fff; letter-spacing: -0.01em; }
.cs-topbar-confidential {
  margin-left: auto; font-family: var(--mono); font-size: 10px;
  color: rgba(255,255,255,0.55); letter-spacing: .08em; text-transform: uppercase;
}
.cs-topbar-date { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.60); }

/* ── Stats bar ── */
.cs-statsbar {
  position: fixed; top: var(--topbar-h); left: 0; right: 0; height: var(--statsbar-h);
  background: #13151a; border-bottom: 1px solid rgba(255,255,255,0.07);
  display: flex; align-items: center; gap: 0; padding: 0 24px; z-index: 290;
  padding-left: calc(var(--nav-width) + 24px);
}
.cs-stat {
  display: flex; align-items: center; gap: 7px; padding: 0 18px;
  border-right: 1px solid rgba(255,255,255,0.07);
}
.cs-stat:first-child { padding-left: 0; }
.cs-stat:last-child { border-right: none; }
.cs-stat-val { font-family: var(--mono); font-size: 13px; font-weight: 700; color: #e0e2e8; }
.cs-stat-label { font-family: var(--mono); font-size: 10px; color: rgba(255,255,255,0.55);
                 letter-spacing: .05em; text-transform: uppercase; }
.cs-stat-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

/* ── Layout ── */
.cs-layout {
  display: flex;
  padding-top: calc(var(--topbar-h) + var(--statsbar-h));
  min-height: 100vh;
}

/* ── Left nav ── */
.cs-leftnav {
  position: fixed;
  top: calc(var(--topbar-h) + var(--statsbar-h));
  left: 0;
  width: var(--nav-width);
  height: calc(100vh - var(--topbar-h) - var(--statsbar-h));
  background: var(--surface-dark);
  border-right: 1px solid rgba(255,255,255,0.07);
  overflow-y: auto;
  z-index: 200;
  padding: 20px 0 40px;
}
.cs-nav-heading {
  font-family: var(--mono); font-size: 9px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: rgba(255,255,255,0.2);
  padding: 0 16px 10px; display: block;
}
.cs-nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; cursor: pointer; text-decoration: none;
  transition: background 0.12s; border-left: 3px solid transparent;
}
.cs-nav-item:hover { background: rgba(255,255,255,0.04); text-decoration: none; }
.cs-nav-item.cs-nav-active { border-left-color: var(--amber); background: rgba(203,123,10,0.08); }
.cs-nav-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.cs-nav-label { font-family: var(--mono); font-size: 11px; font-weight: 600;
                color: rgba(255,255,255,0.45); letter-spacing: .02em; flex: 1; }
.cs-nav-item.cs-nav-active .cs-nav-label { color: rgba(255,255,255,0.85); }
.cs-nav-badge {
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.35);
  border-radius: 10px; padding: 1px 6px; min-width: 18px; text-align: center;
}
.cs-nav-item.cs-nav-active .cs-nav-badge { background: rgba(203,123,10,0.25); color: var(--amber); }

/* ── Main content ── */
.cs-content {
  margin-left: var(--nav-width);
  flex: 1;
  padding: 32px 36px 80px;
  max-width: 960px;
}

/* ── Topic section ── */
.cs-topic-block {
  margin-bottom: 56px;
  scroll-margin-top: calc(var(--topbar-h) + var(--statsbar-h) + 20px);
}
.cs-topic-header {
  display: flex; align-items: baseline; gap: 16px;
  padding: 0 0 16px;
  border-bottom: 2px solid var(--border);
  margin-bottom: 20px;
}
.cs-topic-name {
  font-size: 28px; font-weight: 800; letter-spacing: -0.02em; line-height: 1;
}
.cs-topic-meta {
  display: flex; align-items: center; gap: 10px; margin-left: auto;
}
.cs-topic-date { font-family: var(--mono); font-size: 11px; color: var(--text-muted); }
.cs-watch-count-badge {
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  padding: 3px 9px; border-radius: 20px; white-space: nowrap;
}

/* ── Summary card ── */
.cs-summary-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 18px 22px; margin-bottom: 24px; position: relative;
}
.cs-summary-card::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0;
  width: 4px; border-radius: 4px 0 0 4px;
}
.cs-summary-text { font-size: 15px; line-height: 1.75; color: var(--text-secondary); }

/* ── Three-col grid ── */
.cs-three-col {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.cs-panel {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; display: flex; flex-direction: column;
}
.cs-panel-head {
  display: flex; align-items: center; gap: 7px;
  padding: 10px 14px; border-bottom: 1px solid var(--border-light);
  background: #FAFBFC;
}
.cs-panel-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.cs-panel-title {
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted);
}
.cs-panel-body { flex: 1; }

/* ── Watch list ── */
.cs-watch-item {
  display: flex; gap: 11px; align-items: flex-start;
  padding: 11px 14px; border-bottom: 1px solid var(--border-light);
}
.cs-watch-item:last-child { border-bottom: none; }
.cs-state-chip {
  display: inline-flex; align-items: center; justify-content: center;
  width: 36px; height: 36px;
  font-family: var(--mono); font-size: 11px; font-weight: 800;
  border-radius: 6px; flex-shrink: 0; border-width: 1px; border-style: solid;
}
.cs-watch-reason { font-size: 13px; color: var(--text-secondary); line-height: 1.5; margin-bottom: 3px; }
.cs-watch-action { font-size: 12px; color: var(--blue); font-style: italic; line-height: 1.4; }

/* ── Next movers ── */
.cs-mover-row {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 10px 14px; border-bottom: 1px solid var(--border-light);
}
.cs-mover-row:last-child { border-bottom: none; }
.cs-urgency-badge {
  display: inline-block; padding: 2px 6px;
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: .04em; border-radius: 3px; text-transform: uppercase;
  white-space: nowrap; flex-shrink: 0; margin-top: 1px;
}
.cs-urgency-badge.high { background: var(--red-bg); color: var(--red); border: 1px solid var(--red-border); }
.cs-urgency-badge.medium { background: var(--amber-bg); color: var(--amber); border: 1px solid var(--amber-border); }
.cs-urgency-badge.low { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-border); }
.cs-mover-state { font-family: var(--mono); font-size: 11px; font-weight: 700;
                  color: var(--text-primary); min-width: 26px; flex-shrink: 0; padding-top: 2px; }
.cs-mover-body { flex: 1; min-width: 0; }
.cs-mover-prediction { font-size: 13px; color: var(--text-secondary); line-height: 1.45; }
.cs-mover-trigger { font-size: 11px; color: var(--text-muted); margin-top: 3px; font-family: var(--mono); }

/* ── Stage clusters ── */
.cs-cluster-card {
  padding: 11px 14px; border-bottom: 1px solid var(--border-light);
}
.cs-cluster-card:last-child { border-bottom: none; }
.cs-cluster-stage { font-family: var(--mono); font-size: 9px; font-weight: 700;
                    letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted);
                    margin-bottom: 6px; }
.cs-cluster-states { display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 6px; }
.cs-state-badge {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 2px 6px;
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  border: 1px solid; border-radius: 3px;
}
.cs-cluster-sig { font-size: 13px; color: var(--text-secondary); line-height: 1.4; }

/* ── Coordinated campaigns ── */
.cs-campaigns-section { margin-bottom: 16px; }
.cs-campaigns-label {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
}
.cs-campaigns-label-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.cs-campaigns-label-text {
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted);
}
.cs-campaigns-label-line { flex: 1; height: 1px; background: var(--border); }
.cs-campaign-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; margin-bottom: 10px;
}
.cs-campaign-header {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  background: var(--blue-bg); border-bottom: 1px solid var(--blue-border);
  cursor: pointer;
}
.cs-campaign-states { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; }
.cs-campaign-toggle {
  width: 20px; height: 20px; flex-shrink: 0; display: flex;
  align-items: center; justify-content: center; color: var(--blue);
  font-size: 10px; transition: transform 0.2s;
}
.cs-campaign-body { display: none; }
.cs-campaign-body.cs-open { display: block; }
.cs-campaign-desc { padding: 12px 14px; font-size: 13.5px; color: var(--text-secondary); line-height: 1.6; }
.cs-campaign-relevance {
  padding: 10px 14px; background: var(--amber-bg);
  border-top: 1px solid var(--amber-border);
  font-size: 13px; color: var(--text-secondary); line-height: 1.55;
}
.cs-campaign-relevance strong {
  display: block; font-family: var(--mono); font-size: 9px;
  letter-spacing: .09em; text-transform: uppercase;
  color: var(--amber); margin-bottom: 4px;
}
.cs-campaign-evidence {
  padding: 8px 14px 12px;
  font-size: 11.5px; color: var(--text-muted); font-family: var(--mono); line-height: 1.5;
  border-top: 1px solid var(--border-light);
}

.cs-empty-panel { padding: 24px 14px; text-align: center; color: var(--text-muted);
                  font-family: var(--mono); font-size: 11px; }
.cs-empty-page { padding: 60px 24px; text-align: center; color: var(--text-muted);
                 font-family: var(--mono); font-size: 13px; }

/* ── Mobile tabs (hidden on desktop) ── */
.cs-mobile-tabs { display: none; }

/* ── Divider ── */
.cs-topic-divider {
  height: 1px; background: var(--border); margin: 0 0 56px;
}

/* ── Responsive ── */
@media (max-width: 900px) {
  :root { --nav-width: 0px; }
  .cs-leftnav { display: none; }
  .cs-statsbar { padding-left: 16px; }
  .cs-content { margin-left: 0; padding: 16px 16px 60px; }
  .cs-three-col { grid-template-columns: 1fr; }
  .cs-topbar { padding: 0 16px; }
  .cs-topbar-confidential { display: none; }
  .cs-mobile-tabs {
    display: flex; overflow-x: auto; scrollbar-width: none;
    background: var(--surface-dark);
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: 0 12px;
    position: sticky;
    top: calc(var(--topbar-h) + var(--statsbar-h));
    z-index: 180;
  }
  .cs-mobile-tabs::-webkit-scrollbar { display: none; }
  .cs-mobile-tab {
    display: inline-flex; align-items: center; padding: 9px 14px;
    font-family: var(--mono); font-size: 11px; font-weight: 600;
    color: rgba(255,255,255,0.4); letter-spacing: .04em; text-transform: uppercase;
    text-decoration: none; border-bottom: 2px solid transparent;
    white-space: nowrap; transition: color 0.15s, border-color 0.15s;
  }
  .cs-mobile-tab:hover { color: rgba(255,255,255,0.75); text-decoration: none; }
}
"""

_JS = """
(function() {
  var sections = document.querySelectorAll('.cs-topic-block');
  var navItems = document.querySelectorAll('.cs-nav-item');

  if (sections.length && navItems.length && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          var id = entry.target.id;
          navItems.forEach(function(n) {
            n.classList.toggle('cs-nav-active', n.getAttribute('href') === '#' + id);
          });
        }
      });
    }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 });
    sections.forEach(function(s) { io.observe(s); });
  }

  document.querySelectorAll('.cs-campaign-header').forEach(function(h) {
    h.addEventListener('click', function() {
      var body = h.nextElementSibling;
      var icon = h.querySelector('.cs-campaign-toggle');
      body.classList.toggle('cs-open');
      icon.style.transform = body.classList.contains('cs-open') ? '' : 'rotate(-90deg)';
    });
  });
})();
"""


def _write_html_report(results: list[dict], today: str) -> Path:
    report_path = Path(Config.DATA_DIR) / "cross_state_report.html"

    # ── Aggregate stats ──────────────────────────────────────────────────────
    total_watch = 0
    total_high = 0
    for item in results:
        a = item.get("analysis", {})
        total_watch += len(a.get("watch_list", []))
        total_high += sum(
            1 for m in a.get("next_mover_predictions", [])
            if (m.get("urgency") or "").upper() == "HIGH"
        )

    # ── Stats bar HTML ───────────────────────────────────────────────────────
    stats_html = (
        f'<div class="cs-stat">'
        f'<span class="cs-stat-val">{len(results)}</span>'
        f'<span class="cs-stat-label">Topics</span>'
        f'</div>'
        f'<div class="cs-stat">'
        f'<span class="cs-stat-dot" style="background:#D63031;"></span>'
        f'<span class="cs-stat-val">{total_watch}</span>'
        f'<span class="cs-stat-label">On Watch</span>'
        f'</div>'
        f'<div class="cs-stat">'
        f'<span class="cs-stat-dot" style="background:#D63031;"></span>'
        f'<span class="cs-stat-val">{total_high}</span>'
        f'<span class="cs-stat-label">High Urgency</span>'
        f'</div>'
        f'<div class="cs-stat">'
        f'<span class="cs-stat-val">{today}</span>'
        f'<span class="cs-stat-label">Report Date</span>'
        f'</div>'
    )

    # ── Left nav HTML ────────────────────────────────────────────────────────
    nav_items_html = '<span class="cs-nav-heading">Topics</span>'
    mobile_tabs_html = ''
    for item in results:
        topic = item["topic"]
        a = item.get("analysis", {})
        color = _TOPIC_COLORS.get(topic, "#6B7280")
        watch_count = len(a.get("watch_list", []))
        badge = f'<span class="cs-nav-badge">{watch_count}</span>' if watch_count else ""
        nav_items_html += (
            f'<a class="cs-nav-item" href="#{topic.lower()}" data-target="{topic.lower()}">'
            f'<span class="cs-nav-dot" style="background:{color};"></span>'
            f'<span class="cs-nav-label">{topic}</span>'
            f'{badge}'
            f'</a>'
        )
        mobile_tabs_html += (
            f'<a class="cs-mobile-tab" href="#{topic.lower()}">{topic}</a>'
        )

    # ── Per-topic sections ───────────────────────────────────────────────────
    sections_html = ""
    for item in results:
        topic = item["topic"]
        a = item.get("analysis", {})
        color = _TOPIC_COLORS.get(topic, "#6B7280")
        watch = a.get("watch_list", [])
        movers = sorted(
            a.get("next_mover_predictions", []),
            key=lambda m: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(
                (m.get("urgency") or "LOW").upper(), 3
            )
        )
        clusters = a.get("stage_clusters", [])
        campaigns = a.get("coordinated_campaigns", [])

        # Topic header
        watch_count = len(watch)
        badge_bg = f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.12)"
        count_badge = (
            f'<span class="cs-watch-count-badge" '
            f'style="background:{badge_bg};color:{color};border:1px solid {color}44;">'
            f'{watch_count} on watch</span>'
        ) if watch_count else ""

        header_html = (
            f'<div class="cs-topic-header">'
            f'<span class="cs-topic-name" style="color:{color};">{topic}</span>'
            f'<div class="cs-topic-meta">'
            f'{count_badge}'
            f'<span class="cs-topic-date">{today}</span>'
            f'</div>'
            f'</div>'
        )

        # Summary
        summary_html = ""
        if a.get("summary"):
            summary_html = (
                f'<div class="cs-summary-card" style="border-left-color:{color};">'
                f'<style>.cs-summary-card[style*="{color}"]::before{{background:{color};}}</style>'
                f'<p class="cs-summary-text">{a["summary"]}</p>'
                f'</div>'
            )

        # Watch list panel
        if watch:
            watch_items = ""
            for w in watch:
                action_html = (
                    f'<div class="cs-watch-action">\u2192 {w["action_needed"]}</div>'
                    if w.get("action_needed") else ""
                )
                watch_items += (
                    f'<div class="cs-watch-item">'
                    f'<div class="cs-state-chip" style="background:{badge_bg};color:{color};'
                    f'border-color:{color}44;">{w.get("state","?")}</div>'
                    f'<div>'
                    f'<div class="cs-watch-reason">{w.get("reason","")}</div>'
                    f'{action_html}'
                    f'</div>'
                    f'</div>'
                )
            watch_panel = (
                f'<div class="cs-panel">'
                f'<div class="cs-panel-head">'
                f'<span class="cs-panel-dot" style="background:var(--red);"></span>'
                f'<span class="cs-panel-title">Watch List</span>'
                f'</div>'
                f'<div class="cs-panel-body">{watch_items}</div>'
                f'</div>'
            )
        else:
            watch_panel = (
                f'<div class="cs-panel">'
                f'<div class="cs-panel-head">'
                f'<span class="cs-panel-dot" style="background:var(--red);"></span>'
                f'<span class="cs-panel-title">Watch List</span>'
                f'</div>'
                f'<div class="cs-empty-panel">No watch items</div>'
                f'</div>'
            )

        # Next movers panel
        if movers:
            mover_rows = ""
            for m in movers:
                urg = (m.get("urgency") or "LOW").lower()
                trigger_html = (
                    f'<div class="cs-mover-trigger">{m["trigger"]}</div>'
                    if m.get("trigger") else ""
                )
                mover_rows += (
                    f'<div class="cs-mover-row">'
                    f'<span class="cs-urgency-badge {urg}">{urg.upper()}</span>'
                    f'<div class="cs-mover-state">{m.get("state","?")}</div>'
                    f'<div class="cs-mover-body">'
                    f'<div class="cs-mover-prediction">{m.get("prediction","")}</div>'
                    f'{trigger_html}'
                    f'</div>'
                    f'</div>'
                )
            movers_panel = (
                f'<div class="cs-panel">'
                f'<div class="cs-panel-head">'
                f'<span class="cs-panel-dot" style="background:var(--amber);"></span>'
                f'<span class="cs-panel-title">Next Movers</span>'
                f'</div>'
                f'<div class="cs-panel-body">{mover_rows}</div>'
                f'</div>'
            )
        else:
            movers_panel = (
                f'<div class="cs-panel">'
                f'<div class="cs-panel-head">'
                f'<span class="cs-panel-dot" style="background:var(--amber);"></span>'
                f'<span class="cs-panel-title">Next Movers</span>'
                f'</div>'
                f'<div class="cs-empty-panel">No predictions</div>'
                f'</div>'
            )

        # Stage clusters panel
        if clusters:
            cluster_cards = ""
            for cl in clusters:
                badges = "".join(
                    f'<span class="cs-state-badge" '
                    f'style="background:{badge_bg};color:{color};border-color:{color}44;">'
                    f'{s}</span>'
                    for s in cl.get("states", [])
                )
                cluster_cards += (
                    f'<div class="cs-cluster-card">'
                    f'<div class="cs-cluster-stage">{cl.get("stage","").replace("_"," ")}</div>'
                    f'<div class="cs-cluster-states">{badges}</div>'
                    f'<div class="cs-cluster-sig">{cl.get("significance","")}</div>'
                    f'</div>'
                )
            clusters_panel = (
                f'<div class="cs-panel">'
                f'<div class="cs-panel-head">'
                f'<span class="cs-panel-dot" style="background:{color};"></span>'
                f'<span class="cs-panel-title">Stage Clusters</span>'
                f'</div>'
                f'<div class="cs-panel-body">{cluster_cards}</div>'
                f'</div>'
            )
        else:
            clusters_panel = (
                f'<div class="cs-panel">'
                f'<div class="cs-panel-head">'
                f'<span class="cs-panel-dot" style="background:{color};"></span>'
                f'<span class="cs-panel-title">Stage Clusters</span>'
                f'</div>'
                f'<div class="cs-empty-panel">No cluster data</div>'
                f'</div>'
            )

        three_col = (
            f'<div class="cs-three-col">'
            f'{watch_panel}{movers_panel}{clusters_panel}'
            f'</div>'
        )

        # Coordinated campaigns
        campaigns_html = ""
        if campaigns:
            cards_html = ""
            for c in campaigns:
                chips = "".join(
                    f'<span class="cs-state-badge" '
                    f'style="background:var(--blue-bg);color:var(--blue);border-color:var(--blue-border);">'
                    f'{s}</span>'
                    for s in c.get("states", [])
                )
                relevance_html = (
                    f'<div class="cs-campaign-relevance">'
                    f'<strong>Company Relevance</strong>'
                    f'{c["company_relevance"]}'
                    f'</div>'
                ) if c.get("company_relevance") else ""
                evidence_html = (
                    f'<div class="cs-campaign-evidence">{c["evidence"]}</div>'
                ) if c.get("evidence") else ""
                cards_html += (
                    f'<div class="cs-campaign-card">'
                    f'<div class="cs-campaign-header">'
                    f'<div class="cs-campaign-states">{chips}</div>'
                    f'<div class="cs-campaign-toggle">&#9660;</div>'
                    f'</div>'
                    f'<div class="cs-campaign-body cs-open">'
                    f'<div class="cs-campaign-desc">{c.get("description","")}</div>'
                    f'{evidence_html}'
                    f'{relevance_html}'
                    f'</div>'
                    f'</div>'
                )
            campaigns_html = (
                f'<div class="cs-campaigns-section">'
                f'<div class="cs-campaigns-label">'
                f'<span class="cs-campaigns-label-dot" style="background:var(--blue);"></span>'
                f'<span class="cs-campaigns-label-text">Coordinated Campaigns</span>'
                f'<div class="cs-campaigns-label-line"></div>'
                f'</div>'
                f'{cards_html}'
                f'</div>'
            )

        sections_html += (
            f'<section class="cs-topic-block" id="{topic.lower()}">'
            f'{header_html}'
            f'{summary_html}'
            f'{three_col}'
            f'{campaigns_html}'
            f'</section>'
            f'<div class="cs-topic-divider"></div>'
        )

    if not sections_html:
        sections_html = '<div class="cs-empty-page">No analysis available yet. Run: python run.py --cross-state</div>'

    # ── Final HTML ───────────────────────────────────────────────────────────
    html = (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Cross-State Legislative Intelligence \u2014 {today}</title>\n'
        f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        f'<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">\n'
        f'<style>{_CSS}</style>\n'
        f'</head>\n<body>\n'
        f'<header class="cs-topbar">'
        f'<a class="cs-topbar-back" href="preview_dashboard.html">\u2190 Dashboard</a>'
        f'<div class="cs-topbar-sep"></div>'
        f'<span class="cs-topbar-title">Cross-State Legislative Intelligence</span>'
        f'<span class="cs-topbar-confidential">Confidential Internal</span>'
        f'<span class="cs-topbar-date">{today}</span>'
        f'</header>\n'
        f'<div class="cs-statsbar">{stats_html}</div>\n'
        f'<div class="cs-mobile-tabs">{mobile_tabs_html}</div>\n'
        f'<div class="cs-layout">'
        f'<nav class="cs-leftnav">{nav_items_html}</nav>'
        f'<main class="cs-content">{sections_html}</main>'
        f'</div>\n'
        f'<script>{_JS}</script>\n'
        f'</body>\n</html>'
    )

    report_path.write_text(html, encoding="utf-8")

    # Archive copy
    archive_dir = Path(Config.DATA_DIR) / "cross_state_reports"
    archive_dir.mkdir(exist_ok=True)
    (archive_dir / f"cross_state_{today}.html").write_text(html, encoding="utf-8")

    logger.info(f"Cross-state report written to {report_path}")
    return report_path
