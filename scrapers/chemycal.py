"""Chemycal scraper — chemical regulatory news and substance updates.

Chemycal aggregates regulatory alerts across jurisdictions, covering PFAS,
REACH, TSCA, and other chemical regulations. Useful for catching new
substance listings, restrictions, and compliance deadlines.
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

_BASE = "https://chemycal.com"
_URLS = [
    "https://chemycal.com/news/",
    "https://chemycal.com/news/?substance=PFAS",
]

_PFAS_SIGNALS = [
    "pfas", "pfoa", "pfos", "polyfluoro", "perfluoro", "fluoropolymer",
    "forever chemical", "reach", "svhc", "tsca", "restriction", "substance",
    "chemical", "regulation", "compliance", "ban", "registration",
]

_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)

# Also try ISO date in meta tags / time elements
_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _parse_date_str(text: str) -> Optional[datetime]:
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%b. %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _topic_for(title: str) -> str:
    t = title.lower()
    if any(s in t for s in ["pfas", "pfoa", "pfos", "polyfluoro", "perfluoro", "fluoropolymer"]):
        return "PFAS"
    if "reach" in t or "svhc" in t or "echa" in t:
        return "REACH"
    if "tsca" in t or "epa" in t or "toxic substances" in t:
        return "TSCA"
    return "PFAS"  # default — most Chemycal PFAS news is PFAS-relevant


class ChemycalScraper(BaseScraper):
    """Scrapes Chemycal for chemical regulatory news relevant to PFAS and supply chain."""
    name = "chemycal"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for url in _URLS:
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=15)
                resp.raise_for_status()
                articles.extend(self._parse(resp.text, seen))
            except Exception as e:
                logger.warning(f"[chemycal] {url}: {e}")

        return articles

    def _parse(self, html: str, seen: set) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []

        for item in soup.find_all(["article", "div", "li"], class_=re.compile(r"news|post|item|entry|card", re.I)):
            link = item.find("a", href=True)
            if not link:
                continue

            title_el = item.find(["h2", "h3", "h4"])
            title = (title_el or link).get_text(strip=True)
            if not title or len(title) < 20:
                continue

            href = link["href"]
            if href.startswith("/"):
                href = _BASE + href
            if not href.startswith("http") or href in seen:
                continue
            if "chemycal.com" not in href:
                continue

            haystack = (title + " " + href).lower()
            if not any(sig in haystack for sig in _PFAS_SIGNALS):
                continue

            # Try to extract date from time element or text
            pub_date = None
            time_el = item.find("time")
            if time_el:
                dt_attr = time_el.get("datetime", "")
                m = _ISO_DATE.search(dt_attr)
                if m:
                    pub_date = _parse_date_str(m.group(1))
            if not pub_date:
                m = _DATE_PATTERN.search(item.get_text(" ", strip=True))
                if m:
                    pub_date = _parse_date_str(m.group())

            topic = _topic_for(title)

            seen.add(href)
            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source="Chemycal",
                topic=topic,
                published_at=pub_date,
                snippet=f"Chemycal regulatory alert: {title}",
            ))

        return articles
