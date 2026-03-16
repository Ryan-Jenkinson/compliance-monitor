"""Configurable multi-state RSS/HTML scraper for EPR and PFAS state programs."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import feedparser
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

# Add more states here without code changes — just extend this list
_STATE_FEEDS: list[dict] = [
    {
        "state": "California",
        "source": "CalRecycle",
        "topic": "EPR",
        "feed_url": "https://calrecycle.ca.gov/rss/news.xml",
        "keywords": ["EPR", "SB 54", "producer responsibility", "packaging"],
    },
    {
        "state": "Oregon",
        "source": "Oregon DEQ",
        "topic": "EPR",
        "feed_url": "https://www.oregon.gov/deq/newsroom/rss.xml",
        "keywords": ["EPR", "producer responsibility", "packaging", "PFAS"],
    },
    {
        "state": "Maine",
        "source": "Maine DEP",
        "topic": "EPR",
        "feed_url": "https://www.maine.gov/dep/news/rss.xml",
        "keywords": ["EPR", "producer responsibility", "packaging"],
    },
]


class StateAgenciesScraper(BaseScraper):
    name = "state_agencies"

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []

        for config in _STATE_FEEDS:
            try:
                results = self._fetch_feed(config)
                articles.extend(results)
            except Exception as e:
                logger.warning(f"[state_agencies] Error for {config['state']}: {e}")

        return articles

    def _fetch_feed(self, config: dict) -> List[RawArticle]:
        feed = feedparser.parse(config["feed_url"])
        articles = []
        keywords = [kw.lower() for kw in config["keywords"]]

        for entry in feed.entries:
            url = entry.get("link", "")
            if not url:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")
            haystack = (title + " " + summary).lower()

            if not any(kw in haystack for kw in keywords):
                continue

            pub_date = self._parse_date(entry)
            if pub_date and pub_date < self.since:
                continue

            articles.append(RawArticle(
                id=self.url_id(url),
                title=title,
                url=url,
                source=config["source"],
                topic=config["topic"],
                published_at=pub_date,
                snippet=summary[:500],
                extra={"state": config["state"]},
            ))

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
