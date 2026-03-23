"""SQLite setup and migrations."""
from __future__ import annotations
import sqlite3
from pathlib import Path

from config.settings import Config

_SCHEMA = """
-- Phase 1: Subscriber management
CREATE TABLE IF NOT EXISTS subscribers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    first_name      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    scheduled_only  INTEGER NOT NULL DEFAULT 0,  -- 1 = skip during --force test sends
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS topic_preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    topic_name      TEXT NOT NULL,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(subscriber_id, topic_name)
);

CREATE TABLE IF NOT EXISTS send_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    sent_at         TEXT NOT NULL DEFAULT (datetime('now')),
    status          TEXT NOT NULL,   -- 'success' | 'failure'
    error_message   TEXT
);

-- Phase 2: Regulation state (designed now, populated later)
CREATE TABLE IF NOT EXISTS regulations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic               TEXT NOT NULL,
    jurisdiction        TEXT NOT NULL,
    regulation_name     TEXT NOT NULL,
    current_status      TEXT,
    effective_date      TEXT,
    source_url          TEXT,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS regulation_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    regulation_id   INTEGER NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    event_date      TEXT,
    description     TEXT,
    source_url      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Phase 3: Weekly article tracking (Sat–Fri window, replaces sent_articles.json)
CREATE TABLE IF NOT EXISTS weekly_articles (
    article_id    TEXT NOT NULL,
    week_start    TEXT NOT NULL,  -- YYYY-MM-DD (the Saturday that starts the week)
    first_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    topic         TEXT,
    PRIMARY KEY (article_id, week_start)
);

-- Phase 3: Archive index (one row per archived Friday end-of-week briefing)
CREATE TABLE IF NOT EXISTS archive_weeks (
    week_start           TEXT PRIMARY KEY,  -- YYYY-MM-DD (Saturday)
    week_end             TEXT NOT NULL,     -- YYYY-MM-DD (Friday)
    label                TEXT NOT NULL,     -- e.g. "Mar 22 – 28"
    year                 TEXT NOT NULL,
    newsletter_url       TEXT,
    weekly_briefing_url  TEXT,
    archived_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- PowerBI export view
CREATE VIEW IF NOT EXISTS powerbi_export AS
SELECT
    r.topic,
    r.jurisdiction,
    r.regulation_name,
    r.current_status,
    r.effective_date,
    e.event_type,
    e.event_date,
    e.description,
    e.source_url,
    r.updated_at
FROM regulations r
LEFT JOIN regulation_events e ON e.regulation_id = r.id
ORDER BY r.topic, r.jurisdiction, e.event_date DESC;
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(Config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = get_connection()
    conn.executescript(_SCHEMA)
    # Migration: add scheduled_only column if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE subscribers ADD COLUMN scheduled_only INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # Column already exists
    conn.close()


def get_archive_weeks() -> list[dict]:
    """Return all archived weeks ordered by week_start descending."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM archive_weeks ORDER BY week_start DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_archive_week(week_start: str, week_end: str, label: str, year: str,
                      newsletter_url: str | None, weekly_briefing_url: str | None) -> None:
    """Insert or replace an archive week entry."""
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO archive_weeks
           (week_start, week_end, label, year, newsletter_url, weekly_briefing_url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (week_start, week_end, label, year, newsletter_url, weekly_briefing_url),
    )
    conn.commit()
    conn.close()
