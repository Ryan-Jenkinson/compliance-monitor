"""
PFAS Legislative Intelligence Scrapers — forward-looking legislative signals.

Targets sources that surface pre-introduction signals: legislative discussions,
committee hearings, advocacy campaigns, AG actions, rulemaking proceedings,
and law firm analysis of where PFAS legislation is heading.

Sources:
  1. NCSL (National Conference of State Legislatures) — PFAS legislation tracker
  2. EWG (Environmental Working Group) — state PFAS legislation pages
  3. Toxic-Free Future — state chemical policy advocacy
  4. Law firm regulatory blogs (Beveridge & Diamond, Keller & Heckman, etc.)
  5. State AG PFAS enforcement/investigation news
  6. LegiScan search — bill text and status for active PFAS bills
  7. InsideEPA / E&E News style coverage (free pages)
  8. Defend Our Health / Safer Chemicals Healthy Families
"""
from __future__ import annotations
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA}
_TIMEOUT = 20

# Shared PFAS signal keywords for relevance filtering
_PFAS_KEYWORDS = [
    "pfas", "pfoa", "pfos", "perfluoro", "polyfluoro", "forever chemical",
    "fluoropolymer", "fluorinated", "per- and polyfluoroalkyl",
]

# Forward-looking signal keywords — what we're really after
_FORWARD_KEYWORDS = [
    "propos", "introduc", "bill", "legislat", "hearing", "committee",
    "rulemaking", "draft", "consider", "advance", "session", "sponsor",
    "co-sponsor", "amendment", "testimony", "stakeholder", "comment period",
    "pre-fil", "study commission", "task force", "executive order",
    "attorney general", "investigation", "enforcement", "petition",
    "campaign", "coalition", "advocacy", "lobby", "urge", "call for",
    "recommend", "emerging", "expect", "likely", "upcoming", "pending",
    "debate", "floor vote", "engross", "enrolled", "fiscal note",
    "working group", "interim study", "ballot", "initiative",
]

# State name → abbreviation mapping
_STATE_ABBRS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def _is_pfas_relevant(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _PFAS_KEYWORDS)


def _has_forward_signal(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _FORWARD_KEYWORDS)


