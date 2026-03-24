"""Generate an .ics calendar file from regulatory deadlines."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import List

from config.settings import Config


def _get_monitored_law_deadlines() -> List[dict]:
    """Pull reporting_deadline events from the regulation_events table."""
    try:
        from subscribers.db import get_connection
        conn = get_connection()
        rows = conn.execute("""
            SELECT
                r.topic,
                r.regulation_name,
                r.source_url AS reg_url,
                e.event_type,
                e.event_date AS deadline_date,
                e.description,
                e.source_url
            FROM regulation_events e
            JOIN regulations r ON r.id = e.regulation_id
            WHERE e.event_type = 'reporting_deadline'
              AND e.event_date IS NOT NULL
              AND e.event_date >= date('now', '-30 days')
            ORDER BY e.event_date ASC
        """).fetchall()
        conn.close()
        result = []
        for row in rows:
            result.append({
                "topic": row["topic"],
                "title": f"{row['regulation_name']} — {row['description'] or row['event_type']}",
                "deadline_date": row["deadline_date"],
                "description": row["description"] or "",
                "jurisdiction": "",
                "source_url": row["source_url"] or row["reg_url"] or "",
                "urgency": "HIGH",
            })
        return result
    except Exception:
        return []


def generate_ics(deadlines: List[dict]) -> Path:
    """Generate a .ics file from a list of deadline dicts. Returns path to file.

    Also automatically includes reporting_deadline events from the monitored
    regulation registry (regulation_events table) so lawyers can subscribe to
    all known compliance dates in one .ics feed.
    """
    # Merge in monitored law deadlines from the regulation registry
    monitored = _get_monitored_law_deadlines()
    if monitored:
        existing_keys = {(d.get("topic", ""), d.get("title", ""), d.get("deadline_date", "")) for d in deadlines}
        for m in monitored:
            key = (m.get("topic", ""), m.get("title", ""), m.get("deadline_date", ""))
            if key not in existing_keys:
                deadlines = list(deadlines) + [m]
                existing_keys.add(key)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Compliance Intelligence//Regulatory Deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Compliance Deadlines",
        "X-WR-CALDESC:Regulatory deadlines tracked by Compliance Intelligence",
    ]

    now_str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for dl in deadlines:
        try:
            d = date.fromisoformat(dl["deadline_date"])
            date_str = d.strftime("%Y%m%d")
            uid = (
                f"compliance-{dl.get('topic','')}-{date_str}"
                f"-{abs(hash(dl.get('title','')))}@compliance-monitor"
            )
            summary = (
                dl.get("title", "Compliance Deadline")
                .replace(",", "\\,")
                .replace(";", "\\;")
            )
            description = (
                (dl.get("description", "") or "")
                .replace(",", "\\,")
                .replace(";", "\\;")
                .replace("\n", "\\n")
            )
            url = dl.get("source_url", "") or ""

            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_str}",
                f"DTSTART;VALUE=DATE:{date_str}",
                f"DTEND;VALUE=DATE:{date_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                f"URL:{url}",
                f"CATEGORIES:{dl.get('topic', '').upper()}",
                "END:VEVENT",
            ]
        except Exception:
            continue

    lines.append("END:VCALENDAR")

    output_path = Config.DATA_DIR / "deadlines.ics"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\r\n".join(lines) + "\r\n")
    return output_path
