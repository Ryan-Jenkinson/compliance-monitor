"""Assent blog scraper — supply chain PFAS and chemical compliance content.

Assent is Andersen's supply chain compliance platform. Their blog covers
PFAS declarations, manufacturer registration requirements, and supply chain
chemical compliance — directly relevant to Andersen's supplier campaign.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_PFAS_SIGNALS = [
    "pfas", "pfoa", "pfos", "polyfluoro", "perfluoro", "fluoropolymer",
    "forever chemical", "amara", "prism", "chemical compliance",
    "supplier declaration", "supply chain compliance", "restricted substance",
    "reach", "svhc", "rohs", "conflict mineral", "esg",
]

_URLS = [
    ("https://www.assent.com/blog/", "https://www.assent.com"),
    ("https://www.assent.com/resources/", "https://www.assent.com"),
]

_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)


def _parse_date_str(text: str) -> Optional[datetime]:
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%b. %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


class AssentScraper(BaseScraper):
    """Scrapes Assent blog and resources for supply chain compliance news."""
    name = "assent"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for url, base in _URLS:
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=15)
                resp.raise_for_status()
                articles.extend(self._parse(resp.text, base, seen))
            except Exception as e:
                logger.warning(f"[assent] {url}: {e}")

        return articles

    def _parse(self, html: str, base: str, seen: set) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []

        # Assent blog uses article cards — look for article elements and generic link blocks
        for block in soup.find_all(["article", "div"], class_=re.compile(r"card|post|blog|resource|item", re.I)):
            link = block.find("a", href=True)
            if not link:
                continue

            title_el = block.find(["h2", "h3", "h4", "h5"])
            title = (title_el or link).get_text(strip=True)
            if not title or len(title) < 20:
                continue

            href = link["href"]
            if href.startswith("/"):
                href = base + href
            if not href.startswith("http") or href in seen:
                continue
            if "assent.com" not in href:
                continue

            haystack = (title + " " + href).lower()
            if not any(sig in haystack for sig in _PFAS_SIGNALS):
                continue

            # Try to extract date
            pub_date = None
            date_el = block.find(class_=re.compile(r"date|time|meta", re.I))
            date_text = (date_el or block).get_text(" ", strip=True)
            m = _DATE_PATTERN.search(date_text)
            if m:
                pub_date = _parse_date_str(m.group())

            seen.add(href)
            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source="Assent",
                topic="PFAS",
                published_at=pub_date,
                snippet=f"Assent supply chain compliance: {title}",
            ))

        return articles
