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

def _write_html_report(results: list[dict], today: str) -> Path:
    report_path = Path(Config.DATA_DIR) / "cross_state_report.html"

    sections = ""
    for item in results:
        topic = item["topic"]
        a = item["analysis"]
        sections += f'<h2 style="color:#0F766E;font-size:15px;margin:24px 0 8px;">{topic}</h2>'

        if a.get("summary"):
            sections += f'<p style="font-size:13px;color:#374151;margin:0 0 12px;">{a["summary"]}</p>'

        # Watch list
        watch = a.get("watch_list", [])
        if watch:
            sections += '<h3 style="font-size:12px;color:#991b1b;margin:12px 0 6px;">Watch List</h3>'
            for w in watch:
                action_html = ""
                if w.get("action_needed"):
                    action_html = "<br><em style='font-size:11px;color:#666;'>" + w["action_needed"] + "</em>"
                sections += (
                    f'<div style="padding:6px 10px;border-left:3px solid #D63031;'
                    f'background:#fef0f0;margin-bottom:6px;border-radius:0 4px 4px 0;">'
                    f'<strong style="font-size:12px;">{w.get("state","")}</strong>'
                    f'<span style="font-size:11px;color:#374151;"> — {w.get("reason","")}</span>'
                    f'{action_html}'
                    f'</div>'
                )

        # Next movers
        movers = a.get("next_mover_predictions", [])
        if movers:
            sections += '<h3 style="font-size:12px;color:#92400e;margin:12px 0 6px;">Next-Mover Predictions</h3>'
            for m in movers:
                urgency_color = {"HIGH": "#D63031", "MEDIUM": "#CB7B0A", "LOW": "#0F7B3F"}.get(m.get("urgency",""), "#718096")
                sections += (
                    f'<div style="padding:6px 10px;margin-bottom:4px;font-size:11px;'
                    f'border:1px solid #e5e7eb;border-radius:4px;">'
                    f'<span style="font-weight:700;color:{urgency_color};">{m.get("state","")}</span>'
                    f' — {m.get("prediction","")}'
                    f'</div>'
                )

        # Coordinated campaigns
        campaigns = a.get("coordinated_campaigns", [])
        if campaigns:
            sections += '<h3 style="font-size:12px;color:#1e40af;margin:12px 0 6px;">Coordinated Campaigns</h3>'
            for c in campaigns:
                states_str = ", ".join(c.get("states", []))
                sections += (
                    f'<div style="padding:6px 10px;margin-bottom:4px;font-size:11px;'
                    f'border:1px solid #bfdbfe;border-radius:4px;background:#eff6ff;">'
                    f'<strong>{states_str}</strong> — {c.get("description","")}'
                    f'</div>'
                )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Cross-State Pattern Analysis — {today}</title>
<style>
  body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        max-width:860px;margin:40px auto;padding:0 20px;color:#111827;}}
  h1 {{font-size:20px;color:#0F766E;margin-bottom:4px;}}
  .meta {{font-size:12px;color:#6b7280;margin-bottom:24px;}}
</style></head>
<body>
<h1>Cross-State Legislative Pattern Analysis</h1>
<div class="meta">Generated {today} · Weekly on Mondays · <code>python run.py --cross-state</code></div>
{sections if sections else '<p style="color:#6b7280;">No analysis available yet.</p>'}
</body></html>"""

    report_path.write_text(html, encoding="utf-8")

    # Archive copy
    archive_dir = Path(Config.DATA_DIR) / "cross_state_reports"
    archive_dir.mkdir(exist_ok=True)
    (archive_dir / f"cross_state_{today}.html").write_text(html, encoding="utf-8")

    logger.info(f"Cross-state report written to {report_path}")
    return report_path
