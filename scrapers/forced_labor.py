"""Forced Labor & Supply Chain Transparency scrapers.

All RSS feeds (DHS, CBP, State Dept) return 0 entries. This scraper uses
direct HTML scraping of working government pages.

Sources:
- DHS UFLPA page (uflpa entity list, enforcement updates)
- CBP Trade Forced Labor page
- CBP newsroom (press releases filtered for forced labor)
- DHS newsroom (filtered for UFLPA/forced labor)
- Federal Register (via existing scraper — topics.yaml terms)
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

_HEADERS = {"User-Agent": "ComplianceMonitor/1.0"}

# All verified HTTP 200 pages
_PAGES = [
    {
        "url": "https://www.dhs.gov/uflpa",
        "source": "DHS — UFLPA",
        "topic": "ForcedLabor",
        "filter_keywords": [],  # All content on this page is relevant
    },
    {
        "url": "https://www.cbp.gov/trade/forced-labor",
        "source": "CBP — Forced Labor",
        "topic": "ForcedLabor",
        "filter_keywords": [],
    },
    {
        "url": "https://www.cbp.gov/newsroom/national-media-release",
        "source": "CBP Newsroom",
        "topic": "ForcedLabor",
        "filter_keywords": ["forced labor", "uflpa", "xinjiang", "withhold release",
                            "detention order", "supply chain", "uyghur", "wro",
                            "trade enforcement", "entity list"],
    },
    {
        "url": "https://www.dhs.gov/news",
        "source": "DHS News",
        "topic": "ForcedLabor",
        "filter_keywords": ["uflpa", "forced labor", "xinjiang", "supply chain",
                            "withhold release", "detention", "uyghur", "entity list"],
    },
    {
        "url": "https://www.dhs.gov/uflpa-entity-list",
        "source": "DHS — UFLPA Entity List",
        "topic": "ForcedLabor",
        "filter_keywords": [],
    },
]

_FORCED_LABOR_KEYWORDS = [
    "forced labor", "uflpa", "xinjiang", "uyghur", "withhold release order",
    "wro", "supply chain transparency", "entity list", "detention order",
    "slave labor", "child labor", "human trafficking", "csddd",
    "supply chain due diligence", "cbp", "trade enforcement",
]


class ForcedLaborScraper(BaseScraper):
    name = "forced_labor"

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen_urls: set[str] = set()

        for page in _PAGES:
            try:
                items = self._scrape_page(
                    page["url"], page["source"], page["topic"],
                    page.get("filter_keywords", [])
                )
                for a in items:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        articles.append(a)
            except Exception as e:
                logger.warning(f"[forced_labor] Page {page['url']} failed: {e}")

        return articles

    def _scrape_page(self, url: str, source: str, topic: str,
                     filter_keywords: list[str]) -> List[RawArticle]:
        try:
            resp = requests.get(url, timeout=25, headers=_HEADERS)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[forced_labor] Failed to fetch {url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        # Remove navigation, header, footer noise
        for nav in soup.select("nav, header, footer, .nav, .header, .footer, .menu, .breadcrumb"):
            nav.decompose()

        # Try structured selectors first
        selectors = [
            "article", ".views-row", ".node--type-news", "li.views-row",
            ".news-item", ".press-release", ".media-release",
            ".field--name-title", ".views-field-title",
            "h2.node__title", "h3.node__title",
        ]

        found_items = []
        for sel in selectors:
            found_items = soup.select(sel)
            if len(found_items) >= 3:
                break

        if len(found_items) < 3:
            # Fallback: links in main content area
            main = soup.select_one("main, #main-content, .region-content, .content-wrapper, #content")
            if not main:
                main = soup

            found_links = main.find_all("a", href=True)
            for link in found_links[:50]:
                href = link.get("href", "")
                title = link.get_text(strip=True)
                if not title or len(title) < 15:
                    continue
                if not href.startswith("http"):
                    href = urljoin(url, href)
                # Skip external non-government links and fragment anchors
                if href == url or href.startswith(url + "#"):
                    continue
                if "javascript:" in href or "mailto:" in href:
                    continue

                # Apply keyword filter
                if filter_keywords:
                    if not any(kw.lower() in title.lower() for kw in filter_keywords):
                        continue

                articles.append(RawArticle(
                    id=self.url_id(href),
                    title=title,
                    url=href,
                    source=source,
                    topic=topic,
                    snippet=f"{source}: {title}",
                    published_at=datetime.now(timezone.utc),
                ))
            return articles[:20]

        for item in found_items[:30]:
            a_tag = item.find("a", href=True) if hasattr(item, 'find') else None
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin(url, href)
            if "javascript:" in href or "mailto:" in href:
                continue

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            snippet = item.get_text(" ", strip=True)[:400]

            # Apply keyword filter on title + snippet
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
        seen = set()
        unique = []
        for a in articles:
            if a.url not in seen:
                seen.add(a.url)
                unique.append(a)
        return unique[:20]
