"""
LegiScan PFAS Bill Tracker — structured bill monitoring with change detection.

Searches for PFAS-related bills across all US states, tracks them in SQLite,
detects week-over-week changes, and produces structured data for the
legislative intelligence pipeline.

Usage:
    from scrapers.legiscan_tracker import LegiScanTracker
    tracker = LegiScanTracker()
    report = tracker.run()
    # report = { "new_bills": [...], "changed_bills": [...], "all_active": [...] }
"""
from __future__ import annotations
import json
import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from config.settings import Config
from scrapers.legiscan_client import LegiScanClient, LegiScanError, STATUS_LABELS

logger = logging.getLogger(__name__)

_DB_PATH = Config.DB_PATH

# PFAS-related search queries — cast a wide net
_SEARCH_QUERIES = [
    'PFAS OR "per- and polyfluoroalkyl"',
    '"forever chemicals" OR perfluoro',
    'PFAS AND (ban OR restriction OR prohibition)',
    'PFAS AND (product OR packaging OR textile OR apparel OR cookware)',
    'PFAS AND (firefighting OR foam OR AFFF)',
    'PFAS AND (reporting OR disclosure OR transparency)',
    'fluoropolymer OR fluorochemical',
]

# Map LegiScan status codes to our pipeline stages
_STATUS_TO_STAGE = {
    1: "introduced",     # Introduced
    2: "passed_one",     # Engrossed (passed originating chamber)
    3: "advanced",       # Enrolled (passed both chambers, heading to governor)
    4: "enacted_watching",  # Passed/signed
    5: "none",           # Vetoed
    6: "none",           # Failed/Dead
}


def _init_db(conn: sqlite3.Connection):
    """Create the legiscan_bills table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS legiscan_bills (
            bill_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            bill_number TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status INTEGER DEFAULT 0,
            status_label TEXT DEFAULT '',
            status_date TEXT DEFAULT '',
            change_hash TEXT DEFAULT '',
            last_action TEXT DEFAULT '',
            last_action_date TEXT DEFAULT '',
            url TEXT DEFAULT '',
            state_link TEXT DEFAULT '',
            sponsors_json TEXT DEFAULT '[]',
            history_json TEXT DEFAULT '[]',
            committee_name TEXT DEFAULT '',
            committee_chamber TEXT DEFAULT '',
            bill_type TEXT DEFAULT '',
            body TEXT DEFAULT '',
            current_body TEXT DEFAULT '',
            scope TEXT DEFAULT '',
            first_seen_date TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            stage TEXT DEFAULT 'introduced'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS legiscan_change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL,
            change_date TEXT NOT NULL,
            old_status INTEGER,
            new_status INTEGER,
            old_hash TEXT,
            new_hash TEXT,
            change_summary TEXT DEFAULT '',
            FOREIGN KEY (bill_id) REFERENCES legiscan_bills(bill_id)
        )
    """)
    conn.commit()


def _classify_scope(title: str, description: str) -> str:
    """Classify bill scope based on title and description."""
    text = (title + " " + description).lower()
    scopes = []
    if any(kw in text for kw in ["product", "consumer", "packaging", "textile", "apparel", "cookware", "cosmetic"]):
        scopes.append("product restrictions")
    if any(kw in text for kw in ["report", "disclos", "transparen", "notification", "register"]):
        scopes.append("reporting")
    if any(kw in text for kw in ["drinking water", "water system", "contaminat", "groundwater", "mcl", "cleanup"]):
        scopes.append("drinking water")
    if any(kw in text for kw in ["firefight", "foam", "afff"]):
        scopes.append("firefighting foam")
    if any(kw in text for kw in ["ban", "prohibit", "phase out", "phase-out", "eliminat"]):
        scopes.append("ban/phase-out")
    if any(kw in text for kw in ["liab", "lawsuit", "damages", "polluter"]):
        scopes.append("liability")
    return ", ".join(scopes) if scopes else "general PFAS"


def _determine_stage(bill: dict) -> str:
    """Determine pipeline stage from LegiScan bill data."""
    status = bill.get("status", 0)
    stage = _STATUS_TO_STAGE.get(status, "introduced")

    # Refine using progress events
    progress = bill.get("progress", [])
    if progress:
        last_event = max(progress, key=lambda p: p.get("date", ""))
        event_id = last_event.get("event", 0)
        if event_id == 2:  # Engrossed
            stage = "passed_one"
        elif event_id == 3:  # Enrolled
            stage = "advanced"
        elif event_id in (4, 8):  # Passed or Chaptered
            stage = "enacted_watching"
        elif event_id in (5, 6):  # Vetoed or Failed
            stage = "none"

    # Check committee assignment for "committee" stage
    if status == 1:  # Introduced
        history = bill.get("history", [])
        for h in history:
            action_lower = h.get("action", "").lower()
            if any(kw in action_lower for kw in ["committee", "referred", "assigned"]):
                stage = "committee"
                break

    return stage


