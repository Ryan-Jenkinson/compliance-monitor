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
question: "What is the real regulatory risk here and what should I be watching?"

CRITICAL CONTEXT about this dashboard's scope:
This is a regulatory intelligence and risk monitoring tool ONLY. It intentionally does NOT track:
- Who is assigned to what compliance task
- Action items or task management
- Internal project owners or deadlines tied to people
- Company-internal workflow status

Those activities happen in a separate company-approved tool. This dashboard cannot and should not
try to replicate them. Do NOT suggest adding task assignments, action item owners, or internal
project management features — those are out of scope by design.

WHAT THIS DASHBOARD CAN AND SHOULD DO WELL:
- Track regulatory deadlines, bill stages, and enforcement developments
- Surface high-risk legislative patterns and jurisdictions
- Identify which regulations are moving fastest and toward what
- Provide cross-state pattern analysis (coordinated campaigns, next movers)
- Give clear signal on urgency and impact level across topics
- Keep the compliance team informed on what changed and what to watch

Your critique should focus exclusively on improving these capabilities: data coverage,
signal quality, risk prioritization, legislative intelligence, trend visibility,
and clarity of what's happening in the regulatory landscape.

Your job right now is to review this compliance intelligence dashboard that your team has built.
Be honest. Be specific. Reference actual numbers and data you see. Point out what's genuinely
useful AND what's falling short. Your feedback will directly drive what gets built next."""

_PROMPT = """Review this compliance intelligence dashboard. I need your honest assessment.

## Dashboard State as of {today}

### Pipeline Output
- Total articles this cycle: {total_articles}
- HIGH urgency: {high_count} | MEDIUM: {medium_count} | LOW: {low_count}
- Topics covered: {topics_covered}

### Executive Summary (AI-generated)
{exec_summary}

### Per-Topic Developments + AI Analysis
{topic_summaries}

### Regulatory Deadlines
- Total tracked: {total_deadlines} | Overdue: {overdue_count} | Critical (≤14d): {critical_count} | Urgent (≤30d): {urgent_count}
- Next deadline: {next_deadline}

**Upcoming deadlines (next 12 months):**
{deadline_detail}

**AI-generated deadline analysis (what the company must actually do):**
{deadline_analysis}

### Legislative Intelligence — Advanced Bills
Bills that have passed at least one chamber or been enacted:
{advanced_bills}

**All tracked bills:** {total_bills} across topics ({bills_by_topic}) | Stage advances this week: {changed_bills}

### Cross-State Legislative Intelligence
{cross_state_intel}

### Tracked Regulations (most recently updated)
{regulations}

### Change Detection (vs yesterday)
{changes_summary}

### What the Dashboard Currently Shows
Pages and panels: main dashboard (KPI row, status matrix, urgency breakdown, bill stage chart,
deadline countdown, "What Changed Today", exec summary, director critique panel, cross-state
intel widget), per-topic pages (article feed with company impact scores, bills panel, deadlines
panel, resources strip, cross-state intel section), standalone cross-state intelligence report
(all 5 topics, sticky nav, watch list + next movers + stage clusters + coordinated campaigns),
weekly briefing email, executive briefing page, director review page.

---

Give me your honest director-level critique based on ALL the content above. Be specific —
reference actual regulation names, bill numbers, deadline dates, and state names you can see.

Structure your response as JSON:

{{
  "verdict": "One sentence: overall usefulness rating and why. Be direct.",
  "what_works": [
    "Specific thing that is genuinely useful, with why"
  ],
  "questions_raised_unanswered": [
    "Question the dashboard raises but does not answer — reference specific data points"
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
      "suggestion": "Specific, buildable improvement to the dashboard itself",
      "why": "What regulatory intelligence problem it solves"
    }}
  ],
  "director_score": {{
    "usefulness": 1-10,
    "actionability": 1-10,
    "signal_to_noise": 1-10,
    "comment": "One sentence on what would move each score up by 2 points"
  }}
}}

Be specific. Reference actual data. Don't give generic dashboard advice.
Return JSON only."""


