"""Forced Labor & Supply Chain Transparency scrapers.

Sources:
- DHS UFLPA Entity List updates
- CBP trade enforcement statistics/press releases
- Federal Register (via existing scraper — adds terms to topics.yaml)
- State supply chain transparency news
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)


_FEEDS = [
    # DHS newsroom RSS
    {
        "url": "https://www.dhs.gov/news/rss.xml",
        "source": "DHS",
        "topic": "ForcedLabor",
        "filter_keywords": ["uflpa", "forced labor", "xinjiang", "supply chain", "withhold release", "detention"],
    },
    # CBP newsroom RSS
    {
        "url": "https://www.cbp.gov/newsroom/rss.xml",
        "source": "CBP",
        "topic": "ForcedLabor",
        "filter_keywords": ["forced labor", "uflpa", "withhold release", "xinjiang", "detention order", "trade enforcement"],
    },
    # State Dept - TIP and supply chain reporting
    {
        "url": "https://www.state.gov/rss-feed/trafficking-in-persons/",
        "source": "State Dept",
        "topic": "ForcedLabor",
        "filter_keywords": ["forced labor", "supply chain", "trafficking", "uyghur", "xinjiang", "manufacturing"],
    },
]

_PAGES = [
    {
        "url": "https://www.dhs.gov/uflpa-entity-list",
        "source": "DHS — UFLPA Entity List",
        "topic": "ForcedLabor",
    },
]


class ForcedLaborScraper(BaseScraper):
    name = "forced_labor"

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen_urls: set[str] = set()

        for feed in _FEEDS:
            try:
                items = self._fetch_rss_filtered(
                    feed["url"], feed["source"], feed["topic"],
                    feed.get("filter_keywords", [])
                )
                for a in items:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        articles.append(a)
            except Exception as e:
                logger.warning(f"[forced_labor] Feed {feed['url']} failed: {e}")

        # Scrape entity list page for recent additions
        for page in _PAGES:
            try:
                items = self._scrape_entity_list(page["url"], page["source"])
                for a in items:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        articles.append(a)
            except Exception as e:
                logger.warning(f"[forced_labor] Page {page['url']} failed: {e}")

        return articles

    def _fetch_rss_filtered(self, url: str, source: str, topic: str,
                             filter_keywords: list[str]) -> List[RawArticle]:
        import feedparser
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                dt = datetime(*pub[:6], tzinfo=timezone.utc)
                if dt < self.since:
                    continue
            else:
                dt = datetime.now(timezone.utc)

            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            if "<" in summary:
                summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)

            # Filter to relevant items only
            text = (title + " " + summary).lower()
            if filter_keywords and not any(kw.lower() in text for kw in filter_keywords):
                continue

            article_url = entry.get("link", "")
            articles.append(RawArticle(
                id=self.url_id(article_url),
                title=title,
                url=article_url,
                source=source,
                topic=topic,
                snippet=summary[:500],
                published_at=dt,
            ))
        return articles

    def _scrape_entity_list(self, url: str, source: str) -> List[RawArticle]:
        """Scrape the UFLPA entity list page for recent additions/updates."""
        resp = requests.get(url, timeout=20, headers={"User-Agent": "ComplianceMonitor/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        # Look for "last updated" info or any dated content blocks
        page_text = soup.get_text(" ", strip=True)[:1000]

        # Return a single article representing the entity list page itself
        # (we track it as a snapshot — Claude will detect changes in snippet content)
        articles.append(RawArticle(
            id=self.url_id(url + "_entity_list"),
            title="UFLPA Entity List — Current Status",
            url=url,
            source=source,
            topic="ForcedLabor",
            snippet=page_text[:500],
            published_at=datetime.now(timezone.utc),
        ))

        return articles
