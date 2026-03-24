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

        # Use streaming for large requests to avoid timeout
        if max_tokens > 8192:
            text = ""
            with self._client.messages.stream(**kwargs) as stream:
                for chunk in stream.text_stream:
                    text += chunk
        else:
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

    def complete_multi_turn(
        self,
        messages: list[dict],
        system: str = "",
        model: str = _SONNET,
        max_tokens: int = 4096,
    ) -> str:
        """Multi-turn conversation. messages = [{"role":"user","content":"..."},...]
        No caching (conversations are unique). Used by SME chat."""
        kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        return response.content[0].text

    def complete_haiku_vision(
        self,
        prompt: str,
        image_data: bytes,
        system: str = "",
        cache_key: str | None = None,
        media_type: str = "image/png",
    ) -> str:
        """Send image + text to Haiku. Used by visual auditor for screenshot analysis."""
        import base64
        if cache_key:
            cached = self._load_cache(cache_key)
            if cached is not None:
                logger.debug(f"Claude vision cache hit: {cache_key}")
                return cached

        image_b64 = base64.standard_b64encode(image_data).decode("utf-8")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        kwargs: dict = dict(model=_HAIKU, max_tokens=2048, messages=messages)
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        text = response.content[0].text

        if cache_key:
            self._save_cache(cache_key, text)
        return text

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
