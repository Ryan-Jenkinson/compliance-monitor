"""Bill Analysis Agent — deep legislative intelligence for individual bills."""
from __future__ import annotations
import json
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior regulatory compliance analyst specializing in chemical regulations,
packaging laws, and environmental compliance for a US manufacturing company (windows/doors manufacturer).

Company compliance context:
- PFAS: Fluoropolymer coatings on products require MN PRISM registration by July 1, 2026.
  Also buying thousands of PFAS-containing components from suppliers — if their manufacturers
  miss PRISM registration it becomes illegal to sell to us in MN, creating operational shutdown risk.
- EPR: Packaging compliance in CA (SB 54), ME, OR, CO and emerging states.
- REACH: EU SVHC tracking for imports/exports; supplier declarations via Assent platform.
- TSCA: Section 6 chemical use restrictions; Section 8 reporting.
- Prop65: California consumer product warnings for windows/doors and components.
- ConflictMinerals: Dodd-Frank 1409 — tin, tantalum, tungsten, gold in supply chain.
- ForcedLabor: UFLPA supply chain due diligence for imported components.

Tone: expert colleague briefing a compliance lead. No definitions, no hedging, no filler.
Specific and actionable. Connect every finding to what the compliance team should actually do.
"""


def _build_prompt(bill: dict, history_text: str, trigger_action: str | None) -> str:
    topic = (bill.get("topic") or "").upper()
    state = bill.get("state", "")
    bill_number = bill.get("bill_number", "")
    title = bill.get("title", "")
    stage = (bill.get("stage") or "").replace("_", " ").title()
    last_action = bill.get("last_action", "")
    last_action_date = bill.get("last_action_date", "")
    description = (bill.get("description") or "")[:400]
    committee = bill.get("committee_name") or ""
    sponsors: list = []
    try:
        sponsors_raw = json.loads(bill.get("sponsors_json") or "[]")
        sponsors = [s.get("name", "") for s in sponsors_raw[:3] if s.get("name")]
    except Exception:
        pass

    today = date.today().isoformat()

    return f"""\
Analyze the following piece of state legislation and produce a structured intelligence brief.

BILL DETAILS:
- Bill: {state} {bill_number}
- Topic Area: {topic}
- Title: {title}
- Description: {description}
- Current Stage: {stage}
- Committee: {committee}
- Key Sponsors: {', '.join(sponsors) if sponsors else 'Not listed'}
- Last Action ({last_action_date}): {last_action}
{f'- Action that triggered this analysis: {trigger_action}' if trigger_action else ''}

LEGISLATIVE HISTORY (chronological):
{history_text}

Today: {today}

Produce a JSON object with this exact structure (return JSON only, no markdown fences):
{{
  "synopsis": "2-3 sentences: what does this bill do and why does it matter for compliance?",
  "stage_meaning": "1-2 sentences: what does '{stage}' mean procedurally in {state}? What is the next step?",
  "recent_action_analysis": "2-3 sentences on what '{last_action}' means for this bill's trajectory — is it advancing, stalling, dying?",
  "company_impact": {{
    "direct": "1-2 sentences: impact on our manufactured products or direct chemical obligations. Null if truly N/A.",
    "supply_chain": "1-2 sentences: which purchased component categories or supplier tiers are affected. Null if truly N/A.",
    "severity": "HIGH | MEDIUM | LOW | MONITORING"
  }},
  "long_term_trajectory": "2-3 sentences: likely outcome over next 6-12 months. Passage probability, risk of similar bills in other states, federal preemption risk?",
  "recommended_actions": [
    "Specific action item 1 for compliance team this week",
    "Specific action item 2"
  ],
  "follow_up_dates": [
    {{
      "date": "YYYY-MM-DD or null",
      "event": "What to watch for on this date",
      "confidence": "known | probable | possible"
    }}
  ],
  "outlook_event": {{
    "title": "Calendar event title — max 60 chars, include bill number",
    "description": "3-4 sentence body: what to review/decide, what data to pull, who to loop in",
    "suggested_date": "YYYY-MM-DD — next meaningful monitoring checkpoint",
    "reminder_days_before": 3
  }}
}}

