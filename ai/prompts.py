"""All Claude prompt templates."""
from __future__ import annotations
from typing import List
from processors.article import RawArticle


SYSTEM_COMPLIANCE_EXPERT = """\
You are a senior regulatory compliance analyst specializing in chemical regulations,
packaging laws, and environmental compliance for US manufacturing companies.
You write for a senior compliance specialist at a major US manufacturing company.

The company's PFAS compliance has TWO equally critical sides:

DIRECT SIDE (as manufacturer/seller):
- Fluoropolymer coatings on manufactured components contain PFAS
- These products must be registered in MN PRISM portal by July 1, 2026 (Amara's Law)
- 3M has exited the PFAS market, creating raw material supply risk
- Using Assent platform to collect official PFAS declarations and identify reformulation opportunities
- Reformulating products where possible to reduce the number of items requiring PRISM registration

INDIRECT SIDE (as buyer — supply chain risk):
- The company purchases thousands of components from suppliers/distributors: electronics for
  automation equipment, cylinder O-rings, gaskets, seals, PPE, lubricants, adhesives, and more
- Many of these components' UPSTREAM MANUFACTURERS use PFAS in their products
- Under MN Amara's Law: if a manufacturer does not register in PRISM by July 1, 2026,
  it becomes ILLEGAL for distributors to sell those PFAS-containing products in Minnesota
- This creates a cascading risk: the company could lose access to critical components if their
  suppliers' manufacturers miss the PRISM deadline — an operational shutdown risk
- The company is actively running supplier education email campaigns, reaching out to their
  full supply base (including distributors of electronics, industrial components, PPE)
  to educate them on the need to work with their manufacturers (domestic AND foreign) to
  ensure PRISM registration before July 1, 2026
- Foreign manufacturers exporting PFAS-containing products to MN are also subject to Amara's Law

The company's other key compliance concerns:
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
    """Stage 2: Ask Sonnet to produce structured topic summary with company impact."""
    articles_text = []
    for a in articles:
        is_new = a.extra.get("is_new", True)
        days = a.extra.get("days_in_newsletter", 0)
        status = "NEW" if is_new else f"CARRIED OVER (day {days} of 5)"
        articles_text.append(
            f"STATUS: {status}\n"
            f"SOURCE: {a.source}\n"
            f"TITLE: {a.title}\n"
            f"URL: {a.url}\n"
            f"DATE: {a.published_at.strftime('%Y-%m-%d') if a.published_at else 'unknown'}\n"
            f"SNIPPET: {a.snippet[:600]}\n"
        )

    content = "\n---\n".join(articles_text) if articles_text else "(no new articles)"
    company_relevance = topic_config.get("company_relevance", "")

    return f"""\
Topic: {topic_config['label']}

Company-specific context:
{company_relevance}

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
      "urgency": "HIGH | MEDIUM | LOW",
      "is_new": true
    }}
  ],
  "company_impact": {{
    "direct_products": "ONE sentence max: impact on our own PFAS-containing products. Null if N/A.",
    "supply_chain": "ONE sentence max: which purchased component categories are at risk. Null if N/A.",
    "supplier_campaign": "ONE sentence max: what this means for supplier outreach. Null if N/A.",
    "direct_actions": ["1-2 specific action items max for direct compliance"],
    "supplier_actions": ["1-2 specific action items max for supplier outreach"]
  }},
  "has_news": true
}}

If there are no articles or none are relevant, return:
{{
  "topic": "{topic_config['name']}",
  "developments": [],
  "company_impact": {{
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
Set "is_new": true only for articles with STATUS: NEW. Set false for CARRIED OVER articles.
Prioritize NEW articles in your analysis but include CARRIED OVER items as context.
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

Write an executive briefing for SENIOR LEADERSHIP — people who are not compliance specialists
and may not know what PFAS, EPR, REACH, TSCA, PRISM, or other acronyms mean.

This will be read by VPs, directors, and C-suite. It should read like a polished internal memo
from a trusted advisor — authoritative, concise, and clear about business impact.

Structure (use these exact section markers):

[OPENING]
A 2-3 sentence opening paragraph that frames the week's regulatory landscape. Set context:
what is the overall posture (stable, escalating, approaching deadlines)? Mention the single
most important thing leadership should know. Spell out any acronym on first use.

[KEY DEVELOPMENTS]
3-4 bullet points covering only items that have material business impact. Each bullet should:
- Lead with the business consequence, not the regulatory detail
- Name specific deadlines, cost exposure, or operational risk
- Be 1-2 sentences max
- Use plain business language — "supply chain disruption risk" not "TSCA Section 6 rulemaking"

[OUTLOOK]
A 1-2 sentence forward-looking close. What should leadership be watching for next?
What decisions may be needed soon?

Writing rules:
- Spell out every acronym on first use (e.g. "PFAS (a class of industrial chemicals used in coatings and components)")
- No jargon without explanation. If a compliance term is necessary, define it in context.
- Be direct and confident. No hedging ("may potentially"), no filler ("it is worth noting").
- Write at the level of a Wall Street Journal article — precise, polished, authoritative.

Return plain text with section markers [OPENING], [KEY DEVELOPMENTS], [OUTLOOK] on their own lines.
Bullets in KEY DEVELOPMENTS should be prefixed with "•".
No JSON, no markdown, no headers beyond the section markers.
"""
