"""
Director's Devil's Advocate Agent.

Plays the role of a skeptical-but-constructive Director of Compliance
reviewing the dashboard. Asks the hard questions a real director would ask:

  - What is this actually telling me?
  - What should I do with this information?
  - What questions does it raise but not answer?
  - What's missing that I'd expect to see?
  - What's noise vs. signal?
  - Where am I getting real value vs. just volume?

Runs weekly (Mondays, or on-demand). Output is saved to dashboard_critiques
and surfaced in a dashboard panel so the team can see how the dashboard is
improving over time against the same questions.

The critique also drives the development backlog — suggestions from the
director become tickets for what to build next.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .claude_client import ClaudeClient
from config.settings import Config

logger = logging.getLogger(__name__)

_DB_PATH = Config.DB_PATH

_SYSTEM = """You are a Director of Compliance at a mid-size US manufacturer of windows and doors.
You have 15 years of regulatory compliance experience. You are sharp, direct, and results-oriented.
You do not have patience for dashboards that show information without enabling action.
You have seen many compliance monitoring tools that look impressive but fail to answer the
question: "What do I actually need to do today?"

Your job right now is to review a compliance intelligence dashboard that your team has built.
Be honest. Be specific. Reference actual numbers and data you see. Point out what's genuinely
useful AND what's falling short. Your feedback will directly drive what gets built next."""

_PROMPT = """Review this compliance intelligence dashboard. I need your honest assessment.

## Dashboard State as of {today}

### Pipeline Output
- Total articles this cycle: {total_articles}
- HIGH urgency: {high_count} | MEDIUM: {medium_count} | LOW: {low_count}
- Topics covered: {topics_covered}

### Per-Topic Summary
{topic_summaries}

### Deadline Status
- Total tracked deadlines: {total_deadlines}
- Next deadline: {next_deadline}
- Overdue: {overdue_count} | Critical (≤14d): {critical_count} | Urgent (≤30d): {urgent_count}

### Legislative Intelligence
- Bills tracked across all topics: {total_bills}
- By topic: {bills_by_topic}
- Bills advanced stage this week: {changed_bills}

### Change Detection (vs yesterday)
{changes_summary}

### What the Dashboard Currently Shows
Panels: KPI row, PFAS legislative intel, status matrix, urgency breakdown,
bill stage chart, deadline countdown list, "What Changed Today",
exec summary, topic cards with article feed, maps & data links,
28-day trend sparklines, company impact scores (1-10) per article.

---

Give me your honest director-level critique. Structure your response as JSON:

{{
  "verdict": "One sentence: overall usefulness rating and why. Be direct.",
  "what_works": [
    "Specific thing that is genuinely useful, with why"
  ],
  "questions_raised_unanswered": [
    "Question the dashboard raises but does not answer"
  ],
  "missing_data": [
    "Specific data point or view that is absent but should be there"
  ],
  "noise_concerns": [
    "Things shown that add volume without adding value"
  ],
  "actionable_suggestions": [
    {{
      "priority": "HIGH|MEDIUM|LOW",
      "suggestion": "Specific, buildable improvement",
      "why": "What director problem it solves"
    }}
  ],
  "director_score": {{
    "usefulness": 1-10,
    "actionability": 1-10,
    "signal_to_noise": 1-10,
    "comment": "One sentence on what would move each score up by 2 points"
  }}
}}

Be specific. Reference actual numbers. Don't give generic dashboard advice.
Return JSON only."""


