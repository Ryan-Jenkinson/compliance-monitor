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
  "company_strategy": "2-3 sentences. Based on NEW developments today, what is the specific recommended action for the compliance team this week? If nothing material changed today, restate the most current plan (e.g. continue monitoring X, prepare Y ahead of deadline Z). Never say 'no updates' — always give a concrete direction.",
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
  "company_strategy": null,
  "has_news": false
}}

Return JSON only. Urgency guide: HIGH = active deadline <90 days or enforcement imminent;
MEDIUM = proposed rule or deadline 90-365 days; LOW = long-range or informational.
Set "is_new": true only for articles with STATUS: NEW. Set false for CARRIED OVER articles.
Prioritize NEW articles in your analysis but include CARRIED OVER items as context.
"""


def stage3_exec_summary_prompt(topic_summaries: list[dict], week_context: dict | None = None) -> str:
    """Stage 3: Generate weekly briefing across all topics, day-aware."""
    topic_text = []
    for ts in topic_summaries:
        topic_text.append(f"TOPIC: {ts['topic']}")
        if ts.get("developments"):
            for d in ts["developments"]:
                status = "NEW" if d.get("is_new", True) else "CARRIED OVER"
                topic_text.append(f"  - [{status}][{d.get('urgency','?')}] {d.get('headline','')}: {d.get('summary','')[:200]}")
        else:
            topic_text.append("  - No new developments")

    summaries_text = "\n".join(topic_text)

    ctx = week_context or {}
    today_name = ctx.get("today_name", "today")
    week_start_long = ctx.get("week_start_long", "this week")
    week_end_long = ctx.get("week_end_long", "this Friday")
    week_label = ctx.get("week_label", "this week")
    is_friday = ctx.get("is_friday", False)

    if is_friday:
        day_framing = (
            f"Today is Friday — this is the END-OF-WEEK summary covering the full week of {week_label} "
            f"({week_start_long} through {week_end_long}). Write it as a complete weekly wrap-up."
        )
        opening_instruction = (
            "1-2 sentences wrapping up the week — what was the overall posture? "
            "What was the most significant development of the week?"
        )
        developments_instruction = (
            "3-6 bullet points covering all material developments from this week. "
            "This is the full week summary — be comprehensive but tight."
        )
    else:
        day_framing = (
            f"Today is {today_name}. This briefing covers developments so far in the week of {week_label} "
            f"(since {week_start_long}). Articles marked CARRIED OVER appeared earlier this week."
        )
        opening_instruction = (
            f"1-2 sentences framing where things stand as of {today_name} — "
            "what is the posture, what's the most significant thing since Monday?"
        )
        developments_instruction = (
            f"3-5 bullet points covering new developments since the start of this week. "
            "Prioritize items marked NEW. Include CARRIED OVER items only if still actively relevant."
        )

    return f"""\
You have just analyzed this week's compliance news across PFAS, EPR, REACH, and TSCA topics.
{day_framing}

Here is a condensed view of all developments (NEW = appeared today or earlier this week, CARRIED OVER = seen earlier this week):

{summaries_text}

Write a weekly briefing for a small, expert compliance team — a compliance lead, their senior manager,
and occasionally a director. These people receive this briefing every week and have been tracking
PFAS, EPR, REACH, and TSCA for years. They know the regulatory landscape, the active campaigns,
and the company's current strategy cold. Do NOT explain what PFAS is. Do NOT re-state known major
deadlines as if they are breaking news. Write as a trusted colleague catching up experts.

Structure (use these EXACT section markers on their own lines):

[OPENING]
{opening_instruction}

[KEY DEVELOPMENTS]
{developments_instruction}
Each bullet: lead with what changed and where, then the implication. 1-2 sentences max. Prefix with "•".

[OUTLOOK]
1-2 sentences on what to watch next. Specific if possible.

[FUN FACT]
One compliance-related fun fact or dry compliance joke for the team. Keep it brief (1-2 sentences).
Prioritize genuinely interesting-but-true facts related to this week's topics (regulatory history,
surprising statistics, obscure rules). If nothing interesting applies, a dry compliance team joke is fine
— something your team would actually chuckle at, not a groan. Examples of the right tone:
"Fun fact: the EU REACH candidate list now covers 240+ substances — it started with 15 in 2008."
"Compliance joke: Why did the PFAS molecule cross the road? To get to the other side of the regulatory threshold."

Writing rules:
- Full familiarity with all acronyms assumed — no definitions
- Direct and confident. No hedging, no filler
- If genuinely no significant new developments, say so plainly in [OPENING], keep [KEY DEVELOPMENTS] brief

Return plain text only. Section markers on their own lines. No JSON, no markdown beyond the markers.
"""


def deadline_extraction_prompt(topic_summaries: list[dict]) -> str:
    """Extract structured regulatory deadlines from all topic summaries."""
    lines = []
    for ts in topic_summaries:
        for d in ts.get("developments", []):
            if d.get("deadline"):
                lines.append(
                    f"TOPIC: {ts['topic']} | TITLE: {d.get('headline','')} | "
                    f"DEADLINE: {d.get('deadline','')} | SUMMARY: {d.get('summary','')[:200]} | "
                    f"URL: {d.get('url','')} | URGENCY: {d.get('urgency','MEDIUM')}"
                )

    if not lines:
        return ""

    content = "\n".join(lines)
    from datetime import date
    today = date.today().isoformat()

    return f"""\
Today is {today}. Extract structured regulatory deadlines from the following compliance developments.
Only extract SPECIFIC deadlines with a known or strongly implied date (not vague "upcoming" references).

{content}

Return a JSON array of deadline objects:
[
  {{
    "topic": "pfas|epr|reach|tsca",
    "title": "Short deadline title (max 12 words)",
    "deadline_date": "YYYY-MM-DD",
    "description": "One sentence explaining what must be done by this date",
    "jurisdiction": "e.g. Minnesota, Federal, EU, California",
    "source_url": "URL",
    "urgency": "HIGH|MEDIUM|LOW"
  }}
]

Rules:
- Only include deadlines with a specific date you can express as YYYY-MM-DD
- If only month/year known, use the last day of that month
- HIGH = deadline within 90 days, MEDIUM = 90-365 days, LOW = beyond 365 days
- Skip vague or speculative deadlines
- Return [] if no concrete deadlines found

Return JSON only.
"""