def _load_rich_context() -> dict:
    """
    Load all rich AI-generated content from the DB for the director review.
    Returns a dict with topic_insights, deadline_analyses, cross_state, regulations, advanced_bills.
    """
    import sqlite3 as _sq
    conn = _sq.connect(str(_DB_PATH))
    conn.row_factory = _sq.Row

    # ── Topic insights (6-month trend analysis per topic) ──────────────────
    topic_insights = {}
    rows = conn.execute("""
        SELECT topic, analysis_date, insights_json
        FROM topic_insights
        WHERE analysis_date = (SELECT MAX(analysis_date) FROM topic_insights)
        ORDER BY topic
    """).fetchall()
    for row in rows:
        try:
            topic_insights[row["topic"]] = json.loads(row["insights_json"])
        except Exception:
            pass

    # ── Deadline analyses (AI breakdown per deadline) ──────────────────────
    deadline_analyses = []
    rows = conn.execute("""
        SELECT rd.title, rd.topic, rd.deadline_date, rd.jurisdiction,
               rd.urgency, rd.description, da.analysis_json
        FROM deadline_analyses da
        JOIN regulatory_deadlines rd ON da.deadline_id = rd.id
        ORDER BY rd.deadline_date ASC
        LIMIT 20
    """).fetchall()
    for row in rows:
        try:
            analysis = json.loads(row["analysis_json"])
            deadline_analyses.append({
                "title": row["title"],
                "topic": row["topic"],
                "deadline_date": row["deadline_date"],
                "jurisdiction": row["jurisdiction"],
                "urgency": row["urgency"],
                "what_is_required": analysis.get("what_is_required", ""),
                "who_must_comply": analysis.get("who_must_comply", ""),
                "what_we_must_do": analysis.get("what_we_must_do", ""),
                "penalties": analysis.get("penalties", ""),
                "company_impact": analysis.get("company_impact", ""),
                "recommended_actions": analysis.get("recommended_actions", []),
            })
        except Exception:
            pass

    # ── Cross-state reports (most recent full analysis) ────────────────────
    cross_state = []
    rows = conn.execute("""
        SELECT topic, report_date, raw_json
        FROM cross_state_reports
        WHERE report_date = (SELECT MAX(report_date) FROM cross_state_reports)
        ORDER BY topic
    """).fetchall()
    for row in rows:
        try:
            analysis = json.loads(row["raw_json"])
            cross_state.append({
                "topic": row["topic"],
                "report_date": row["report_date"],
                "summary": analysis.get("summary", ""),
                "watch_list": analysis.get("watch_list", []),
                "next_mover_predictions": analysis.get("next_mover_predictions", []),
                "coordinated_campaigns": analysis.get("coordinated_campaigns", []),
                "stage_clusters": analysis.get("stage_clusters", []),
            })
        except Exception:
            pass

    # ── Regulations (most recently updated) ───────────────────────────────
    regulations = []
    rows = conn.execute("""
        SELECT topic, regulation_name, current_status, effective_date
        FROM regulations
        ORDER BY updated_at DESC
        LIMIT 20
    """).fetchall()
    for row in rows:
        regulations.append(dict(row))

    # ── Advanced bills (passed one chamber or further) ─────────────────────
    advanced_bills = []
    rows = conn.execute("""
        SELECT state, topic, bill_number, title, stage, last_action, last_action_date
        FROM legiscan_bills
        WHERE is_active = 1
          AND stage IN ('passed_one', 'advanced', 'enacted_watching', 'signed')
        ORDER BY last_action_date DESC
        LIMIT 30
    """).fetchall()
    for row in rows:
        advanced_bills.append(dict(row))

    # ── Recent regulatory deadlines (next 12 months) ───────────────────────
    deadline_list = []
    rows = conn.execute("""
        SELECT title, topic, deadline_date, jurisdiction, urgency, description
        FROM regulatory_deadlines
        WHERE deadline_date >= date('now')
          AND deadline_date <= date('now', '+365 days')
        ORDER BY deadline_date ASC
        LIMIT 25
    """).fetchall()
    for row in rows:
        deadline_list.append(dict(row))

    conn.close()

    return {
        "topic_insights": topic_insights,
        "deadline_analyses": deadline_analyses,
        "cross_state": cross_state,
        "regulations": regulations,
        "advanced_bills": advanced_bills,
        "deadline_list": deadline_list,
    }