def _build_prompt(pipeline_output: dict, watchdog: Optional[dict],
                  legiscan_report: Optional[dict],
                  daily_changes: Optional[list]) -> str:
    today = date.today().isoformat()
    topics = pipeline_output.get("topics", [])

    # Urgency counts
    high = medium = low = 0
    for t in topics:
        for d in t.get("developments", []):
            u = (d.get("urgency") or "").upper()
            if u == "HIGH":
                high += 1
            elif u == "MEDIUM":
                medium += 1
            else:
                low += 1

    # Per-topic summaries
    topic_lines = []
    for t in topics:
        devs = t.get("developments", [])
        hi = sum(1 for d in devs if (d.get("urgency") or "").upper() == "HIGH")
        top_scores = sorted(
            [d.get("impact_score", 0) for d in devs if d.get("impact_score")],
            reverse=True
        )[:3]
        score_str = f"top impact scores: {top_scores}" if top_scores else "no impact scores yet"
        headlines = [d.get("headline", "")[:70] for d in devs[:3]]
        topic_lines.append(
            f"  {t['topic']}: {len(devs)} developments, {hi} HIGH | {score_str}\n"
            f"    Top headlines: {'; '.join(headlines) if headlines else 'none'}"
        )

    # Deadlines
    total_deadlines = 0
    next_dl = "none"
    overdue = critical = urgent = 0
    if watchdog:
        total_deadlines = watchdog.get("total", 0)
        counts = watchdog.get("counts", {})
        overdue = counts.get("overdue", 0)
        critical = counts.get("critical", 0)
        urgent = counts.get("urgent", 0)
        nd = watchdog.get("next_deadline")
        if nd:
            next_dl = f"{nd['title'][:60]} ({nd['deadline_date']}, {nd['days_until']}d)"

    # LegiScan
    total_bills = 0
    bills_by_topic = "none"
    changed_bills = 0
    if legiscan_report:
        total_bills = legiscan_report.get("total_tracked", 0)
        by_topic = legiscan_report.get("by_topic", {})
        bills_by_topic = ", ".join(f"{t}: {len(v)}" for t, v in by_topic.items())
        changed_bills = len(legiscan_report.get("changed_bills", []))

    # Changes
    if daily_changes:
        change_lines = []
        for c in daily_changes[:8]:
            change_lines.append(f"  [{c['change_type']}] {c['description'][:80]}")
        changes_summary = "\n".join(change_lines) if change_lines else "None detected"
    else:
        changes_summary = "Change detection not yet populated (first run)"

    return _PROMPT.format(
        today=today,
        total_articles=pipeline_output.get("total_articles", 0),
        high_count=high,
        medium_count=medium,
        low_count=low,
        topics_covered=", ".join(t["topic"] for t in topics),
        topic_summaries="\n".join(topic_lines) if topic_lines else "  No topics",
        total_deadlines=total_deadlines,
        next_deadline=next_dl,
        overdue_count=overdue,
        critical_count=critical,
        urgent_count=urgent,
        total_bills=total_bills,
        bills_by_topic=bills_by_topic,
        changed_bills=changed_bills,
        changes_summary=changes_summary,
    )


