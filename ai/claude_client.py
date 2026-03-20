"""Anthropic SDK wrapper with per-run-date caching."""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic

from config.settings import Config

logger = logging.getLogger(__name__)

_HAIKU = "claude-haiku-4-5-20251001"  # claude-haiku-4-5
_SONNET = "claude-sonnet-4-6"


class ClaudeClient:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=Config.anthropic_api_key())
        self._cache_dir = Config.CACHE_DIR / "claude"
        self._cache_dir.mkdir(exist_ok=True)

    def complete(
        self,
        prompt: str,
        system: str = "",
        model: str = _SONNET,
        max_tokens: int = 4096,
        cache_key: str | None = None,
    ) -> str:
        """
        Call Claude and return the text response.
        Results are cached by (cache_key, run date) if cache_key is provided.
        """
        if cache_key:
            cached = self._load_cache(cache_key)
            if cached is not None:
                logger.debug(f"Claude cache hit: {cache_key}")
                return cached

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        text = response.content[0].text

        if cache_key:
            self._save_cache(cache_key, text)

        return text

    def complete_haiku(self, prompt: str, system: str = "", cache_key: str | None = None) -> str:
        return self.complete(prompt, system=system, model=_HAIKU,
                             max_tokens=2048, cache_key=cache_key)

    def complete_sonnet(self, prompt: str, system: str = "", cache_key: str | None = None) -> str:
        return self.complete(prompt, system=system, model=_SONNET,
                             max_tokens=8096, cache_key=cache_key)

    def _cache_path(self, key: str) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_key = hashlib.md5(key.encode()).hexdigest()[:12]
        return self._cache_dir / f"{date_str}_{safe_key}.json"

    def _load_cache(self, key: str) -> str | None:
        path = self._cache_path(key)
        if path.exists():
            try:
                return json.loads(path.read_text())["text"]
            except Exception:
                return None
        return None

    def _save_cache(self, key: str, text: str) -> None:
        path = self._cache_path(key)
        path.write_text(json.dumps({"text": text}))