def _try_parse_date(date_str: str) -> Optional[datetime]:
    formats = [
        "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%b. %d, %Y",
        "%B %d %Y", "%d %B %Y", "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_date_from_text(text: str) -> Optional[datetime]:
    """Try to find a date in free text."""
    patterns = [
        r"(\w+ \d{1,2},? \d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            result = _try_parse_date(m.group(1))
            if result:
                return result
    return None


def _detect_states(text: str) -> list[str]:
    """Return list of US state abbreviations mentioned in text."""
    t = text.lower()
    found = []
    for name, abbr in _STATE_ABBRS.items():
        if name in t:
            found.append(abbr)
    # Also check for abbreviation patterns like "N.Y." or "NY"
    for abbr in _STATE_ABBRS.values():
        if re.search(rf'\b{abbr}\b', text):
            if abbr not in found:
                found.append(abbr)
    return found


def _fetch_and_parse(url: str, timeout: int = _TIMEOUT) -> Optional[BeautifulSoup]:
    """Safely fetch a URL and return a BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _fetch_text(url: str, timeout: int = _TIMEOUT) -> Optional[str]:
    """Fetch raw HTML text from a URL."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _scrape_article_fulltext(url: str, max_chars: int = 3000) -> str:
    """Fetch an article page and extract the main body text."""
    soup = _fetch_and_parse(url, timeout=15)
    if not soup:
        return ""
    # Try common article body selectors
    for selector in ["article", ".entry-content", ".post-content", ".article-body",
                     ".field--body", ".content-body", "main", "#content"]:
        body = soup.select_one(selector)
        if body:
            text = body.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return text[:max_chars]
    # Fallback: get all paragraph text
    paragraphs = soup.find_all("p")
    text = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
    return text[:max_chars]


# =============================================================================
# 1. NCSL PFAS Legislation Tracker
# =============================================================================

class NCSLPFASScraper(BaseScraper):
    """Scrape NCSL's PFAS state legislation pages."""
    name = "ncsl_pfas"

    _URLS = [
        "https://www.ncsl.org/environment-and-natural-resources/per-and-polyfluoroalkyl-substances-pfas",
        "https://www.ncsl.org/environment-and-natural-resources/state-pfas-legislation",
        "https://www.ncsl.org/environment-and-natural-resources/per-and-polyfluoroalkyl-substances-pfas-state-legislation",
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()
        for url in self._URLS:
            soup = _fetch_and_parse(url)
            if not soup:
                continue
            # NCSL often has tables with state legislation data
            articles.extend(self._parse_ncsl_page(soup, url, seen))
        return articles

    def _parse_ncsl_page(self, soup: BeautifulSoup, base_url: str,
                         seen: set[str]) -> List[RawArticle]:
        results = []

        # Extract all links with PFAS relevance
        for a_tag in soup.find_all("a", href=True):
            href = urljoin(base_url, a_tag["href"])
            text = a_tag.get_text(strip=True)
            if len(text) < 15 or href in seen:
                continue

            # Get surrounding context
            parent = a_tag.parent
            context = parent.get_text(strip=True)[:500] if parent else text

            if not _is_pfas_relevant(text + " " + context):
                continue

            seen.add(href)
            states = _detect_states(context)

            results.append(RawArticle(
                id=self.url_id(href),
                title=text[:200],
                url=href,
                source="NCSL",
                topic="PFAS",
                snippet=f"NCSL: {context[:400]}",
                extra={"states_mentioned": states, "signal_type": "legislation_tracker"},
            ))

        # Also extract table data (NCSL often has legislation tables)
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])] if rows else []
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                row_text = " | ".join(c.get_text(strip=True) for c in cells)
                if not _is_pfas_relevant(row_text):
                    continue

                # Extract any link in the row
                link = row.find("a", href=True)
                href = urljoin(base_url, link["href"]) if link else base_url
                if href in seen:
                    continue
                seen.add(href)

                states = _detect_states(row_text)
                results.append(RawArticle(
                    id=self.url_id(href + row_text[:50]),
                    title=row_text[:200],
                    url=href,
                    source="NCSL",
                    topic="PFAS",
                    snippet=f"NCSL legislation table: {row_text[:400]}",
                    extra={"states_mentioned": states, "signal_type": "legislation_table"},
                ))

        # Extract the full page text as one large article for Claude analysis
        page_text = soup.get_text(separator="\n", strip=True)[:8000]
        if _is_pfas_relevant(page_text):
            results.append(RawArticle(
                id=self.url_id(base_url + "_fulltext"),
                title=f"NCSL PFAS Legislation Overview ({base_url.split('/')[-1]})",
                url=base_url,
                source="NCSL",
                topic="PFAS",
                full_text=page_text,
                snippet="Full NCSL page content for Claude analysis",
                extra={"signal_type": "overview_page"},
            ))

        return results


# =============================================================================
# 2. EWG State PFAS Legislation Tracker
# =============================================================================

