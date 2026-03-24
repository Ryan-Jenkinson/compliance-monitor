"""OEHHA / Proposition 65 scraper.

OEHHA's own website uses JS rendering (returns ~843 bytes). We scrape
the California AG Prop 65 portal instead, which returns full HTML:
  - oag.ca.gov/prop65/60-day-notice-search-results  (recent 60-day notices)
  - oag.ca.gov/prop65                                (general news/updates)

Additionally monitor Federal Register for Prop 65-related notices.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 ComplianceMonitor/1.0"}
_CA_AG_BASE = "https://oag.ca.gov"

_PAGES = [
    {
        "url": "https://oag.ca.gov/prop65/60-day-notice-search-results",
        "source": "CA AG — Prop 65 60-Day Notices",
        "topic": "Prop65",
        "selector": ".views-row",
        "filter_keywords": [],  # All items here are 60-day notices
    },
    {
        "url": "https://oag.ca.gov/prop65",
        "source": "CA AG — Prop 65",
        "topic": "Prop65",
        "selector": "article, .views-row, h2 a, h3 a",
        "filter_keywords": ["proposition 65", "prop 65", "chemical", "listing",
                            "settlement", "notice", "warning", "oehha"],
    },
]

_PROP65_KEYWORDS = [
    "proposition 65", "prop 65", "oehha", "safe harbor", "60-day notice",
    "chemical listing", "settlement", "warning label", "nsrl", "madl",
    "carcinogen", "reproductive toxicant", "california chemical",
]


class OEHHAScraper(BaseScraper):
    name = "oehha"

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen_urls: set[str] = set()

        for page in _PAGES:
            try:
                items = self._scrape_page(
                    page["url"], page["source"], page["topic"],
                    page["selector"], page.get("filter_keywords", [])
                )
                for a in items:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        articles.append(a)
            except Exception as e:
                logger.warning(f"[oehha] Page {page['url']} failed: {e}")

        return articles

    def _scrape_page(self, url: str, source: str, topic: str,
                     selector: str, filter_keywords: list[str]) -> List[RawArticle]:
        resp = requests.get(url, timeout=20, headers=_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        items = soup.select(selector)

        if not items:
            # Fallback: all links in main content
            main = soup.select_one("main, #main-content, .region-content, .content")
            if main:
                items = main.find_all("a", href=True)

        for item in items[:30]:
            # Handle both container elements and direct <a> tags
            if item.name == "a":
                a_tag = item
            else:
                a_tag = item.find("a", href=True)

            if not a_tag:
                continue

            href = a_tag.get("href", "")
            if not href or "javascript:" in href or "mailto:" in href:
                continue
            if not href.startswith("http"):
                href = urljoin(url, href)

            title = a_tag.get_text(strip=True)
            # For 60-day notices, build a richer title from the row
            if "60-day" in source.lower() or "notice" in source.lower():
                row_text = item.get_text(" ", strip=True) if hasattr(item, 'get_text') else title
                # Extract filing details: "AG Number YYYY-XXXXX ... Date Filed: MM/DD"
                if row_text and len(row_text) > len(title):
                    title = row_text[:120].strip()

            if not title or len(title) < 8:
                continue

            snippet = item.get_text(" ", strip=True)[:400] if hasattr(item, 'get_text') else title

            if filter_keywords:
                text = (title + " " + snippet).lower()
                if not any(kw.lower() in text for kw in filter_keywords):
                    continue

            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source=source,
                topic=topic,
                snippet=snippet,
                published_at=datetime.now(timezone.utc),
            ))

        # Deduplicate
        seen: set[str] = set()
        unique = []
        for a in articles:
            if a.url not in seen:
                seen.add(a.url)
                unique.append(a)
        return unique[:20]