class LegiScanTracker:
    """
    Track PFAS-related bills across all US states using the LegiScan API.
    Persists state to SQLite for change detection across runs.
    """

    def __init__(self, api_key: str = ""):
        self._client = LegiScanClient(api_key=api_key)
        self._conn = sqlite3.connect(str(_DB_PATH))
        self._conn.row_factory = sqlite3.Row
        _init_db(self._conn)

    def close(self):
        self._conn.close()

    def run(self) -> dict:
        """
        Run the full tracking cycle:
          1. Search for PFAS bills across all states
          2. Fetch details for new/changed bills
          3. Update local database
          4. Return report of new, changed, and all active bills

        Returns:
            {
                "new_bills": [...],
                "changed_bills": [...],
                "all_active": [...],
                "by_state": { "CA": [...], ... },
                "api_calls": int,
                "run_date": "2026-03-23",
            }
        """
        today = date.today().isoformat()
        logger.info("LegiScan Tracker: Starting PFAS bill search...")

        # Step 1: Search for all PFAS-related bills
        found_bills = self._search_all_queries()
        logger.info(f"Found {len(found_bills)} unique PFAS bills across all states")

        # Step 2: Identify new and changed bills
        new_ids, changed_ids = self._detect_changes(found_bills)
        logger.info(f"New: {len(new_ids)}, Changed: {len(changed_ids)}")

        # Step 3: Fetch full details for new/changed bills
        bills_to_fetch = new_ids | changed_ids
        fetched_details = {}
        for bill_id in bills_to_fetch:
            try:
                detail = self._client.get_bill(bill_id)
                if detail:
                    fetched_details[bill_id] = detail
            except LegiScanError as e:
                logger.warning(f"Failed to fetch bill {bill_id}: {e}")

        logger.info(f"Fetched details for {len(fetched_details)} bills")

        # Step 4: Update database
        new_bills = []
        changed_bills = []

        for bill_id, detail in fetched_details.items():
            record = self._bill_to_record(detail, today)
            if bill_id in new_ids:
                self._insert_bill(record)
                new_bills.append(record)
            else:
                old_record = self._get_bill(bill_id)
                self._update_bill(record, old_record)
                changed_bills.append(record)

        # Step 5: Mark bills not found in search as potentially inactive
        self._mark_inactive(found_bills, today)

        # Step 6: Build report
        all_active = self._get_all_active()
        by_state = {}
        for bill in all_active:
            state = bill["state"]
            if state not in by_state:
                by_state[state] = []
            by_state[state].append(bill)

        report = {
            "new_bills": new_bills,
            "changed_bills": changed_bills,
            "all_active": all_active,
            "by_state": by_state,
            "api_calls": self._client.call_count,
            "run_date": today,
            "total_tracked": len(all_active),
            "states_with_bills": len(by_state),
        }

        logger.info(
            f"Tracker complete: {len(all_active)} active bills across "
            f"{len(by_state)} states ({self._client.call_count} API calls)"
        )

        return report

    def _search_all_queries(self) -> dict[int, dict]:
        """Run all PFAS search queries and deduplicate by bill_id."""
        found: dict[int, dict] = {}
        for query in _SEARCH_QUERIES:
            try:
                results = self._client.search_all_pages(
                    query=query, state="ALL", year=2, max_pages=5
                )
                for r in results:
                    bill_id = r.get("bill_id")
                    if bill_id and bill_id not in found:
                        found[bill_id] = r
            except LegiScanError as e:
                logger.warning(f"Search failed for '{query}': {e}")
        return found

    def _detect_changes(self, found_bills: dict[int, dict]) -> tuple[set[int], set[int]]:
        """Compare found bills against stored data. Return (new_ids, changed_ids)."""
        new_ids = set()
        changed_ids = set()

        for bill_id, search_result in found_bills.items():
            row = self._conn.execute(
                "SELECT bill_id, change_hash FROM legiscan_bills WHERE bill_id = ?",
                (bill_id,)
            ).fetchone()

            if row is None:
                new_ids.add(bill_id)
            else:
                stored_hash = row["change_hash"]
                incoming_hash = search_result.get("change_hash", "")
                if incoming_hash and incoming_hash != stored_hash:
                    changed_ids.add(bill_id)

        return new_ids, changed_ids

    def _bill_to_record(self, detail: dict, today: str) -> dict:
        """Convert a LegiScan bill detail response to a flat record."""
        sponsors = detail.get("sponsors", [])
        sponsors_clean = []
        for s in sponsors:
            sponsors_clean.append({
                "name": s.get("name", ""),
                "party": s.get("party", ""),
                "role": s.get("role", ""),
                "district": s.get("district", ""),
                "sponsor_type_id": s.get("sponsor_type_id", 0),
            })

        history = detail.get("history", [])
        history_clean = []
        for h in history:
            history_clean.append({
                "date": h.get("date", ""),
                "action": h.get("action", ""),
                "chamber": h.get("chamber", ""),
            })

        committee = detail.get("committee", {}) or {}
        title = detail.get("title", "")
        description = detail.get("description", "")

        return {
            "bill_id": detail.get("bill_id"),
            "state": detail.get("state", ""),
            "bill_number": detail.get("bill_number", ""),
            "title": title,
            "description": description,
            "status": detail.get("status", 0),
            "status_label": STATUS_LABELS.get(detail.get("status", 0), "Unknown"),
            "status_date": detail.get("status_date", ""),
            "change_hash": detail.get("change_hash", ""),
            "last_action": history_clean[-1]["action"] if history_clean else "",
            "last_action_date": history_clean[-1]["date"] if history_clean else "",
            "url": detail.get("url", ""),
            "state_link": detail.get("state_link", ""),
            "sponsors_json": json.dumps(sponsors_clean),
            "history_json": json.dumps(history_clean),
            "committee_name": committee.get("name", ""),
            "committee_chamber": committee.get("chamber", ""),
            "bill_type": detail.get("bill_type", ""),
            "body": detail.get("body", ""),
            "current_body": detail.get("current_body", ""),
            "scope": _classify_scope(title, description),
            "first_seen_date": today,
            "last_updated": today,
            "is_active": 1 if detail.get("status", 0) not in (4, 5, 6) else 0,
            "stage": _determine_stage(detail),
        }

    def _insert_bill(self, record: dict):
        """Insert a new bill into the database."""
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        self._conn.execute(
            f"INSERT OR REPLACE INTO legiscan_bills ({cols}) VALUES ({placeholders})",
            list(record.values())
        )
        self._conn.commit()

    def _update_bill(self, record: dict, old_record: Optional[dict]):
        """Update an existing bill and log the change."""
        bill_id = record["bill_id"]

        # Log the change
        if old_record:
            old_status = old_record.get("status", 0)
            new_status = record.get("status", 0)
            summary_parts = []
            if old_status != new_status:
                summary_parts.append(
                    f"Status: {STATUS_LABELS.get(old_status, '?')} → {STATUS_LABELS.get(new_status, '?')}"
                )
            if record.get("last_action") != old_record.get("last_action"):
                summary_parts.append(f"Action: {record.get('last_action', '')[:100]}")

            self._conn.execute(
                """INSERT INTO legiscan_change_log
                   (bill_id, change_date, old_status, new_status, old_hash, new_hash, change_summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    bill_id,
                    record["last_updated"],
                    old_record.get("status", 0) if old_record else None,
                    record.get("status", 0),
                    old_record.get("change_hash", "") if old_record else "",
                    record.get("change_hash", ""),
                    "; ".join(summary_parts),
                )
            )

        # Update the bill record (preserve first_seen_date)
        record.pop("first_seen_date", None)
        set_clause = ", ".join(f"{k} = ?" for k in record.keys() if k != "bill_id")
        values = [v for k, v in record.items() if k != "bill_id"]
        values.append(bill_id)
        self._conn.execute(
            f"UPDATE legiscan_bills SET {set_clause} WHERE bill_id = ?",
            values
        )
        self._conn.commit()

    def _get_bill(self, bill_id: int) -> Optional[dict]:
        """Get a bill record from the database."""
        row = self._conn.execute(
            "SELECT * FROM legiscan_bills WHERE bill_id = ?", (bill_id,)
        ).fetchone()
        if row:
            return dict(row)
        return None

    def _mark_inactive(self, found_bills: dict[int, dict], today: str):
        """Mark bills not in the current search as potentially inactive."""
        # Only mark inactive if they haven't been updated recently
        # (they might just not match the search anymore but still be active)
        pass  # Conservative: don't auto-deactivate

    def _get_all_active(self) -> list[dict]:
        """Get all active bills from the database."""
        rows = self._conn.execute(
            "SELECT * FROM legiscan_bills WHERE is_active = 1 ORDER BY state, bill_number"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_changes_since(self, since_date: str) -> list[dict]:
        """Get all bill changes since a given date."""
        rows = self._conn.execute(
            """SELECT cl.*, b.state, b.bill_number, b.title
               FROM legiscan_change_log cl
               JOIN legiscan_bills b ON cl.bill_id = b.bill_id
               WHERE cl.change_date >= ?
               ORDER BY cl.change_date DESC""",
            (since_date,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_bills_by_state(self, state: str) -> list[dict]:
        """Get all active bills for a specific state."""
        rows = self._conn.execute(
            "SELECT * FROM legiscan_bills WHERE state = ? AND is_active = 1 ORDER BY bill_number",
            (state,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_state_summary(self) -> dict[str, dict]:
        """
        Get a summary of PFAS legislative activity by state.
        Returns a dict keyed by state abbreviation with bill counts and most advanced stage.
        """
        rows = self._conn.execute(
            """SELECT state, COUNT(*) as bill_count,
                      GROUP_CONCAT(bill_number, ', ') as bill_numbers,
                      GROUP_CONCAT(DISTINCT stage) as stages
               FROM legiscan_bills
               WHERE is_active = 1
               GROUP BY state
               ORDER BY state"""
        ).fetchall()

        stage_priority = {
            "enacted_watching": 7, "advanced": 6, "passed_one": 5,
            "committee": 4, "introduced": 3, "none": 0,
        }

        summary = {}
        for row in rows:
            state = row["state"]
            stages = (row["stages"] or "").split(",")
            best_stage = max(stages, key=lambda s: stage_priority.get(s.strip(), 0))
            summary[state] = {
                "bill_count": row["bill_count"],
                "bill_numbers": row["bill_numbers"],
                "best_stage": best_stage.strip(),
            }
        return summary

    def export_for_pipeline(self) -> list[dict]:
        """
        Export bill data in a format ready for the legislative intel pipeline.
        Returns list of dicts with the fields Claude needs.
        """
        bills = self._get_all_active()
        export = []
        for b in bills:
            sponsors = json.loads(b.get("sponsors_json", "[]"))
            sponsor_names = [s["name"] for s in sponsors[:3]]
            history = json.loads(b.get("history_json", "[]"))
            recent_actions = [
                f"{h['date']}: {h['action']}" for h in history[-3:]
            ]

            export.append({
                "bill_id": b["bill_id"],
                "state": b["state"],
                "bill_number": b["bill_number"],
                "title": b["title"],
                "description": b["description"],
                "status": b["status_label"],
                "stage": b["stage"],
                "scope": b["scope"],
                "committee": b["committee_name"],
                "sponsors": sponsor_names,
                "recent_actions": recent_actions,
                "last_action_date": b["last_action_date"],
                "url": b["url"],
                "state_link": b["state_link"],
                "first_seen": b["first_seen_date"],
            })
        return export


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        tracker = LegiScanTracker()
        report = tracker.run()

        print(f"\n{'='*60}")
        print(f"LegiScan PFAS Bill Tracker Report — {report['run_date']}")
        print(f"{'='*60}")
        print(f"Total active bills: {report['total_tracked']}")
        print(f"States with bills:  {report['states_with_bills']}")
        print(f"New this run:       {len(report['new_bills'])}")
        print(f"Changed this run:   {len(report['changed_bills'])}")
        print(f"API calls used:     {report['api_calls']}")

        print(f"\n--- Bills by State ---")
        for state in sorted(report["by_state"]):
            bills = report["by_state"][state]
            print(f"\n  {state} ({len(bills)} bills):")
            for b in bills:
                print(f"    {b['bill_number']}: {b['title'][:70]}")
                print(f"      Stage: {b['stage']} | Status: {b['status_label']} | Scope: {b['scope']}")

        if report["new_bills"]:
            print(f"\n--- New Bills ---")
            for b in report["new_bills"]:
                print(f"  [{b['state']}] {b['bill_number']}: {b['title'][:80]}")

        if report["changed_bills"]:
            print(f"\n--- Changed Bills ---")
            for b in report["changed_bills"]:
                print(f"  [{b['state']}] {b['bill_number']}: {b['title'][:80]}")

        tracker.close()
    except LegiScanError as e:
        print(f"Error: {e}")
