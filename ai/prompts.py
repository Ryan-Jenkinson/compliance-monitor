"""All Claude prompt templates."""
from __future__ import annotations
from typing import List
from processors.article import RawArticle


SYSTEM_COMPLIANCE_EXPERT = """\
You are a senior regulatory compliance analyst specializing in chemical regulations,
packaging laws, and environmental compliance for US manufacturing companies.
You write for a senior compliance specialist at Andersen Windows & Doors —
a major window and door manufacturer headquartered in Bayport, Minnesota.

Andersen's PFAS compliance has TWO equally critical sides:

DIRECT SIDE (Andersen as manufacturer/seller):
- Fluoropolymer coatings on weatherstripping and window/door seals contain PFAS
- Andersen must register these products in MN PRISM portal by July 1, 2026 (Amara's Law)
- 3M has exited the PFAS market, creating raw material supply risk
- Using Assent platform to collect official PFAS declarations and identify reformulation opportunities
- Reformulating products where possible to reduce the number of items requiring PRISM registration

INDIRECT SIDE (Andersen as buyer — supply chain risk):
- Andersen purchases thousands of components from suppliers/distributors: electronics for
  automation equipment, cylinder O-rings, gaskets, seals, PPE, lubricants, adhesives, and more
- Many of these components' UPSTREAM MANUFACTURERS use PFAS in their products
- Under MN Amara's Law: if a manufacturer does not register in PRISM by July 1, 2026,
  it becomes ILLEGAL for distributors to sell those PFAS-containing products in Minnesota
- This creates a cascading risk: Andersen could lose access to critical components if their
  suppliers' manufacturers miss the PRISM deadline — an operational shutdown risk
- Andersen is actively running supplier education email campaigns, reaching out to their
  full supply base (including distributors of electronics, industrial components, PPE)
  to educate them on the need to work with their manufacturers (domestic AND foreign) to
  ensure PRISM registration before July 1, 2026
- Foreign manufacturers exporting PFAS-containing products to MN are also subject to Amara's Law

Andersen's other key compliance concerns:
- EPR: packaging compliance in CA, ME, OR, CO and emerging states
- REACH: EU/international supplier requirements and SVHC substance tracking
- TSCA: chemical reporting and potential use restrictions in manufacturing

Your tone: precise, factual, actionable. No hedging. No generic advice.
For every development, consider BOTH the direct product compliance angle AND the indirect
supply chain / procurement risk angle. Supplier campaign action items are as important as
direct registration action items.
"""


def stage1_filter_prompt(articles: List[RawArticle], topic: str) -> str:
    """Stage 1: Ask Haiku to filter articles to genuinely new regulatory developments."""
    lines = []
    for a in articles:
        lines.append(f'ID: {a.id} | Title: {a.title} | Snippet: {a.snippet[:200]}')

    articles_text = "\n".join(lines) if lines else "(no articles)"

    return f"""\
Topic: {topic}

Below is a list of articles scraped over the last 30 days. Your job is to identify which ones
represent GENUINELY NEW regulatory developments — new rules, proposals, enforcement actions,
deadlines, or significant policy changes. Exclude: opinion pieces, general news summaries,
industry commentary without new regulatory content, and pure duplicates.

Return ONLY a JSON array of article IDs to keep. If none qualify, return [].

Articles:
{articles_text}

Return JSON only, no explanation. Example: ["abc123", "def456"]
"""


def stage2_summarize_prompt(articles: List[RawArticle], topic_config: dict) -> str:
    """Stage 2: Ask Sonnet to produce structured topic summary with Andersen impact."""
    articles_text = []
    for a in articles:
        articles_text.append(
            f"SOURCE: {a.source}\n"
            f"TITLE: {a.title}\n"
            f"URL: {a.url}\n"
            f"DATE: {a.published_at.strftime('%Y-%m-%d') if a.published_at else 'unknown'}\n"
            f"SNIPPET: {a.snippet[:600]}\n"
        )

    content = "\n---\n".join(articles_text) if articles_text else "(no new articles)"
    andersen_relevance = topic_config.get("andersen_relevance", "")

    return f"""\
Topic: {topic_config['label']}

Andersen-specific context:
{andersen_relevance}

Articles to analyze (may span up to 30 days — prioritize and clearly label the most recent
developments first; note the date of each development in the output):
{content}

Produce a JSON object with this exact structure:
{{
  "topic": "{topic_config['name']}",
  "developments": [
    {{
      "headline": "Concise headline (max 15 words)",
      "summary": "2-3 sentence factual summary of the regulatory development",
      "url": "source URL",
      "source": "source name",
      "date": "YYYY-MM-DD or null",
      "deadline": "Key compliance deadline if present, else null",
      "urgency": "HIGH | MEDIUM | LOW"
    }}
  ],
  "andersen_impact": {{
    "direct_products": "Impact on Andersen's OWN products containing PFAS — registration, reformulation, labeling obligations. Null if not applicable.",
    "supply_chain": "Impact on Andersen's PURCHASING side — which component categories (electronics, gaskets, PPE, etc.) are at risk if their manufacturers miss registration deadlines. Be specific about procurement risk. Null if not applicable.",
    "supplier_campaign": "What this development means for Andersen's supplier education campaigns — does it add urgency, identify new supplier segments to target, or change messaging? Null if not applicable.",
    "direct_actions": ["Specific action item for Andersen's own product compliance"],
    "supplier_actions": ["Specific action for Andersen's supplier outreach or Assent declarations"]
  }},
  "has_news": true
}}

If there are no articles or none are relevant, return:
{{
  "topic": "{topic_config['name']}",
  "developments": [],
  "andersen_impact": {{
    "direct_products": null,
    "supply_chain": null,
    "supplier_campaign": null,
    "direct_actions": [],
    "supplier_actions": []
  }},
  "has_news": false
}}

Return JSON only. Urgency guide: HIGH = active deadline <90 days or enforcement imminent;
MEDIUM = proposed rule or deadline 90-365 days; LOW = long-range or informational.
"""


def stage3_exec_summary_prompt(topic_summaries: list[dict]) -> str:
    """Stage 3: Generate 3-5 sentence executive summary across all topics."""
    topic_text = []
    for ts in topic_summaries:
        topic_text.append(f"TOPIC: {ts['topic']}")
        if ts.get("developments"):
            for d in ts["developments"]:
                topic_text.append(f"  - [{d.get('urgency','?')}] {d.get('headline','')}: {d.get('summary','')[:200]}")
        else:
            topic_text.append("  - No new developments")

    summaries_text = "\n".join(topic_text)

    return f"""\
You have just analyzed today's compliance news across PFAS, EPR, REACH, and TSCA topics.
Here is a condensed view of all developments:

{summaries_text}

Write a 3-5 sentence executive summary for the top of today's compliance briefing email.
Focus on the 1-2 most actionable or time-sensitive items. Be specific about Andersen's
exposure. Mention deadlines if present. Use professional but direct language — no filler.

Return plain text only (no JSON, no markdown headers).
"""
