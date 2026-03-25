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

    _CSS = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #F4F5F7; --surface: #FFFFFF; --border: #D8DBE0; --border-light: #E8EAED;
      --text-primary: #111318; --text-secondary: #4A4F5C; --text-muted: #7A8194;
      --red: #D63031; --red-bg: #FEF0F0; --red-border: #FACACA;
      --amber: #CB7B0A; --amber-bg: #FEF6E8; --amber-border: #F5DFA6;
      --green: #0F7B3F; --green-bg: #EEFAF3; --green-border: #B2E0C7;
      --blue: #1565C0; --blue-bg: #EBF3FD;
      --surface-dark: #1A1D23;
      --sans: 'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      --mono: 'IBM Plex Mono', 'Consolas', monospace;
      --radius: 6px;
    }
    html { font-size: 14px; }
    body { background: var(--bg); font-family: var(--sans); color: var(--text-primary);
           line-height: 1.5; -webkit-font-smoothing: antialiased; }
    a { color: var(--blue); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .cs-topbar {
      position: fixed; top: 0; left: 0; right: 0; height: 52px;
      background: var(--surface-dark); display: flex; align-items: center; gap: 16px;
      padding: 0 24px; z-index: 200; border-bottom: 3px solid var(--amber);
    }
    .cs-topbar-title { font-weight: 700; font-size: 14px; color: #fff; letter-spacing: -0.01em; }
    .cs-topbar-sep { width: 1px; height: 18px; background: rgba(255,255,255,0.15); }
    .cs-topbar-label { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.4);
                       letter-spacing: .04em; text-transform: uppercase; }
    .cs-topbar-date { margin-left: auto; font-family: var(--mono); font-size: 11px;
                      color: rgba(255,255,255,0.35); }
    .cs-topbar-back {
      display: inline-flex; align-items: center; gap: 5px;
      font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.5);
      border: 1px solid rgba(255,255,255,0.12); border-radius: 4px;
      padding: 3px 9px; text-decoration: none; transition: color 0.15s, border-color 0.15s;
    }
    .cs-topbar-back:hover { color: #fff; border-color: rgba(255,255,255,0.3); text-decoration: none; }

    .cs-tab-nav-wrap {
      position: sticky; top: 52px; z-index: 100;
      background: var(--surface-dark); border-bottom: 1px solid rgba(255,255,255,0.08);
      padding: 0 24px;
    }
    .cs-tab-nav { display: flex; gap: 0; overflow-x: auto; scrollbar-width: none; }
    .cs-tab-nav::-webkit-scrollbar { display: none; }
    .cs-tab {
      display: inline-flex; align-items: center; padding: 10px 18px;
      font-family: var(--mono); font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.4);
      letter-spacing: .05em; text-transform: uppercase;
      background: none; border: none; border-bottom: 2px solid transparent;
      cursor: pointer; transition: color 0.15s, border-color 0.15s; white-space: nowrap;
    }
    .cs-tab:hover { color: rgba(255,255,255,0.75); }
    .cs-tab.cs-tab-active { color: var(--amber); border-bottom-color: var(--amber); }

    .cs-main { max-width: 1000px; margin: 0 auto; padding: 32px 24px 64px;
               padding-top: calc(52px + 44px + 32px); }

    .cs-topic-section { display: none; }
    .cs-topic-section.cs-active { display: block; }

    .cs-section-header { display: flex; align-items: center; gap: 10px; margin: 28px 0 14px; }
    .cs-section-dot { width: 7px; height: 7px; border-radius: 50%;
                      background: var(--amber); flex-shrink: 0; }
    .cs-section-label { font-family: var(--mono); font-size: 10px; font-weight: 700;
                        letter-spacing: .1em; text-transform: uppercase; color: var(--text-muted);
                        white-space: nowrap; }
    .cs-section-line { flex: 1; height: 1px; background: var(--border); }

    .cs-summary-card {
      background: var(--surface); border: 1px solid var(--border);
      border-left: 4px solid var(--amber);
      border-radius: 0 var(--radius) var(--radius) 0;
      padding: 18px 20px; margin-bottom: 4px;
    }
    .cs-summary-text { font-size: 14px; line-height: 1.7; color: var(--text-secondary); }

    .cs-watch-grid { display: flex; flex-direction: column; gap: 8px; }
    .cs-watch-item {
      background: var(--surface); border: 1px solid var(--border);
      border-left: 4px solid var(--red); border-radius: 0 var(--radius) var(--radius) 0;
      padding: 12px 16px; display: flex; gap: 12px; align-items: flex-start;
    }
    .cs-state-chip {
      display: inline-flex; align-items: center; justify-content: center;
      width: 32px; height: 32px; background: var(--red-bg); color: var(--red);
      font-family: var(--mono); font-size: 11px; font-weight: 700;
      border-radius: 4px; flex-shrink: 0; border: 1px solid var(--red-border);
    }
    .cs-watch-reason { font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; margin-bottom: 4px; }
    .cs-watch-action { font-size: 11.5px; color: var(--blue); font-style: italic; line-height: 1.4; }
    .cs-watch-action::before { content: '\2192  '; font-weight: 600; font-style: normal; }

    .cs-movers-table { background: var(--surface); border: 1px solid var(--border);
                       border-radius: var(--radius); overflow: hidden; }
    .cs-mover-row { display: flex; gap: 12px; align-items: flex-start; padding: 10px 14px;
                    border-bottom: 1px solid var(--border-light); }
    .cs-mover-row:last-child { border-bottom: none; }
    .cs-urgency-badge {
      display: inline-block; padding: 2px 6px;
      font-family: var(--mono); font-size: 9px; font-weight: 700;
      letter-spacing: .05em; border-radius: 3px; text-transform: uppercase;
      white-space: nowrap; flex-shrink: 0; margin-top: 1px;
    }
    .cs-urgency-badge.high { background: var(--red-bg); color: var(--red); border: 1px solid var(--red-border); }
    .cs-urgency-badge.medium { background: var(--amber-bg); color: var(--amber); border: 1px solid var(--amber-border); }
    .cs-urgency-badge.low { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-border); }
    .cs-mover-state { font-family: var(--mono); font-size: 12px; font-weight: 700;
                      color: var(--text-primary); min-width: 28px; flex-shrink: 0; padding-top: 1px; }
    .cs-mover-body { flex: 1; min-width: 0; }
    .cs-mover-prediction { font-size: 12.5px; color: var(--text-secondary); line-height: 1.4; }
    .cs-mover-trigger { font-size: 11px; color: var(--text-muted); margin-top: 3px; font-family: var(--mono); }

    .cs-campaign-grid { display: flex; flex-direction: column; gap: 10px; }
    .cs-campaign-card { background: var(--surface); border: 1px solid var(--border);
                        border-radius: var(--radius); overflow: hidden; }
    .cs-campaign-header { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
                          background: var(--blue-bg); border-bottom: 1px solid var(--border-light);
                          cursor: pointer; }
    .cs-campaign-states { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; }
    .cs-state-badge { display: inline-flex; align-items: center; justify-content: center;
                      padding: 2px 7px; background: var(--blue-bg); color: var(--blue);
                      font-family: var(--mono); font-size: 10px; font-weight: 700;
                      border: 1px solid rgba(21,101,192,0.25); border-radius: 3px; }
    .cs-campaign-desc { padding: 12px 14px; font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; }
    .cs-campaign-relevance { padding: 10px 14px; background: var(--amber-bg);
                             border-top: 1px solid var(--amber-border);
                             font-size: 12px; color: var(--text-secondary); line-height: 1.45; }
    .cs-campaign-relevance strong { display: block; font-family: var(--mono); font-size: 10px;
                                    letter-spacing: .07em; text-transform: uppercase;
                                    color: var(--amber); margin-bottom: 3px; }
    .cs-campaign-toggle { width: 20px; height: 20px; flex-shrink: 0; display: flex;
                          align-items: center; justify-content: center; color: var(--blue);
                          font-size: 11px; transition: transform 0.2s; }
    .cs-campaign-body { display: none; }
    .cs-campaign-body.cs-open { display: block; }

    .cs-cluster-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
    .cs-cluster-card { background: var(--surface); border: 1px solid var(--border);
                       border-radius: var(--radius); padding: 12px 14px; }
    .cs-cluster-stage { font-family: var(--mono); font-size: 10px; font-weight: 700;
                        letter-spacing: .07em; text-transform: uppercase; color: var(--text-muted);
                        margin-bottom: 6px; }
    .cs-cluster-states { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
    .cs-cluster-sig { font-size: 12px; color: var(--text-secondary); line-height: 1.4; }
    .cs-empty { padding: 40px 20px; text-align: center; color: var(--text-muted); font-size: 13px;
                font-family: var(--mono); }
    """

    # Build topic tabs
    tab_buttons = ""
    for i, item in enumerate(results):
        topic = item["topic"]
        active = " cs-tab-active" if i == 0 else ""
        tab_buttons += (
            f'<button class="cs-tab{active}" data-topic="{topic}" '
            f'onclick="csShowTopic(\'{topic}\')">{topic}</button>'
        )

    # Build per-topic sections
    sections = ""
    for i, item in enumerate(results):
        topic = item["topic"]
        a = item["analysis"]
        active = " cs-active" if i == 0 else ""

        # Summary
        summary_html = ""
        if a.get("summary"):
            summary_html = (
                f'<div class="cs-summary-card">'
                f'<p class="cs-summary-text">{a["summary"]}</p>'
                f'</div>'
            )

        # Watch list
        watch_html = ""
        watch = a.get("watch_list", [])
        if watch:
            items_html = ""
            for w in watch:
                action_html = (
                    f'<div class="cs-watch-action">{w["action_needed"]}</div>'
                    if w.get("action_needed") else ""
                )
                items_html += (
                    f'<div class="cs-watch-item">'
                    f'<div class="cs-state-chip">{w.get("state","?")}</div>'
                    f'<div><div class="cs-watch-reason">{w.get("reason","")}</div>{action_html}</div>'
                    f'</div>'
                )
            watch_html = (
                f'<div class="cs-section-header">'
                f'<div class="cs-section-dot" style="background:var(--red);"></div>'
                f'<span class="cs-section-label">Watch List</span>'
                f'<div class="cs-section-line"></div>'
                f'</div>'
                f'<div class="cs-watch-grid">{items_html}</div>'
            )

        # Next movers
        movers_html = ""
        movers = a.get("next_mover_predictions", [])
        if movers:
            rows_html = ""
            for m in movers:
                urg = (m.get("urgency") or "LOW").lower()
                trigger_html = (
                    f'<div class="cs-mover-trigger">{m["trigger"]}</div>'
                    if m.get("trigger") else ""
                )
                rows_html += (
                    f'<div class="cs-mover-row">'
                    f'<span class="cs-urgency-badge {urg}">{urg.upper()}</span>'
                    f'<div class="cs-mover-state">{m.get("state","?")}</div>'
                    f'<div class="cs-mover-body">'
                    f'<div class="cs-mover-prediction">{m.get("prediction","")}</div>'
                    f'{trigger_html}'
                    f'</div>'
                    f'</div>'
                )
            movers_html = (
                f'<div class="cs-section-header">'
                f'<div class="cs-section-dot" style="background:var(--amber);"></div>'
                f'<span class="cs-section-label">Next-Mover Predictions</span>'
                f'<div class="cs-section-line"></div>'
                f'</div>'
                f'<div class="cs-movers-table">{rows_html}</div>'
            )

        # Coordinated campaigns
        campaigns_html = ""
        campaigns = a.get("coordinated_campaigns", [])
        if campaigns:
            cards_html = ""
            for c in campaigns:
                chips = "".join(
                    f'<span class="cs-state-badge">{s}</span>'
                    for s in c.get("states", [])
                )
                relevance_html = (
                    f'<div class="cs-campaign-relevance">'
                    f'<strong>Company Relevance</strong>{c["company_relevance"]}'
                    f'</div>'
                    if c.get("company_relevance") else ""
                )
                cards_html += (
                    f'<div class="cs-campaign-card">'
                    f'<div class="cs-campaign-header" onclick="csCampaignToggle(this)">'
                    f'<div class="cs-campaign-states">{chips}</div>'
                    f'<div class="cs-campaign-toggle">&#9660;</div>'
                    f'</div>'
                    f'<div class="cs-campaign-body cs-open">'
                    f'<div class="cs-campaign-desc">{c.get("description","")}</div>'
                    f'{relevance_html}'
                    f'</div>'
                    f'</div>'
                )
            campaigns_html = (
                f'<div class="cs-section-header">'
                f'<div class="cs-section-dot" style="background:var(--blue);"></div>'
                f'<span class="cs-section-label">Coordinated Campaigns</span>'
                f'<div class="cs-section-line"></div>'
                f'</div>'
                f'<div class="cs-campaign-grid">{cards_html}</div>'
            )

        # Stage clusters
        clusters_html = ""
        clusters = a.get("stage_clusters", [])
        if clusters:
            cluster_cards = ""
            for cl in clusters:
                badges = "".join(
                    f'<span class="cs-state-badge">{s}</span>'
                    for s in cl.get("states", [])
                )
                cluster_cards += (
                    f'<div class="cs-cluster-card">'
                    f'<div class="cs-cluster-stage">{cl.get("stage","").replace("_"," ")}</div>'
                    f'<div class="cs-cluster-states">{badges}</div>'
                    f'<div class="cs-cluster-sig">{cl.get("significance","")}</div>'
                    f'</div>'
                )
            clusters_html = (
                f'<div class="cs-section-header">'
                f'<div class="cs-section-dot"></div>'
                f'<span class="cs-section-label">Stage Clusters</span>'
                f'<div class="cs-section-line"></div>'
                f'</div>'
                f'<div class="cs-cluster-grid">{cluster_cards}</div>'
            )

        sections += (
            f'<div class="cs-topic-section{active}" data-topic="{topic}">'
            f'{summary_html}{watch_html}{movers_html}{campaigns_html}{clusters_html}'
            f'</div>'
        )

    empty_html = '<div class="cs-empty">No analysis available yet. Run: python run.py --cross-state</div>'
    content = sections if sections else empty_html

    html = (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Cross-State Legislative Intelligence \u2014 {today}</title>\n'
        f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        f'<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700'
        f'&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">\n'
        f'<style>{_CSS}</style>\n'
        f'</head>\n<body>\n'
        f'<div class="cs-topbar">'
        f'<a class="cs-topbar-back" href="preview_dashboard.html">\u2190 Dashboard</a>'
        f'<div class="cs-topbar-sep"></div>'
        f'<span class="cs-topbar-title">Cross-State Legislative Intelligence</span>'
        f'<span class="cs-topbar-date">{today}</span>'
        f'</div>\n'
        f'<div class="cs-tab-nav-wrap"><nav class="cs-tab-nav">{tab_buttons}</nav></div>\n'
        f'<main class="cs-main">{content}</main>\n'
        f'<script>\n'
        f'function csShowTopic(t){{\n'
        f'  document.querySelectorAll(".cs-topic-section").forEach(e=>e.classList.remove("cs-active"));\n'
        f'  document.querySelectorAll(".cs-tab").forEach(e=>e.classList.remove("cs-tab-active"));\n'
        f'  var s=document.querySelector(".cs-topic-section[data-topic=\'"+t+"\']");\n'
        f'  var b=document.querySelector(".cs-tab[data-topic=\'"+t+"\']");\n'
        f'  if(s)s.classList.add("cs-active"); if(b)b.classList.add("cs-tab-active");\n'
        f'}}\n'
        f'function csCampaignToggle(h){{\n'
        f'  var body=h.nextElementSibling; var icon=h.querySelector(".cs-campaign-toggle");\n'
        f'  body.classList.toggle("cs-open");\n'
        f'  icon.style.transform=body.classList.contains("cs-open")?"":"rotate(-90deg)";\n'
        f'}}\n'
        f'</script>\n'
        f'</body>\n</html>'
    )

    report_path.write_text(html, encoding="utf-8")

    # Archive copy
    archive_dir = Path(Config.DATA_DIR) / "cross_state_reports"
    archive_dir.mkdir(exist_ok=True)
    (archive_dir / f"cross_state_{today}.html").write_text(html, encoding="utf-8")

    logger.info(f"Cross-state report written to {report_path}")
    return report_path
