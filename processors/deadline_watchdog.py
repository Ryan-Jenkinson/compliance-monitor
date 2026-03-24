"""
Deadline Watchdog — threshold tracking and status for regulatory_deadlines.

Computes days-until, threshold bucket, and on-track/at-risk/overdue status
for every deadline. Surfaces critical items for the dashboard and change
detection pipeline.

Threshold buckets:
    overdue     deadline_date < today
    critical    1–14 days
    urgent      15–30 days
    warning     31–60 days
    watch       61–90 days
    upcoming    91+ days

Status labels (for display):
    OVERDUE     missed
    CRITICAL    ≤ 14 days — needs immediate action
    URGENT      ≤ 30 days — prepare now
    WARNING     ≤ 60 days — schedule review
    WATCH       ≤ 90 days — on radar
    OK          > 90 days — monitoring
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from config.settings import Config

logger = logging.getLogger(__name__)

_DB_PATH = Config.DB_PATH

# Threshold → (bucket_name, display_label, severity)
_THRESHOLDS = [
    (0,   "overdue",  "OVERDUE",  "critical"),
    (14,  "critical", "CRITICAL", "critical"),
    (30,  "urgent",   "URGENT",   "high"),
    (60,  "warning",  "WARNING",  "medium"),
    (90,  "watch",    "WATCH",    "low"),
]


def _classify(days_until: int) -> tuple[str, str, str]:
    """Return (bucket, label, severity) for a given days_until value."""
    if days_until < 0:
        return "overdue", "OVERDUE", "critical"
    for threshold, bucket, label, severity in _THRESHOLDS:
        if days_until <= threshold:
            return bucket, label, severity
    return "upcoming", "OK", "normal"


def enrich_deadlines(deadlines: list[dict], as_of: Optional[date] = None) -> list[dict]:
    """
    Add computed fields to a list of deadline dicts.

    Adds: days_until, bucket, watch_label, severity
    Returns the list sorted by deadline_date ascending.
    """
    today = as_of or date.today()
    enriched = []
    for dl in deadlines:
        dl = dict(dl)
        try:
            dl_date = date.fromisoformat(str(dl["deadline_date"])[:10])
            days = (dl_date - today).days
        except (KeyError, ValueError):
            days = 9999
        bucket, label, severity = _classify(days)
        dl["days_until"] = days
        dl["bucket"] = bucket
        dl["watch_label"] = label
        dl["severity"] = severity
        enriched.append(dl)
    enriched.sort(key=lambda x: x["days_until"])
    return enriched


def deduplicate_db() -> int:
    """
    Remove duplicate rows from regulatory_deadlines, keeping the latest entry
    per (topic, title, deadline_date). Returns count of rows removed.
    """
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    # Find all groups with duplicates, keep MAX(id)
    conn.execute("""
        DELETE FROM regulatory_deadlines
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM regulatory_deadlines
            GROUP BY topic, title, deadline_date
        )
    """)
    removed = conn.total_changes
    conn.commit()
    conn.close()
    if removed:
        logger.info(f"Deadline dedup: removed {removed} duplicate rows")
    return removed


def get_watchdog_summary(as_of: Optional[date] = None) -> dict:
    """
    Return a summary dict of deadlines by threshold bucket.

    {
        "by_bucket": {"overdue": [...], "critical": [...], ...},
        "counts": {"overdue": 0, "critical": 2, ...},
        "next_deadline": {deadline dict} or None,
        "critical_count": int,
    }
    """
    from subscribers.db import get_upcoming_deadlines
    today = as_of or date.today()

    # Fetch all deadlines (next 3 years)
    all_deadlines = get_upcoming_deadlines(days_ahead=1095)
    enriched = enrich_deadlines(all_deadlines, as_of=today)

    by_bucket: dict[str, list] = {
        "overdue": [], "critical": [], "urgent": [],
        "warning": [], "watch": [], "upcoming": [],
    }
    for dl in enriched:
        bucket = dl.get("bucket", "upcoming")
        by_bucket.setdefault(bucket, []).append(dl)

    counts = {k: len(v) for k, v in by_bucket.items()}
    critical_count = counts["overdue"] + counts["critical"] + counts["urgent"]

    next_dl = enriched[0] if enriched else None

    return {
        "by_bucket": by_bucket,
        "counts": counts,
        "next_deadline": next_dl,
        "critical_count": critical_count,
        "total": len(enriched),
        "enriched": enriched,
    }


def get_threshold_alerts(as_of: Optional[date] = None) -> list[dict]:
    """
    Return list of deadlines that have crossed a threshold boundary today
    (useful for daily change detection / alerting).

    A boundary crossing is defined as: days_until ∈ {90, 60, 30, 14, 7, 0}
    """
    today = as_of or date.today()
    alert_days = {90, 60, 30, 14, 7, 0}

    from subscribers.db import get_upcoming_deadlines
    deadlines = get_upcoming_deadlines(days_ahead=95)
    enriched = enrich_deadlines(deadlines, as_of=today)

    alerts = []
    for dl in enriched:
        if dl["days_until"] in alert_days:
            alerts.append(dl)
    return alerts


def run_watchdog(as_of: Optional[date] = None) -> dict:
    """
    Full watchdog run: deduplicate DB, compute summary, log critical items.
    Returns the summary dict from get_watchdog_summary().
    """
    deduplicate_db()
    summary = get_watchdog_summary(as_of=as_of)
    counts = summary["counts"]

    logger.info(
        f"Deadline Watchdog: {summary['total']} deadlines | "
        f"overdue={counts['overdue']} critical={counts['critical']} "
        f"urgent={counts['urgent']} warning={counts['warning']}"
    )

    # Log each critical/urgent item
    for dl in summary["by_bucket"].get("overdue", []):
        logger.warning(f"  OVERDUE [{dl['topic']}]: {dl['title']} ({dl['deadline_date']})")
    for dl in summary["by_bucket"].get("critical", []):
        logger.warning(f"  CRITICAL [{dl['topic']}]: {dl['title']} ({dl['deadline_date']}, "
                       f"{dl['days_until']}d)")
    for dl in summary["by_bucket"].get("urgent", []):
        logger.info(f"  URGENT [{dl['topic']}]: {dl['title']} ({dl['deadline_date']}, "
                    f"{dl['days_until']}d)")

    return summary
