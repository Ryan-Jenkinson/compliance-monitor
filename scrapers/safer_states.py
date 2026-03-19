"""Safer States scraper — chemical policy news from saferstates.org."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.saferstates.org"
_NEWS_URL = "https://www.saferstates.org/news/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# Topic keyword mapping — checked in order; first match wins
_TOPIC_KEYWORDS: list[tuple[str, list[str]]] = [
    ("PFAS", ["pfas", "pfoa", "pfos", "perfluoro", "polyfluoro", "fluoropolymer", "forever chemical"]),
    ("REACH", ["reach", "svhc", "substance of very high concern", "eu chemical"]),
    ("TSCA", ["tsca", "toxic substances", "section 6", "risk evaluation", "new chemical"]),
    ("EPR", ["epr", "extended producer responsibility", "product stewardship", "packaging", "recycl"]),
]
_DEFAULT_TOPIC = "PFAS"  # Safer States is primarily a chemical safety / PFAS advocacy org


def _match_topic(haystack: str) -> str:
    """Return the best-matching topic label for the given text."""
    text = haystack.lower()
    for topic, keywords in _TOPIC_KEYWORDS:
        if any(kw in text for kw in keywords):
            return topic
    return _DEFAULT_TOPIC


class SaferStatesScraper(BaseScraper):
    name = "safer_states"

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        try:
            resp = requests.get(_NEWS_URL, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            articles = self._parse_page(resp.text)
        except Exception as e:
            logger.warning(f"[safer_states] Error fetching {_NEWS_URL}: {e}")
        return articles

    def _parse_page(self, html: str) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []
        seen: set[str] = set()

        candidates = []

        # Pattern 1: article elements
        for article_el in soup.find_all("article"):
            a_tag = article_el.find("a", href=True)
            title_el = article_el.find(["h1", "h2", "h3", "h4"])
            date_el = article_el.find(["time", "span"], class_=lambda c: c and any(
                word in (c if isinstance(c, str) else " ".join(c))
                for word in ("date", "time", "posted", "published", "entry")
            ))
            if a_tag and title_el:
                candidates.append({
                    "href": a_tag["href"],
                    "title": title_el.get_text(strip=True),
                    "date_el": date_el,
                    "snippet_el": article_el,
                })

        # Pattern 2: fallback — scan all substantial links
        if not candidates:
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text(strip=True)
                if len(text) < 20:
                    continue
                href = a_tag["href"]
                if "saferstates.org" in href or href.startswith("/"):
                    candidates.append({
                        "href": href,
                        "title": text,
                        "date_el": None,
                        "snippet_el": None,
                    })

        for item in candidates:
            href = item["href"]
            title = item["title"]

            # Resolve relative URLs
            if href.startswith("/"):
                href = _BASE_URL + href
            elif not href.startswith("http"):
                continue

            if href in seen:
                continue
            if "saferstates.org" not in href:
                continue

            seen.add(href)

            # Build snippet from surrounding text if available
            snippet_text = title
            if item.get("snippet_el"):
                p_tag = item["snippet_el"].find("p")
                if p_tag:
                    snippet_text = p_tag.get_text(strip=True)[:300] or title

            # Parse date if available
            pub_date: datetime | None = None
            date_el = item.get("date_el")
            if date_el:
                date_str = date_el.get("datetime") or date_el.get_text(strip=True)
                if date_str:
                    pub_date = self._try_parse_date(date_str)

            # Apply lookback filter only when we have a real date
            if pub_date and pub_date < self.since:
                continue

            topic = _match_topic(title + " " + snippet_text)

            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source="Safer States",
                topic=topic,
                published_at=pub_date,
                snippet=f"Safer States: {snippet_text}",
            ))

        return articles

    @staticmethod
    def _try_parse_date(date_str: str) -> datetime | None:
        """Attempt to parse a date string into a UTC-aware datetime."""
        formats = [
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%m/%d/%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
