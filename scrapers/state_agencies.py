"""Configurable multi-state RSS/HTML scraper for EPR and PFAS state programs."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List

import feedparser
import requests
from bs4 import BeautifulSoup

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

# Add more states here without code changes — just extend this list
_STATE_FEEDS: list[dict] = [
    {
        "state": "California",
        "source": "CalRecycle",
        "topic": "EPR",
        "feed_url": "https://calrecycle.ca.gov/rss/",
        "keywords": ["EPR", "SB 54", "producer responsibility", "packaging", "plastic", "recycl"],
    },
    # PFAS-specific RSS feeds for states that block direct HTML scraping
    {
        "state": "New Jersey",
        "source": "New Jersey DEP",
        "topic": "PFAS",
        "feed_url": "https://www.nj.gov/dep/rss/newsrel.xml",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro", "pafc"],
    },
    {
        "state": "Massachusetts",
        "source": "Massachusetts DEP",
        "topic": "PFAS",
        "feed_url": "https://www.mass.gov/rss/news?tid=all&org=massachusetts-department-of-environmental-protection",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro"],
    },
    {
        "state": "New Hampshire",
        "source": "New Hampshire DES",
        "topic": "PFAS",
        "feed_url": "https://www.des.nh.gov/about-des/news-and-updates/rss",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro", "drinking water"],
    },
    {
        "state": "California",
        "source": "California DTSC",
        "topic": "PFAS",
        "feed_url": "https://dtsc.ca.gov/category/news/feed/",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro", "ab 347", "ab 1817"],
    },
    {
        "state": "Connecticut",
        "source": "Connecticut DEEP",
        "topic": "PFAS",
        "feed_url": "https://portal.ct.gov/DEEP/RSS-Feeds",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro", "pa 24-59"],
    },
    {
        "state": "Michigan",
        "source": "Michigan EGLE",
        "topic": "PFAS",
        "feed_url": "https://www.michigan.gov/egle/rss/newsroom",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro"],
    },
    {
        "state": "Wisconsin",
        "source": "Wisconsin DNR",
        "topic": "PFAS",
        "feed_url": "https://dnr.wisconsin.gov/topic/Contaminants/rss",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro"],
    },
    {
        "state": "Illinois",
        "source": "Illinois EPA",
        "topic": "PFAS",
        "feed_url": "https://epa.illinois.gov/rss/newsroom.xml",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro", "hb 2516"],
    },
    {
        "state": "Virginia",
        "source": "Virginia DEQ",
        "topic": "PFAS",
        "feed_url": "https://www.deq.virginia.gov/rss/news-releases",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro"],
    },
    {
        "state": "North Carolina",
        "source": "North Carolina DEQ",
        "topic": "PFAS",
        "feed_url": "https://deq.nc.gov/rss.xml",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro"],
    },
    {
        "state": "Florida",
        "source": "Florida DEP",
        "topic": "PFAS",
        "feed_url": "https://floridadep.gov/rss.xml",
        "keywords": ["pfas", "pfoa", "pfos", "forever chemical", "polyfluoro", "perfluoro"],
    },
    # EPR state feeds
    {
        "state": "Oregon",
        "source": "Oregon DEQ EPR",
        "topic": "EPR",
        "feed_url": "https://apps.oregon.gov/oregon-newsroom/OR/DEQ/Posts/rss",
        "keywords": ["EPR", "producer responsibility", "packaging", "plastic", "SB 543", "sb543"],
    },
    {
        "state": "Colorado",
        "source": "Colorado CDPHE EPR",
        "topic": "EPR",
        "feed_url": "https://cdphe.colorado.gov/rss.xml",
        "keywords": ["EPR", "producer responsibility", "packaging", "plastic", "recycl"],
    },
    {
        "state": "Washington",
        "source": "Washington Ecology EPR",
        "topic": "EPR",
        "feed_url": "https://ecology.wa.gov/rss/news",
        "keywords": ["EPR", "producer responsibility", "packaging", "plastic", "recycl"],
    },
]


class StateAgenciesScraper(BaseScraper):
    name = "state_agencies"

    def __init__(self):
        super().__init__(lookback_hours=168)  # 7 days — state agencies post infrequently

    def fetch(self) -> List[RawArticle]:
        articles: list[RawArticle] = []

        for config in _STATE_FEEDS:
            try:
                results = self._fetch_feed(config)
                articles.extend(results)
            except Exception as e:
                logger.warning(f"[state_agencies] Error for {config['state']}: {e}")

        return articles

    def _fetch_feed(self, config: dict) -> List[RawArticle]:
        feed = feedparser.parse(config["feed_url"])
        articles = []
        keywords = [kw.lower() for kw in config["keywords"]]

        for entry in feed.entries:
            url = entry.get("link", "")
            if not url:
                continue

            title = entry.get("title", "")
            summary = entry.get("summary", "")
            haystack = (title + " " + summary).lower()

            if not any(kw in haystack for kw in keywords):
                continue

            pub_date = self._parse_date(entry)
            if pub_date and pub_date < self.since:
                continue

            articles.append(RawArticle(
                id=self.url_id(url),
                title=title,
                url=url,
                source=config["source"],
                topic=config["topic"],
                published_at=pub_date,
                snippet=summary[:500],
                extra={"state": config["state"]},
            ))

        return articles

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        for field in ("published", "updated"):
            val = entry.get(field)
            if val:
                try:
                    return parsedate_to_datetime(val).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
        return None
