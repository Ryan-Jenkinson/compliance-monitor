"""OEHHA Proposition 65 scraper — new listings, safe harbor updates, settlements."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_BASE = "https://oehha.ca.gov"

_FEEDS = [
    # What's new on OEHHA
    {
        "url": "https://oehha.ca.gov/rss/oehha-news.xml",
        "source": "OEHHA",
        "topic": "Prop65",
    },
    # Prop 65 news specifically
    {
        "url": "https://oehha.ca.gov/rss/proposition-65-news.xml",
        "source": "OEHHA Prop 65",
        "topic": "Prop65",
    },
]

# Fallback HTML pages if RSS is unavailable
_PAGES = [
    {
        "url": "https://oehha.ca.gov/proposition-65/new-proposition-65-listings",
        "source": "OEHHA — New Listings",
        "topic": "Prop65",
    },
    {
        "url": "https://oehha.ca.gov/proposition-65/public-comments",
        "source": "OEHHA — Public Comments",
        "topic": "Prop65",
    },
]


class OEHHAScraper(BaseScraper):
    name = "oehha"

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen_urls: set[str] = set()

        # Try RSS feeds first
        for feed in _FEEDS:
            try:
                items = self._fetch_rss(feed["url"], feed["source"], feed["topic"])
                for a in items:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        articles.append(a)
            except Exception as e:
                logger.warning(f"[oehha] RSS feed {feed['url']} failed: {e}")

        # If RSS gave nothing, fall back to HTML scraping
        if not articles:
            for page in _PAGES:
                try:
                    items = self._scrape_page(page["url"], page["source"], page["topic"])
                    for a in items:
                        if a.url not in seen_urls:
                            seen_urls.add(a.url)
                            articles.append(a)
                except Exception as e:
                    logger.warning(f"[oehha] Page {page['url']} failed: {e}")

        return articles

    def _fetch_rss(self, url: str, source: str, topic: str) -> List[RawArticle]:
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

            article_url = entry.get("link", "")
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            # Strip HTML from summary
            if "<" in summary:
                summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)

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

    def _scrape_page(self, url: str, source: str, topic: str) -> List[RawArticle]:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "ComplianceMonitor/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        # Look for article/news links in main content
        for item in soup.select("article, .views-row, .node--type-news, li.views-row"):
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
            href = a_tag["href"]
            if not href.startswith("http"):
                href = _BASE + href

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            snippet = item.get_text(" ", strip=True)[:400]

            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source=source,
                topic=topic,
                snippet=snippet,
                published_at=datetime.now(timezone.utc),
            ))

        return articles
