"""Deadline Analysis Agent — deep compliance intelligence for regulatory deadlines."""
from __future__ import annotations
import json
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior regulatory compliance analyst specializing in chemical regulations,
packaging laws, and environmental compliance for a US manufacturing company (windows/doors).

Company compliance context:
- PFAS: Fluoropolymer coatings on products; MN PRISM registration deadline July 1, 2026.
  Also buying PFAS-containing components from thousands of suppliers — if their upstream
  manufacturers miss PRISM registration it becomes illegal to sell to us in MN (shutdown risk).
- EPR: Extended Producer Responsibility — packaging compliance in CA (SB 54), ME, OR, CO.
  As a manufacturer we are likely a "covered producer" for packaging used to ship products.
- REACH: EU SVHC substance restrictions; supplier declarations via Assent platform.
- TSCA: Section 6 use restrictions and Section 8 chemical data reporting.
- Prop65: California consumer product warnings for windows/doors sold in CA.
- ConflictMinerals: Dodd-Frank 1409 — tin, tantalum, tungsten, gold in components.
- ForcedLabor: UFLPA supply chain due diligence for imported components.

Tone: trusted expert colleague briefing a compliance lead who knows the regulatory landscape.
Be specific and actionable. Connect every finding to what the compliance team must actually do.
"""


def _build_prompt(dl: dict) -> str:
    today = date.today().isoformat()
    days_until = None
    try:
        days_until = (date.fromisoformat(dl["deadline_date"]) - date.today()).days
    except Exception:
        pass

    countdown = ""
    if days_until is not None:
        if days_until < 0:
            countdown = f"THIS DEADLINE IS {abs(days_until)} DAYS OVERDUE."
        elif days_until == 0:
            countdown = "THIS DEADLINE IS TODAY."
        else:
            countdown = f"{days_until} days until this deadline."

    return f"""\
Analyze the following regulatory compliance deadline and produce a structured intelligence brief.

DEADLINE DETAILS:
- Title: {dl.get('title', '')}
- Date: {dl.get('deadline_date', '')} ({countdown})
- Topic Area: {(dl.get('topic') or '').upper()}
- Jurisdiction: {dl.get('jurisdiction', '')}
- Urgency: {dl.get('urgency', '')}
- Description: {(dl.get('description') or 'Not provided')[:500]}
- Source URL: {dl.get('source_url', 'Not provided')}

Today: {today}

Produce a JSON object with this exact structure (return JSON only, no markdown fences):
{{
  "what_is_required": "2-3 sentences: exactly what must be done by this date? Be specific about the action, the regulated entity, and the regulatory basis (statute/rule citation if known).",
  "who_must_comply": "1-2 sentences: which types of companies must comply? Be specific — manufacturers, distributors, importers, retailers? Size thresholds? Geographic scope?",
  "what_we_must_do": "2-3 sentences: what specifically must THIS company do? Address both the direct product side AND the supply chain/procurement side if relevant.",
  "penalties": "1-2 sentences: what are the consequences of missing this deadline? Civil penalties, criminal liability, loss of market access, etc.",
  "company_impact": {{
    "direct": "1-2 sentences: impact on our manufactured products or direct regulatory obligations. Null if not applicable.",
    "supply_chain": "1-2 sentences: which purchased component categories or supplier tiers are at risk. Null if not applicable.",
    "severity": "HIGH | MEDIUM | LOW | MONITORING"
  }},
  "preparation_timeline": [
    {{
      "days_before": 90,
      "action": "What should be done 90 days before the deadline"
    }},
    {{
      "days_before": 60,
      "action": "What should be done 60 days before"
    }},
    {{
      "days_before": 30,
      "action": "What should be done 30 days before"
    }},
    {{
      "days_before": 0,
      "action": "What must be completed on/before the deadline date"
    }}
  ],
  "related_context": "1-2 sentences: how does this fit into the broader regulatory scheme? Any related deadlines, preceding requirements, or follow-on obligations to be aware of?",
  "recommended_actions": [
    "Specific action item 1 for compliance team right now",
    "Specific action item 2"
  ],
  "outlook_event": {{
    "title": "Calendar event title — max 60 chars, include jurisdiction and deadline type",
    "description": "3-4 sentences: what to review/verify/submit on this date, who needs to be involved",
    "suggested_date": "YYYY-MM-DD — suggest 30 days before the actual deadline as the review checkpoint",
    "reminder_days_before": 7
  }}
}}

