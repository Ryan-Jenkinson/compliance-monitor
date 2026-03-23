"""
PFAS Legislative Intelligence Pipeline.

Orchestrates:
  1. Run all legislative intel scrapers (+ existing PFAS scrapers)
  2. Multi-pass Claude extraction to identify forward-looking state signals
  3. Structured output per state with confidence levels and evidence
  4. Feed into proposed legislation map generator
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from processors.article import RawArticle

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "claude"


def _load_existing_pfas_articles() -> List[RawArticle]:
    """Load today's cached PFAS articles from the existing scrapers."""
    cache_dir = Path(__file__).parent.parent / "data" / "cache"
    articles = []
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    for f in cache_dir.glob(f"*{today}.json"):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                for d in data:
                    topic = d.get("topic", "")
                    title = d.get("title", "")
                    snippet = d.get("snippet", "") or ""
                    full = d.get("full_text", "") or ""
                    text = (title + " " + snippet + " " + full).lower()
                    if "pfas" in topic.lower() or "pfas" in text or "pfoa" in text or "pfos" in text:
                        articles.append(RawArticle(
                            id=d.get("id", ""),
                            title=d.get("title", ""),
                            url=d.get("url", ""),
                            source=d.get("source", ""),
                            topic="PFAS",
                            snippet=d.get("snippet", ""),
                            full_text=d.get("full_text", ""),
                            extra=d.get("extra", {}),
                        ))
        except Exception:
            pass

    return articles


def _prepare_article_context(articles: List[RawArticle], max_chars: int = 50000) -> str:
    """
    Prepare a compact text representation of all articles for Claude.
    Prioritizes articles with full text, state mentions, and forward-looking signals.
    """
    # Score and sort
    scored = []
    for a in articles:
        score = 0
        text = a.title + " " + a.snippet + " " + (a.full_text or "")
        t = text.lower()

        # Forward-looking signals
        forward_kw = ["propos", "bill", "introduc", "hearing", "committee",
                      "rulemaking", "draft", "session", "upcoming", "pending",
                      "consider", "campaign", "investigation", "petition",
                      "task force", "study commission", "executive order"]
        score += sum(2 for kw in forward_kw if kw in t)

        # State mentions
        if a.extra.get("states_mentioned"):
            score += len(a.extra["states_mentioned"]) * 3

        # Has full text
        if a.full_text and len(a.full_text) > 200:
            score += 5

        # Source type bonus
        signal = a.extra.get("signal_type", "")
        if signal in ("legal_analysis", "ag_enforcement", "advocacy_campaign"):
            score += 3
        if signal in ("legislation_tracker", "legislation_table"):
            score += 4

        scored.append((score, a))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Build context string
    parts = []
    total_chars = 0
    for score, a in scored:
        if total_chars >= max_chars:
            break

        states_str = ", ".join(a.extra.get("states_mentioned", [])) or "N/A"
        signal_str = a.extra.get("signal_type", "unknown")

        entry = f"""---
SOURCE: {a.source}
TITLE: {a.title}
URL: {a.url}
SIGNAL TYPE: {signal_str}
STATES MENTIONED: {states_str}
RELEVANCE SCORE: {score}
"""
        if a.full_text and len(a.full_text) > 100:
            entry += f"FULL TEXT:\n{a.full_text[:2000]}\n"
        elif a.snippet:
            entry += f"SNIPPET: {a.snippet}\n"

        parts.append(entry)
        total_chars += len(entry)

    return "\n".join(parts)


