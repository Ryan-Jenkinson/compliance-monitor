"""Subject Matter Expert (SME) agent — one class, seven topic configurations.

Usage:
    # Single-turn (used by content auditor):
    agent = SMEAgent("PFAS")
    answer = agent.ask("Is the MN PRISM deadline still July 1, 2026?")

    # Interactive multi-turn chat (used by CLI):
    agent = SMEAgent("PFAS")
    agent.chat()
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from ai.claude_client import ClaudeClient
from ai.sme_knowledge import get_profile, list_topics

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"


class SMEAgent:
    def __init__(self, topic: str):
        self._profile = get_profile(topic)
        self._topic = self._profile["label"]
        self._model = self._profile["model"]
        self._client = ClaudeClient()

        # Build full system prompt = base + live DB context + recent article summaries
        db_context = self._load_db_context()
        article_context = self._load_article_summaries()

        self._system = (
            self._profile["system_prompt"]
            + "\n\n## Live Database Context (current as of today)\n\n"
            + db_context
            + "\n\n## Recent Article Intelligence (last "
            + str(self._profile["cache_lookback_days"])
            + " days)\n\n"
            + article_context
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(self, question: str) -> str:
        """Single-turn question/answer. Used by Content Auditor and programmatic callers."""
        return self._client.complete_multi_turn(
            messages=[{"role": "user", "content": question}],
            system=self._system,
            model=self._model,
            max_tokens=2048,
        )

    def chat(self) -> None:
        """Interactive multi-turn CLI loop. Type 'quit' or 'exit' to end, 'context' to show
        what DB and article data was loaded."""
        print(f"\n{'='*60}")
        print(f"  SME Agent: {self._topic}")
        print(f"  Model: {self._model}")
        print(f"  Type 'quit' to exit, 'context' to show loaded data")
        print(f"{'='*60}\n")

        messages: list[dict] = []

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[Session ended]")
                break

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                print("[Session ended]")
                break

            if user_input.lower() == "context":
                self._print_context_summary()
                continue

            messages.append({"role": "user", "content": user_input})

            try:
                response = self._client.complete_multi_turn(
                    messages=messages,
                    system=self._system,
                    model=self._model,
                    max_tokens=4096,
                )
                messages.append({"role": "assistant", "content": response})
                print(f"\nSME: {response}\n")
            except Exception as e:
                logger.error(f"SME chat error: {e}")
                print(f"\n[Error: {e}]\n")

    # ------------------------------------------------------------------
    # Internal context loading
    # ------------------------------------------------------------------

    def _load_db_context(self) -> str:
        """Execute DB queries and format results as readable context."""
        try:
            from subscribers.db import get_connection
            conn = get_connection()
            parts: list[str] = []

            for query in self._profile["db_context_queries"]:
                try:
                    rows = conn.execute(query).fetchall()
                    if not rows:
                        continue
                    # Use column names from cursor description
                    cols = [d[0] for d in conn.execute(query).description]
                    # Re-fetch with description
                    rows = conn.execute(query).fetchall()
                    if not rows:
                        continue
                    # Infer section label from query
                    label = self._infer_query_label(query)
                    parts.append(f"### {label} ({len(rows)} records)\n")
                    for row in rows:
                        row_dict = dict(zip(cols, row))
                        parts.append(self._format_row(row_dict))
                    parts.append("")
                except Exception as e:
                    logger.warning(f"SME DB query failed: {e}")

            conn.close()
            return "\n".join(parts) if parts else "(No DB records found)"
        except Exception as e:
            logger.warning(f"SME could not load DB context: {e}")
            return "(DB context unavailable)"

    def _load_article_summaries(self) -> str:
        """Load recent article summaries from the Claude cache directory."""
        lookback = self._profile["cache_lookback_days"]
        cache_dir = _CACHE_DIR / "claude"
        if not cache_dir.exists():
            return "(No article cache available)"

        today = date.today()
        cutoff = today - timedelta(days=lookback)
        parts: list[str] = []

        # Look for pipeline result files (not individual prompt caches)
        topic_key = self._infer_topic_key()
        found = 0

        for path in sorted(cache_dir.glob("*.json"), reverse=True):
            if found >= 10:  # cap at 10 cached results per SME
                break
            # Skip non-date-prefixed files
            stem = path.stem
            if len(stem) < 10 or stem[4] != "-" or stem[7] != "-":
                continue
            try:
                file_date = date.fromisoformat(stem[:10])
            except ValueError:
                continue
            if file_date < cutoff:
                continue

            try:
                data = json.loads(path.read_text())
                text = data.get("text", "")
                if not text or len(text) < 50:
                    continue
                # Only include if it's plausibly about this topic
                if topic_key.lower() not in text.lower():
                    continue
                # Truncate to reasonable length
                preview = text[:800].replace("\n", " ").strip()
                parts.append(f"- [{stem[:10]}] {preview}...\n")
                found += 1
            except Exception:
                continue

        return "\n".join(parts) if parts else f"(No recent {topic_key} articles cached)"

    def _infer_query_label(self, query: str) -> str:
        q = query.strip().lower()
        if "legiscan_bills" in q:
            return "Active Legislative Bills"
        if "regulatory_deadlines" in q:
            return "Upcoming Regulatory Deadlines"
        if "regulations" in q:
            return "Regulation Registry"
        return "Database Records"

    def _infer_topic_key(self) -> str:
        """Return the canonical topic name for cache search."""
        label = self._topic
        for key in list_topics():
            if key.lower() in label.lower():
                return key
        return label.split("&")[0].strip()

    def _format_row(self, row: dict) -> str:
        """Format a DB row dict as a compact readable string."""
        parts = []
        for k, v in row.items():
            if v is None or v == "":
                continue
            if k in ("url", "state_link", "source_url") and v:
                parts.append(f"{k}: {v}")
            elif len(str(v)) > 100:
                parts.append(f"{k}: {str(v)[:100]}...")
            else:
                parts.append(f"{k}: {v}")
        return "  " + " | ".join(parts)

    def _print_context_summary(self) -> None:
        total_chars = len(self._system)
        print(f"\n[Context loaded for {self._topic}]")
        print(f"  System prompt: {total_chars:,} characters")
        print(f"  DB queries configured: {len(self._profile['db_context_queries'])}")
        print(f"  Article lookback: {self._profile['cache_lookback_days']} days")
        print(f"  Model: {self._model}\n")