Rules:
- If this deadline does not apply to us at all, say so in what_we_must_do and set severity MONITORING
- preparation_timeline: skip milestones that are already past (based on today's date {today})
- recommended_actions: max 3, specific to THIS deadline, not generic compliance advice
- Return only valid JSON
"""


def _empty_analysis(dl_id: int, reason: str = "") -> dict:
    return {
        "deadline_id": dl_id,
        "what_is_required": None,
        "error": reason,
        "analyzed_at": datetime.now().isoformat(),
    }


def analyze_deadline(deadline_id: int, force: bool = False) -> dict:
    """Generate deep analysis for a single deadline. Caches in DB.

    Args:
        deadline_id: The regulatory_deadlines.id value
        force: Re-analyze even if cached result exists
    """
    from subscribers.db import get_connection, save_deadline_analysis, get_deadline_analysis
    from ai.claude_client import ClaudeClient

    if not force:
        existing = get_deadline_analysis(deadline_id)
        if existing and existing.get("what_is_required"):
            logger.debug(f"Deadline analysis cache hit: id={deadline_id}")
            return existing

    # Load deadline from DB
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM regulatory_deadlines WHERE id=?", (deadline_id,)
    ).fetchone()
    conn.close()

    if not row:
        return _empty_analysis(deadline_id, "Deadline not found in database")

    dl = dict(row)
    prompt = _build_prompt(dl)
    client = ClaudeClient()

    # Cache per deadline per day
    cache_key = f"deadline_analysis_{deadline_id}_{date.today().isoformat()}"
    try:
        raw = client.complete_sonnet(prompt, system=_SYSTEM, cache_key=cache_key)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = text[:-3].strip()
        analysis = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Deadline analysis JSON parse failed id={deadline_id}: {e}")
        return _empty_analysis(deadline_id, f"JSON parse error: {e}")
    except Exception as e:
        logger.warning(f"Deadline analysis failed id={deadline_id}: {e}")
        return _empty_analysis(deadline_id, str(e))

    # Enrich with deadline metadata
    analysis["deadline_id"] = deadline_id
    analysis["title"] = dl.get("title", "")
    analysis["deadline_date"] = dl.get("deadline_date", "")
    analysis["topic"] = (dl.get("topic") or "").upper()
    analysis["jurisdiction"] = dl.get("jurisdiction", "")
    analysis["urgency"] = dl.get("urgency", "")
    analysis["source_url"] = dl.get("source_url", "")
    analysis["description"] = dl.get("description", "")
    analysis["analyzed_at"] = datetime.now().isoformat()

    try:
        save_deadline_analysis(deadline_id, analysis)
    except Exception as e:
        logger.warning(f"Failed to save deadline analysis to DB: {e}")

    return analysis


def run_batch_analysis(limit: int = 30) -> int:
    """Analyze all upcoming HIGH/MEDIUM deadlines. Run during pipeline.

    Returns count of new analyses generated.
    """
    from subscribers.db import get_connection, get_deadline_analysis

    today = date.today().isoformat()

    conn = get_connection()
    rows = conn.execute(
        """SELECT id FROM regulatory_deadlines
           WHERE deadline_date >= ?
             AND urgency IN ('HIGH', 'MEDIUM')
           ORDER BY deadline_date ASC
           LIMIT ?""",
        (today, limit),
    ).fetchall()
    conn.close()

    count = 0
    for r in rows:
        dl_id = r["id"]
        try:
            existing = get_deadline_analysis(dl_id)
            if existing and existing.get("what_is_required"):
                continue
            result = analyze_deadline(dl_id)
            if result.get("what_is_required"):
                count += 1
                logger.info(f"Deadline analyzed: id={dl_id} ({result.get('title','')[:50]})")
        except Exception as e:
            logger.warning(f"Batch deadline analysis skipped id={dl_id}: {e}")

    logger.info(f"Deadline batch analysis complete: {count} new analyses")
    return count