def _run_claude_extraction(article_context: str) -> dict:
    """
    Multi-pass Claude extraction:
      Pass 1: Extract all state-level PFAS legislative signals
      Pass 2: Enrich with forward-looking analysis and engagement guidance
    """
    from ai.claude_client import ClaudeClient
    client = ClaudeClient()

    # =========================================================================
    # Pass 1: Extract raw state signals from articles
    # =========================================================================
    pass1_prompt = f"""You are a legislative intelligence analyst specializing in US state chemical regulation. Today is March 23, 2026.

I have collected articles from law firm blogs, advocacy organizations, state agencies, legal news aggregators, and regulatory news outlets. Your job is to extract EVERY signal about PFAS-related legislative activity at the US state level.

CRITICAL: I need FORWARD-LOOKING intelligence. This means:
- Bills that have been introduced but not yet enacted
- Rulemaking proceedings in progress
- Committee hearings being scheduled or conducted
- Legislative study commissions or task forces examining PFAS
- Attorney General investigations or enforcement actions (these often precede legislation)
- Advocacy campaigns targeting specific states
- Executive orders or gubernatorial actions
- States where advocacy groups or industry associations have announced legislative pushes
- Pre-filing announcements or draft bill language being circulated
- States where similar legislation has been proposed in prior sessions and is likely to return
- Any discussion, analysis, or prediction about upcoming state PFAS action

For EACH state where you find any signal, extract:
1. State abbreviation
2. Signal type: "bill_introduced" | "in_committee" | "passed_one_chamber" | "rulemaking" | "hearing_scheduled" | "study_commission" | "ag_investigation" | "advocacy_campaign" | "executive_action" | "pre_filing" | "prior_session_expected_return" | "discussion_only"
3. Bill number(s) if applicable
4. Description of the activity
5. What specifically is being proposed (scope: product bans, reporting, drinking water, foam, etc.)
6. Evidence: which article(s) mention this
7. How recent is this signal (date if available)

Also use your training knowledge (through August 2025) to supplement the article data. If you know about state PFAS legislative activity that isn't in the articles, include it but mark the evidence as "training_knowledge".

ARTICLES:
{article_context}

Return ONLY a JSON array (no markdown fences), where each entry is:
{{
  "state": "XX",
  "signals": [
    {{
      "type": "signal_type",
      "bill": "HB 123 or null",
      "description": "what is happening",
      "scope": "product restrictions | reporting | drinking water | foam | broad ban | contamination | multiple",
      "evidence": "source: title or training_knowledge",
      "date": "2026-03-XX or 2025-XX or null",
      "confidence": "high | medium | low"
    }}
  ]
}}

Include ALL 50 states + DC. For states with no signals, include them with an empty signals array.
Be thorough — capture every hint of PFAS legislative activity. It is better to include a low-confidence signal than to miss it entirely.
"""

    logger.info("Pass 1: Extracting state-level PFAS signals from articles...")
    pass1_raw = client.complete_sonnet(
        pass1_prompt,
        system="You are a legislative intelligence analyst. Return only valid JSON, no markdown fences or commentary.",
        cache_key="pfas_intel_pass1_2026-03-23_v3",
    )

    # Parse pass 1 result
    pass1_raw = pass1_raw.strip()
    if pass1_raw.startswith("```"):
        pass1_raw = pass1_raw.split("\n", 1)[1]
        pass1_raw = pass1_raw.rsplit("```", 1)[0]

    try:
        pass1_data = json.loads(pass1_raw)
    except json.JSONDecodeError as e:
        logger.error(f"Pass 1 JSON parse error: {e}")
        logger.error(f"Raw output (first 500 chars): {pass1_raw[:500]}")
        return {}

    # =========================================================================
    # Pass 2: Synthesize into map-ready format with engagement guidance
    # =========================================================================

    # Summarize pass 1 for pass 2 context
    pass1_summary = json.dumps(pass1_data, indent=1)

    pass2_prompt = f"""You are a senior regulatory strategist advising a US manufacturer (window/door products with fluoropolymer PFAS-containing coatings) on state PFAS legislative engagement opportunities. Today is March 23, 2026.

Below is raw intelligence about PFAS legislative activity in each US state. Your job is to synthesize this into a final map dataset that will help the legal team prioritize which states to engage with.

RAW INTELLIGENCE:
{pass1_summary}

For each state that has ANY signal (even low-confidence), produce a final entry with:

1. **stage** — Choose the most advanced/important stage:
   - "pre_discussion": Signals suggest potential future action but nothing concrete yet (advocacy targeting, prior session bills expected to return, related enforcement actions)
   - "discussion": Active discussions, study commissions, task forces, hearings without a bill
   - "rulemaking": Administrative rulemaking proceeding in progress (not legislative but equally important)
   - "introduced": Bill has been filed/introduced
   - "committee": Bill is in committee review
   - "passed_one": Bill has passed one chamber
   - "advanced": Bill near final passage or governor's desk
   - "enacted_watching": Recently enacted, implementation phase with open rulemaking or comment periods

2. **bills**: Array of bill numbers/names
3. **summary**: 2-4 sentence description covering what's proposed, current status, and trajectory
4. **scope**: What the legislation covers (product restrictions, reporting, drinking water, foam, contamination liability, broad ban, multiple)
5. **session**: Legislative session year
6. **engagement_note**: Specific guidance for the legal engagement team:
   - What action to take at this stage
   - Who to engage (committee chair, bill sponsor, governor's office, rulemaking docket)
   - What the company's angle should be (as a fluoropolymer user with legitimate industrial applications)
   - Time urgency (session end dates, comment deadlines, hearing dates)
7. **confidence**: "high" (direct evidence in articles), "medium" (partial evidence + inference), "low" (training knowledge or weak signals)
8. **evidence_sources**: Array of source names that support this assessment

For states with NO signals at all, set stage to "none" and include minimal fields.

IMPORTANT: Be aggressive about including states. If there's even a hint of potential PFAS activity — an AG investigation, a neighboring state's action that could inspire copycats, an advocacy group announcing a campaign — include it at "pre_discussion" with appropriate confidence. The legal team would rather know about 40 states to watch than miss one.

Return ONLY a JSON object (no markdown):
{{
  "generated": "2026-03-23",
  "pipeline_version": "v2_deep_scrape",
  "total_signals": <count>,
  "states": {{
    "XX": {{
      "name": "Full State Name",
      "stage": "stage_value",
      "bills": ["..."],
      "summary": "...",
      "scope": "...",
      "session": "...",
      "engagement_note": "...",
      "confidence": "high|medium|low",
      "evidence_sources": ["..."]
    }}
  }}
}}
"""

    logger.info("Pass 2: Synthesizing intelligence into engagement-ready format...")
    pass2_raw = client.complete(
        pass2_prompt,
        system="You are a regulatory strategist. Return only valid JSON, no markdown fences.",
        model="claude-sonnet-4-6",
        max_tokens=12000,
        cache_key="pfas_intel_pass2_2026-03-23_v3",
    )

    pass2_raw = pass2_raw.strip()
    if pass2_raw.startswith("```"):
        pass2_raw = pass2_raw.split("\n", 1)[1]
        pass2_raw = pass2_raw.rsplit("```", 1)[0]

    try:
        final_data = json.loads(pass2_raw)
    except json.JSONDecodeError as e:
        logger.error(f"Pass 2 JSON parse error: {e}")
        logger.error(f"Raw output (first 500 chars): {pass2_raw[:500]}")
        return {}

    return final_data