def _save_critique(critique: dict, today: str) -> None:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("DELETE FROM dashboard_critiques WHERE critique_date = ?", (today,))
    conn.execute("""
        INSERT INTO dashboard_critiques
            (critique_date, what_works, questions_raised, missing_data,
             actionable_suggestions, verdict, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        today,
        json.dumps(critique.get("what_works", [])),
        json.dumps(critique.get("questions_raised_unanswered", [])),
        json.dumps(critique.get("missing_data", [])),
        json.dumps(critique.get("actionable_suggestions", [])),
        critique.get("verdict", ""),
        json.dumps(critique),
    ))
    conn.commit()
    conn.close()


def get_latest_critique() -> Optional[dict]:
    """Return the most recent critique, or None."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM dashboard_critiques ORDER BY critique_date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in ("what_works", "questions_raised", "missing_data", "actionable_suggestions"):
        try:
            d[field] = json.loads(d[field] or "[]")
        except Exception:
            d[field] = []
    try:
        d["raw"] = json.loads(d.get("raw_json") or "{}")
    except Exception:
        d["raw"] = {}
    return d


def _already_ran_today() -> bool:
    """Return True if a critique was already saved for today."""
    conn = sqlite3.connect(str(_DB_PATH))
    row = conn.execute(
        "SELECT critique_date FROM dashboard_critiques ORDER BY critique_date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return bool(row and row[0] == date.today().isoformat())


def run_director_critique(
    pipeline_output: dict,
    watchdog: Optional[dict] = None,
    legiscan_report: Optional[dict] = None,
    daily_changes: Optional[list] = None,
    force: bool = False,
) -> Optional[dict]:
    """
    Run the director critique. Returns parsed critique dict, or None if skipped.

    Runs daily (once per day). Pass force=True to re-run even if already done today.
    """
    if not force and _already_ran_today():
        logger.info("Director critique: already ran today, skipping (use force=True to re-run)")
        return get_latest_critique()

    logger.info("Director critique: running weekly analysis...")

    client = ClaudeClient()
    prompt = _build_prompt(pipeline_output, watchdog, legiscan_report, daily_changes)
    cache_key = f"director_critique_{today.isoformat()}"

    try:
        response = client.complete_sonnet(
            prompt,
            system=_SYSTEM,
            cache_key=cache_key,
        )
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        critique = json.loads(text.strip())
    except Exception as e:
        logger.warning(f"Director critique failed: {e}")
        return get_latest_critique()

    _save_critique(critique, today.isoformat())
    _write_report(critique, today.isoformat())

    # Log the verdict and scores
    verdict = critique.get("verdict", "")
    scores = critique.get("director_score", {})
    logger.info(f"Director verdict: {verdict}")
    logger.info(
        f"Director scores — usefulness: {scores.get('usefulness')}, "
        f"actionability: {scores.get('actionability')}, "
        f"signal/noise: {scores.get('signal_to_noise')}"
    )
    for s in critique.get("actionable_suggestions", [])[:3]:
        logger.info(f"  [{s.get('priority')}] {s.get('suggestion')}")

    return critique


def _write_report(critique: dict, today: str) -> Path:
    """Write a readable HTML report to data/director_review.html."""
    report_path = Path(Config.DATA_DIR) / "director_review.html"

    scores = critique.get("director_score", {})

    def score_color(v):
        if v >= 7: return "#0F766E"
        if v >= 5: return "#CB7B0A"
        return "#D63031"

    def badge(priority):
        colors = {"HIGH": "#fee2e2:#991b1b", "MEDIUM": "#fef3c7:#92400e", "LOW": "#d1fae5:#065f46"}
        bg, fg = colors.get(priority, "#f3f4f6:#374151").split(":")
        return f'<span style="background:{bg};color:{fg};padding:2px 7px;border-radius:3px;font-size:11px;font-weight:700;">{priority}</span>'

    sections_html = ""

    if critique.get("verdict"):
        sections_html += f'<blockquote style="border-left:4px solid #0F766E;margin:0 0 20px;padding:12px 16px;background:#f0fdfa;font-style:italic;color:#134e4a;">{critique["verdict"]}</blockquote>'

    for section_key, title, color in [
        ("what_works",                  "What's Working",                   "#065f46"),
        ("questions_raised_unanswered", "Questions Raised But Not Answered", "#92400e"),
        ("missing_data",                "Missing Data",                      "#1e40af"),
        ("noise_concerns",              "Noise Concerns",                    "#6b21a8"),
    ]:
        items = critique.get(section_key, [])
        if not items:
            continue
        items_html = "".join(f"<li style='margin-bottom:8px;line-height:1.5;'>{i}</li>" for i in items)
        sections_html += f"""
        <h3 style="color:{color};font-size:14px;margin:20px 0 8px;border-bottom:1px solid #e5e7eb;padding-bottom:4px;">{title}</h3>
        <ul style="margin:0;padding-left:20px;color:#374151;font-size:13px;">{items_html}</ul>"""

    suggestions = critique.get("actionable_suggestions", [])
    if suggestions:
        cards = ""
        for s in suggestions:
            cards += f"""
            <div style="border:1px solid #e5e7eb;border-radius:6px;padding:10px 12px;margin-bottom:8px;">
              {badge(s.get("priority","MEDIUM"))}
              <span style="font-size:13px;font-weight:600;color:#111827;margin-left:8px;">{s.get("suggestion","")}</span>
              {f'<div style="font-size:12px;color:#6b7280;margin-top:5px;">{s["why"]}</div>' if s.get("why") else ""}
            </div>"""
        sections_html += f'<h3 style="color:#991b1b;font-size:14px;margin:20px 0 8px;border-bottom:1px solid #e5e7eb;padding-bottom:4px;">Build Next</h3>{cards}'

    score_cards = ""
    for label, key in [("Usefulness", "usefulness"), ("Actionability", "actionability"), ("Signal / Noise", "signal_to_noise")]:
        v = scores.get(key, "—")
        score_cards += f"""
        <div style="flex:1;text-align:center;border:1px solid #e5e7eb;border-radius:8px;padding:12px 8px;">
          <div style="font-size:28px;font-weight:700;color:{score_color(v) if isinstance(v, int) else '#6b7280'};">{v}/10</div>
          <div style="font-size:11px;color:#6b7280;margin-top:2px;">{label}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Director Review — {today}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #111827; background: #fff; }}
  h1 {{ font-size: 20px; color: #0F766E; margin-bottom: 4px; }}
  .meta {{ font-size: 12px; color: #6b7280; margin-bottom: 24px; }}
  .scores {{ display: flex; gap: 12px; margin-bottom: 24px; }}
  .comment {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px 14px; font-size: 12px; color: #4b5563; margin-top: 12px; }}
</style>
</head>
<body>
<h1>Director's Compliance Review</h1>
<div class="meta">Generated {today} · Runs weekly on Mondays · Use <code>python run.py --director-review</code> to regenerate</div>

<div class="scores">{score_cards}</div>
{f'<div class="comment">{scores["comment"]}</div>' if scores.get("comment") else ""}

{sections_html}
</body>
</html>"""

    report_path.write_text(html, encoding="utf-8")
    logger.info(f"Director review written to {report_path}")
    return report_path
