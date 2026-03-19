"""Product Stewardship Institute scraper — producer responsibility and chemical stewardship news.

PSI covers EPR programs, product stewardship policy, and chemical management
across all US states. Relevant to both PFAS producer registration requirements
and EPR packaging programs that affect Andersen.
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

_BASE = "https://www.productstewardship.us"
_URLS = [
    "https://www.productstewardship.us/news/",
]

_PFAS_SIGNALS = [
    "pfas", "pfoa", "pfos", "polyfluoro", "perfluoro", "fluoropolymer",
    "forever chemical", "epr", "extended producer", "producer responsibility",
    "packaging", "product stewardship", "stewardship", "registration",
    "amara", "prism", "manufacturer", "supply chain",
]

_NAV_SKIP = [
    "home", "about", "contact", "login", "search", "donate",
    "member", "join", "sign up", "newsletter",
]

_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)


def _parse_date_str(text: str) -> Optional[datetime]:
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _topic_for(title: str) -> str:
    t = title.lower()
    if any(s in t for s in ["pfas", "pfoa", "pfos", "polyfluoro", "perfluoro"]):
        return "PFAS"
    if any(s in t for s in ["epr", "packaging", "extended producer", "producer responsibility"]):
        return "EPR"
    return "PFAS"


class ProductStewardshipScraper(BaseScraper):
    """Scrapes Product Stewardship Institute for EPR and PFAS policy news."""
    name = "product_stewardship"

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
                logger.warning(f"[product_stewardship] {url}: {e}")

        return articles

    def _parse(self, html: str, seen: set) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []

        for a_tag in soup.find_all("a", href=True):
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 25:
                continue
            if any(skip in title.lower() for skip in _NAV_SKIP):
                continue

            href = a_tag["href"]
            if href.startswith("/"):
                href = _BASE + href
            if not href.startswith("http") or href in seen:
                continue
            if "productstewardship.us" not in href:
                continue

            haystack = (title + " " + href).lower()
            if not any(sig in haystack for sig in _PFAS_SIGNALS):
                continue

            # Try to find date in surrounding context
            pub_date = None
            container = a_tag.parent
            for _ in range(3):
                if container is None:
                    break
                m = _DATE_PATTERN.search(container.get_text(" ", strip=True))
                if m:
                    pub_date = _parse_date_str(m.group())
                    break
                container = container.parent

            topic = _topic_for(title)
            seen.add(href)
            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source="Product Stewardship Institute",
                topic=topic,
                published_at=pub_date,
                snippet=f"PSI: {title}",
            ))

        return articles
