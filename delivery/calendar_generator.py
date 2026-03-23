"""Generate an .ics calendar file from regulatory deadlines."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import List

from config.settings import Config


def generate_ics(deadlines: List[dict]) -> Path:
    """Generate a .ics file from a list of deadline dicts. Returns path to file."""
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
