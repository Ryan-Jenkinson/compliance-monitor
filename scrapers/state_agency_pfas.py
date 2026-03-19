"""Dedicated PFAS scrapers for state agencies: WA, ME, NY, OR, CO, VT, CT."""
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
    "Accept-Language": "en-US,en;q=0.5",
}

_PFAS_SIGNALS = [
    "pfas", "pfoa", "pfos", "pfbs", "pfna", "polyfluoro", "perfluoro",
    "fluorin", "forever chemical", "amara", "prism", "hb 2658", "sb 5135",
    "ld 1503", "hb 2771", "toxic chemical", "emerging contaminant",
]

# Short/common nav words that indicate a link is a navigation element
_NAV_PHRASES = [
    "home", "contact us", "accessibility", "sitemap", "privacy policy",
    "translate", "skip to", "sign in", "log in", "facebook", "twitter",
    "linkedin", "youtube", "instagram", "back to top", "subscribe",
    "print page", "share this", "all news", "view all", "read more",
    "click here", "learn more", "find out more",
]

_TIMEOUT = 15

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
    """Return True if title looks like a navigation/UI element rather than an article."""
    t = title.lower().strip()
    if len(t) < 30:
        return True
    return any(phrase in t for phrase in _NAV_PHRASES)


def _parse_date_str(text: str) -> Optional[datetime]:
    text = text.strip()
    fmts = [
        "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d",
        "%b. %d, %Y", "%B %Y", "%b %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _scrape_page(
    url: str,
    source_name: str,
    base_url: str,
    allowed_domain: str,
    seen: set,
) -> List[RawArticle]:
    """Shared link-scraping logic used by all state agency scrapers."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"[{source_name.lower().replace(' ', '_')}] {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
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

        # Strip fragments
        href = href.split("#")[0]

        if allowed_domain not in href or href in seen:
            continue

        haystack = (title + " " + href).lower()
        if not _is_pfas_relevant(haystack):
            continue

        # Try to grab date from surrounding container
        pub_date = None
        container = a_tag.parent
        for _ in range(3):  # walk up 3 levels
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
# Maine DEP
# ---------------------------------------------------------------------------

class MaineDEPScraper(BaseScraper):
    name = "maine_dep"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = _scrape_page(
            "https://www.maine.gov/dep/news/",
            "Maine DEP", "https://www.maine.gov", "maine.gov", seen,
        )
        articles += _scrape_page(
            "https://www.maine.gov/dep/spills/topics/pfas/",
            "Maine DEP", "https://www.maine.gov", "maine.gov", seen,
        )
        return articles


# ---------------------------------------------------------------------------
# New York DEC
# ---------------------------------------------------------------------------

class NewYorkDECScraper(BaseScraper):
    name = "new_york_dec"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = _scrape_page(
            "https://dec.ny.gov/environmental-protection/per-and-polyfluoroalkyl-substances-pfas",
            "New York DEC", "https://dec.ny.gov", "ny.gov", seen,
        )
        return articles


# ---------------------------------------------------------------------------
# Washington Ecology
# ---------------------------------------------------------------------------

class WashingtonEcologyScraper(BaseScraper):
    name = "washington_ecology"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = _scrape_page(
            "https://ecology.wa.gov/waste-toxics/reducing-toxic-chemicals",
            "Washington Ecology", "https://ecology.wa.gov", "ecology.wa.gov", seen,
        )
        articles += _scrape_page(
            "https://ecology.wa.gov/blog",
            "Washington Ecology", "https://ecology.wa.gov", "ecology.wa.gov", seen,
        )
        return articles


# ---------------------------------------------------------------------------
# Colorado CDPHE
# ---------------------------------------------------------------------------

class ColoradoCDPHEScraper(BaseScraper):
    name = "colorado_cdphe"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = _scrape_page(
            "https://cdphe.colorado.gov/pfas",
            "Colorado CDPHE", "https://cdphe.colorado.gov", "colorado.gov", seen,
        )
        articles += _scrape_page(
            "https://cdphe.colorado.gov/pfas/health",
            "Colorado CDPHE", "https://cdphe.colorado.gov", "colorado.gov", seen,
        )
        return articles


# ---------------------------------------------------------------------------
# Vermont DEC
# ---------------------------------------------------------------------------

class VermontDECScraper(BaseScraper):
    name = "vermont_dec"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        seen: set[str] = set()
        articles = _scrape_page(
            "https://dec.vermont.gov/pfas",
            "Vermont DEC", "https://dec.vermont.gov", "vermont.gov", seen,
        )
        articles += _scrape_page(
            "https://dec.vermont.gov/news",
            "Vermont DEC", "https://dec.vermont.gov", "vermont.gov", seen,
        )
        return articles