class EWGPFASScraper(BaseScraper):
    """Scrape EWG's PFAS coverage — state legislation and advocacy."""
    name = "ewg_pfas"

    _URLS = [
        "https://www.ewg.org/areas-focus/toxic-chemicals/pfas-chemicals",
        "https://www.ewg.org/news-insights?topics=pfas",
        "https://www.ewg.org/interactive-maps/pfas_contamination/",
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()

        for url in self._URLS:
            soup = _fetch_and_parse(url)
            if not soup:
                continue
            articles.extend(self._parse_ewg_page(soup, url, seen))

        return articles

    def _parse_ewg_page(self, soup: BeautifulSoup, base_url: str,
                        seen: set[str]) -> List[RawArticle]:
        results = []

        # Find article cards, news items
        for el in soup.find_all(["article", "div"], class_=lambda c: c and any(
            x in (c if isinstance(c, str) else " ".join(c))
            for x in ("card", "news", "post", "item", "result", "teaser")
        )):
            a_tag = el.find("a", href=True)
            title_el = el.find(["h1", "h2", "h3", "h4", "h5"])
            if not a_tag:
                continue

            href = urljoin(base_url, a_tag["href"])
            title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
            if len(title) < 15 or href in seen:
                continue

            snippet_text = ""
            p_tag = el.find("p")
            if p_tag:
                snippet_text = p_tag.get_text(strip=True)[:300]

            combined = title + " " + snippet_text
            if not _is_pfas_relevant(combined):
                continue

            seen.add(href)
            pub_date = None
            date_el = el.find(["time", "span"], class_=lambda c: c and "date" in str(c).lower())
            if date_el:
                pub_date = _try_parse_date(date_el.get("datetime", "") or date_el.get_text(strip=True))

            states = _detect_states(combined)

            results.append(RawArticle(
                id=self.url_id(href),
                title=title[:200],
                url=href,
                source="EWG",
                topic="PFAS",
                published_at=pub_date,
                snippet=f"EWG: {snippet_text or title}",
                extra={"states_mentioned": states, "signal_type": "advocacy_news"},
            ))

        # Fallback: grab all substantial PFAS links
        if not results:
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text(strip=True)
                href = urljoin(base_url, a_tag["href"])
                if len(text) < 20 or href in seen:
                    continue
                if not _is_pfas_relevant(text):
                    continue
                seen.add(href)
                results.append(RawArticle(
                    id=self.url_id(href),
                    title=text[:200],
                    url=href,
                    source="EWG",
                    topic="PFAS",
                    snippet=f"EWG: {text[:300]}",
                    extra={"signal_type": "advocacy_link"},
                ))

        return results


# =============================================================================
# 3. Law Firm Regulatory Blog Scrapers
# =============================================================================

class LawFirmPFASScraper(BaseScraper):
    """
    Scrape major environmental law firm blogs for PFAS regulatory analysis.
    These firms publish forward-looking analysis of pending state legislation.
    """
    name = "law_firm_pfas"

    _SOURCES = [
        {
            "name": "Beveridge & Diamond",
            "urls": [
                "https://www.bdlaw.com/publications/?topics=pfas",
                "https://www.bdlaw.com/publications/?practice=pfas",
            ],
        },
        {
            "name": "Keller & Heckman",
            "urls": [
                "https://www.khlaw.com/insights?q=PFAS",
                "https://www.packaginglaw.com/search?q=PFAS",
            ],
        },
        {
            "name": "Bergeson & Campbell",
            "urls": [
                "https://www.lawbc.com/?s=PFAS",
            ],
        },
        {
            "name": "Arnold & Porter",
            "urls": [
                "https://www.arnoldporter.com/en/search#q=PFAS&sort=date",
            ],
        },
        {
            "name": "Perkins Coie",
            "urls": [
                "https://www.perkinscoie.com/en/news-insights/index.html?q=PFAS",
            ],
        },
        {
            "name": "Hunton Andrews Kurth",
            "urls": [
                "https://www.huntonak.com/en/search.html?q=PFAS",
            ],
        },
        {
            "name": "JD Supra PFAS",
            "urls": [
                "https://www.jdsupra.com/topics/pfas/",
                "https://www.jdsupra.com/legalnews/pfas/",
            ],
        },
        {
            "name": "Lexology PFAS",
            "urls": [
                "https://www.lexology.com/search?q=PFAS+state+legislation",
            ],
        },
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()

        for source in self._SOURCES:
            for url in source["urls"]:
                soup = _fetch_and_parse(url)
                if not soup:
                    continue
                articles.extend(
                    self._parse_law_firm(soup, url, source["name"], seen)
                )

        return articles

    def _parse_law_firm(self, soup: BeautifulSoup, base_url: str,
                        firm_name: str, seen: set[str]) -> List[RawArticle]:
        results = []

        # Generic pattern: find all links with substantial text
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True)
            href = urljoin(base_url, a_tag["href"])

            if len(text) < 20 or href in seen:
                continue

            # Check for PFAS + forward-looking relevance
            # Get parent context for better matching
            parent = a_tag.parent
            context = parent.get_text(strip=True)[:500] if parent else text
            combined = text + " " + context

            if not _is_pfas_relevant(combined):
                continue

            # Extra relevance boost if forward-looking signals present
            is_forward = _has_forward_signal(combined)

            seen.add(href)

            # Try to find date near the link
            pub_date = None
            for sibling in (a_tag.previous_sibling, a_tag.next_sibling):
                if sibling and hasattr(sibling, 'get_text'):
                    date_text = sibling.get_text(strip=True)
                    pub_date = _extract_date_from_text(date_text)
                    if pub_date:
                        break
            if not pub_date and parent:
                date_text = parent.get_text(strip=True)
                pub_date = _extract_date_from_text(date_text)

            states = _detect_states(combined)

            results.append(RawArticle(
                id=self.url_id(href),
                title=text[:200],
                url=href,
                source=f"Law Firm: {firm_name}",
                topic="PFAS",
                published_at=pub_date,
                snippet=f"{firm_name}: {context[:400]}",
                extra={
                    "states_mentioned": states,
                    "signal_type": "legal_analysis",
                    "is_forward_looking": is_forward,
                    "firm": firm_name,
                },
            ))

        return results


# =============================================================================
# 4. Environmental Advocacy Organization Scrapers
# =============================================================================

class AdvocacyOrgScraper(BaseScraper):
    """
    Scrape environmental advocacy organizations for PFAS campaign signals.
    These orgs often telegraph which states they're targeting for legislation.
    """
    name = "advocacy_pfas"

    _SOURCES = [
        {
            "name": "Toxic-Free Future",
            "urls": [
                "https://toxicfreefuture.org/mind-the-store/pfas/",
                "https://toxicfreefuture.org/science/pfas/",
                "https://toxicfreefuture.org/policy/",
            ],
        },
        {
            "name": "Safer Chemicals Healthy Families",
            "urls": [
                "https://saferchemicals.org/newsroom/",
                "https://saferchemicals.org/pfas-2/",
            ],
        },
        {
            "name": "Defend Our Health",
            "urls": [
                "https://www.defendourhealth.org/toxic-chemicals/pfas/",
                "https://www.defendourhealth.org/news/",
            ],
        },
        {
            "name": "Clean Water Action",
            "urls": [
                "https://www.cleanwateraction.org/features/pfas",
                "https://www.cleanwateraction.org/features/pfas-contamination",
            ],
        },
        {
            "name": "Sierra Club (PFAS)",
            "urls": [
                "https://www.sierraclub.org/search?query=PFAS+state+legislation",
            ],
        },
        {
            "name": "NRDC (PFAS)",
            "urls": [
                "https://www.nrdc.org/search?query=PFAS+legislation",
            ],
        },
        {
            "name": "Earthjustice (PFAS)",
            "urls": [
                "https://earthjustice.org/search?query=PFAS",
            ],
        },
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()

        for source in self._SOURCES:
            for url in source["urls"]:
                soup = _fetch_and_parse(url)
                if not soup:
                    continue
                articles.extend(
                    self._parse_advocacy(soup, url, source["name"], seen)
                )

        return articles

    def _parse_advocacy(self, soup: BeautifulSoup, base_url: str,
                        org_name: str, seen: set[str]) -> List[RawArticle]:
        results = []

        # Try structured article/card elements first
        for el in soup.find_all(["article", "div", "li"], class_=lambda c: c and any(
            x in (c if isinstance(c, str) else " ".join(c))
            for x in ("card", "post", "item", "result", "teaser", "news", "entry", "view")
        )):
            a_tag = el.find("a", href=True)
            title_el = el.find(["h1", "h2", "h3", "h4", "h5"])
            if not a_tag:
                continue

            href = urljoin(base_url, a_tag["href"])
            title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
            if len(title) < 15 or href in seen:
                continue

            snippet_text = ""
            p_tag = el.find("p")
            if p_tag:
                snippet_text = p_tag.get_text(strip=True)[:300]

            combined = title + " " + snippet_text
            if not _is_pfas_relevant(combined):
                continue

            seen.add(href)
            states = _detect_states(combined)

            results.append(RawArticle(
                id=self.url_id(href),
                title=title[:200],
                url=href,
                source=f"Advocacy: {org_name}",
                topic="PFAS",
                snippet=f"{org_name}: {snippet_text or title}",
                extra={
                    "states_mentioned": states,
                    "signal_type": "advocacy_campaign",
                    "is_forward_looking": _has_forward_signal(combined),
                    "org": org_name,
                },
            ))

        # Fallback: all substantial PFAS links
        if not results:
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text(strip=True)
                href = urljoin(base_url, a_tag["href"])
                if len(text) < 20 or href in seen:
                    continue
                if not _is_pfas_relevant(text):
                    continue
                seen.add(href)
                results.append(RawArticle(
                    id=self.url_id(href),
                    title=text[:200],
                    url=href,
                    source=f"Advocacy: {org_name}",
                    topic="PFAS",
                    snippet=f"{org_name}: {text[:300]}",
                    extra={"signal_type": "advocacy_link", "org": org_name},
                ))

        return results


# =============================================================================
# 5. State AG PFAS Enforcement / Investigation Tracker
# =============================================================================

class StateAGPFASScraper(BaseScraper):
    """
    Scrape state attorney general offices for PFAS enforcement,
    investigations, and multi-state actions that often precede legislation.
    """
    name = "state_ag_pfas"

    _AG_PAGES = [
        ("https://oag.ca.gov/news?search_api_fulltext=PFAS", "California AG"),
        ("https://www.mass.gov/search?q=PFAS+attorney+general", "Massachusetts AG"),
        ("https://ag.ny.gov/search?search=PFAS", "New York AG"),
        ("https://www.michigan.gov/ag/search?q=PFAS", "Michigan AG"),
        ("https://www.ag.state.mn.us/Consumer/Default.asp", "Minnesota AG"),
        ("https://www.atg.wa.gov/search?query=PFAS", "Washington AG"),
        ("https://portal.ct.gov/AG/Press-Releases?q=PFAS", "Connecticut AG"),
        ("https://www.nj.gov/oag/newsreleases.html", "New Jersey AG"),
        ("https://www.naag.org/issues/pfas/", "NAAG (Multi-state)"),
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()

        for url, ag_name in self._AG_PAGES:
            soup = _fetch_and_parse(url)
            if not soup:
                continue
            articles.extend(self._parse_ag_page(soup, url, ag_name, seen))

        return articles

    def _parse_ag_page(self, soup: BeautifulSoup, base_url: str,
                       ag_name: str, seen: set[str]) -> List[RawArticle]:
        results = []

        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True)
            href = urljoin(base_url, a_tag["href"])

            if len(text) < 15 or href in seen:
                continue

            parent = a_tag.parent
            context = parent.get_text(strip=True)[:500] if parent else text
            combined = text + " " + context

            if not _is_pfas_relevant(combined):
                continue

            seen.add(href)
            pub_date = _extract_date_from_text(context)
            states = _detect_states(combined)

            results.append(RawArticle(
                id=self.url_id(href),
                title=text[:200],
                url=href,
                source=f"AG Office: {ag_name}",
                topic="PFAS",
                published_at=pub_date,
                snippet=f"{ag_name}: {context[:400]}",
                extra={
                    "states_mentioned": states,
                    "signal_type": "ag_enforcement",
                    "ag_office": ag_name,
                },
            ))

        return results


# =============================================================================
# 6. JD Supra / Legal News Aggregator (broader legal coverage)
# =============================================================================

class LegalNewsPFASScraper(BaseScraper):
    """
    Scrape legal news aggregators for PFAS legislative analysis.
    JD Supra, National Law Review, and regulatory-focused outlets.
    """
    name = "legal_news_pfas"

    _URLS = [
        "https://www.jdsupra.com/topics/pfas/",
        "https://natlawreview.com/?s=PFAS+legislation",
        "https://www.natlawreview.com/topic/pfas",
        "https://www.regulatoryoversight.com/?s=PFAS",
        "https://news.bloomberglaw.com/search?query=PFAS+state+legislation",
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()

        for url in self._URLS:
            soup = _fetch_and_parse(url)
            if not soup:
                continue
            articles.extend(self._parse_legal_news(soup, url, seen))

        return articles

    def _parse_legal_news(self, soup: BeautifulSoup, base_url: str,
                          seen: set[str]) -> List[RawArticle]:
        results = []

        # Look for article-like elements
        for el in soup.find_all(["article", "div", "li"], class_=lambda c: c and any(
            x in (c if isinstance(c, str) else " ".join(c))
            for x in ("result", "post", "item", "card", "article", "entry",
                       "search-result", "teaser", "listing")
        )):
            a_tag = el.find("a", href=True)
            title_el = el.find(["h1", "h2", "h3", "h4", "h5"])
            if not a_tag:
                continue

            href = urljoin(base_url, a_tag["href"])
            title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
            if len(title) < 15 or href in seen:
                continue

            snippet_text = ""
            p_tag = el.find("p")
            if p_tag:
                snippet_text = p_tag.get_text(strip=True)[:400]

            combined = title + " " + snippet_text
            if not _is_pfas_relevant(combined):
                continue

            seen.add(href)
            pub_date = None
            date_el = el.find(["time", "span"], class_=lambda c: c and "date" in str(c).lower())
            if date_el:
                pub_date = _try_parse_date(date_el.get("datetime", "") or date_el.get_text(strip=True))

            states = _detect_states(combined)

            source_name = "JD Supra" if "jdsupra" in base_url else \
                          "National Law Review" if "natlawreview" in base_url else \
                          "Bloomberg Law" if "bloomberg" in base_url else \
                          "Legal News"

            results.append(RawArticle(
                id=self.url_id(href),
                title=title[:200],
                url=href,
                source=source_name,
                topic="PFAS",
                published_at=pub_date,
                snippet=f"{source_name}: {snippet_text or title}",
                extra={
                    "states_mentioned": states,
                    "signal_type": "legal_analysis",
                    "is_forward_looking": _has_forward_signal(combined),
                },
            ))

        # Fallback for simpler page structures
        if not results:
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text(strip=True)
                href = urljoin(base_url, a_tag["href"])
                if len(text) < 25 or href in seen:
                    continue
                if not _is_pfas_relevant(text):
                    continue
                seen.add(href)
                results.append(RawArticle(
                    id=self.url_id(href),
                    title=text[:200],
                    url=href,
                    source="Legal News",
                    topic="PFAS",
                    snippet=text[:400],
                    extra={"signal_type": "legal_link"},
                ))

        return results


# =============================================================================
# 7. Regulatory News (InsideEPA / E&E News free pages, Reuters, AP)
# =============================================================================

class RegulatoryNewsScraper(BaseScraper):
    """Scrape regulatory news outlets for PFAS state legislation coverage."""
    name = "regulatory_news_pfas"

    _URLS = [
        "https://www.reuters.com/search/news?query=PFAS+state+legislation",
        "https://apnews.com/search?q=PFAS+state+legislation",
        "https://www.theguardian.com/environment/pfas",
        "https://insideclimatenews.org/?s=PFAS+state+legislation",
        "https://www.eenews.net/search/?keyword=PFAS+state+legislation",
        "https://www.chemistryworld.com/search?q=PFAS+state+legislation",
    ]

    def fetch(self) -> List[RawArticle]:
        articles = []
        seen: set[str] = set()

        for url in self._URLS:
            soup = _fetch_and_parse(url)
            if not soup:
                continue
            articles.extend(self._parse_news(soup, url, seen))

        return articles

    def _parse_news(self, soup: BeautifulSoup, base_url: str,
                    seen: set[str]) -> List[RawArticle]:
        results = []

        for el in soup.find_all(["article", "div", "li"], class_=lambda c: c and any(
            x in (c if isinstance(c, str) else " ".join(c))
            for x in ("result", "story", "card", "item", "media", "search", "teaser")
        )):
            a_tag = el.find("a", href=True)
            title_el = el.find(["h1", "h2", "h3", "h4"])
            if not a_tag:
                continue

            href = urljoin(base_url, a_tag["href"])
            title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
            if len(title) < 15 or href in seen:
                continue

            snippet_text = ""
            p_tag = el.find("p")
            if p_tag:
                snippet_text = p_tag.get_text(strip=True)[:400]

            combined = title + " " + snippet_text
            if not _is_pfas_relevant(combined):
                continue

            seen.add(href)
            pub_date = None
            time_el = el.find("time")
            if time_el:
                pub_date = _try_parse_date(time_el.get("datetime", "") or time_el.get_text(strip=True))

            source_name = "Reuters" if "reuters" in base_url else \
                          "AP News" if "apnews" in base_url else \
                          "The Guardian" if "guardian" in base_url else \
                          "Inside Climate" if "insideclimate" in base_url else \
                          "E&E News" if "eenews" in base_url else \
                          "Chemistry World" if "chemistry" in base_url else \
                          "Regulatory News"

            states = _detect_states(combined)

            results.append(RawArticle(
                id=self.url_id(href),
                title=title[:200],
                url=href,
                source=source_name,
                topic="PFAS",
                published_at=pub_date,
                snippet=f"{source_name}: {snippet_text or title}",
                extra={
                    "states_mentioned": states,
                    "signal_type": "regulatory_news",
                    "is_forward_looking": _has_forward_signal(combined),
                },
            ))

        return results


# =============================================================================
# 8. Deep Article Fetcher — Follow up on promising links
# =============================================================================

class ArticleDeepFetcher:
    """
    Not a BaseScraper — utility class that takes a list of RawArticles
    from the other scrapers and fetches full text from the most promising ones.
    Returns enriched articles with full_text populated.
    """

    def __init__(self, max_articles: int = 30):
        self.max_articles = max_articles

    def enrich(self, articles: List[RawArticle]) -> List[RawArticle]:
        """Score and fetch full text for the most forward-looking articles."""
        scored = []
        for a in articles:
            score = 0
            text = a.title + " " + a.snippet
            if _has_forward_signal(text):
                score += 2
            if a.extra.get("is_forward_looking"):
                score += 2
            if a.extra.get("states_mentioned"):
                score += len(a.extra["states_mentioned"])
            if a.extra.get("signal_type") in ("legal_analysis", "advocacy_campaign"):
                score += 1
            scored.append((score, a))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:self.max_articles]

        enriched = []
        for score, article in top:
            if article.full_text:
                enriched.append(article)
                continue

            if score < 2:
                enriched.append(article)
                continue

            logger.info(f"Fetching full text: {article.title[:60]}...")
            full_text = _scrape_article_fulltext(article.url)
            if full_text:
                article.full_text = full_text
            enriched.append(article)

        logger.info(f"Enriched {sum(1 for a in enriched if a.full_text)} articles with full text")
        return enriched


# =============================================================================
# Public API — run all legislative intel scrapers
# =============================================================================

ALL_LEGISLATIVE_SCRAPERS = [
    NCSLPFASScraper,
    EWGPFASScraper,
    LawFirmPFASScraper,
    AdvocacyOrgScraper,
    StateAGPFASScraper,
    LegalNewsPFASScraper,
    RegulatoryNewsScraper,
]


def run_all_legislative_scrapers(enrich: bool = True) -> List[RawArticle]:
    """
    Run all legislative intelligence scrapers and return combined results.
    If enrich=True, follows up on the most promising articles for full text.
    """
    all_articles = []
    seen_urls: set[str] = set()

    for scraper_cls in ALL_LEGISLATIVE_SCRAPERS:
        scraper = scraper_cls()
        try:
            articles = scraper.scrape()
            for a in articles:
                if a.url not in seen_urls:
                    seen_urls.add(a.url)
                    all_articles.append(a)
            logger.info(f"[{scraper.name}] Collected {len(articles)} articles")
        except Exception as e:
            logger.warning(f"[{scraper.name}] Scraper failed: {e}")

    logger.info(f"Total legislative intel articles: {len(all_articles)}")

    if enrich and all_articles:
        fetcher = ArticleDeepFetcher(max_articles=30)
        all_articles = fetcher.enrich(all_articles)

    return all_articles


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    articles = run_all_legislative_scrapers(enrich=True)
    print(f"\nTotal articles collected: {len(articles)}")
    print(f"With full text: {sum(1 for a in articles if a.full_text)}")
    print(f"With state mentions: {sum(1 for a in articles if a.extra.get('states_mentioned'))}")
    print(f"Forward-looking: {sum(1 for a in articles if a.extra.get('is_forward_looking'))}")
    print()

    # Show top articles by signal type
    by_type: dict[str, int] = {}
    for a in articles:
        t = a.extra.get("signal_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    print("By signal type:")
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")
