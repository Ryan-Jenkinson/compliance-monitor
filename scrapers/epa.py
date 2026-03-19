"""EPA topic page scraper — PFAS and TSCA updates."""
from __future__ import annotations
import logging
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# EPA topic pages that list news/updates
_EPA_TOPIC_PAGES = [
    {
        "url": "https://www.epa.gov/pfas/news-and-updates-pfas",
        "topic": "PFAS",
        "fallback_url": "https://www.epa.gov/pfas",
    },
    {
        "url": "https://www.epa.gov/assessing-and-managing-chemicals-under-tsca/news-and-events-tsca",
        "topic": "TSCA",
        "fallback_url": "https://www.epa.gov/tsca",
    },
]

_PFAS_KEYWORDS = ["pfas", "pfoa", "pfos", "perfluoro", "polyfluoro", "fluoropolymer"]
_TSCA_KEYWORDS = ["tsca", "toxic substances", "section 6", "section 8", "risk evaluation", "new chemical", "chemical data reporting"]


class EPAScraper(BaseScraper):
    name = "epa"

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for page_config in _EPA_TOPIC_PAGES:
            for url in [page_config["url"], page_config["fallback_url"]]:
                try:
                    resp = requests.get(url, headers=_HEADERS, timeout=15)
                    resp.raise_for_status()
                    found = self._parse_page(resp.text, url, page_config["topic"], seen)
                    articles.extend(found)
                    if found:
                        break  # got results from primary URL, skip fallback
                except Exception as e:
                    logger.warning(f"[epa] Error fetching {url}: {e}")

        return articles

    def _parse_page(self, html: str, base_url: str, topic: str, seen: set) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []
        keywords = _PFAS_KEYWORDS if topic == "PFAS" else _TSCA_KEYWORDS

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)

            if not text or len(text) < 20:
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                href = "https://www.epa.gov" + href
            elif not href.startswith("http"):
                continue

            if "epa.gov" not in href:
                continue

            if href in seen:
                continue

            haystack = (text + " " + href).lower()
            if not any(kw in haystack for kw in keywords):
                continue

            seen.add(href)
            articles.append(RawArticle(
                id=self.url_id(href),
                title=text,
                url=href,
                source="EPA",
                topic=topic,
                published_at=None,
                snippet=f"EPA {topic} update: {text}",
            ))

        return articles
