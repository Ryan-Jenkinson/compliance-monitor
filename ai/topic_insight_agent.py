"""Topic Insight Agent — analyzes 6-month article corpus per topic to generate
trend analysis, action items, company impact, and strategic recommendations.
Runs weekly (Mondays) and caches results in the topic_insights DB table.
"""
from __future__ import annotations
import json
import logging
from datetime import date, timedelta
from collections import defaultdict

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

_TOPICS_PATH = Path(__file__).parent.parent / "config" / "topics.yaml"

_SYSTEM = """\
You are a senior regulatory compliance analyst specializing in chemical regulations,
packaging laws, and environmental compliance for a US manufacturer (windows/doors).

Company context:
- PFAS: Fluoropolymer coatings on products; MN PRISM registration deadline July 1, 2026.
  Also buying PFAS-containing components — supplier registration risk is an operational shutdown risk.
- EPR: Extended Producer Responsibility — CA (SB 54), ME, OR, CO packaging compliance.
- REACH: EU SVHC substance restrictions; supplier declarations via Assent platform.
- TSCA: Section 6 use restrictions and Section 8 chemical data reporting.
- Prop65: California consumer product warnings for windows/doors.
- ConflictMinerals: Dodd-Frank 1409 supply chain due diligence.
- ForcedLabor: UFLPA supply chain compliance for imported components.

Tone: trusted expert colleague briefing a compliance lead. Specific, actionable, no hedging.
"""


def _load_topics() -> list[dict]:
    with open(_TOPICS_PATH) as f:
        return yaml.safe_load(f)["topics"]


def _build_prompt(topic_name: str, topic_config: dict, articles: list[dict],
                  monthly_counts: list[dict]) -> str:
    today = date.today().isoformat()
    cutoff_30 = (date.today() - timedelta(days=30)).isoformat()
    cutoff_7 = (date.today() - timedelta(days=7)).isoformat()

    # Split articles by time period
    breaking = [a for a in articles if a.get("first_seen", "")[:10] >= cutoff_7]
    last_30 = [a for a in articles if cutoff_30 <= a.get("first_seen", "")[:10] < cutoff_7]
    older = [a for a in articles if a.get("first_seen", "")[:10] < cutoff_30]

    def fmt_articles(arts: list[dict], max_count: int = 30) -> str:
        lines = []
        for a in arts[:max_count]:
            lines.append(f"- [{a.get('source','')}] {a.get('title','')} ({a.get('pub_date') or a.get('first_seen','')[:10]})")
        return "\n".join(lines) if lines else "(none)"

    monthly_summary = "\n".join(
        f"  {m['month']}: {m['count']} articles" for m in monthly_counts
    )

    company_relevance = topic_config.get("company_relevance", "")

    return f"""\
Analyze the last 6 months of regulatory intelligence for topic: {topic_config.get('label', topic_name)}

Today: {today}
Total articles in 6-month window: {len(articles)}

Company context for this topic:
{company_relevance}

Monthly article volume (trend indicator):
{monthly_summary}

BREAKING NEWS (last 7 days, {len(breaking)} articles):
{fmt_articles(breaking, 20)}

RECENT DEVELOPMENTS (last 30 days, {len(last_30)} articles):
{fmt_articles(last_30, 30)}

HISTORICAL CONTEXT (older than 30 days, {len(older)} articles — sample):
{fmt_articles(older, 20)}

Produce a JSON object with this exact structure (return JSON only, no markdown fences):
{{
  "topic": "{topic_name}",
  "analysis_date": "{today}",
  "six_month_trend": "2-3 sentences: what is the overall regulatory direction and momentum over the past 6 months? Is activity accelerating, decelerating, or stable? What is the dominant theme?",
  "biggest_changes_6mo": [
    "Most significant regulatory development in the past 6 months (1-2 sentences)",
    "Second most significant development",
    "Third most significant (if applicable)"
  ],
  "last_30_days": "2-3 sentences summarizing the key developments and signals from the past 30 days. What moved, what was filed, what enforcement happened?",
  "breaking_news": "1-2 sentences on the most urgent development from the past 7 days. If nothing significant, say so briefly.",
  "company_impact": {{
    "direct": "1-2 sentences: how do the 6-month trends affect our manufactured products directly?",
    "supply_chain": "1-2 sentences: what supply chain / procurement risks have emerged or intensified?",
    "severity": "HIGH | MEDIUM | LOW | MONITORING"
  }},
  "strategic_priorities": [
    "Top priority action item for the compliance team right now",
    "Second priority",
    "Third priority (if applicable)"
  ],
  "watch_list": "1-2 sentences: what specific developments, rulings, or deadlines should the team keep closest eye on in the next 60-90 days?",
  "article_count": {len(articles)},
  "breaking_count": {len(breaking)},
  "last_30_count": {len(last_30)}
}}
"""


def analyze_topic(topic_name: str, topic_config: dict, force: bool = False) -> dict | None:
    """Generate 6-month insight analysis for a single topic. Caches in DB (once per day)."""
    from subscribers.db import get_topic_insight, save_topic_insight, get_articles_for_display
    from ai.claude_client import ClaudeClient

    today = date.today().isoformat()

    if not force:
        existing = get_topic_insight(topic_name, period="weekly")
        if existing and existing.get("analysis_date") == today:
            logger.debug(f"Topic insight cache hit: {topic_name}")
            return existing

    # Load articles from DB
    articles = get_articles_for_display(topic=topic_name, days=180)

    if not articles:
        logger.info(f"No articles in DB for {topic_name} — skipping insight generation")
        return None

    # Build monthly counts
    from collections import defaultdict
    month_counts: dict = defaultdict(int)
    for a in articles:
        try:
            ym = a["first_seen"][:7]  # "2026-03"
            month_counts[ym] += 1
        except Exception:
            pass

    monthly_counts = [
        {"month": k, "count": v}
        for k, v in sorted(month_counts.items())
    ]

    prompt = _build_prompt(topic_name, topic_config, articles, monthly_counts)
    client = ClaudeClient()
    cache_key = f"topic_insight_{topic_name}_{today}"

    try:
        raw = client.complete_sonnet(prompt, system=_SYSTEM, cache_key=cache_key)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            if text.endswith("```"):
                text = text[:-3].strip()
        insight = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Topic insight JSON parse failed for {topic_name}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Topic insight failed for {topic_name}: {e}")
        return None

    insight["monthly_counts"] = monthly_counts

    try:
        save_topic_insight(topic_name, "weekly", today, insight)
        logger.info(f"Topic insight saved: {topic_name} ({len(articles)} articles)")
    except Exception as e:
        logger.warning(f"Failed to save topic insight for {topic_name}: {e}")

    return insight


def run_all_insights(force: bool = False) -> int:
    """Run insight analysis for all topics. Returns count of insights generated."""
    topics = _load_topics()
    count = 0
    for tc in topics:
        try:
            result = analyze_topic(tc["name"], tc, force=force)
            if result:
                count += 1
        except Exception as e:
            logger.warning(f"Topic insight skipped for {tc['name']}: {e}")
    logger.info(f"Topic insights complete: {count}/{len(topics)} generated")
    return count
