"""Conflict Minerals (SEC/Dodd-Frank 1502) scrapers.

Sources:
- SEC press releases and investor alerts
- OECD Due Diligence Guidance updates
- State Dept annual conflict minerals report
- Federal Register (handled via topics.yaml federal_register_terms)
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
    # SEC press releases
    {
        "url": "https://www.sec.gov/rss/news/press-releases.xml",
        "source": "SEC",
        "topic": "ConflictMinerals",
        "filter_keywords": ["conflict minerals", "dodd-frank", "section 1502", "form sd",
                            "supply chain", "responsible minerals", "3tg", "tantalum",
                            "csddd", "due diligence"],
    },
    # OECD newsroom (no dedicated RSS — use main)
    {
        "url": "https://www.oecd.org/newsroom/rss.xml",
        "source": "OECD",
        "topic": "ConflictMinerals",
        "filter_keywords": ["conflict minerals", "due diligence", "responsible supply chain",
                            "responsible business", "3tg", "mining"],
    },
    # Responsible Minerals Initiative news
    {
        "url": "https://www.responsibleminerals.org/rss/",
        "source": "Responsible Minerals Initiative",
        "topic": "ConflictMinerals",
        "filter_keywords": [],  # All items are relevant
    },
]

_PAGES = [
    {
        "url": "https://www.sec.gov/litigation/enforcement/conflict-minerals.shtml",
        "source": "SEC — Conflict Minerals Enforcement",
        "topic": "ConflictMinerals",
    },
]


class ConflictMineralsScraper(BaseScraper):
    name = "conflict_minerals"

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
                logger.warning(f"[conflict_minerals] Feed {feed['url']} failed: {e}")

        # SEC enforcement page
        for page in _PAGES:
            try:
                items = self._scrape_sec_page(page["url"], page["source"])
                for a in items:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        articles.append(a)
            except Exception as e:
                logger.warning(f"[conflict_minerals] Page {page['url']} failed: {e}")

        return articles

    def _fetch_rss_filtered(self, url: str, source: str, topic: str,
                             filter_keywords: list[str]) -> List[RawArticle]:
        import feedparser
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.warning(f"[conflict_minerals] feedparser error {url}: {e}")
            return []

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

            # Filter if keywords defined
            if filter_keywords:
                text = (title + " " + summary).lower()
                if not any(kw.lower() in text for kw in filter_keywords):
                    continue

            article_url = entry.get("link", "")
            if not article_url:
                continue

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

    def _scrape_sec_page(self, url: str, source: str) -> List[RawArticle]:
        """Scrape SEC conflict minerals enforcement page for actions."""
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "ComplianceMonitor/1.0"})
            resp.raise_for_status()
        except Exception:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        for link in soup.find_all("a", href=True):
            href = link["href"]
            title = link.get_text(strip=True)
            if not title or len(title) < 15:
                continue
            if not href.startswith("http"):
                href = "https://www.sec.gov" + href

            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source=source,
                topic="ConflictMinerals",
                snippet=f"SEC enforcement action: {title}",
                published_at=datetime.now(timezone.utc),
            ))

        return articles[:20]  # Cap to avoid noise
