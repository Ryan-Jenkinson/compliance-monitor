"""ECHA scraper — SVHC Candidate List table via Playwright (bypasses 403 bot block)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

from playwright.sync_api import sync_playwright

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_CANDIDATE_LIST_URL = "https://echa.europa.eu/candidate-list-table"
_ECHA_BASE = "https://echa.europa.eu"


class ECHAScraper(BaseScraper):
    name = "echa"

    def __init__(self):
        super().__init__(lookback_hours=4320)  # 180 days — ECHA updates list a few times per year

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(_CANDIDATE_LIST_URL, timeout=30000)
                page.wait_for_selector("table tbody tr", timeout=20000)
                html = page.content()
                browser.close()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            articles = self._parse_candidate_list(soup)
        except Exception as e:
            logger.warning(f"[echa] Error fetching candidate list: {e}")

        return articles

    def _parse_candidate_list(self, soup) -> List[RawArticle]:
        articles = []

        for row in soup.select("table tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            name_cell = cells[0]
            date_cell = cells[3]

            substance = name_cell.get_text(separator=" ", strip=True)
            substance = substance.split("show/hide")[0].strip()[:200]

            date_str = date_cell.get_text(strip=True)
            try:
                added_date = datetime.strptime(date_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            if added_date < self.since:
                continue

            link_tag = name_cell.find("a", href=True)
            url = (_ECHA_BASE + link_tag["href"]) if link_tag else _CANDIDATE_LIST_URL
            url_id = self.url_id(url + substance)

            articles.append(RawArticle(
                id=url_id,
                title=f"SVHC Candidate List addition: {substance}",
                url=url,
                source="ECHA",
                topic="REACH",
                published_at=added_date,
                snippet=f"Substance added to ECHA SVHC Candidate List on {date_str}: {substance}",
            ))

        return articles
