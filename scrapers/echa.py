"""ECHA RSS feed scraper (REACH / SVHC updates)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import feedparser

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_ECHA_FEEDS = [
    "https://echa.europa.eu/rss/news_en.xml",
    "https://echa.europa.eu/rss/svhc_en.xml",
]


class ECHAScraper(BaseScraper):
    name = "echa"

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for feed_url in _ECHA_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url or url in seen:
                        continue

                    pub_date = self._parse_date(entry)
                    if pub_date and pub_date < self.since:
                        continue

                    seen.add(url)
                    articles.append(RawArticle(
                        id=self.url_id(url),
                        title=entry.get("title", "Untitled"),
                        url=url,
                        source="ECHA",
                        topic="REACH",
                        published_at=pub_date,
                        snippet=entry.get("summary", "")[:500],
                    ))
            except Exception as e:
                logger.warning(f"[echa] Error parsing feed {feed_url}: {e}")

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
