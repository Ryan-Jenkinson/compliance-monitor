"""Federal Register REST API scraper — covers all topics."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List

import requests
import yaml
from pathlib import Path

from .base import BaseScraper
from processors.article import RawArticle

logger = logging.getLogger(__name__)

_TOPICS_PATH = Path(__file__).parent.parent / "config" / "topics.yaml"
_API_BASE = "https://www.federalregister.gov/api/v1/documents.json"


def _load_topic_terms() -> dict[str, list[str]]:
    with open(_TOPICS_PATH) as f:
        data = yaml.safe_load(f)
    return {
        t["name"]: t.get("federal_register_terms", [])
        for t in data["topics"]
    }


class FederalRegisterScraper(BaseScraper):
    name = "federal_register"

    def fetch(self) -> List[RawArticle]:
        topic_terms = _load_topic_terms()
        articles: list[RawArticle] = []

        since_str = self.since.strftime("%Y-%m-%d")

        for topic, terms in topic_terms.items():
            if not terms:
                continue
            for term in terms:
                try:
                    results = self._query(term, since_str)
                    for item in results:
                        article = self._to_article(item, topic)
                        if article:
                            articles.append(article)
                except Exception as e:
                    logger.warning(f"[federal_register] Error fetching '{term}': {e}")

        # Deduplicate within this scraper by URL
        seen = set()
        unique = []
        for a in articles:
            if a.url not in seen:
                seen.add(a.url)
                unique.append(a)
        return unique

    def _query(self, term: str, since: str) -> list[dict]:
        params = {
            "conditions[term]": term,
            "conditions[publication_date][gte]": since,
            "fields[]": ["document_number", "title", "abstract", "html_url",
                         "publication_date", "type", "agencies"],
            "per_page": 20,
            "order": "newest",
        }
        resp = requests.get(_API_BASE, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _to_article(self, item: dict, topic: str) -> RawArticle | None:
        url = item.get("html_url", "")
        if not url:
            return None

        pub_date = None
        if item.get("publication_date"):
            try:
                pub_date = datetime.strptime(item["publication_date"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass

        agencies = ", ".join(
            a.get("name", "") for a in (item.get("agencies") or [])
        )

        return RawArticle(
            id=self.url_id(url),
            title=item.get("title", "Untitled"),
            url=url,
            source="Federal Register",
            topic=topic,
            published_at=pub_date,
            snippet=(item.get("abstract") or "")[:500],
            extra={
                "document_number": item.get("document_number"),
                "type": item.get("type"),
                "agencies": agencies,
            },
        )
