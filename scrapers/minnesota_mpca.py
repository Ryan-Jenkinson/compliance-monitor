"""Minnesota MPCA scraper — PFAS news and updates."""
from __future__ import annotations
import logging
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_MPCA_BASE = "https://www.pca.state.mn.us"
_MPCA_URLS = [
    "https://www.pca.state.mn.us/news-and-stories",
    "https://www.pca.state.mn.us/pfas",
]
_PFAS_SIGNALS = ["pfas", "prism", "fluorin", "amara", "polyfluoro", "perfluoro"]


class MinnesotaMPCAScraper(BaseScraper):
    name = "minnesota_mpca"

    def __init__(self):
        super().__init__(lookback_hours=168)  # 7 days — MPCA posts infrequently

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for url in _MPCA_URLS:
            try:
                resp = requests.get(url, timeout=15,
                                    headers={"User-Agent": "ComplianceMonitor/1.0"})
                resp.raise_for_status()
                found = self._parse_page(resp.text, url, seen)
                articles.extend(found)
            except Exception as e:
                logger.warning(f"[minnesota_mpca] Error fetching {url}: {e}")

        return articles

    def _parse_page(self, html: str, source_url: str, seen: set) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)

            if not text or len(text) < 20:
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                href = _MPCA_BASE + href
            elif not href.startswith("http"):
                continue

            if "pca.state.mn.us" not in href:
                continue

            if href in seen:
                continue

            haystack = (text + " " + href).lower()
            if not any(sig in haystack for sig in _PFAS_SIGNALS):
                continue

            seen.add(href)
            articles.append(RawArticle(
                id=self.url_id(href),
                title=text,
                url=href,
                source="MN MPCA",
                topic="PFAS",
                published_at=None,
                snippet=f"Minnesota MPCA update: {text}",
            ))

        return articles
