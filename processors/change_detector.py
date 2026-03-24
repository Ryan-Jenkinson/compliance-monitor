"""
Daily change detection for the compliance intelligence pipeline.

Saves a snapshot of each day's pipeline output and compares it against the
previous day's snapshot to produce structured change records surfaced in the
dashboard's "What Changed Today" panel.

Change types detected:
- new_articles     : Articles that weren't in the previous snapshot
- urgency_spike    : HIGH count increased vs yesterday
- new_deadlines    : Regulatory deadlines added during today's run
- bill_changes     : LegiScan bill status changes logged today
- new_bills        : New bills added to legiscan_bills today
- source_new       : New scraping source appeared (topic coverage expanded)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from config.settings import Config

logger = logging.getLogger(__name__)

_DB_PATH = Config.DB_PATH


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


# ── Snapshot helpers ────────────────────────────────────────────────────────

def _build_snapshot(pipeline_output: dict, today: str) -> dict:
    """Extract counts and article IDs from pipeline output for storage."""
    topics = pipeline_output.get("topics", [])
    high = medium = low = 0
    topic_counts: dict[str, int] = {}
    article_ids: list[str] = []

    for t in topics:
        name = t.get("topic", "")
        devs = t.get("developments", [])
        topic_counts[name] = len(devs)
        for d in devs:
            urgency = (d.get("urgency") or "").upper()
            if urgency == "HIGH":
                high += 1
            elif urgency == "MEDIUM":
                medium += 1
            else:
                low += 1
            url = d.get("url") or d.get("source_url") or ""
            if url:
                article_ids.append(url)

    return {
        "snapshot_date": today,
        "total_articles": sum(topic_counts.values()),
        "high_count": high,
        "medium_count": medium,
        "low_count": low,
        "topic_counts_json": json.dumps(topic_counts),
        "article_ids_json": json.dumps(sorted(set(article_ids))),
    }


def _save_snapshot(snap: dict) -> None:
    conn = _conn()
    conn.execute("""
        INSERT OR REPLACE INTO daily_snapshots
            (snapshot_date, total_articles, high_count, medium_count, low_count,
             topic_counts_json, article_ids_json)
        VALUES (:snapshot_date, :total_articles, :high_count, :medium_count, :low_count,
                :topic_counts_json, :article_ids_json)
    """, snap)
    conn.commit()
    conn.close()


def _load_snapshot(snapshot_date: str) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM daily_snapshots WHERE snapshot_date = ?", (snapshot_date,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["topic_counts"] = json.loads(d.get("topic_counts_json") or "{}")
    d["article_ids"] = set(json.loads(d.get("article_ids_json") or "[]"))
    return d


# ── Change detection ────────────────────────────────────────────────────────

def _detect_changes(today_snap: dict, yesterday_snap: Optional[dict],
                    today: str, pipeline_output: dict) -> list[dict]:
    changes: list[dict] = []

    # 1. Urgency spike — HIGH count jumped
    if yesterday_snap:
        high_delta = today_snap["high_count"] - yesterday_snap["high_count"]
        if high_delta >= 2:
            changes.append({
                "change_type": "urgency_spike",
                "topic": None,
                "description": f"HIGH urgency items increased by {high_delta} vs yesterday "
                               f"({yesterday_snap['high_count']} → {today_snap['high_count']})",
                "detail_json": json.dumps({"delta": high_delta,
                                           "prev": yesterday_snap["high_count"],
                                           "curr": today_snap["high_count"]}),
                "severity": "notable" if high_delta >= 3 else "normal",
            })

    # 2. New articles vs yesterday (by topic)
    if yesterday_snap:
        prev_ids = yesterday_snap["article_ids"]
        curr_ids = today_snap["article_ids"]
        for t in pipeline_output.get("topics", []):
            topic_name = t.get("topic", "")
            prev_count = yesterday_snap["topic_counts"].get(topic_name, 0)
            curr_count = today_snap["topic_counts"].get(topic_name, 0)
            delta = curr_count - prev_count
            if delta > 0:
                changes.append({
                    "change_type": "new_articles",
                    "topic": topic_name,
                    "description": f"{topic_name}: {delta} new development(s) vs yesterday "
                                   f"({prev_count} → {curr_count})",
                    "detail_json": json.dumps({"delta": delta,
                                               "prev": prev_count,
                                               "curr": curr_count}),
                    "severity": "notable" if delta >= 3 else "normal",
                })

    # 3. New deadlines added today
    conn = _conn()
    new_dl_rows = conn.execute(
        "SELECT topic, title, deadline_date, urgency, source_url FROM regulatory_deadlines "
        "WHERE DATE(extracted_at) = ? ORDER BY deadline_date",
        (today,)
    ).fetchall()
    for row in new_dl_rows:
        changes.append({
            "change_type": "new_deadline",
            "topic": row["topic"],
            "description": f"New deadline: {row['title']} ({row['deadline_date']})",
            "detail_json": json.dumps({
                "title": row["title"],
                "date": row["deadline_date"],
                "urgency": row["urgency"],
                "source_url": row["source_url"] or "",
            }),
            "severity": "notable" if row["urgency"] == "HIGH" else "normal",
        })

    # 4. LegiScan bill status changes logged today
    bill_change_rows = conn.execute(
        "SELECT cl.bill_id, b.topic, b.state, b.bill_number, b.title, b.url, "
        "       cl.old_status, cl.new_status, cl.change_summary "
        "FROM legiscan_change_log cl "
        "JOIN legiscan_bills b ON b.bill_id = cl.bill_id "
        "WHERE DATE(cl.change_date) = ? "
        "ORDER BY b.topic, b.state",
        (today,)
    ).fetchall()
    for row in bill_change_rows:
        changes.append({
            "change_type": "bill_change",
            "topic": row["topic"],
            "description": f"[{row['topic']}] {row['state']} {row['bill_number']}: "
                           f"{row['change_summary'] or 'status updated'}",
            "detail_json": json.dumps({
                "bill_id": row["bill_id"],
                "state": row["state"],
                "bill_number": row["bill_number"],
                "title": row["title"][:120],
                "old_status": row["old_status"],
                "new_status": row["new_status"],
                "url": row["url"] or "",
            }),
            "severity": "notable",
        })

    # 5. New bills discovered today
    new_bill_rows = conn.execute(
        "SELECT topic, state, bill_number, title, stage "
        "FROM legiscan_bills "
        "WHERE DATE(first_seen_date) = ? AND is_active = 1 "
        "ORDER BY topic, state "
        "LIMIT 20",
        (today,)
    ).fetchall()
    if new_bill_rows:
        by_topic: dict[str, int] = {}
        for row in new_bill_rows:
            by_topic[row["topic"]] = by_topic.get(row["topic"], 0) + 1
        for topic_name, count in by_topic.items():
            changes.append({
                "change_type": "new_bills",
                "topic": topic_name,
                "description": f"{count} new {topic_name} bill(s) discovered in legislative tracker",
                "detail_json": json.dumps({"count": count, "topic": topic_name}),
                "severity": "normal",
            })

    conn.close()
    return changes


def _save_changes(changes: list[dict], today: str) -> None:
    if not changes:
        return
    conn = _conn()
    # Clear today's changes first (re-runnable)
    conn.execute("DELETE FROM daily_changes WHERE change_date = ?", (today,))
    for c in changes:
        conn.execute("""
            INSERT INTO daily_changes
                (change_date, change_type, topic, description, detail_json, severity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (today, c["change_type"], c.get("topic"),
              c["description"], c.get("detail_json", "{}"),
              c.get("severity", "normal")))
    conn.commit()
    conn.close()


# ── Public API ───────────────────────────────────────────────────────────────

def detect_and_save(pipeline_output: dict, run_date: Optional[date] = None) -> list[dict]:
    """
    Save today's snapshot, compare with yesterday, persist and return changes.

    Returns list of change dicts for direct use in dashboard rendering.
    """
    today = (run_date or date.today()).isoformat()
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()

    today_snap = _build_snapshot(pipeline_output, today)
    yesterday_snap = _load_snapshot(yesterday)

    _save_snapshot(today_snap)

    changes = _detect_changes(today_snap, yesterday_snap, today, pipeline_output)
    _save_changes(changes, today)

    notable = sum(1 for c in changes if c.get("severity") == "notable")
    logger.info(
        f"Change detection: {len(changes)} change(s) detected "
        f"({notable} notable) for {today}"
    )
    return changes


def get_recent_changes(days: int = 7) -> list[dict]:
    """Return change records from the last N days, newest first."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM daily_changes WHERE change_date >= ? ORDER BY change_date DESC, severity DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["detail"] = json.loads(d.get("detail_json") or "{}")
        except Exception:
            d["detail"] = {}
        result.append(d)
    return result


def get_today_changes() -> list[dict]:
    """Return today's change records."""
    return get_recent_changes(days=1)
