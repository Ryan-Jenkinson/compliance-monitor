"""EPA RSS feed scraper."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import feedparser
import yaml
from pathlib import Path

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_TOPICS_PATH = Path(__file__).parent.parent / "config" / "topics.yaml"

# EPA news RSS feeds
_EPA_FEEDS = [
    "https://www.epa.gov/newsreleases/search/rss",
    "https://www.epa.gov/rss/epa-newsroom.xml",
]


def _load_epa_keywords() -> dict[str, list[str]]:
    with open(_TOPICS_PATH) as f:
        data = yaml.safe_load(f)
    return {
        t["name"]: [kw.lower() for kw in t["keywords"]]
        for t in data["topics"]
    }


class EPAScraper(BaseScraper):
    name = "epa"

    def fetch(self) -> List[RawArticle]:
        topic_keywords = _load_epa_keywords()
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for feed_url in _EPA_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url or url in seen:
                        continue

                    pub_date = self._parse_date(entry)
                    if pub_date and pub_date < self.since:
                        continue

                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    haystack = (title + " " + summary).lower()

                    matched_topic = self._match_topic(haystack, topic_keywords)
                    if not matched_topic:
                        continue

                    seen.add(url)
                    articles.append(RawArticle(
                        id=self.url_id(url),
                        title=title,
                        url=url,
                        source="EPA",
                        topic=matched_topic,
                        published_at=pub_date,
                        snippet=summary[:500],
                    ))
            except Exception as e:
                logger.warning(f"[epa] Error parsing feed {feed_url}: {e}")

        return articles

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        for field in ("published", "updated"):
            val = entry.get(field)
            if val:
                try:
                    return parsedate_to_datetime(val).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
        return None

    @staticmethod
    def _match_topic(haystack: str, topic_keywords: dict[str, list[str]]) -> str | None:
        for topic, keywords in topic_keywords.items():
            if any(kw in haystack for kw in keywords):
                return topic
        return None
