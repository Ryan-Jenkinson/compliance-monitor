"""Remove cross-source duplicate articles by URL and title similarity."""
from __future__ import annotations
import re
from typing import List
from .article import RawArticle


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def deduplicate(articles: List[RawArticle]) -> List[RawArticle]:
    """
    Remove duplicates from a list of articles.

    Deduplication strategy:
    1. Exact URL match (keep first seen)
    2. Normalized title similarity — if two titles share >= 80% of tokens, keep first seen
    """
    seen_urls: set[str] = set()
    seen_title_tokens: list[frozenset] = []
    result: list[RawArticle] = []

    for article in articles:
        # URL dedup
        if article.url in seen_urls:
            continue

        # Title token dedup (catches rewrites of same story across sources)
        tokens = frozenset(_normalize(article.title).split())
        is_dup = False
        for existing_tokens in seen_title_tokens:
            if not tokens or not existing_tokens:
                continue
            overlap = len(tokens & existing_tokens) / len(tokens | existing_tokens)
            if overlap >= 0.80:
                is_dup = True
                break

        if is_dup:
            continue

        seen_urls.add(article.url)
        seen_title_tokens.append(tokens)
        result.append(article)

    return result
