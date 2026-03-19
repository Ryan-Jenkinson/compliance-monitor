#!/usr/bin/env python3.14
"""
Sync today's article URLs into a persistent NotebookLM notebook.

Called by run.py via subprocess after each successful run:
    python3.14 notebooklm/sync_sources.py <url1> <url2> ...

State is persisted in data/notebooklm_state.json so URLs are never re-added.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_STATE_PATH = _PROJECT_ROOT / "data" / "notebooklm_state.json"
_NOTEBOOK_TITLE = "Andersen Compliance Intelligence"
_STORAGE_PATH = Path.home() / ".notebooklm" / "storage_state.json"


def _load_state() -> dict:
    if _STATE_PATH.exists():
        return json.loads(_STATE_PATH.read_text())
    return {"notebook_id": None, "added_urls": []}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2))


async def _find_or_create_notebook(client) -> str:
    """Return the notebook ID, creating it if it doesn't exist yet."""
    notebooks = await client.notebooks.list()
    for nb in notebooks:
        if nb.title == _NOTEBOOK_TITLE:
            logger.info(f"Found existing notebook: {nb.id}")
            return nb.id

    logger.info(f"Creating new notebook: {_NOTEBOOK_TITLE}")
    nb = await client.notebooks.create(_NOTEBOOK_TITLE)
    logger.info(f"Created notebook: {nb.id}")
    return nb.id


async def _sync(urls: list[str]) -> None:
    from notebooklm import NotebookLMClient

    state = _load_state()
    already_added = set(state["added_urls"])
    new_urls = [u for u in urls if u not in already_added]

    if not new_urls:
        logger.info("No new URLs to add — all already in notebook.")
        return

    async with await NotebookLMClient.from_storage(str(_STORAGE_PATH)) as client:
        # Find or create the notebook
        if not state["notebook_id"]:
            state["notebook_id"] = await _find_or_create_notebook(client)
        else:
            # Verify notebook still exists
            try:
                await client.notebooks.get(state["notebook_id"])
            except Exception:
                logger.warning("Stored notebook ID not found — creating new one.")
                state["notebook_id"] = await _find_or_create_notebook(client)

        notebook_id = state["notebook_id"]
        logger.info(f"Syncing {len(new_urls)} new URLs into notebook {notebook_id}")

        # Add sources (don't wait — let NotebookLM process in background)
        successfully_added = []
        for url in new_urls:
            try:
                await client.sources.add_url(notebook_id, url, wait=False)
                successfully_added.append(url)
                logger.info(f"  Added: {url}")
            except Exception as e:
                logger.warning(f"  Failed to add {url}: {e}")

        # Persist state
        state["added_urls"] = list(already_added | set(successfully_added))
        state["last_sync"] = datetime.now().isoformat()
        _save_state(state)
        logger.info(f"Done. Added {len(successfully_added)}/{len(new_urls)} sources.")


def main() -> None:
    urls = sys.argv[1:]
    if not urls:
        logger.info("No URLs provided — nothing to sync.")
        return

    if not _STORAGE_PATH.exists():
        logger.error(f"NotebookLM not authenticated. Run: python3.14 -m notebooklm login")
        sys.exit(1)

    asyncio.run(_sync(urls))


if __name__ == "__main__":
    main()
