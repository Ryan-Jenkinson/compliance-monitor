"""Generate Gantt-style regulatory deadline timelines as self-contained HTML files."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "compliance.db"
_PFAS_DATA_PATH = Path(__file__).parent.parent / "config" / "pfas_state_data.json"
_DATA_DIR = Path(__file__).parent.parent / "data"
_PAGES_BASE = "https://ryan-jenkinson.github.io/compliance-maps"

_STATE_ABBR: Dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}

_TOPIC_COLORS: Dict[str, str] = {
    "pfas":             "#D64045",
    "tsca":             "#7A9EB5",
    "epr":              "#4A9062",
    "reach":            "#9E8540",
    "prop65":           "#8B4513",
    "conflictminerals": "#5B4A72",
    "forcedlabor":      "#2C5F6E",
}
_TOPIC_LABELS: Dict[str, str] = {
    "pfas": "PFAS", "tsca": "TSCA", "epr": "EPR", "reach": "REACH",
    "prop65": "Prop 65", "conflictminerals": "Conflict Minerals", "forcedlabor": "Forced Labor",
}
_URGENCY_CFG: Dict[str, Dict[str, str]] = {
    "HIGH":   {"bg": "#3A1A1E", "border": "#7A3030", "text": "#F08080", "end": "#D64045"},
    "MEDIUM": {"bg": "#2E2510", "border": "#7A6025", "text": "#D4A84B", "end": "#C49030"},
    "LOW":    {"bg": "#0C201A", "border": "#2E7050", "text": "#5EB88A", "end": "#3A8A62"},
}

# Per-topic page config
_TOPIC_CFG: Dict = {
    "pfas": {
        "page_title": "PFAS Regulatory Deadline Timeline",
        "eyebrow": "PFAS / Fluoropolymer Compliance",
        "accent": "#D64045",
        "filename": "pfas-timeline.html",
        "show_all_states": True,
        "back_links": [(f"{_PAGES_BASE}/index.html", "← PFAS Map")],
    },
    "epr": {
        "page_title": "EPR Regulatory Deadline Timeline",
        "eyebrow": "Extended Producer Responsibility",
        "accent": "#4A9062",
        "filename": "epr-timeline.html",
        "show_all_states": False,
        "back_links": [(f"{_PAGES_BASE}/epr-map.html", "← EPR Map")],
    },
    "reach": {
        "page_title": "REACH Regulatory Deadline Timeline",
        "eyebrow": "REACH / EU Chemical Compliance",
        "accent": "#9E8540",
        "filename": "reach-timeline.html",
        "show_all_states": False,
        "back_links": [(f"{_PAGES_BASE}/reach-map.html", "← REACH Map")],
    },
    "tsca": {
        "page_title": "TSCA Regulatory Deadline Timeline",
        "eyebrow": "Toxic Substances Control Act",
        "accent": "#7A9EB5",
        "filename": "tsca-timeline.html",
        "show_all_states": False,
        "back_links": [(f"{_PAGES_BASE}/index.html", "← PFAS Map")],
    },
    "prop65": {
        "page_title": "Prop 65 Regulatory Deadline Timeline",
        "eyebrow": "California Proposition 65",
        "accent": "#8B4513",
        "filename": "prop65-timeline.html",
        "show_all_states": False,
        "back_links": [],
    },
    "conflictminerals": {
        "page_title": "Conflict Minerals Compliance Timeline",
        "eyebrow": "SEC Dodd-Frank Section 1502 / Conflict Minerals",
        "accent": "#5B4A72",
        "filename": "conflict-minerals-timeline.html",
        "show_all_states": False,
        "back_links": [],
    },
    "forcedlabor": {
        "page_title": "Forced Labor & Supply Chain Timeline",
        "eyebrow": "UFLPA / Forced Labor Compliance",
        "accent": "#2C5F6E",
        "filename": "forced-labor-timeline.html",
        "show_all_states": False,
        "back_links": [],
    },
    None: {
        "page_title": "Regulatory Deadline Timeline",
        "eyebrow": "Compliance Intelligence",
        "accent": "#D64045",
        "filename": "deadline-timeline.html",
        "show_all_states": True,
        "back_links": [
            (f"{_PAGES_BASE}/index.html", "← PFAS Map"),
            (f"{_PAGES_BASE}/epr-map.html", "← EPR Map"),
            (f"{_PAGES_BASE}/reach-map.html", "← REACH Map"),
        ],
    },
}


def _load_deadlines(topic: Optional[str] = None) -> List[Dict]:
    """Load deadlines from the DB, optionally filtered to a single topic."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    if topic:
        rows = conn.execute("""
            SELECT topic, title, deadline_date, description, jurisdiction, source_url, urgency
            FROM regulatory_deadlines
            WHERE topic = ?
            GROUP BY topic, title, deadline_date, jurisdiction
            ORDER BY deadline_date, jurisdiction
        """, (topic,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT topic, title, deadline_date, description, jurisdiction, source_url, urgency
            FROM regulatory_deadlines
            GROUP BY topic, title, deadline_date, jurisdiction
            ORDER BY deadline_date, jurisdiction
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_all_states() -> Dict[str, str]:
    """Return {abbr: full_name} for all tracked US states."""
    try:
        data = json.loads(_PFAS_DATA_PATH.read_text())
        return {abbr: info["name"] for abbr, info in data.get("states", {}).items()}
    except Exception:
        return {v: k for k, v in _STATE_ABBR.items()}


def _parse_key_date(entry: str) -> Optional[date]:
    """Parse a key_date string like 'Jan 1, 2026: ...' into a date. Returns None if unparseable."""
    if re.match(r"^(Ongoing|Pending|TBD)", entry.strip(), re.IGNORECASE):
        return None
    prefix = entry.split(":")[0].strip()
    # Handle "Jan 2027/2028" → use first year
    prefix = re.sub(r"(\d{4})/\d{4}", r"\1", prefix).strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return date(*__import__("time").strptime(prefix, fmt)[:3])
        except Exception:
            pass
    for fmt in ("%b %Y", "%B %Y"):
        try:
            import time as _t
            t = _t.strptime(prefix, fmt)
            return date(t[0], t[1], 1)
        except Exception:
            pass
    m = re.match(r"^(\d{4})$", prefix)
    if m:
        yr = int(m.group(1))
        return date(yr, 1, 1)
    return None


def _load_key_date_deadlines() -> Dict[str, List[Dict]]:
    """Parse key_dates from pfas_state_data.json into deadline dicts grouped by state full name.
    Returns ALL dates (past and future) so callers can decide what to show."""
    result: Dict[str, List[Dict]] = {}
    try:
        data = json.loads(_PFAS_DATA_PATH.read_text())
        today = date.today()
        for abbr, info in data.get("states", {}).items():
            state_name = info.get("name", abbr)
            for entry in info.get("key_dates", []):
                dl_date = _parse_key_date(entry)
                if not dl_date:
                    continue
                # Include future dates only
                if dl_date < today:
                    continue
                days_out = (dl_date - today).days
                urgency = "HIGH" if days_out <= 180 else ("MEDIUM" if days_out <= 365 else "LOW")
                parts = entry.split(":", 1)
                title = parts[1].strip() if len(parts) > 1 else entry
                result.setdefault(state_name, []).append({
                    "topic": "pfas",
                    "title": title,
                    "deadline_date": dl_date.isoformat(),
                    "description": "",
                    "jurisdiction": state_name,
                    "source_url": "",
                    "urgency": urgency,
                    "_source": "key_dates",
                })
    except Exception as e:
        logger.warning(f"key_dates parse failed: {e}")
    return result


def _pct(d: date, start: date, end: date) -> float:
    total = (end - start).days
    return max(0.0, min(100.0, (d - start).days / total * 100)) if total > 0 else 0.0


def _h(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_bar(dl: Dict, tl_start: date, tl_end: date) -> str:
    dl_date = date.fromisoformat(dl["deadline_date"])
    width = _pct(dl_date, tl_start, tl_end)
    urg = dl.get("urgency", "LOW").upper()
    urg_cls = urg.lower()  # "high", "medium", "low"
    topic = dl.get("topic", "").lower()
    tc = _TOPIC_COLORS.get(topic, "#888888")
    tl = _TOPIC_LABELS.get(topic, topic.upper())
    title = _h(dl["title"])
    desc = _h((dl.get("description") or "")[:160])
    url = dl.get("source_url") or ""
    month_str = dl_date.strftime("%b %d, %Y")
    short_title = dl["title"][:80] + ("…" if len(dl["title"]) > 80 else "")
    return f"""
      <div class="dl-row" title="{title}&#10;Due: {month_str}&#10;{desc}">
        <div class="dl-chart-area">
          <div class="dl-bar urg-{urg_cls}" style="width:{width:.2f}%;">
            <span class="dl-end-pip pip-{urg_cls}"></span>
            <span class="dl-title title-{urg_cls}">{_h(short_title)}</span>
          </div>
          <div class="dl-meta">
            <span class="dl-date">{month_str}</span>
            <span class="dl-badge" style="color:{tc};border-color:{tc}80;">{tl}</span>
            <span class="dl-urg urg-txt-{urg_cls}">{urg}</span>
          </div>
        </div>
      </div>"""


def _render_group(name: str, deadlines: Optional[List[Dict]], tl_start: date, tl_end: date,
                  inactive: bool = False, label_px: int = 220) -> str:
    abbr = _STATE_ABBR.get(name, "")
    abbr_html = f'<span class="jx-abbr">{abbr}</span>' if abbr else ""
    cls = ' class="jx-group inactive"' if inactive else ' class="jx-group"'
    if inactive or not deadlines:
        rows_html = '<div class="dl-row empty"><span class="no-dl">No tracked deadlines</span></div>'
    else:
        rows_html = "".join(_render_bar(d, tl_start, tl_end) for d in sorted(deadlines, key=lambda x: x["deadline_date"]))
    return f"""
    <div{cls}>
      <div class="jx-label">
        <span class="jx-name">{_h(name)}</span>
        {abbr_html}
      </div>
      <div class="jx-rows">{rows_html}</div>
    </div>"""


def generate_deadline_timeline(topic: Optional[str] = None, output_path: Optional[Path] = None) -> Path:
    """Generate a Gantt-style deadline timeline HTML file.

    Args:
        topic: One of "pfas", "epr", "reach", "tsca", or None for all topics combined.
        output_path: Override the output file path.
    """
    cfg = _TOPIC_CFG.get(topic, _TOPIC_CFG[None])
    default_out = _DATA_DIR / cfg["filename"]
    out = Path(output_path) if output_path else default_out
    out.parent.mkdir(parents=True, exist_ok=True)

    db_deadlines = _load_deadlines(topic)
    today = date.today()

    # For PFAS (or combined), supplement DB data with key_dates from pfas_state_data.json
    key_date_deadlines: Dict[str, List[Dict]] = {}
    all_states: Dict[str, str] = {}
    if topic in (None, "pfas"):
        key_date_deadlines = _load_key_date_deadlines()
        all_states = _load_all_states()

    # Merge: DB deadlines first; supplement with key_dates where DB has no entry
    by_jx: Dict[str, List[Dict]] = {}
    for dl in db_deadlines:
        by_jx.setdefault(dl["jurisdiction"], []).append(dl)
    for state_name, kd_list in key_date_deadlines.items():
        existing_titles = {d["title"][:40] for d in by_jx.get(state_name, [])}
        for kd in kd_list:
            if kd["title"][:40] not in existing_titles:
                by_jx.setdefault(state_name, []).append(kd)

    all_deadlines = [d for dls in by_jx.values() for d in dls]
    if all_deadlines:
        max_dl = max(date.fromisoformat(d["deadline_date"]) for d in all_deadlines)
    else:
        max_dl = today + timedelta(days=365)
    tl_start = today
    tl_end = max(max_dl + timedelta(days=90), today + timedelta(days=600))

    # Quarter axis labels
    quarters: List[Tuple[float, str]] = []
    q_start_month = ((tl_start.month - 1) // 3) * 3 + 1
    d = date(tl_start.year, q_start_month, 1)
    while d <= tl_end:
        quarters.append((_pct(d, tl_start, tl_end), f"Q{(d.month-1)//3+1} {d.year}"))
        nm = d.month + 3
        ny = d.year + (1 if nm > 12 else 0)
        nm = nm - 12 if nm > 12 else nm
        d = date(ny, nm, 1)

    # Chart sizing: 150px per month, minimum 2400px
    total_months = (tl_end.year - tl_start.year) * 12 + (tl_end.month - tl_start.month) + 1
    chart_px = max(total_months * 150, 2400)
    label_px = 220
    total_px = label_px + chart_px

    # Build display order — alphabetical; Federal always first
    # If show_all_states: include all US states (dimmed if no deadlines)
    # Otherwise: only show jurisdictions present in DB
    active_jx_names = {name for name in by_jx if name != "Federal"}

    if cfg["show_all_states"] and all_states:
        # All US states in alphabetical order by full name
        all_state_names_sorted = sorted(all_states.values())
    else:
        # Only states/jurisdictions present in data
        all_state_names_sorted = sorted(active_jx_names)

    # Axis HTML
    axis_html = "".join(
        f'<div class="q-lbl" style="left:{p:.2f}%">{_h(lbl)}</div>'
        for p, lbl in quarters
    )

    # Group HTML — Federal first, then alphabetical states
    groups_html = ""
    if "Federal" in by_jx:
        groups_html += _render_group("Federal", by_jx["Federal"], tl_start, tl_end, label_px=label_px)
    for state_name in all_state_names_sorted:
        has_data = state_name in by_jx
        inactive = not has_data
        groups_html += _render_group(
            state_name,
            by_jx.get(state_name),
            tl_start, tl_end,
            inactive=inactive,
            label_px=label_px,
        )
    # For non-state jurisdictions (if any, e.g. "EU" for REACH)
    for jx in sorted(active_jx_names):
        if jx not in all_state_names_sorted and jx != "Federal":
            groups_html += _render_group(jx, by_jx[jx], tl_start, tl_end, label_px=label_px)

    today_str = today.strftime("%B %d, %Y")
    dl_count = len(all_deadlines)
    jx_count = len(by_jx)

    accent = cfg["accent"]
    page_title = cfg["page_title"]
    eyebrow = cfg["eyebrow"]
    current_file = cfg["filename"]

    _BASE = "https://ryan-jenkinson.github.io/compliance-maps"
    _MAPS = [
        (f"{_BASE}/index.html",     "PFAS",  "index.html"),
        (f"{_BASE}/epr-map.html",   "EPR",   "epr-map.html"),
        (f"{_BASE}/reach-map.html", "REACH", "reach-map.html"),
    ]
    _TIMELINES = [
        (f"{_BASE}/pfas-timeline.html",     "PFAS",       "pfas-timeline.html"),
        (f"{_BASE}/epr-timeline.html",      "EPR",        "epr-timeline.html"),
        (f"{_BASE}/reach-timeline.html",    "REACH",      "reach-timeline.html"),
        (f"{_BASE}/tsca-timeline.html",     "TSCA",       "tsca-timeline.html"),
        (f"{_BASE}/deadline-timeline.html", "All Topics", "deadline-timeline.html"),
    ]

    def _nav_link(url: str, label: str, filename: str) -> str:
        cls = 'nav-item active' if filename == current_file else 'nav-item'
        return f'<a href="{url}" class="{cls}">{_h(label)}</a>'

    map_links = "".join(_nav_link(u, l, f) for u, l, f in _MAPS)
    tl_links = "".join(_nav_link(u, l, f) for u, l, f in _TIMELINES)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_h(page_title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #F4F5F7;
      --surface: #FFFFFF;
      --surface-sunken: #EBEDF0;
      --surface-dark: #1A1D23;
      --surface-dark-2: #22252C;
      --border: #D8DBE0;
      --border-light: #E8EAED;
      --text-primary: #111318;
      --text-secondary: #4A4F5C;
      --text-tertiary: #7A8194;
      --red: #D63031;
      --red-bg: #FEF0F0;
      --red-border: #FACACA;
      --amber: #CB7B0A;
      --amber-bg: #FEF6E8;
      --amber-border: #F5DFA6;
      --green: #0F7B3F;
      --green-bg: #EEFAF3;
      --green-border: #B2E0C7;
      --blue: #1565C0;
      --teal: #0F766E;
      --accent: {accent};
      --sans: 'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      --mono: 'IBM Plex Mono', 'Consolas', monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      height: 100%;
      background: var(--bg);
      color: var(--text-primary);
      font-family: var(--sans);
      font-size: 13px;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
    }}

    /* ── Page layout ─────────────────────────── */
    .page-wrap {{
      display: flex;
      flex-direction: column;
      height: 100vh;
    }}

    /* ── Topbar ─────────────────────────────── */
    .page-hdr {{
      background: var(--surface);
      border-bottom: 3px solid {accent};
      padding: 0 24px;
      height: 50px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-shrink: 0;
    }}
    .hdr-left {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .hdr-brand {{
      width: 26px; height: 26px;
      background: linear-gradient(135deg, #0F766E, #1565C0);
      border-radius: 5px;
      flex-shrink: 0;
    }}
    .hdr-eyebrow {{
      font-family: var(--mono);
      font-size: 8px;
      font-weight: 600;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: {accent};
    }}
    .hdr-title {{
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 600;
      color: var(--text-primary);
      letter-spacing: .5px;
    }}
    .hdr-sub {{
      font-family: var(--mono);
      font-size: 9px;
      color: var(--text-tertiary);
      letter-spacing: .5px;
      margin-top: 2px;
    }}
    /* ── Site nav ─────────────────────────────── */
    .site-nav {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
      height: 36px;
      display: flex;
      align-items: center;
      gap: 2px;
      flex-shrink: 0;
    }}
    .nav-section {{
      font-family: var(--mono);
      color: var(--text-tertiary);
      font-size: 9px;
      font-weight: 600;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 0 8px 0 4px;
    }}
    .nav-sep {{
      width: 1px;
      height: 14px;
      background: var(--border);
      margin: 0 8px;
    }}
    .nav-item {{
      font-family: var(--mono);
      color: var(--text-secondary);
      font-size: 10px;
      font-weight: 500;
      letter-spacing: .5px;
      text-decoration: none;
      padding: 4px 10px;
      border-radius: 4px;
      transition: background 0.12s, color 0.12s;
    }}
    .nav-item:hover {{ background: var(--surface-sunken); color: var(--text-primary); }}
    .nav-item.active {{ background: var(--bg); color: {accent}; font-weight: 700; border: 1px solid var(--border); }}

    /* ── Gantt scroll container ───────────────── */
    .tl-scroll {{
      flex: 1;
      overflow: auto;
      position: relative;
      background: var(--bg);
    }}
    .tl-scroll::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    .tl-scroll::-webkit-scrollbar-track {{ background: transparent; }}
    .tl-scroll::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}

    /* ── Inner container — sets total width ────── */
    .tl-inner {{
      min-width: {total_px}px;
    }}

    /* ── Axis header ─────────────────────────── */
    .tl-axis {{
      display: flex;
      position: sticky;
      top: 0;
      z-index: 50;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }}
    .axis-jx-col {{
      width: {label_px}px;
      flex-shrink: 0;
      padding: 8px 16px;
      font-family: var(--mono);
      font-size: 8px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--text-tertiary);
      border-right: 1px solid var(--border);
      position: sticky;
      left: 0;
      z-index: 55;
      background: var(--surface);
    }}
    .axis-chart-col {{
      width: {chart_px}px;
      flex-shrink: 0;
      position: relative;
      height: 38px;
    }}
    .q-lbl {{
      position: absolute;
      top: 50%;
      transform: translate(-50%, -50%);
      font-family: var(--mono);
      font-size: 9px;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--text-tertiary);
      white-space: nowrap;
      pointer-events: none;
    }}
    .q-tick {{
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: var(--border-light);
      pointer-events: none;
    }}

    /* ── Jurisdiction group ──────────────────── */
    .jx-group {{
      display: flex;
      border-bottom: 1px solid var(--border-light);
    }}
    .jx-group:last-child {{ border-bottom: none; }}
    .jx-group:hover {{ background: #FAFBFC; }}
    .jx-group.inactive {{ opacity: 0.35; }}

    .jx-label {{
      width: {label_px}px;
      flex-shrink: 0;
      padding: 10px 16px;
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 2px;
      min-height: 52px;
      position: sticky;
      left: 0;
      z-index: 5;
      background: var(--surface);
    }}
    .jx-name {{
      font-size: 12px;
      font-weight: 600;
      color: var(--text-primary);
      line-height: 1.2;
    }}
    .jx-abbr {{
      font-family: var(--mono);
      font-size: 8px;
      letter-spacing: 2px;
      color: var(--text-tertiary);
      text-transform: uppercase;
      margin-top: 2px;
    }}
    .jx-group.inactive .jx-name {{ color: var(--text-tertiary); }}

    .jx-rows {{
      width: {chart_px}px;
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
    }}

    /* ── Deadline row ────────────────────────── */
    .dl-row {{
      display: flex;
      align-items: stretch;
      border-bottom: 1px solid var(--border-light);
      min-height: 52px;
    }}
    .dl-row:last-child {{ border-bottom: none; }}
    .dl-row.empty {{ min-height: 40px; align-items: center; }}

    .dl-chart-area {{
      width: {chart_px}px;
      flex-shrink: 0;
      padding: 8px 20px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      justify-content: center;
    }}

    .dl-bar {{
      position: relative;
      height: 24px;
      border: 1px solid;
      border-radius: 3px;
      display: flex;
      align-items: center;
      padding-left: 10px;
      padding-right: 4px;
      overflow: hidden;
      min-width: 6px;
      max-width: 100%;
    }}
    /* urgency bar colors — light-theme versions */
    .dl-bar.urg-high   {{ background: var(--red-bg);   border-color: var(--red-border); }}
    .dl-bar.urg-medium {{ background: var(--amber-bg); border-color: var(--amber-border); }}
    .dl-bar.urg-low    {{ background: var(--green-bg); border-color: var(--green-border); }}
    .dl-end-pip {{
      position: absolute;
      right: 0;
      top: 0;
      bottom: 0;
      width: 4px;
      border-radius: 0 2px 2px 0;
      flex-shrink: 0;
    }}
    .pip-high   {{ background: var(--red); }}
    .pip-medium {{ background: var(--amber); }}
    .pip-low    {{ background: var(--green); }}
    .dl-title {{
      font-size: 11px;
      font-weight: 500;
      white-space: normal;
      word-break: break-word;
      letter-spacing: 0.2px;
      padding-right: 8px;
    }}
    .title-high   {{ color: var(--red); }}
    .title-medium {{ color: #92400E; }}
    .title-low    {{ color: var(--green); }}

    .dl-meta {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .dl-date {{
      font-family: var(--mono);
      font-size: 9px;
      color: var(--text-secondary);
      letter-spacing: 0.5px;
    }}
    .dl-badge {{
      font-family: var(--mono);
      font-size: 8px;
      font-weight: 600;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 1px 5px;
      border: 1px solid;
      border-radius: 2px;
    }}
    .dl-urg {{
      font-family: var(--mono);
      font-size: 8px;
      font-weight: 700;
      letter-spacing: 2px;
      text-transform: uppercase;
    }}
    .urg-txt-high   {{ color: var(--red); }}
    .urg-txt-medium {{ color: var(--amber); }}
    .urg-txt-low    {{ color: var(--green); }}
    .dl-src {{
      font-family: var(--mono);
      font-size: 9px;
      color: var(--blue);
      text-decoration: none;
      letter-spacing: 0.5px;
    }}
    .dl-src:hover {{ text-decoration: underline; }}

    .no-dl {{
      font-family: var(--mono);
      font-size: 10px;
      color: var(--text-tertiary);
      letter-spacing: 1px;
      padding-left: 20px;
    }}

    /* ── Legend ──────────────────────────────── */
    .legend {{
      flex-shrink: 0;
      background: var(--surface);
      border-top: 1px solid var(--border);
      padding: 10px 24px;
      display: flex;
      align-items: center;
      gap: 20px;
      flex-wrap: wrap;
    }}
    .legend-title {{
      font-family: var(--mono);
      font-size: 8px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--text-tertiary);
      margin-right: 4px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-family: var(--mono);
      font-size: 9px;
      letter-spacing: .5px;
      color: var(--text-secondary);
    }}
    .legend-swatch {{
      width: 14px;
      height: 10px;
      border: 1px solid;
      border-radius: 2px;
    }}
    .sw-high   {{ background: var(--red-bg);   border-color: var(--red-border); }}
    .sw-medium {{ background: var(--amber-bg); border-color: var(--amber-border); }}
    .sw-low    {{ background: var(--green-bg); border-color: var(--green-border); }}
  </style>
</head>
<body>
<div class="page-wrap">

<!-- Topbar -->
<div class="page-hdr">
  <div class="hdr-left">
    <div class="hdr-brand"></div>
    <div>
      <div class="hdr-eyebrow">{_h(eyebrow)}</div>
      <div class="hdr-title">{_h(page_title)}</div>
    </div>
  </div>
  <div class="hdr-sub">Generated {today_str} &nbsp;&middot;&nbsp; {dl_count} deadline{'s' if dl_count != 1 else ''} across {jx_count} jurisdiction{'s' if jx_count != 1 else ''}</div>
</div>

<!-- Site nav -->
<nav class="site-nav">
  <span class="nav-section">Maps</span>
  {map_links}
  <div class="nav-sep"></div>
  <span class="nav-section">Timelines</span>
  {tl_links}
</nav>

<!-- Gantt scroll area -->
<div class="tl-scroll">
  <div class="tl-inner">

    <!-- Sticky axis header -->
    <div class="tl-axis">
      <div class="axis-jx-col">Jurisdiction</div>
      <div class="axis-chart-col" id="axisChart">
        {axis_html}
      </div>
    </div>

    <!-- Jurisdiction rows -->
{groups_html}

  </div><!-- /tl-inner -->
</div><!-- /tl-scroll -->

<!-- Legend -->
<div class="legend">
  <span class="legend-title">Urgency:</span>
  <span class="legend-item"><span class="legend-swatch sw-high"></span>High (&lt;6 mo)</span>
  <span class="legend-item"><span class="legend-swatch sw-medium"></span>Medium (6&ndash;12 mo)</span>
  <span class="legend-item"><span class="legend-swatch sw-low"></span>Low (&gt;12 mo)</span>
  <span class="legend-title" style="margin-left:16px">Bar width = time remaining until deadline</span>
</div>

</div><!-- /page-wrap -->

<script>
(function() {{
  var axisChart = document.getElementById('axisChart');
  if (!axisChart) return;
  var ticks = {json.dumps([p for p, _ in quarters])};
  ticks.forEach(function(p) {{
    var t = document.createElement('div');
    t.className = 'q-tick';
    t.style.left = p + '%';
    axisChart.appendChild(t);
  }});
}})();
</script>

</body>
</html>"""

    out.write_text(html)
    logger.info(f"Deadline timeline ({topic or 'all'}) written to {out}")
    return out


def generate_all_timelines() -> Dict[str, Path]:
    """Generate timeline pages for all topics plus the combined view."""
    results = {}
    for topic in (None, "pfas", "epr", "reach", "tsca", "prop65", "conflictminerals", "forcedlabor"):
        try:
            path = generate_deadline_timeline(topic=topic)
            results[topic or "all"] = path
        except Exception as e:
            logger.warning(f"Timeline generation failed for topic={topic}: {e}")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    paths = generate_all_timelines()
    for k, v in paths.items():
        print(f"{k}: {v}")
