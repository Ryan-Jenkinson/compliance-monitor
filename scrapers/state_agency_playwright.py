"""Playwright-based PFAS scrapers for Oregon DEQ and Connecticut DEEP.

These sites render content via JavaScript, so requests+BeautifulSoup returns
near-empty pages. Playwright loads the full page like a real browser.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_PFAS_SIGNALS = [
    "pfas", "pfoa", "pfos", "pfbs", "pfna", "polyfluoro", "perfluoro",
    "fluorin", "forever chemical", "toxic chemical", "emerging contaminant",
]

_NAV_PHRASES = [
    "home", "contact us", "accessibility", "sitemap", "privacy policy",
    "translate", "skip to", "sign in", "log in", "facebook", "twitter",
    "linkedin", "youtube", "instagram", "back to top", "subscribe",
    "print page", "share this", "view all", "read more", "click here",
    "learn more",
]

_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)


def _is_pfas_relevant(text: str) -> bool:
    t = text.lower()
    return any(sig in t for sig in _PFAS_SIGNALS)


def _is_nav_link(title: str) -> bool:
    t = title.lower().strip()
    if len(t) < 30:
        return True
    return any(phrase in t for phrase in _NAV_PHRASES)


def _parse_date_str(text: str) -> Optional[datetime]:
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%b. %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _fetch_with_playwright(url: str, wait_selector: str = "main, #main, .main-content, body", timeout: int = 25000) -> Optional[str]:
    """Load a URL with Playwright and return the full rendered HTML."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
            })
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            # Wait a moment for JS to settle
            try:
                page.wait_for_selector(wait_selector, timeout=10000)
            except PWTimeout:
                pass  # proceed with whatever loaded
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.warning(f"[playwright] Error fetching {url}: {e}")
        return None


def _extract_pfas_links(
    html: str,
    source_name: str,
    base_url: str,
    allowed_domain: str,
    seen: set,
) -> List[RawArticle]:
    soup = BeautifulSoup(html, "lxml")
    articles = []

    for a_tag in soup.find_all("a", href=True):
        title = a_tag.get_text(strip=True)
        if not title or _is_nav_link(title):
            continue

        href = a_tag["href"]
        if href.startswith("/"):
            href = base_url + href
        elif not href.startswith("http"):
            continue

        href = href.split("#")[0]

        if allowed_domain not in href or href in seen:
            continue

        if not _is_pfas_relevant(title + " " + href):
            continue

        # Try to find a date in surrounding container
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

        seen.add(href)
        articles.append(RawArticle(
            id=BaseScraper.url_id(href),
            title=title,
            url=href,
            source=source_name,
            topic="PFAS",
            published_at=pub_date,
            snippet=f"{source_name}: {title}",
        ))

    return articles


# ---------------------------------------------------------------------------
# Oregon DEQ
# ---------------------------------------------------------------------------

class OregonDEQPlaywrightScraper(BaseScraper):
    name = "oregon_deq"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = []

        # PFAS-specific topic page (Hazards & Cleanup section)
        for url, base, domain in [
            (
                "https://www.oregon.gov/deq/Hazards-and-Cleanup/ToxicReduction/Pages/PFAS-in-Oregon.aspx",
                "https://www.oregon.gov",
                "oregon.gov",
            ),
            (
                "https://www.oregon.gov/deq/Hazards-and-Cleanup/Pages/default.aspx",
                "https://www.oregon.gov",
                "oregon.gov",
            ),
            # DEQ newsroom (different subdomain: apps.oregon.gov)
            (
                "https://apps.oregon.gov/oregon-newsroom/OR/DEQ/Posts",
                "https://apps.oregon.gov",
                "oregon.gov",
            ),
        ]:
            html = _fetch_with_playwright(url, wait_selector="body")
            if html:
                found = _extract_pfas_links(html, "Oregon DEQ", base, domain, seen)
                articles.extend(found)

        return articles


# ---------------------------------------------------------------------------
# Connecticut DEEP
# ---------------------------------------------------------------------------

class ConnecticutDEEPPlaywrightScraper(BaseScraper):
    """CT DEEP portal is SharePoint-based and requires authentication for content.
    This scraper attempts several public-facing pages but typically returns empty —
    CT PFAS updates are covered by Safer States and Environmental Health News.
    Kept as a placeholder in case CT publishes accessible content in the future.
    """
    name = "connecticut_deep"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = []
        for url, base, domain in [
            (
                "https://portal.ct.gov/DEEP/Remediation--Site-Clean-Up/PFAS-in-Connecticut",
                "https://portal.ct.gov",
                "ct.gov",
            ),
        ]:
            html = _fetch_with_playwright(url, wait_selector="body")
            if html:
                found = _extract_pfas_links(html, "Connecticut DEEP", base, domain, seen)
                articles.extend(found)
        return articles
