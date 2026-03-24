"""
Weekly article window tracking (Sat–Fri) stored in SQLite.

Replaces the JSON-based rolling window. Each week runs Saturday through Friday.
Monday's run includes any articles from the preceding Saturday and Sunday.
Articles from prior weeks never carry over.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from subscribers.db import get_connection


def get_week_start(d: Optional[date] = None) -> date:
    """Return the most recent Saturday on or before d (the week's start date).

    weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    days_since_saturday: Sat→0, Sun→1, Mon→2, Tue→3, Wed→4, Thu→5, Fri→6
    """
    d = d or date.today()
    days_since_saturday = (d.weekday() - 5) % 7
    return d - timedelta(days=days_since_saturday)


def get_week_end(week_start: date) -> date:
    """Return the Friday that ends the week (week_start + 6 days)."""
    return week_start + timedelta(days=6)


def get_week_label(week_start: date) -> str:
    """Return a human-readable label like 'Mar 22 – 28' or 'Mar 29 – Apr 4'."""
    week_end = get_week_end(week_start)
    if week_start.month == week_end.month:
        return f"{week_start.strftime('%b %-d')} – {week_end.day}"
    return f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d')}"


def get_week_context(d: Optional[date] = None) -> dict:
    """Return all week-related context needed by the AI pipeline and renderer."""
    d = d or date.today()
    week_start = get_week_start(d)
    week_end = get_week_end(week_start)
    return {
        "today": d.isoformat(),
        "today_name": d.strftime("%A"),          # "Monday"
        "week_start": week_start.isoformat(),    # "2026-03-21"
        "week_end": week_end.isoformat(),        # "2026-03-27"
        "week_label": get_week_label(week_start),  # "Mar 21 – 27"
        "week_start_long": week_start.strftime("%B %-d, %Y"),  # "March 21, 2026"
        "week_end_long": week_end.strftime("%B %-d, %Y"),      # "March 27, 2026"
        "is_friday": d.weekday() == 4,
        "is_monday": d.weekday() == 0,
        "year": str(d.year),
    }


ROLLING_DAYS = 39  # Dashboard and pipeline window


def apply_weekly_window(articles: list) -> tuple[list, int, int]:
    """
    Mark articles as new or carried-over within a rolling 39-day window.

    New articles are recorded in the DB (still tagged with week_start for
    archiving). Articles older than 39 days are not carried over.

    Returns:
        (filtered_articles, new_count, carried_count)
    """
    week_start = get_week_start()
    week_start_str = week_start.isoformat()
    conn = get_connection()

    # Load article IDs seen in the last 39 days (rolling window)
    rows = conn.execute(
        "SELECT article_id, first_seen FROM weekly_articles "
        "WHERE first_seen > datetime('now', ?)",
        (f"-{ROLLING_DAYS} days",),
    ).fetchall()
    seen_this_week: dict[str, str] = {r["article_id"]: r["first_seen"] for r in rows}

    result = []
    new_ids: list[tuple] = []
    new_count = 0
    carried_count = 0

    for article in articles:
        if article.id in seen_this_week:
            first_seen_str = seen_this_week[article.id]
            first_seen = datetime.fromisoformat(first_seen_str)
            article.extra["is_new"] = False
            article.extra["days_in_newsletter"] = (datetime.now() - first_seen).days
            carried_count += 1
        else:
            article.extra["is_new"] = True
            article.extra["days_in_newsletter"] = 0
            now_str = datetime.now().isoformat()
            new_ids.append((article.id, week_start_str, now_str, article.topic))
            seen_this_week[article.id] = now_str
            new_count += 1
        result.append(article)

    if new_ids:
        conn.executemany(
            "INSERT OR IGNORE INTO weekly_articles "
            "(article_id, week_start, first_seen, topic) VALUES (?, ?, ?, ?)",
            new_ids,
        )
        conn.commit()

    conn.close()
    return result, new_count, carried_count


def last_week_is_archived() -> bool:
    """Check if the previous week has an archive entry (used on Mondays)."""
    today = date.today()
    current_week_start = get_week_start(today)
    prev_week_start = current_week_start - timedelta(days=7)
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM archive_weeks WHERE week_start = ?",
        (prev_week_start.isoformat(),),
    ).fetchone()
    conn.close()
    return row is not None
