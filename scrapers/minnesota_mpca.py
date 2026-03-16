"""Minnesota MPCA HTML scraper — PFAS / PRISM program."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_MPCA_PFAS_URL = "https://www.pca.state.mn.us/air-water-land-climate/pfas"
_MPCA_NEWS_URL = "https://www.pca.state.mn.us/news-and-stories"


class MinnesotaMPCAScraper(BaseScraper):
    name = "minnesota_mpca"

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []

        for url, label in [(_MPCA_PFAS_URL, "PFAS"), (_MPCA_NEWS_URL, "PFAS")]:
            try:
                resp = requests.get(url, timeout=15,
                                    headers={"User-Agent": "ComplianceMonitor/1.0"})
                resp.raise_for_status()
                articles.extend(self._parse_page(resp.text, url, label))
            except Exception as e:
                logger.warning(f"[minnesota_mpca] Error fetching {url}: {e}")

        return articles

    def _parse_page(self, html: str, base_url: str, topic: str) -> List[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles = []

        # Look for news/update links on the page
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)

            if not text or len(text) < 20:
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                href = "https://www.pca.state.mn.us" + href
            elif not href.startswith("http"):
                continue

            # Only keep MPCA pages that look like news/updates
            if "pca.state.mn.us" not in href:
                continue

            pfas_signals = ["pfas", "prism", "fluorin", "amara"]
            if not any(sig in (text + href).lower() for sig in pfas_signals):
                continue

            articles.append(RawArticle(
                id=self.url_id(href),
                title=text,
                url=href,
                source="MN MPCA",
                topic=topic,
                published_at=datetime.now(tz=timezone.utc),  # No pub date from links
                snippet=f"Minnesota MPCA update: {text}",
            ))

        return articles