Rules:
- If bill is genuinely not relevant to the company, set severity to MONITORING and say so clearly
- For follow_up_dates: derive from legislative calendar patterns for this state/stage
- recommended_actions: max 3, make them specific to THIS bill not generic advice
- Return only valid JSON
"""


def _empty_analysis(state: str, bill_number: str, reason: str = "") -> dict:
    return {
        "state": state,
        "bill_number": bill_number,
        "bill_title": "",
        "synopsis": None,
        "error": reason,
        "analyzed_at": datetime.now().isoformat(),
    }


def analyze_bill(state: str, bill_number: str,
                 trigger_action: str | None = None,
                 force: bool = False) -> dict:
    """Generate deep analysis for a single bill. Caches in DB by date.

    Args:
        state: Two-letter state abbreviation, e.g. "MN"
        bill_number: Bill number, e.g. "HF 1234"
        trigger_action: The specific action text that triggered analysis (for context)
        force: Re-analyze even if a cached result exists
    """
    from subscribers.db import get_connection, save_bill_analysis, get_bill_analysis
    from ai.claude_client import ClaudeClient

    if not force:
        existing = get_bill_analysis(state, bill_number)
        if existing and existing.get("synopsis"):
            logger.debug(f"Bill analysis cache hit: {state} {bill_number}")
            return existing

    # Load bill data from DB
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM legiscan_bills WHERE state=? AND bill_number=?",
        (state, bill_number),
    ).fetchone()
    conn.close()

    if not row:
        return _empty_analysis(state, bill_number, "Bill not found in database")

    bill = dict(row)
    history: list = []
    try:
        history = json.loads(bill.get("history_json") or "[]")
    except Exception:
        pass

    history_text = "\n".join(
        f"  {h.get('date', '?')}: {h.get('action', '')}"
        for h in sorted(history, key=lambda x: x.get("date", ""))
        if h.get("date") and h.get("action")
    ) or "  (no history available)"

    prompt = _build_prompt(bill, history_text, trigger_action)
    client = ClaudeClient()

    # Cache key: per bill per day (so re-runs don't re-call)
    cache_key = f"bill_analysis_{state}_{bill_number}_{date.today().isoformat()}"
    try:
        raw = client.complete_sonnet(prompt, system=_SYSTEM, cache_key=cache_key)
        text = raw.strip()
        # Strip markdown fences if model adds them
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = text[:-3].strip()
        analysis = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Bill analysis JSON parse failed for {state} {bill_number}: {e}")
        return _empty_analysis(state, bill_number, f"JSON parse error: {e}")
    except Exception as e:
        logger.warning(f"Bill analysis failed for {state} {bill_number}: {e}")
        return _empty_analysis(state, bill_number, str(e))

    # Enrich with bill metadata
    analysis["state"] = state
    analysis["bill_number"] = bill_number
    analysis["bill_title"] = bill.get("title", "")
    analysis["topic"] = (bill.get("topic") or "").upper()
    analysis["stage"] = bill.get("stage", "")
    analysis["last_action"] = bill.get("last_action", "")
    analysis["last_action_date"] = bill.get("last_action_date", "")
    analysis["source_url"] = bill.get("url") or bill.get("state_link") or ""
    analysis["analyzed_at"] = datetime.now().isoformat()

    # Persist
    try:
        save_bill_analysis(
            state, bill_number, bill.get("bill_id"),
            trigger_action or bill.get("last_action"), analysis
        )
    except Exception as e:
        logger.warning(f"Failed to save bill analysis to DB: {e}")

    return analysis


def run_batch_analysis(days_past: int = 30, limit: int = 40) -> int:
    """Analyze high-signal bills with recent actions. Run during pipeline.

    Targets bills in significant stages (committee+) with activity in the
    last `days_past` days. Skips bills already analyzed today.

    Returns count of new analyses generated.
    """
    from subscribers.db import get_connection, get_bill_analysis

    cutoff = (date.today() - timedelta(days=days_past)).isoformat()

    conn = get_connection()
    rows = conn.execute(
        """SELECT state, bill_number, last_action, last_action_date, topic
           FROM legiscan_bills
           WHERE last_action_date >= ?
             AND is_active = 1
             AND stage IN ('passed_one', 'advanced', 'enacted_watching',
                           'committee', 'rulemaking')
           ORDER BY last_action_date DESC
           LIMIT ?""",
        (cutoff, limit),
    ).fetchall()
    conn.close()

    count = 0
    for r in rows:
        state = r["state"]
        bill_number = r["bill_number"]
        try:
            existing = get_bill_analysis(state, bill_number)
            if existing and existing.get("synopsis"):
                continue  # Already have a good analysis
            result = analyze_bill(
                state, bill_number,
                trigger_action=r["last_action"],
            )
            if result.get("synopsis"):
                count += 1
                logger.info(f"Bill analyzed: {state} {bill_number} ({r['topic']})")
        except Exception as e:
            logger.warning(f"Batch analysis skipped {state} {bill_number}: {e}")

    logger.info(f"Bill batch analysis complete: {count} new analyses")
    return count
