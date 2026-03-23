#!/usr/bin/env python3.14
"""
Sync weekly compliance briefing into the persistent NotebookLM notebook.

Called by run.py on Fridays after a successful end-of-week run:
    python3.14 notebooklm/sync_sources.py --weekly-url <url> [--digest <text>]

Strategy (avoids the 50-source limit):
  1. Add the weekly briefing URL as a new source (1 per week, ~1 year before limit)
  2. Replace the rolling "historical digest" text source with an updated version
     covering all prior weeks — so full history lives in just 1 source slot

State is persisted in data/notebooklm_state.json.
"""
import argparse
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
_NOTEBOOK_TITLE = "Compliance Intelligence"
_STORAGE_PATH = Path.home() / ".notebooklm" / "storage_state.json"


def _load_state() -> dict:
    if _STATE_PATH.exists():
        s = json.loads(_STATE_PATH.read_text())
        # Migrate old format (added_urls list → weekly_urls list)
        if "added_urls" in s and "weekly_urls" not in s:
            s["weekly_urls"] = s.pop("added_urls")
            s.setdefault("digest_source_id", None)
        return s
    return {"notebook_id": None, "weekly_urls": [], "digest_source_id": None}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2))


async def _find_or_create_notebook(client) -> str:
    notebooks = await client.notebooks.list()
    for nb in notebooks:
        if nb.title == _NOTEBOOK_TITLE:
            logger.info(f"Found existing notebook: {nb.id}")
            return nb.id
    logger.info(f"Creating new notebook: {_NOTEBOOK_TITLE}")
    nb = await client.notebooks.create(_NOTEBOOK_TITLE)
    return nb.id


async def _sync(weekly_url: str | None, digest_text: str | None) -> None:
    from notebooklm import NotebookLMClient

    state = _load_state()

    async with await NotebookLMClient.from_storage(str(_STORAGE_PATH)) as client:
        # Find or verify notebook
        if not state["notebook_id"]:
            state["notebook_id"] = await _find_or_create_notebook(client)
        else:
            try:
                await client.notebooks.get(state["notebook_id"])
            except Exception:
                logger.warning("Stored notebook ID not found — creating new one.")
                state["notebook_id"] = await _find_or_create_notebook(client)

        notebook_id = state["notebook_id"]
        already_added = set(state["weekly_urls"])

        # 1. Add this week's briefing URL (if new)
        if weekly_url and weekly_url not in already_added:
            try:
                await client.sources.add_url(notebook_id, weekly_url, wait=False)
                state["weekly_urls"].append(weekly_url)
                logger.info(f"Added weekly briefing: {weekly_url}")
            except Exception as e:
                logger.warning(f"Failed to add weekly URL: {e}")

        # 2. Replace historical digest document
        if digest_text:
            # Remove old digest source if we have its ID
            if state.get("digest_source_id"):
                try:
                    await client.sources.delete(notebook_id, state["digest_source_id"])
                    logger.info("Removed old historical digest source.")
                except Exception as e:
                    logger.warning(f"Could not remove old digest (may already be gone): {e}")
                state["digest_source_id"] = None

            # Add updated digest as a text source
            try:
                source = await client.sources.add_text(
                    notebook_id,
                    title="Historical Compliance Digest",
                    content=digest_text,
                )
                state["digest_source_id"] = source.id
                logger.info(f"Uploaded historical digest (source {source.id})")
            except Exception as e:
                logger.warning(f"Failed to upload digest: {e}")

        state["last_sync"] = datetime.now().isoformat()
        _save_state(state)
        logger.info("NotebookLM sync complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync weekly briefing to NotebookLM")
    parser.add_argument("--weekly-url", help="URL of this week's archived briefing page")
    parser.add_argument("--digest", help="Historical digest text to upload/replace")
    args = parser.parse_args()

    if not args.weekly_url and not args.digest:
        logger.info("Nothing to sync — pass --weekly-url and/or --digest.")
        return

    if not _STORAGE_PATH.exists():
        logger.error("NotebookLM not authenticated. Run: python3.14 -m notebooklm login")
        sys.exit(1)

    asyncio.run(_sync(weekly_url=args.weekly_url, digest_text=args.digest))


if __name__ == "__main__":
    main()
