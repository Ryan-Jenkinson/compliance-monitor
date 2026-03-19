"""Environmental Health News scraper — PFAS coverage."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_EHN_PFAS_URL = "https://www.ehn.org/tag/pfas"
_EHN_BASE = "https://www.ehn.org"


class PFASCentralScraper(BaseScraper):
    """Scrapes Environmental Health News PFAS coverage (replaces blocked pfascentral.org)."""
    name = "pfas_central"

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        try:
            resp = requests.get(_EHN_PFAS_URL, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            articles = self._parse_page(resp.text)
        except Exception as e:
            logger.warning(f"[pfas_central] Error fetching EHN PFAS page: {e}")
        return articles

    def _parse_page(self, html: str) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []
        seen: set[str] = set()

        for article_el in soup.find_all("article"):
            link_tag = article_el.find("a", href=True)
            title_el = article_el.find(["h2", "h3", "h4"])
            if not link_tag or not title_el:
                continue

            href = link_tag["href"]
            if href.startswith("/"):
                href = _EHN_BASE + href
            if not href.startswith("http") or href in seen:
                continue

            title = title_el.get_text(strip=True)
            if len(title) < 15:
                continue

            seen.add(href)
            articles.append(RawArticle(
                id=self.url_id(href),
                title=title,
                url=href,
                source="Environmental Health News",
                topic="PFAS",
                published_at=None,
                snippet=f"EHN PFAS coverage: {title}",
            ))

        return articles