def _load_legiscan_data() -> str:
    """
    Run LegiScan tracker and return structured bill data as context for Claude.
    Returns empty string if LegiScan is not configured.
    """
    try:
        from scrapers.legiscan_tracker import LegiScanTracker
        tracker = LegiScanTracker()
        report = tracker.run()
        bills = tracker.export_for_pipeline()
        tracker.close()

        if not bills:
            return ""

        lines = [
            f"\n\n=== LEGISCAN STRUCTURED BILL DATA ({len(bills)} active PFAS bills) ===",
            "This is authoritative, real-time data from state legislature tracking systems.",
            "Use this data with HIGH confidence — it overrides article-based inferences.\n",
        ]
        for b in bills:
            sponsors_str = ", ".join(b["sponsors"][:3]) if b["sponsors"] else "N/A"
            actions_str = " | ".join(b["recent_actions"][-2:]) if b["recent_actions"] else "N/A"
            lines.append(
                f"STATE: {b['state']} | BILL: {b['bill_number']} | STATUS: {b['status']}\n"
                f"  TITLE: {b['title'][:150]}\n"
                f"  DESCRIPTION: {b['description'][:200]}\n"
                f"  STAGE: {b['stage']} | SCOPE: {b['scope']}\n"
                f"  COMMITTEE: {b['committee'] or 'N/A'}\n"
                f"  SPONSORS: {sponsors_str}\n"
                f"  RECENT ACTIONS: {actions_str}\n"
                f"  URL: {b['url']}\n"
            )

        logger.info(f"LegiScan: {len(bills)} active bills across {report['states_with_bills']} states "
                     f"({report['api_calls']} API calls)")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"LegiScan integration skipped: {e}")
        return ""


def run_pipeline(skip_scrape: bool = False) -> dict:
    """
    Run the full PFAS legislative intelligence pipeline.
    Returns structured state-level data ready for map generation.
    """
    # Step 1: Collect articles
    logger.info("=" * 60)
    logger.info("PFAS Legislative Intelligence Pipeline")
    logger.info("=" * 60)

    all_articles = []

    if not skip_scrape:
        # Run new legislative intel scrapers
        logger.info("\n--- Running legislative intelligence scrapers ---")
        from scrapers.pfas_legislative_intel import run_all_legislative_scrapers
        intel_articles = run_all_legislative_scrapers(enrich=True)
        all_articles.extend(intel_articles)
        logger.info(f"Legislative intel scrapers: {len(intel_articles)} articles")

    # Also load existing PFAS articles from today's cache
    logger.info("\n--- Loading existing PFAS articles from cache ---")
    existing = _load_existing_pfas_articles()
    all_articles.extend(existing)
    logger.info(f"Existing PFAS cache: {len(existing)} articles")

    logger.info(f"\nTotal articles for analysis: {len(all_articles)}")

    # Step 1b: Run LegiScan bill tracker (if configured)
    logger.info("\n--- Running LegiScan bill tracker ---")
    legiscan_context = _load_legiscan_data()

    # Step 2: Prepare context for Claude
    logger.info("\n--- Preparing article context ---")
    context = _prepare_article_context(all_articles, max_chars=50000)
    # Append LegiScan structured data — this takes priority in Claude's analysis
    if legiscan_context:
        context = context + "\n" + legiscan_context
    logger.info(f"Context prepared: {len(context)} chars total")

    # Step 3: Run Claude extraction pipeline
    logger.info("\n--- Running Claude extraction pipeline ---")
    result = _run_claude_extraction(context)

    if result:
        # Save the result
        output_path = _CACHE_DIR / "pfas_legislative_intel_result.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2))
        logger.info(f"\nPipeline result saved to: {output_path}")

        states = result.get("states", {})
        active = {k: v for k, v in states.items() if v.get("stage", "none") != "none"}
        logger.info(f"Active states: {len(active)} / {len(states)}")

        # Show summary by stage
        by_stage: dict[str, int] = {}
        for s in states.values():
            stage = s.get("stage", "none")
            by_stage[stage] = by_stage.get(stage, 0) + 1
        logger.info("By stage:")
        for stage, count in sorted(by_stage.items(), key=lambda x: -x[1]):
            logger.info(f"  {stage}: {count}")

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_pipeline()
    if result:
        print(f"\nPipeline complete. States: {len(result.get('states', {}))}")
    else:
        print("\nPipeline failed.")
