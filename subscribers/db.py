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

-- Regulatory deadlines extracted by AI pipeline
CREATE TABLE IF NOT EXISTS regulatory_deadlines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT NOT NULL,
    title           TEXT NOT NULL,
    deadline_date   TEXT NOT NULL,  -- YYYY-MM-DD
    description     TEXT,
    jurisdiction    TEXT,           -- e.g. "Minnesota", "EU", "Federal"
    source_url      TEXT,
    urgency         TEXT,           -- HIGH/MEDIUM/LOW
    extracted_at    TEXT NOT NULL DEFAULT (datetime('now')),
    week_start      TEXT            -- which week's pipeline extracted this
);

-- 6-month article archive (full content, permanent storage)
CREATE TABLE IF NOT EXISTS articles (
    id          TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    source      TEXT,
    pub_date    TEXT,
    snippet     TEXT,
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    week_start  TEXT,
    is_new      INTEGER DEFAULT 1
);

-- Topic insights from historical analysis agent (weekly runs)
CREATE TABLE IF NOT EXISTS topic_insights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic         TEXT NOT NULL,
    period        TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    insights_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(topic, period, analysis_date)
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
    # Migration: add regulatory_deadlines table if it doesn't exist
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS regulatory_deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            deadline_date TEXT NOT NULL,
            description TEXT,
            jurisdiction TEXT,
            source_url TEXT,
            urgency TEXT,
            extracted_at TEXT NOT NULL DEFAULT (datetime('now')),
            week_start TEXT,
            UNIQUE(topic, title, deadline_date)
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add daily_snapshots and daily_changes tables
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_snapshots (
            snapshot_date TEXT PRIMARY KEY,
            total_articles INTEGER DEFAULT 0,
            high_count INTEGER DEFAULT 0,
            medium_count INTEGER DEFAULT 0,
            low_count INTEGER DEFAULT 0,
            topic_counts_json TEXT DEFAULT '{}',
            article_ids_json TEXT DEFAULT '[]',
            new_deadlines_count INTEGER DEFAULT 0,
            bill_changes_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            change_date TEXT NOT NULL,
            change_type TEXT NOT NULL,
            topic TEXT,
            description TEXT NOT NULL,
            detail_json TEXT DEFAULT '{}',
            severity TEXT DEFAULT 'normal',
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add dashboard_critiques table
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS dashboard_critiques (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            critique_date TEXT NOT NULL,
            what_works TEXT DEFAULT '',
            questions_raised TEXT DEFAULT '',
            missing_data TEXT DEFAULT '',
            actionable_suggestions TEXT DEFAULT '',
            verdict TEXT DEFAULT '',
            raw_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add site_audit_reports table
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS site_audit_reports (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_date       TEXT NOT NULL,
            audit_type       TEXT NOT NULL,
            summary_json     TEXT NOT NULL DEFAULT '{}',
            issues_count     INTEGER DEFAULT 0,
            critical_count   INTEGER DEFAULT 0,
            confidence_score REAL,
            report_path      TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(audit_date, audit_type)
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add deadline_analyses table
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS deadline_analyses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            deadline_id     INTEGER NOT NULL UNIQUE,
            analysis_json   TEXT NOT NULL DEFAULT '{}',
            model_used      TEXT DEFAULT 'claude-sonnet-4-6',
            analyzed_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add updated_at to regulatory_deadlines
    try:
        conn.execute("ALTER TABLE regulatory_deadlines ADD COLUMN updated_at TEXT")
        conn.commit()
    except Exception:
        pass  # Column already exists
    # Migration: add articles table
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT,
            pub_date TEXT,
            snippet TEXT,
            first_seen TEXT NOT NULL DEFAULT (datetime('now')),
            week_start TEXT,
            is_new INTEGER DEFAULT 1
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add topic_insights table
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS topic_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            period TEXT NOT NULL,
            analysis_date TEXT NOT NULL,
            insights_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(topic, period, analysis_date)
        )""")
        conn.commit()
    except Exception:
        pass
    # Migration: add bill_analyses table
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS bill_analyses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            state           TEXT NOT NULL,
            bill_number     TEXT NOT NULL,
            bill_id         INTEGER,
            trigger_action  TEXT,
            analysis_json   TEXT NOT NULL DEFAULT '{}',
            model_used      TEXT DEFAULT 'claude-sonnet-4-6',
            analyzed_at     TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(state, bill_number)
        )""")
        conn.commit()
    except Exception:
        pass
    conn.close()


def save_bill_analysis(state: str, bill_number: str, bill_id: int | None,
                       trigger_action: str | None, analysis: dict) -> None:
    """Insert or replace a bill analysis."""
    import json as _json
    conn = get_connection()
    conn.execute(
        """INSERT INTO bill_analyses
               (state, bill_number, bill_id, trigger_action, analysis_json, analyzed_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(state, bill_number) DO UPDATE SET
               bill_id = excluded.bill_id,
               trigger_action = excluded.trigger_action,
               analysis_json = excluded.analysis_json,
               analyzed_at = excluded.analyzed_at""",
        (state, bill_number, bill_id, trigger_action, _json.dumps(analysis)),
    )
    conn.commit()
    conn.close()


def get_bill_analysis(state: str, bill_number: str) -> dict | None:
    """Return the stored analysis for a bill, or None."""
    import json as _json
    conn = get_connection()
    row = conn.execute(
        "SELECT analysis_json FROM bill_analyses WHERE state=? AND bill_number=?",
        (state, bill_number),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return _json.loads(row["analysis_json"])
    except Exception:
        return None


def get_all_bill_analyses() -> dict:
    """Return all analyses keyed by '{state}_{bill_number}' (spaces replaced with _)."""
    import json as _json
    conn = get_connection()
    rows = conn.execute(
        "SELECT state, bill_number, analysis_json FROM bill_analyses"
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        key = f"{r['state']}_{r['bill_number'].replace(' ', '_')}"
        try:
            result[key] = _json.loads(r["analysis_json"])
        except Exception:
            pass
    return result


def save_deadline_analysis(deadline_id: int, analysis: dict) -> None:
    """Insert or replace a deadline analysis."""
    import json as _json
    conn = get_connection()
    conn.execute(
        """INSERT INTO deadline_analyses (deadline_id, analysis_json, analyzed_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(deadline_id) DO UPDATE SET
               analysis_json = excluded.analysis_json,
               analyzed_at = excluded.analyzed_at""",
        (deadline_id, _json.dumps(analysis)),
    )
    conn.commit()
    conn.close()


def get_deadline_analysis(deadline_id: int) -> dict | None:
    """Return the stored analysis for a deadline, or None."""
    import json as _json
    conn = get_connection()
    row = conn.execute(
        "SELECT analysis_json FROM deadline_analyses WHERE deadline_id=?",
        (deadline_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return _json.loads(row["analysis_json"])
    except Exception:
        return None


def get_all_deadline_analyses() -> dict:
    """Return all deadline analyses keyed by deadline_id (as string)."""
    import json as _json
    conn = get_connection()
    rows = conn.execute(
        "SELECT deadline_id, analysis_json FROM deadline_analyses"
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[str(r["deadline_id"])] = _json.loads(r["analysis_json"])
        except Exception:
            pass
    return result


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


def upsert_deadline(topic: str, title: str, deadline_date: str,
                    description: str, jurisdiction: str, source_url: str,
                    urgency: str, week_start: str) -> None:
    """Insert a new deadline or update fields if content changed.
    Sets updated_at only when an existing row's content actually changes.
    """
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, description, urgency, jurisdiction, source_url FROM regulatory_deadlines "
        "WHERE topic=? AND title=? AND deadline_date=?",
        (topic, title, deadline_date),
    ).fetchone()

    if existing:
        # Check if any meaningful field changed
        changed = (
            (description or "") != (existing["description"] or "")
            or (urgency or "") != (existing["urgency"] or "")
            or (jurisdiction or "") != (existing["jurisdiction"] or "")
            or (source_url or "") != (existing["source_url"] or "")
        )
        if changed:
            conn.execute(
                """UPDATE regulatory_deadlines
                   SET description=?, urgency=?, jurisdiction=?, source_url=?,
                       updated_at=datetime('now')
                   WHERE id=?""",
                (description, urgency, jurisdiction, source_url, existing["id"]),
            )
            conn.commit()
    else:
        conn.execute(
            """INSERT INTO regulatory_deadlines
                   (topic, title, deadline_date, description, jurisdiction,
                    source_url, urgency, week_start)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic, title, deadline_date, description, jurisdiction,
             source_url, urgency, week_start),
        )
        conn.commit()
    conn.close()


def upsert_regulation(topic: str, jurisdiction: str, regulation_name: str,
                      current_status: str, effective_date: str | None = None,
                      source_url: str | None = None) -> int:
    """Insert or update a regulation. Returns the regulation id."""
    conn = get_connection()
    # Check if it already exists
    row = conn.execute(
        """SELECT id FROM regulations
           WHERE topic = ? AND jurisdiction = ? AND regulation_name = ?""",
        (topic, jurisdiction, regulation_name)
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE regulations SET current_status = ?, effective_date = ?,
               source_url = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (current_status, effective_date, source_url, row["id"])
        )
        conn.commit()
        reg_id = row["id"]
    else:
        cursor = conn.execute(
            """INSERT INTO regulations
               (topic, jurisdiction, regulation_name, current_status, effective_date, source_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (topic, jurisdiction, regulation_name, current_status, effective_date, source_url)
        )
        conn.commit()
        reg_id = cursor.lastrowid
    conn.close()
    return reg_id


def add_regulation_event(regulation_id: int, event_type: str,
                         event_date: str | None = None, description: str | None = None,
                         source_url: str | None = None) -> None:
    """Add an event to a regulation. Skips if identical event already exists."""
    conn = get_connection()
    existing = conn.execute(
        """SELECT id FROM regulation_events
           WHERE regulation_id = ? AND event_type = ? AND event_date = ?""",
        (regulation_id, event_type, event_date)
    ).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO regulation_events
               (regulation_id, event_type, event_date, description, source_url)
               VALUES (?, ?, ?, ?, ?)""",
            (regulation_id, event_type, event_date, description, source_url)
        )
        conn.commit()
    conn.close()


def get_regulations(topic: str | None = None, jurisdiction: str | None = None) -> list[dict]:
    """Query regulations with optional filters."""
    conn = get_connection()
    query = "SELECT * FROM regulations WHERE 1=1"
    params = []
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if jurisdiction:
        query += " AND jurisdiction = ?"
        params.append(jurisdiction)
    query += " ORDER BY topic, jurisdiction, regulation_name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_regulation_events(regulation_id: int) -> list[dict]:
    """Get all events for a regulation, ordered by date."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM regulation_events
           WHERE regulation_id = ? ORDER BY event_date ASC""",
        (regulation_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_regulation_count() -> int:
    """Return total count of regulations in the registry."""
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM regulations").fetchone()[0]
    conn.close()
    return count


def get_upcoming_deadlines(days_ahead: int = 365) -> list[dict]:
    """Return deadlines from today through days_ahead, ordered by date."""
    from datetime import date, timedelta
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM regulatory_deadlines
           WHERE deadline_date >= ? AND deadline_date <= ?
           ORDER BY deadline_date ASC""",
        (today, cutoff)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


_STAGE_URGENCY = {
    "advanced": "HIGH",
    "passed_one": "HIGH",
    "enacted_watching": "HIGH",
    "rulemaking": "HIGH",
    "committee": "MEDIUM",
    "discussion": "MEDIUM",
    "introduced": "LOW",
    "pre_discussion": "LOW",
    "none": "LOW",
}


def get_bill_calendar_events(days_past: int = 30, days_ahead: int = 180) -> list[dict]:
    """Return legiscan bill action dates as deadline-like dicts for the calendar.

    Includes:
    - All bills with a future last_action_date (upcoming scheduled actions)
    - Bills in significant stages (committee+) with recent last_action_date

    Topics are lowercased to match the template's ``topic.topic|lower`` filter.
    ``days_until`` is pre-calculated so the timeline widget renders the items.
    """
    from datetime import date, timedelta
    today = date.today()
    past_cutoff = (today - timedelta(days=days_past)).isoformat()
    future_cutoff = (today + timedelta(days=days_ahead)).isoformat()
    today_str = today.isoformat()

    conn = get_connection()
    rows = conn.execute(
        """SELECT state, bill_number, title, last_action_date, last_action,
                  stage, topic, url, state_link, status_date, history_json
           FROM legiscan_bills
           WHERE (
               (last_action_date > ? AND last_action_date <= ?)
               OR
               (last_action_date >= ? AND last_action_date <= ?
                AND stage IN ('committee','passed_one','advanced','rulemaking','enacted_watching'))
           )
           AND stage != 'none'
           ORDER BY last_action_date ASC""",
        (today_str, future_cutoff, past_cutoff, today_str),
    ).fetchall()
    conn.close()

    import json as _json
    from datetime import date as _date

    results = []
    seen = set()  # dedupe (bill_id, date, action) tuples

    for r in rows:
        r = dict(r)
        stage = r.get("stage", "introduced")
        urgency = _STAGE_URGENCY.get(stage, "LOW")
        bill_label = f"{r['state']} {r['bill_number']}"
        title_short = (r.get("title") or "")[:60].rstrip()
        topic_lc = (r.get("topic") or "").lower()
        source_url = r.get("url") or r.get("state_link") or ""

        # Expand every history entry within the date window
        history = []
        try:
            history = _json.loads(r.get("history_json") or "[]")
        except Exception:
            pass

        for entry in history:
            h_date = (entry.get("date") or "").strip()
            h_action = (entry.get("action") or "").strip()
            if not h_date or not h_action:
                continue
            if h_date < past_cutoff or h_date > future_cutoff:
                continue
            key = (bill_label, h_date, h_action[:40])
            if key in seen:
                continue
            seen.add(key)
            try:
                d = _date.fromisoformat(h_date)
                days_until = (d - today).days
            except Exception:
                days_until = None
            is_future = h_date > today_str
            results.append({
                "topic": topic_lc,
                "title": f"{bill_label} — {h_action[:60]}",
                "deadline_date": h_date,
                "days_until": days_until,
                "description": (
                    f"{'Scheduled: ' if is_future else ''}{h_action} "
                    f"[{stage.replace('_',' ').title()} stage] {title_short}"
                ).strip(),
                "jurisdiction": r.get("state", ""),
                "source_url": source_url,
                "urgency": urgency,
                "is_bill_event": True,
            })

        # Always include last_action_date even if outside the history window
        action_date = r.get("last_action_date") or ""
        if action_date and past_cutoff <= action_date <= future_cutoff:
            action_desc = r.get("last_action") or ""
            key = (bill_label, action_date, action_desc[:40])
            if key not in seen:
                seen.add(key)
                try:
                    d = _date.fromisoformat(action_date)
                    days_until = (d - today).days
                except Exception:
                    days_until = None
                is_future = action_date > today_str
                results.append({
                    "topic": topic_lc,
                    "title": f"{bill_label} — {action_desc[:60]}",
                    "deadline_date": action_date,
                    "days_until": days_until,
                    "description": (
                        f"{'Scheduled: ' if is_future else ''}{action_desc} "
                        f"[{stage.replace('_',' ').title()} stage] {title_short}"
                    ).strip(),
                    "jurisdiction": r.get("state", ""),
                    "source_url": source_url,
                    "urgency": urgency,
                    "is_bill_event": True,
                })

    results.sort(key=lambda x: x["deadline_date"])
    return results


# ── Action outcome classification ──────────────────────────────────────────

def _classify_action(action: str) -> dict:
    """Classify a bill action text into a structured outcome type and display label."""
    a = action.lower()

    # Vote outcomes — most important
    if any(x in a for x in ("prevailed", "passed; ", "passed on ", "passed by", "do pass")):
        return {"outcome": "PASSED", "color": "#0A7C4B", "bg": "#F0FFF8"}
    if any(x in a for x in ("failed", "do not pass", "defeated", "tabled", "laid on table")):
        return {"outcome": "FAILED", "color": "#C0392B", "bg": "#FFF0F0"}
    if any(x in a for x in ("signed by governor", "signed by the governor", "chaptered", "enacted")):
        return {"outcome": "SIGNED", "color": "#1A5276", "bg": "#EBF5FF"}
    if "vetoed" in a:
        return {"outcome": "VETOED", "color": "#7D3C98", "bg": "#F9F0FF"}
    if any(x in a for x in ("passed house", "passed senate", "passed assembly", "passed chamber",
                              "concurred", "third reading", "third reading passed")):
        return {"outcome": "ADVANCED", "color": "#1E8449", "bg": "#F0FFF4"}
    if any(x in a for x in ("roll call", "voice vote", "division of the house", "recorded vote", "yeas", "nays")):
        return {"outcome": "VOTE", "color": "#784212", "bg": "#FEFAE0"}
    if any(x in a for x in ("public hearing", "hearing scheduled", "hearing set")):
        return {"outcome": "HEARING", "color": "#1F618D", "bg": "#EBF5FB"}
    if any(x in a for x in ("introduced", "first reading", "prefiled")):
        return {"outcome": "INTRODUCED", "color": "#717D7E", "bg": "#F8F9FA"}
    if any(x in a for x in ("referred to", "assigned to", "rereferred")):
        return {"outcome": "REFERRED", "color": "#717D7E", "bg": "#F8F9FA"}
    if any(x in a for x in ("amendment", "amended")):
        return {"outcome": "AMENDMENT", "color": "#9C640C", "bg": "#FEFAE0"}

    return {"outcome": "ACTION", "color": "#717D7E", "bg": "#F8F9FA"}


_HIGH_SIGNAL_OUTCOMES = {"PASSED", "FAILED", "SIGNED", "VETOED", "ADVANCED", "VOTE"}
_ALL_OUTCOMES = _HIGH_SIGNAL_OUTCOMES | {"HEARING", "AMENDMENT", "REFERRED", "INTRODUCED", "ACTION"}


def get_bill_activity_feed(days_past: int = 60, limit: int = 200) -> list[dict]:
    """Return structured legislative activity feed from LegiScan bill history.

    Returns one entry per bill action, classified by outcome type.
    Sorted newest-first. High-signal actions (votes, passage, signing) are
    flagged so the UI can surface them prominently.
    """
    from datetime import date, timedelta
    import json as _json

    today = date.today()
    past_cutoff = (today - timedelta(days=days_past)).isoformat()
    today_str = today.isoformat()

    conn = get_connection()
    rows = conn.execute(
        """SELECT state, bill_number, title, topic, url, state_link,
                  stage, last_action, last_action_date, history_json
           FROM legiscan_bills
           WHERE last_action_date >= ?
             AND stage != 'none'
           ORDER BY last_action_date DESC""",
        (past_cutoff,),
    ).fetchall()
    conn.close()

    results = []
    seen = set()

    for r in rows:
        r = dict(r)
        bill_label = f"{r['state']} {r['bill_number']}"
        topic_lc = (r.get("topic") or "").lower()
        source_url = r.get("url") or r.get("state_link") or ""
        bill_title = (r.get("title") or "")[:120]
        stage = r.get("stage", "")

        history = []
        try:
            history = _json.loads(r.get("history_json") or "[]")
        except Exception:
            pass

        for entry in sorted(history, key=lambda x: x.get("date", ""), reverse=True):
            h_date = (entry.get("date") or "").strip()
            h_action = (entry.get("action") or "").strip()
            if not h_date or not h_action or h_date < past_cutoff:
                continue
            key = (bill_label, h_date, h_action[:50])
            if key in seen:
                continue
            seen.add(key)

            classification = _classify_action(h_action)
            results.append({
                "bill": bill_label,
                "bill_title": bill_title,
                "topic": topic_lc,
                "state": r["state"],
                "date": h_date,
                "action": h_action,
                "stage": stage,
                "outcome": classification["outcome"],
                "outcome_color": classification["color"],
                "outcome_bg": classification["bg"],
                "is_high_signal": classification["outcome"] in _HIGH_SIGNAL_OUTCOMES,
                "source_url": source_url,
            })

    # Sort newest first, high-signal actions bubble up within same date
    results.sort(key=lambda x: (x["date"], x["is_high_signal"]), reverse=True)
    return results[:limit]


def save_article(article_id: str, topic: str, title: str, url: str,
                 source: str | None, pub_date: str | None, snippet: str | None,
                 week_start: str | None = None, is_new: bool = True) -> None:
    """Persist full article metadata. INSERT OR IGNORE so we never overwrite first_seen."""
    conn = get_connection()
    conn.execute(
        """INSERT OR IGNORE INTO articles
               (id, topic, title, url, source, pub_date, snippet, week_start, is_new)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (article_id, topic, title, url, source, pub_date, snippet, week_start, 1 if is_new else 0),
    )
    conn.commit()
    conn.close()


def get_articles_for_display(topic: str | None = None, days: int = 180, limit: int = 2000) -> list[dict]:
    """Return stored articles from the last `days` days, sorted by publish date newest first."""
    conn = get_connection()
    query = """SELECT id, topic, title, url, source, pub_date, snippet, first_seen, is_new,
                      COALESCE(pub_date, date(first_seen)) AS display_date
               FROM articles
               WHERE first_seen > datetime('now', ?)"""
    params: list = [f"-{days} days"]
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    query += " ORDER BY display_date DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_article_counts(months: int = 6) -> dict:
    """Return monthly article counts per topic over the last `months` months.
    Returns {months: ["Oct 2025", ...], by_topic: {PFAS: [5,3,...], ...}, total: [...]}.
    """
    from datetime import date, timedelta
    import calendar as _cal

    today = date.today()
    month_labels = []
    month_keys = []
    for i in range(months - 1, -1, -1):
        # Go back i months
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        label = date(y, m, 1).strftime("%b %Y")
        month_labels.append(label)
        month_keys.append((y, m))

    conn = get_connection()
    # Get all articles in range — use pub_date if available and not absurdly future,
    # fall back to first_seen. Cap pub_date at today+30d to filter scraper outliers.
    cutoff = date(month_keys[0][0], month_keys[0][1], 1).isoformat()
    rows = conn.execute(
        """SELECT topic,
                  CASE WHEN pub_date IS NOT NULL
                            AND pub_date <= date('now', '+30 days')
                            AND pub_date >= '2020-01-01'
                       THEN pub_date
                       ELSE date(first_seen)
                  END AS article_date
           FROM articles WHERE first_seen >= ?""",
        (cutoff,)
    ).fetchall()
    conn.close()

    from collections import defaultdict
    counts: dict = defaultdict(lambda: defaultdict(int))
    for r in rows:
        try:
            d = r["article_date"][:10]  # YYYY-MM-DD
            y, m = int(d[:4]), int(d[5:7])
            counts[(y, m)][r["topic"]] += 1
            counts[(y, m)]["_total"] += 1
        except Exception:
            pass

    topics = ["PFAS", "EPR", "REACH", "TSCA", "Prop65", "ConflictMinerals", "ForcedLabor"]
    by_topic = {t: [counts[mk].get(t, 0) for mk in month_keys] for t in topics}
    total = [counts[mk].get("_total", 0) for mk in month_keys]

    return {"months": month_labels, "by_topic": by_topic, "total": total}


def get_daily_article_counts(days: int = 30) -> dict:
    """Return daily article counts per topic over the last `days` days by publish date.
    Returns {days: ["2026-02-23", ...], by_topic: {PFAS: [3,1,...], ...}, total: [...]}.
    """
    from datetime import date, timedelta

    today = date.today()
    day_keys = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]

    conn = get_connection()
    rows = conn.execute(
        """SELECT topic,
                  CASE WHEN pub_date IS NOT NULL
                            AND pub_date <= date('now', '+30 days')
                            AND pub_date >= '2020-01-01'
                       THEN pub_date
                       ELSE date(first_seen)
                  END AS article_date
           FROM articles WHERE first_seen >= date('now', ?)""",
        (f"-{days} days",)
    ).fetchall()
    conn.close()

    from collections import defaultdict
    counts: dict = defaultdict(lambda: defaultdict(int))
    for r in rows:
        try:
            d = r["article_date"][:10]
            if d in day_keys:
                counts[d][r["topic"]] += 1
                counts[d]["_total"] += 1
        except Exception:
            pass

    topics = ["PFAS", "EPR", "REACH", "TSCA", "Prop65", "ConflictMinerals", "ForcedLabor"]
    by_topic = {t: [counts[dk].get(t, 0) for dk in day_keys] for t in topics}
    total = [counts[dk].get("_total", 0) for dk in day_keys]
    # Compact day labels: "Mar 24"
    day_labels = [
        (today - timedelta(days=days - 1 - i)).strftime("%-m/%-d")
        for i in range(days)
    ]

    return {"days": day_keys, "day_labels": day_labels, "by_topic": by_topic, "total": total}


def save_topic_insight(topic: str, period: str, analysis_date: str, insights: dict) -> None:
    """Save or replace a topic insight analysis."""
    import json as _json
    conn = get_connection()
    conn.execute(
        """INSERT INTO topic_insights (topic, period, analysis_date, insights_json)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(topic, period, analysis_date) DO UPDATE SET
               insights_json = excluded.insights_json,
               created_at = datetime('now')""",
        (topic, period, analysis_date, _json.dumps(insights))
    )
    conn.commit()
    conn.close()


def get_topic_insight(topic: str, period: str = "weekly") -> dict | None:
    """Return the most recent insight for a topic and period."""
    import json as _json
    conn = get_connection()
    row = conn.execute(
        """SELECT insights_json FROM topic_insights
           WHERE topic = ? AND period = ?
           ORDER BY analysis_date DESC LIMIT 1""",
        (topic, period)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return _json.loads(row["insights_json"])
    except Exception:
        return None


def get_all_topic_insights(period: str = "weekly") -> dict:
    """Return most recent insights for all topics keyed by topic name."""
    import json as _json
    conn = get_connection()
    rows = conn.execute(
        """SELECT topic, insights_json, analysis_date FROM topic_insights
           WHERE period = ?
           GROUP BY topic HAVING analysis_date = MAX(analysis_date)""",
        (period,)
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[r["topic"]] = _json.loads(r["insights_json"])
        except Exception:
            pass
    return result
