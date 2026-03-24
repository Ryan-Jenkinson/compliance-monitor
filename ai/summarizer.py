"""3-stage AI pipeline: filter → summarize → executive summary."""
from __future__ import annotations
import json
import logging
from typing import List

import yaml
from pathlib import Path

from .claude_client import ClaudeClient
from .prompts import (
    SYSTEM_COMPLIANCE_EXPERT,
    stage1_filter_prompt,
    stage2_summarize_prompt,
    stage3_exec_summary_prompt,
    deadline_extraction_prompt,
)
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_TOPICS_PATH = Path(__file__).parent.parent / "config" / "topics.yaml"


def _load_topics() -> list[dict]:
    with open(_TOPICS_PATH) as f:
        return yaml.safe_load(f)["topics"]


class Summarizer:
    def __init__(self):
        self.client = ClaudeClient()
        self.topics = _load_topics()

    def run(self, articles: List[RawArticle], week_context: dict | None = None) -> dict:
        """
        Run the full 3-stage pipeline.

        Returns:
            {
                "exec_summary": "...",
                "topics": [<topic_summary>, ...],
                "total_articles": N,
                "total_sources": N,
            }
        """
        # Group articles by topic
        by_topic: dict[str, List[RawArticle]] = {}
        for t in self.topics:
            by_topic[t["name"]] = []
        for article in articles:
            if article.topic in by_topic:
                by_topic[article.topic].append(article)

        topic_summaries = []

        for topic_config in self.topics:
            topic_name = topic_config["name"]
            topic_articles = by_topic.get(topic_name, [])

            logger.info(f"Processing {topic_name}: {len(topic_articles)} articles")

            # Stage 1: filter with Haiku (only if we have articles)
            filtered_articles = []
            if topic_articles:
                filtered_articles = self._stage1_filter(topic_articles, topic_name)
                logger.info(f"  Stage 1 kept {len(filtered_articles)}/{len(topic_articles)}")

            # Stage 2: summarize with Sonnet
            summary = self._stage2_summarize(filtered_articles, topic_config)
            topic_summaries.append(summary)

        # Stage 3: weekly briefing (day-aware)
        exec_summary = self._stage3_exec_summary(topic_summaries, week_context=week_context)

        # Extract and store deadlines
        if week_context:
            self._extract_deadlines(topic_summaries, week_context.get("week_start", ""))

        # Extract regulation records from pipeline output
        try:
            from processors.regulation_registry import extract_from_pipeline
            extract_from_pipeline(topic_summaries)
        except Exception as e:
            logger.warning(f"Regulation extraction failed (non-fatal): {e}")

        return {
            "exec_summary": exec_summary,
            "topics": topic_summaries,
            "total_articles": len(articles),
            "total_sources": len({a.source for a in articles}),
        }

    def _stage1_filter(
        self, articles: List[RawArticle], topic_name: str
    ) -> List[RawArticle]:
        if not articles:
            return []

        prompt = stage1_filter_prompt(articles, topic_name)
        cache_key = f"s1_{topic_name}_{'_'.join(sorted(a.id for a in articles))}"

        try:
            response = self.client.complete_haiku(
                prompt,
                system=SYSTEM_COMPLIANCE_EXPERT,
                cache_key=cache_key,
            )
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            keep_ids = set(json.loads(text.strip()))
            return [a for a in articles if a.id in keep_ids]
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Stage 1 filter failed for {topic_name}: {e} — keeping all")
            return articles

    def _stage2_summarize(
        self, articles: List[RawArticle], topic_config: dict
    ) -> dict:
        topic_name = topic_config["name"]
        article_ids = "_".join(sorted(a.id for a in articles)) if articles else "empty"
        cache_key = f"s2_{topic_name}_{article_ids}"

        prompt = stage2_summarize_prompt(articles, topic_config)

        try:
            response = self.client.complete_sonnet(
                prompt,
                system=SYSTEM_COMPLIANCE_EXPERT,
                cache_key=cache_key,
            )
            # Strip markdown code fences if present
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Stage 2 summarize failed for {topic_name}: {e}")
            return {
                "topic": topic_name,
                "developments": [],
                "company_impact": {
                    "direct_products": None,
                    "supply_chain": None,
                    "supplier_campaign": None,
                    "direct_actions": [],
                    "supplier_actions": [],
                },
                "has_news": False,
            }

    def _extract_deadlines(self, topic_summaries: list, week_start: str) -> int:
        """Extract and store regulatory deadlines from topic summaries. Returns count saved."""
        from subscribers.db import upsert_deadline

        prompt = deadline_extraction_prompt(topic_summaries)
        if not prompt:
            return 0

        try:
            response = self.client.complete_haiku(
                prompt,
                system="You extract structured data. Return valid JSON only.",
                cache_key=f"deadlines_{week_start}",
            )
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            deadlines = json.loads(text.strip())
            if not isinstance(deadlines, list):
                return 0
            count = 0
            for dl in deadlines:
                try:
                    upsert_deadline(
                        topic=dl.get("topic", ""),
                        title=dl.get("title", ""),
                        deadline_date=dl.get("deadline_date", ""),
                        description=dl.get("description", ""),
                        jurisdiction=dl.get("jurisdiction", ""),
                        source_url=dl.get("source_url", ""),
                        urgency=dl.get("urgency", "MEDIUM"),
                        week_start=week_start,
                    )
                    count += 1
                except Exception:
                    pass
            logger.info(f"Extracted {count} deadlines.")
            return count
        except Exception as e:
            logger.warning(f"Deadline extraction failed: {e}")
            return 0

    def _stage3_exec_summary(self, topic_summaries: list[dict], week_context: dict | None = None) -> str:
        today = (week_context or {}).get("today", "")
        cache_key = f"s3_{today}_{'_'.join(ts['topic'] for ts in topic_summaries)}"
        prompt = stage3_exec_summary_prompt(topic_summaries, week_context=week_context)

        try:
            return self.client.complete_sonnet(
                prompt,
                system=SYSTEM_COMPLIANCE_EXPERT,
                cache_key=cache_key,
            ).strip()
        except Exception as e:
            logger.warning(f"Stage 3 exec summary failed: {e}")
            return "Today's compliance briefing is ready. See topic sections below for details."
