"""SQLite setup and migrations."""
from __future__ import annotations
import sqlite3
from pathlib import Path

from config.settings import Config

_SCHEMA = """
-- Phase 1: Subscriber management
CREATE TABLE IF NOT EXISTS subscribers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE,
    first_name  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
    conn.commit()
    conn.close()