def _build_prompt(pipeline_output: dict, watchdog: Optional[dict],
                  legiscan_report: Optional[dict],
                  daily_changes: Optional[list]) -> str:
    today = date.today().isoformat()
    topics = pipeline_output.get("topics", [])

    # Load rich DB content
    ctx = _load_rich_context()

    # ── Pipeline article counts ────────────────────────────────────────────
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

    # ── Exec summary ──────────────────────────────────────────────────────
    exec_summary = pipeline_output.get("exec_summary", "").strip()

    # ── Per-topic: pipeline developments + AI topic insights ──────────────
    topic_sections = []
    all_topics = set(t["topic"] for t in topics) | set(ctx["topic_insights"].keys())
    for topic_name in sorted(all_topics):
        # Pipeline articles
        topic_data = next((t for t in topics if t["topic"] == topic_name), {})
        devs = topic_data.get("developments", [])
        hi = sum(1 for d in devs if (d.get("urgency") or "").upper() == "HIGH")
        headlines = [
            f"    [{d.get('urgency','?')}|score:{d.get('impact_score','?')}] {d.get('headline','')[:80]}"
            + (f"\n      Impact: {d.get('company_impact','')[:120]}" if d.get('company_impact') else "")
            for d in devs[:5]
        ]

        # Topic insight
        insight = ctx["topic_insights"].get(topic_name, {})
        insight_lines = []
        if insight:
            if insight.get("six_month_trend"):
                insight_lines.append(f"  6-month trend: {insight['six_month_trend']}")
            if insight.get("last_30_days"):
                insight_lines.append(f"  Last 30 days: {insight['last_30_days']}")
            if insight.get("breaking_news"):
                insight_lines.append(f"  Breaking: {insight['breaking_news']}")
            if insight.get("company_impact"):
                insight_lines.append(f"  Company impact: {insight['company_impact']}")
            if insight.get("strategic_priorities"):
                pris = insight["strategic_priorities"]
                if isinstance(pris, list):
                    insight_lines.append(f"  Strategic priorities: {'; '.join(str(p)[:80] for p in pris[:3])}")
                else:
                    insight_lines.append(f"  Strategic priorities: {str(pris)[:200]}")

        section = f"### {topic_name}\n"
        section += f"  Articles this cycle: {len(devs)} ({hi} HIGH)\n"
        if headlines:
            section += "  Top developments:\n" + "\n".join(headlines) + "\n"
        if insight_lines:
            section += "  AI-generated topic analysis:\n" + "\n".join(insight_lines) + "\n"

        topic_sections.append(section)

    # ── Deadlines: watchdog counts + deadline list + AI analyses ──────────
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

    deadline_detail_lines = []
    for dl in ctx["deadline_list"][:15]:
        deadline_detail_lines.append(
            f"  [{dl['urgency'] or 'WATCH'}] {dl['title'][:70]} | {dl['topic']} | {dl['deadline_date']} | {dl['jurisdiction'] or 'Federal'}"
        )

    def _str(v, limit=100):
        """Convert any value to a string snippet for the prompt."""
        if isinstance(v, dict):
            # Concatenate dict values
            return "; ".join(f"{kk}: {str(vv)[:60]}" for kk, vv in list(v.items())[:3])[:limit]
        if isinstance(v, list):
            return "; ".join(str(i)[:60] for i in v[:3])[:limit]
        return str(v or "")[:limit]

    deadline_analysis_lines = []
    for da in ctx["deadline_analyses"][:8]:
        deadline_analysis_lines.append(
            f"  {da['title'][:60]} ({da['deadline_date']}, {da['topic']}):\n"
            f"    Required: {_str(da['what_is_required'])}\n"
            f"    Who: {_str(da['who_must_comply'], 80)}\n"
            f"    Company must do: {_str(da['what_we_must_do'])}\n"
            f"    Company impact: {_str(da['company_impact'])}"
        )

    # ── Cross-state intelligence ───────────────────────────────────────────
    cross_state_lines = []
    for cs in ctx["cross_state"]:
        topic_name = cs["topic"]
        watch = cs.get("watch_list", [])
        movers = [m for m in cs.get("next_mover_predictions", []) if (m.get("urgency") or "").upper() == "HIGH"]
        campaigns = cs.get("coordinated_campaigns", [])
        summary_str = cs.get("summary", "")[:200]
        cross_state_lines.append(
            f"  {topic_name} (as of {cs['report_date']}): {len(watch)} states on watch, "
            f"{len(movers)} HIGH urgency movers, {len(campaigns)} coordinated campaigns\n"
            f"    Summary: {summary_str}"
        )
        for w in watch[:3]:
            cross_state_lines.append(
                f"    Watch: {w.get('state','?')} — {w.get('reason','')[:80]}"
            )
        for m in movers[:2]:
            cross_state_lines.append(
                f"    HIGH mover: {m.get('state','?')} — {m.get('prediction','')[:80]}"
            )

    # ── Regulations ────────────────────────────────────────────────────────
    reg_lines = []
    for reg in ctx["regulations"][:12]:
        reg_lines.append(
            f"  [{reg['topic']}] {reg['regulation_name'][:70]} | status: {reg['current_status']} | effective: {reg['effective_date'] or 'TBD'}"
        )

    # ── Advanced bills ─────────────────────────────────────────────────────
    bill_lines = []
    for bill in ctx["advanced_bills"][:15]:
        bill_lines.append(
            f"  [{bill['topic']}|{bill['state']}] {bill['bill_number']} — {bill['title'][:60]} | stage: {bill['stage']} | {bill['last_action_date']}"
        )

    # ── LegiScan counts ────────────────────────────────────────────────────
    total_bills = 0
    bills_by_topic = "none"
    changed_bills = 0
    if legiscan_report:
        total_bills = legiscan_report.get("total_tracked", 0)
        by_topic = legiscan_report.get("by_topic", {})
        bills_by_topic = ", ".join(f"{t}: {len(v)}" for t, v in by_topic.items())
        changed_bills = len(legiscan_report.get("changed_bills", []))

    # ── Daily changes ──────────────────────────────────────────────────────
    if daily_changes:
        change_lines = [f"  [{c['change_type']}] {c['description'][:80]}" for c in daily_changes[:10]]
        changes_summary = "\n".join(change_lines) if change_lines else "None detected"
    else:
        changes_summary = "Change detection not yet populated (first run)"

    return _PROMPT.format(
        today=today,
        total_articles=pipeline_output.get("total_articles", 0),
        high_count=high,
        medium_count=medium,
        low_count=low,
        topics_covered=", ".join(t["topic"] for t in topics) or ", ".join(sorted(ctx["topic_insights"].keys())),
        exec_summary=exec_summary or "(not available — pipeline not run today)",
        topic_summaries="\n".join(topic_sections) if topic_sections else "  No topic data available",
        total_deadlines=total_deadlines or len(ctx["deadline_list"]),
        next_deadline=next_dl,
        overdue_count=overdue,
        critical_count=critical,
        urgent_count=urgent,
        deadline_detail="\n".join(deadline_detail_lines) if deadline_detail_lines else "  No upcoming deadlines",
        deadline_analysis="\n".join(deadline_analysis_lines) if deadline_analysis_lines else "  No deadline analyses yet",
        advanced_bills="\n".join(bill_lines) if bill_lines else "  None",
        total_bills=total_bills,
        bills_by_topic=bills_by_topic,
        changed_bills=changed_bills,
        cross_state_intel="\n".join(cross_state_lines) if cross_state_lines else "  No cross-state analysis yet",
        regulations="\n".join(reg_lines) if reg_lines else "  No regulations tracked",
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

    today = date.today()
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

    # Also save a dated archive copy so reviews accumulate over time
    archive_dir = Path(Config.DATA_DIR) / "director_reviews"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"director_review_{today}.html"
    archive_path.write_text(html, encoding="utf-8")

    # Write/update the archive index
    _write_review_index(archive_dir)

    logger.info(f"Director review written to {report_path} + archived to {archive_path}")
    return report_path


def _write_review_index(archive_dir: Path) -> None:
    """Write a simple HTML index of all archived director reviews."""
    reviews = sorted(archive_dir.glob("director_review_*.html"), reverse=True)
    if not reviews:
        return

    items_html = ""
    for p in reviews:
        date_str = p.stem.replace("director_review_", "")
        items_html += (
            f'<li style="padding:6px 0;border-bottom:1px solid #e5e7eb;">'
            f'<a href="{p.name}" style="color:#1565C0;font-weight:600;">'
            f'Director Review — {date_str}</a>'
            f'</li>\n'
        )

    index_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Director Reviews Archive</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:600px;margin:40px auto;padding:0 20px;}}
h1{{font-size:18px;color:#0F766E;}} ul{{list-style:none;padding:0;margin:0;}}</style>
</head>
<body>
<h1>Director Reviews Archive</h1>
<p style="color:#6b7280;font-size:12px;">{len(reviews)} review(s) saved</p>
<ul>{items_html}</ul>
</body></html>"""

    (archive_dir / "index.html").write_text(index_html, encoding="utf-8")
