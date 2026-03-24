"""Keyword pre-filter — cheap fast pass before Claude API calls."""
from __future__ import annotations
import re
from typing import List
import yaml
from pathlib import Path
from .article import RawArticle

_TOPICS_PATH = Path(__file__).parent.parent / "config" / "topics.yaml"


def _load_keywords() -> dict[str, list[str]]:
    with open(_TOPICS_PATH) as f:
        data = yaml.safe_load(f)
    return {t["name"]: [kw.lower() for kw in t["keywords"]] for t in data["topics"]}


_KEYWORDS = _load_keywords()


def keyword_filter(articles: List[RawArticle]) -> List[RawArticle]:
    """
    Keep articles where title or snippet contains at least one keyword
    for the article's assigned topic.

    Articles from topic-specific scrapers (Prop65, ConflictMinerals, ForcedLabor)
    bypass the keyword check — their content is pre-classified by the scraper.
    """
    # These scrapers already guarantee topic relevance; their content often lacks
    # the keyword terms (e.g. CA AG 60-day notice filings, SEC Form SD numbers).
    _TRUSTED_TOPICS = {"Prop65", "ConflictMinerals", "ForcedLabor"}

    result = []
    for article in articles:
        if article.topic in _TRUSTED_TOPICS:
            result.append(article)
            continue
        keywords = _KEYWORDS.get(article.topic, [])
        haystack = (article.title + " " + article.snippet).lower()
        if any(kw in haystack for kw in keywords):
            result.append(article)
    return result
