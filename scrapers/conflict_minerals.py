"""Conflict Minerals (SEC/Dodd-Frank 1502) scrapers.

Sources:
- SEC EDGAR full-text search API (Form SD filers — conflict minerals reports)
- SEC investor alerts and press releases (HTML scraping)
- OECD Due Diligence page (HTML scraping — RSS is malformed)
- Responsible Minerals Initiative news (HTML scraping — RSS is malformed)
- Federal Register (handled via topics.yaml federal_register_terms)
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

_HEADERS = {"User-Agent": "ComplianceMonitor/1.0 (compliance research)"}

# SEC EDGAR full-text search — Form SD = conflict minerals annual reports
_EDGAR_API = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%22conflict+minerals%22&forms=SD&dateRange=custom"
    "&startdt={start}&enddt={end}&hits.hits.total.value=true"
)
# SEC investor alerts — filtered for conflict minerals
_SEC_INVESTOR_ALERTS_URL = "https://www.sec.gov/investor/pubs/sec-guide-to-conflict-minerals-rule.htm"
_SEC_CORP_FIN_URL = "https://www.sec.gov/corpfin/cf-noaction/conflictminerals.shtml"

# Working HTML pages (RSS feeds are all broken)
_PAGES = [
    {
        # RMI news page — HTML works even though RSS is malformed
        "url": "https://www.responsibleminerals.org/news",
        "source": "Responsible Minerals Initiative",
        "topic": "ConflictMinerals",
        "filter_keywords": [],
    },
    {
        # SEC EDGAR EFTS search page (HTML) for recent Form SD activity
        "url": "https://efts.sec.gov/LATEST/search-index?q=%22conflict+minerals%22&forms=SD&dateRange=custom&startdt=2024-01-01",
        "source": "SEC EDGAR — Form SD Search",
        "topic": "ConflictMinerals",
        "filter_keywords": [],
        "skip_html_scrape": True,  # handled by _fetch_edgar_form_sd()
    },
]

_CONFLICT_KEYWORDS = [
    "conflict minerals", "dodd-frank 1502", "form sd", "3tg", "tantalum", "tungsten",
    "tin", "gold", "drc", "democratic republic of congo", "responsible minerals",
    "smelter", "refiner", "cmrt", "rmap", "csddd", "due diligence", "supply chain transparency",
]


class ConflictMineralsScraper(BaseScraper):
    name = "conflict_minerals"

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen_urls: set[str] = set()

        # 1. SEC EDGAR Form SD filings (most authoritative source)
        try:
            items = self._fetch_edgar_form_sd()
            for a in items:
                if a.url not in seen_urls:
                    seen_urls.add(a.url)
                    articles.append(a)
        except Exception as e:
            logger.warning(f"[conflict_minerals] EDGAR API failed: {e}")

        # 2. HTML pages
        for page in _PAGES:
            if page.get("skip_html_scrape"):
                continue
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
                logger.warning(f"[conflict_minerals] Page {page['url']} failed: {e}")

        return articles

    def _fetch_edgar_form_sd(self) -> List[RawArticle]:
        """Use SEC EDGAR full-text search to find recent Form SD filers."""
        from datetime import timedelta
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=90)

        url = (
            f"https://efts.sec.gov/LATEST/search-index"
            f"?q=%22conflict+minerals%22&forms=SD"
            f"&dateRange=custom&startdt={start}&enddt={end}"
        )
        resp = requests.get(url, timeout=20, headers=_HEADERS)
        resp.raise_for_status()

        data = resp.json()
        # Response: {"hits": {"hits": [...], "total": {...}}, ...}
        hits_wrapper = data.get("hits", {})
        hits = hits_wrapper.get("hits", []) if isinstance(hits_wrapper, dict) else []
        articles = []

        for hit in hits[:20]:
            if not isinstance(hit, dict):
                continue
            src = hit.get("_source", {})
            if not isinstance(src, dict):
                continue

            file_date = src.get("file_date", "")
            display_names = src.get("display_names", [])
            company_name = "Unknown"
            if display_names and isinstance(display_names, list):
                first = display_names[0]
                company_name = first.get("name", "Unknown") if isinstance(first, dict) else str(first)

            # Accession number is in 'adsh' field (format: XXXXXXXXXX-YY-NNNNNN)
            adsh = src.get("adsh", "")
            ciks = src.get("ciks", [])
            cik = ciks[0] if ciks else ""

            # Build EDGAR filing index URL
            if adsh and cik:
                adsh_nodash = adsh.replace("-", "")
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_nodash}/{adsh}-index.htm"
            elif adsh:
                doc_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=SD&dateb=&owner=include&count=40&search_text={adsh}"
            else:
                doc_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=SD&dateb=&owner=include&count=40"

            try:
                if file_date:
                    parsed = datetime.fromisoformat(file_date.replace("Z", "+00:00"))
                    pub_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                else:
                    pub_dt = datetime.now(timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            if pub_dt < self.since:
                continue

            month_label = file_date[:7] if len(file_date) >= 7 else "recent"
            title = f"{company_name} — Form SD Conflict Minerals Report ({month_label})"
            snippet = (
                f"SEC Form SD annual conflict minerals disclosure under Dodd-Frank Section 1502. "
                f"Company: {company_name}. Filed: {file_date}. Accession: {adsh}."
            )

            articles.append(RawArticle(
                id=self.url_id(doc_url),
                title=title,
                url=doc_url,
                source="SEC EDGAR — Form SD",
                topic="ConflictMinerals",
                snippet=snippet,
                published_at=pub_dt,
            ))

        return articles

    def _scrape_page(self, url: str, source: str, topic: str,
                     filter_keywords: list[str]) -> List[RawArticle]:
        try:
            resp = requests.get(url, timeout=20, headers=_HEADERS)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[conflict_minerals] Failed to fetch {url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []

        # Look for news/article links
        selectors = [
            "article", ".views-row", ".node--type-news", "li.views-row",
            ".news-item", ".press-release", ".announcement",
            ".entry", ".post", "h2 a", "h3 a",
        ]

        found_items = []
        for sel in selectors:
            found_items = soup.select(sel)
            if found_items:
                break

        if not found_items:
            # Fallback: links in main content
            main = soup.select_one("main, #main-content, .content, article, .region-content")
            if main:
                found_items = main.find_all("a", href=True)
                # Wrap each in a pseudo-item
                for link in found_items[:30]:
                    href = link.get("href", "")
                    title = link.get_text(strip=True)
                    if not title or len(title) < 15:
                        continue
                    if not href.startswith("http"):
                        href = urljoin(url, href)

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
                return articles[:15]

        for item in found_items[:25]:
            a_tag = item.find("a", href=True) if hasattr(item, 'find') else item
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin(url, href)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            # Apply keyword filter
            snippet = item.get_text(" ", strip=True)[:400] if hasattr(item, 'get_text') else title
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
