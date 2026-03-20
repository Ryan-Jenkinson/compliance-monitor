"""Config-driven PFAS and EPR news scraper for all 50 US states.

Each state entry lists one or more agency URLs to scrape. The shared
_scrape_page helper (from state_agency_pfas) handles HTML parsing,
PFAS relevance filtering, and nav-link exclusion. Failed URLs are
silently skipped — so stale/wrong URLs degrade gracefully to no results.

States already covered by dedicated scrapers (excluded here to avoid duplication):
  MN (MPCA), ME (DEP), NY (DEC), WA (Ecology), CO (CDPHE), VT (DEC),
  OR (DEQ via Playwright), CT (DEEP via Playwright)
"""
from __future__ import annotations
import logging
from typing import List

from .base import BaseScraper
from .state_agency_pfas import _scrape_page
from processors.article import RawArticle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State configuration: (source_name, base_url, allowed_domain, [urls...])
# ---------------------------------------------------------------------------
# Each tuple: (source_label, base_url, allowed_domain, list_of_page_urls)
# Pages are scraped in order; `seen` set is shared so no URL is duplicated.
# ---------------------------------------------------------------------------

_STATE_PFAS_CONFIGS: list[tuple[str, str, str, list[str]]] = [

    # ---- COMPREHENSIVE STATES (highest priority) ----
    # Note: CA, MA, NH, NJ sites return 403 with scrapers — covered by PFAS Central + Safer States aggregators

    # California: DTSC blocks scrapers; CalEPA news accessible
    ("California EPA", "https://calepa.ca.gov", "calepa.ca.gov", [
        "https://calepa.ca.gov/newsroom/",
    ]),

    # Illinois — works well
    ("Illinois EPA", "https://epa.illinois.gov", "illinois.gov", [
        "https://epa.illinois.gov/topics/water-quality/pfas.html",
    ]),

    # Rhode Island — works well
    ("Rhode Island DEM", "https://dem.ri.gov", "ri.gov", [
        "https://dem.ri.gov/environmental-protection-bureau/water-resources/pfas",
        "https://dem.ri.gov/news",
    ]),

    # New Mexico — works very well
    ("New Mexico Environment Dept", "https://www.env.nm.gov", "nm.gov", [
        "https://www.env.nm.gov/pfas/",
        "https://www.env.nm.gov/news/",
    ]),

    # ---- LIMITED STATES (significant regulatory activity) ----

    # Maryland — MDE site times out; use MD news portal which works
    ("Maryland MDE News", "https://news.maryland.gov", "maryland.gov", [
        "https://news.maryland.gov/mde/",
    ]),

    # Michigan — works well
    ("Michigan EGLE", "https://www.michigan.gov", "michigan.gov", [
        "https://www.michigan.gov/pfasresponse",
        "https://www.michigan.gov/egle/newsroom",
    ]),

    # Wisconsin — works well
    ("Wisconsin DNR", "https://dnr.wisconsin.gov", "wisconsin.gov", [
        "https://dnr.wisconsin.gov/topic/Contaminants/pfas.html",
        "https://dnr.wisconsin.gov/newsroom",
    ]),

    # Pennsylvania — site reorganized to pa.gov; use PA newsroom
    ("Pennsylvania DEP", "https://www.pa.gov", "pa.gov", [
        "https://www.pa.gov/agencies/dep/newsroom.html",
    ]),

    # Hawaii
    ("Hawaii DOH", "https://health.hawaii.gov", "hawaii.gov", [
        "https://health.hawaii.gov/about/pfas/",
        "https://health.hawaii.gov/news/",
    ]),

    # Delaware
    ("Delaware DNREC", "https://dnrec.delaware.gov", "delaware.gov", [
        "https://dnrec.delaware.gov/pfas",
        "https://news.delaware.gov/category/dnrec/",
    ]),

    # Montana
    ("Montana DEQ", "https://deq.mt.gov", "mt.gov", [
        "https://deq.mt.gov/cleanupandrec/programs/pfas",
        "https://deq.mt.gov/news",
    ]),

    # Alaska
    ("Alaska DEC", "https://dec.alaska.gov", "alaska.gov", [
        "https://dec.alaska.gov/water/pfas/",
    ]),

    # Indiana
    ("Indiana IDEM", "https://www.in.gov", "in.gov", [
        "https://www.in.gov/idem/cleanups/pfas/",
        "https://www.in.gov/idem/whats-new/",
    ]),

    # Florida
    ("Florida DEP", "https://floridadep.gov", "floridadep.gov", [
        "https://floridadep.gov/water/source-drinking-water/content/pfas",
        "https://floridadep.gov/news",
    ]),

    # ---- PROPOSED / ACTIVE LEGISLATIVE STATES ----

    # Virginia
    ("Virginia DEQ", "https://www.deq.virginia.gov", "virginia.gov", [
        "https://www.deq.virginia.gov/our-programs/water/pfas",
        "https://www.deq.virginia.gov/news-info/news-releases",
    ]),

    # North Carolina
    ("North Carolina DEQ", "https://deq.nc.gov", "nc.gov", [
        "https://deq.nc.gov/pfas",
        "https://deq.nc.gov/news",
    ]),

    # Nevada
    ("Nevada NDEP", "https://ndep.nv.gov", "nv.gov", [
        "https://ndep.nv.gov/water/pfas",
    ]),

    # Missouri
    ("Missouri DNR", "https://dnr.mo.gov", "mo.gov", [
        "https://dnr.mo.gov/pfas",
        "https://dnr.mo.gov/newsrooms",
    ]),

    # Ohio
    ("Ohio EPA", "https://epa.ohio.gov", "ohio.gov", [
        "https://epa.ohio.gov/divisions-and-offices/drinking-and-ground-waters/rules-and-regulations/pfas",
        "https://epa.ohio.gov/about/media-center/news",
    ]),

    # West Virginia
    ("West Virginia DEP", "https://dep.wv.gov", "wv.gov", [
        "https://dep.wv.gov/WWE/wateruse/pfas/Pages/default.aspx",
    ]),

    # ---- OTHER STATES WITH PFAS MONITORING PROGRAMS ----

    ("Texas TCEQ", "https://www.tceq.texas.gov", "tceq.texas.gov", [
        "https://www.tceq.texas.gov/drinkingwater/pfas",
    ]),
    ("Georgia EPD", "https://epd.georgia.gov", "georgia.gov", [
        "https://epd.georgia.gov/drinking-water/pfas-georgias-drinking-water",
    ]),
    ("Arizona ADEQ", "https://azdeq.gov", "azdeq.gov", [
        "https://azdeq.gov/pfas",
    ]),
    ("Iowa DNR", "https://www.iowadnr.gov", "iowa.gov", [
        "https://www.iowadnr.gov/Environmental-Protection/Water-Quality/Water-Monitoring/PFAS",
    ]),
    ("Kansas KDHE", "https://www.kdhe.ks.gov", "ks.gov", [
        "https://www.kdhe.ks.gov/1606/PFAS",
    ]),
    ("Nebraska DEE", "https://dee.ne.gov", "ne.gov", [
        "https://dee.ne.gov/dee.nsf/pfas",
    ]),
    ("South Carolina DHEC", "https://scdhec.gov", "sc.gov", [
        "https://scdhec.gov/environment/your-air-land-water/water/pfas-sc",
    ]),
    ("North Dakota Health", "https://www.health.nd.gov", "nd.gov", [
        "https://www.health.nd.gov/pfas",
    ]),
    ("South Dakota DENR", "https://danr.sd.gov", "sd.gov", [
        "https://danr.sd.gov/pfas",
    ]),
    ("Idaho DEQ", "https://www.deq.idaho.gov", "idaho.gov", [
        "https://www.deq.idaho.gov/pfas",
    ]),
    ("Utah DEQ", "https://deq.utah.gov", "utah.gov", [
        "https://deq.utah.gov/pfas",
    ]),
    ("Wyoming DEQ", "https://deq.wyoming.gov", "wyoming.gov", [
        "https://deq.wyoming.gov/pfas",
    ]),
    ("Mississippi DEQ", "https://www.mdeq.ms.gov", "ms.gov", [
        "https://www.mdeq.ms.gov/pfas",
    ]),
    ("Louisiana DEQ", "https://www.deq.louisiana.gov", "louisiana.gov", [
        "https://www.deq.louisiana.gov/pfas",
    ]),
    ("Arkansas DEQ", "https://www.adeq.state.ar.us", "adeq.state.ar.us", [
        "https://www.adeq.state.ar.us/water/pfas/",
    ]),
    ("Tennessee DEA", "https://www.tn.gov", "tn.gov", [
        "https://www.tn.gov/environment/program-areas/wr-water-resources/water-quality/pfas.html",
    ]),
    ("Kentucky Energy Env", "https://eec.ky.gov", "ky.gov", [
        "https://eec.ky.gov/Natural-Resources/Water/Pages/PFAS.aspx",
    ]),
    ("Alabama ADEM", "https://adem.alabama.gov", "alabama.gov", [
        "https://adem.alabama.gov/programs/water/pfas.cnt",
    ]),
    ("Oklahoma DEQ", "https://www.deq.ok.gov", "ok.gov", [
        "https://www.deq.ok.gov/pfas",
    ]),
]

