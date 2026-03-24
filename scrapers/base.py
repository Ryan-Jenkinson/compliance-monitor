"""Abstract base class for all scrapers."""
from __future__ import annotations
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from config.settings import Config
from processors.article import RawArticle

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    All scrapers inherit from this class.

    Subclasses must implement `fetch()` which returns a list of RawArticles.
    Caching is handled here: results are saved to data/cache/<name>_<date>.json
    and reused within CACHE_TTL_HOURS.
    """

    name: str = "base"  # Override in subclass

    def __init__(self, lookback_hours: int = 936):  # 39 days
        self.lookback_hours = lookback_hours
        self.since = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)

    @abstractmethod
    def fetch(self) -> List[RawArticle]:
        """Fetch and return raw articles. Must be implemented by subclass."""
        ...

    def scrape(self) -> List[RawArticle]:
        """Public entry point. Returns cached results if available."""
        cache_path = self._cache_path()
        if cache_path.exists() and self._cache_valid(cache_path):
            logger.info(f"[{self.name}] Loading from cache: {cache_path}")
            return self._load_cache(cache_path)

        logger.info(f"[{self.name}] Fetching live data…")
        articles = self.fetch()
        self._save_cache(cache_path, articles)
        logger.info(f"[{self.name}] Fetched {len(articles)} articles")
        return articles

    # --- Cache helpers ---

    def _cache_path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return Config.CACHE_DIR / f"{self.name}_{date_str}.json"

    def _cache_valid(self, path: Path) -> bool:
        age_hours = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
        return age_hours < Config.CACHE_TTL_HOURS

    def _save_cache(self, path: Path, articles: List[RawArticle]) -> None:
        data = []
        for a in articles:
            d = a.__dict__.copy()
            if isinstance(d.get("published_at"), datetime):
                d["published_at"] = d["published_at"].isoformat()
            data.append(d)
        path.write_text(json.dumps(data, indent=2))

    def _load_cache(self, path: Path) -> List[RawArticle]:
        data = json.loads(path.read_text())
        articles = []
        for d in data:
            if d.get("published_at"):
                d["published_at"] = datetime.fromisoformat(d["published_at"])
            articles.append(RawArticle(**d))
        return articles

    @staticmethod
    def url_id(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]
