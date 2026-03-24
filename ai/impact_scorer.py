"""
Company Impact Scorer — Haiku post-Stage-2 scoring for each regulatory development.

Scores each development on four dimensions (1–10):
  direct_product  — risk to our own PFAS-coated products/finishes
  supply_chain    — risk to purchased components (vinyl, aluminum, glass, motors, electronics)
  financial       — potential financial/legal exposure
  timeline        — urgency of action window

Combined impact_score = weighted average (rounded to 1dp):
  direct_product * 0.35 + supply_chain * 0.25 + financial * 0.20 + timeline * 0.20

Runs as a Haiku batch call per topic — low cost, fast.
Results are cached by content hash to avoid re-scoring unchanged developments.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from .claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_COMPANY_CONTEXT = """
Windows and doors manufacturer (Andersen Corp). Key risk profile:
- DIRECT PRODUCT: PFAS fluoropolymer coatings/finishes applied to our own windows and doors
- SUPPLY CHAIN: purchases vinyl, aluminum, glass, wood, hardware, o-rings, motors, electronics, MRO
- MARKETS: sells in all 50 US states; no food packaging
- NOT a chemical manufacturer; regulatory burden is via product labeling + supplier disclosure
"""

_SCORE_PROMPT = """You score regulatory developments for a specific manufacturer's risk exposure.

Company: {company_context}

Score each development on:
1. direct_product (1-10): direct compliance risk to our own PFAS-containing products/finishes
   1=irrelevant, 5=monitoring needed, 10=immediate compliance action on our own products
2. supply_chain (1-10): risk to materials we purchase (vinyl, aluminum, glass, motors, electronics, o-rings)
   1=irrelevant, 5=supplier outreach warranted, 10=critical supply chain disruption risk
3. financial (1-10): potential cost/legal exposure
   1=negligible, 5=moderate cost or liability risk, 10=major financial or regulatory penalty exposure
4. timeline (1-10): urgency of action window
   1=>2 years away, 5=6-12 months, 8=<90 days, 10=<30 days or immediate enforcement

impact_score = (direct_product×0.35) + (supply_chain×0.25) + (financial×0.20) + (timeline×0.20), round to 1dp.

Developments to score (topic: {topic}):
{developments}

Return a JSON array — one object per development in the same order:
[{{"idx": 0, "direct_product": 4, "supply_chain": 6, "financial": 3, "timeline": 5, "impact_score": 4.6}}, ...]

Rules:
- Keep scores proportional: a 10 means company-stopping action needed NOW
- HIGH urgency ≠ automatically high scores — relevance to our specific products matters
- Return JSON only, no commentary
"""


def _content_hash(headline: str, summary: str) -> str:
    return hashlib.md5(f"{headline}::{summary}".encode()).hexdigest()[:12]


def score_developments(
    topic_name: str,
    developments: list[dict],
    client: Optional[ClaudeClient] = None,
) -> list[dict]:
    """
    Score a list of developments for company impact. Returns developments with
    added fields: direct_product, supply_chain, financial, timeline, impact_score.

    Uses a single Haiku call per topic batch. Cached by content hash.
    Failures are non-fatal — original developments returned unchanged.
    """
    if not developments:
        return developments

    if client is None:
        client = ClaudeClient()

    # Build compact development list for the prompt
    dev_lines = []
    for i, dev in enumerate(developments):
        headline = dev.get("headline", "")
        summary = dev.get("summary", "")
        urgency = dev.get("urgency", "")
        dev_lines.append(
            f"{i}. [{urgency}] {headline}\n   {summary[:200]}"
        )

    devs_text = "\n".join(dev_lines)
    cache_key = f"impact_{topic_name}_" + "_".join(
        _content_hash(d.get("headline", ""), d.get("summary", ""))
        for d in developments
    )

    prompt = _SCORE_PROMPT.format(
        company_context=_COMPANY_CONTEXT.strip(),
        topic=topic_name,
        developments=devs_text,
    )

    try:
        response = client.complete_haiku(
            prompt,
            system="You are a precise risk scorer. Return only valid JSON arrays.",
            cache_key=cache_key,
        )
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        scores = json.loads(text.strip())

        # Merge scores back into developments
        result = list(developments)
        for s in scores:
            idx = s.get("idx")
            if idx is not None and 0 <= idx < len(result):
                result[idx] = dict(result[idx])
                result[idx]["direct_product"] = s.get("direct_product", 5)
                result[idx]["supply_chain"] = s.get("supply_chain", 5)
                result[idx]["financial"] = s.get("financial", 5)
                result[idx]["timeline"] = s.get("timeline", 5)
                result[idx]["impact_score"] = s.get("impact_score", 5.0)

        logger.info(
            f"Impact scored {len(scores)}/{len(developments)} {topic_name} developments"
        )
        return result

    except Exception as e:
        logger.warning(f"Impact scoring failed for {topic_name} (non-fatal): {e}")
        return developments