# ---------------------------------------------------------------------------
# EPR state agency sources (for Extended Producer Responsibility news)
# States not already covered by CalRecycle RSS or dedicated scrapers
# ---------------------------------------------------------------------------
_STATE_EPR_CONFIGS: list[tuple[str, str, str, list[str]]] = [
    ("Maine DEP EPR", "https://www.maine.gov", "maine.gov", [
        "https://www.maine.gov/dep/waste/ewaste/",
        "https://www.maine.gov/dep/waste/solidwaste/epr/",
    ]),
    ("Maryland MDE EPR", "https://mde.maryland.gov", "maryland.gov", [
        "https://mde.maryland.gov/programs/land/RecyclingandOperationsprogram/Pages/EPR.aspx",
    ]),
    ("New Jersey DEP EPR", "https://www.nj.gov", "nj.gov", [
        "https://www.nj.gov/dep/dshw/recycling/epr.html",
    ]),
    ("Illinois EPA EPR", "https://epa.illinois.gov", "illinois.gov", [
        "https://epa.illinois.gov/topics/waste-management/extended-producer-responsibility.html",
    ]),
    ("Minnesota MPCA EPR", "https://www.pca.state.mn.us", "mn.us", [
        "https://www.pca.state.mn.us/business-with-us/extended-producer-responsibility",
    ]),
    ("Washington Ecology EPR", "https://ecology.wa.gov", "ecology.wa.gov", [
        "https://ecology.wa.gov/waste-toxics/reducing-waste/extended-producer-responsibility",
    ]),
    ("Hawaii EPR", "https://health.hawaii.gov", "hawaii.gov", [
        "https://health.hawaii.gov/shwb/epr/",
    ]),
    ("Connecticut DEEP EPR", "https://portal.ct.gov", "ct.gov", [
        "https://portal.ct.gov/DEEP/Waste-Management-and-Disposal/Extended-Producer-Responsibility",
    ]),
    ("New York DEC EPR", "https://dec.ny.gov", "ny.gov", [
        "https://dec.ny.gov/environmental-protection/pollution-prevention-recycling/packaging-epr",
    ]),
    ("Massachusetts EPR", "https://www.mass.gov", "mass.gov", [
        "https://www.mass.gov/extended-producer-responsibility",
    ]),
]


class AllStatesPFASScraper(BaseScraper):
    """Scrapes PFAS agency pages for all US states not covered by dedicated scrapers."""
    name = "all_states_pfas"

    def __init__(self):
        super().__init__(lookback_hours=168)  # 7 days

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for source, base_url, allowed_domain, urls in _STATE_PFAS_CONFIGS:
            count_before = len(articles)
            for url in urls:
                found = _scrape_page(url, source, base_url, allowed_domain, seen)
                articles.extend(found)
            count_after = len(articles)
            if count_after > count_before:
                logger.debug(f"[all_states_pfas] {source}: {count_after - count_before} articles")

        return articles


class AllStatesEPRScraper(BaseScraper):
    """Scrapes EPR agency pages for states with enacted or proposed EPR packaging laws."""
    name = "all_states_epr"

    def __init__(self):
        super().__init__(lookback_hours=168)

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []
        seen: set[str] = set()

        for source, base_url, allowed_domain, urls in _STATE_EPR_CONFIGS:
            for url in urls:
                found = _scrape_page(url, source, base_url, allowed_domain, seen)
                # Override topic to EPR for these sources
                for a in found:
                    a.topic = "EPR"
                articles.extend(found)

        return articles
