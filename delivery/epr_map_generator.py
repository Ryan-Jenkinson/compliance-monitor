"""Generate an interactive EPR (Extended Producer Responsibility) state map as a self-contained HTML file."""
from __future__ import annotations
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional, Dict

from config.settings import Config

logger = logging.getLogger(__name__)

# Grid layout: (grid-row, grid-col) — 0-indexed, 9 rows x 12 cols
# Identical cartogram positions as the PFAS map.
_STATE_GRID: dict[str, tuple[int, int]] = {
    "ME": (0, 11),
    "VT": (1, 9),  "NH": (1, 10),
    "WA": (2, 0),  "MT": (2, 1),  "ND": (2, 2),  "MN": (2, 3),
    "WI": (2, 5),  "MI": (2, 6),
    "NY": (2, 8),  "MA": (2, 9),  "RI": (2, 10), "CT": (2, 11),
    "OR": (3, 0),  "ID": (3, 1),  "WY": (3, 2),  "SD": (3, 3),
    "IA": (3, 4),  "IL": (3, 5),  "IN": (3, 6),  "OH": (3, 7),
    "PA": (3, 8),  "NJ": (3, 9),
    "CA": (4, 0),  "NV": (4, 1),  "UT": (4, 2),  "CO": (4, 3),
    "NE": (4, 4),  "MO": (4, 5),  "KY": (4, 6),  "WV": (4, 7),
    "VA": (4, 8),  "MD": (4, 9),  "DE": (4, 10),
    "AZ": (5, 1),  "NM": (5, 2),
    "KS": (5, 4),  "TN": (5, 5),  "NC": (5, 6),  "SC": (5, 7),
    "OK": (6, 3),  "AR": (6, 4),  "MS": (6, 5),  "GA": (6, 6),  "AL": (6, 7),
    "TX": (7, 3),  "LA": (7, 4),  "FL": (7, 8),
    "AK": (8, 0),  "HI": (8, 1),
}

_STATUS_COLORS: dict[str, str] = {
    "comprehensive": "#1B6CA8",
    "limited":       "#4A9EC4",
    "proposed":      "#A8D4E8",
    "none":          "#E8EDF0",
}

_STATUS_LABELS: dict[str, str] = {
    "comprehensive": "Comprehensive Programs",
    "limited":       "Limited Programs (1-2)",
    "proposed":      "Proposed Legislation",
    "none":          "No EPR Programs",
}

# EPR state data: status, programs, summary, key dates
# Sources: NCSL, Product Stewardship Institute, state agency databases (as of early 2026)
_EPR_STATES: dict[str, dict] = {
    "AL": {
        "name": "Alabama",
        "status": "none",
        "programs": [],
        "summary": "Alabama has no statewide EPR programs for packaging, electronics, paint, or tires.",
        "key_dates": [],
    },
    "AK": {
        "name": "Alaska",
        "status": "none",
        "programs": [],
        "summary": "Alaska has no statewide EPR programs.",
        "key_dates": [],
    },
    "AZ": {
        "name": "Arizona",
        "status": "none",
        "programs": [],
        "summary": "Arizona has no statewide EPR programs.",
        "key_dates": [],
    },
    "AR": {
        "name": "Arkansas",
        "status": "none",
        "programs": [],
        "summary": "Arkansas has no statewide EPR programs.",
        "key_dates": [],
    },
    "CA": {
        "name": "California",
        "status": "comprehensive",
        "programs": [
            "Packaging EPR — SB 54 (2022): Plastic Pollution Prevention and Packaging Producer Responsibility Act",
            "Electronics/E-Waste — Electronic Waste Recycling Act (2003)",
            "Paint — PaintCare program (2014, ARB-approved stewardship plan)",
            "Tires — California Tire Recycling Act",
            "Mattresses — Mattress Recycling Act (2013)",
            "Carpet — Carpet Stewardship Program (2011)",
        ],
        "summary": (
            "California is the national leader in EPR policy. SB 54 (2022) mandates 25% reduction in single-use "
            "plastic packaging by 2032 and full producer responsibility. Active programs span electronics, paint, "
            "tires, mattresses, and carpet."
        ),
        "key_dates": [
            "2003 — Electronic Waste Recycling Act enacted",
            "2011 — Carpet stewardship program launched",
            "2013 — Mattress Recycling Act signed",
            "2014 — PaintCare program launched statewide",
            "Jul 2022 — SB 54 (packaging EPR) signed by Governor Newsom",
            "2032 — Target: 25% reduction in single-use plastic packaging",
        ],
    },
    "CO": {
        "name": "Colorado",
        "status": "comprehensive",
        "programs": [
            "Packaging EPR — HB 22-1355 (2022): Producer Responsibility for Statewide Recycling Act",
            "Electronics — E-Cycles Colorado (voluntary program with mandatory manufacturer registration)",
            "Paint — PaintCare program (2014)",
        ],
        "summary": (
            "Colorado enacted landmark packaging EPR legislation in 2022 (HB 22-1355), requiring producers to fund "
            "and manage a statewide recycling program. Electronics collection is managed through E-Cycles. "
            "PaintCare operates statewide for leftover paint."
        ),
        "key_dates": [
            "2014 — PaintCare program launched",
            "Jun 2022 — HB 22-1355 (packaging EPR) signed into law",
            "2026 — Producer Responsibility Organization must be operational",
            "2028 — Minimum recycling rate requirements take effect",
        ],
    },
    "CT": {
        "name": "Connecticut",
        "status": "limited",
        "programs": [
            "Electronics — Connecticut E-Cycles program (manufacturer take-back mandate)",
            "Paint — PaintCare program",
            "Tires — Scrap tire management program (generator fees)",
        ],
        "summary": (
            "Connecticut has active EPR programs for electronics, paint, and tires. A packaging EPR bill has been "
            "introduced but not yet enacted. The state has one of the oldest electronics take-back mandates in "
            "the Northeast."
        ),
        "key_dates": [
            "2007 — Electronics take-back law enacted",
            "2013 — PaintCare program launched",
            "2024 — Packaging EPR bill introduced (pending)",
        ],
    },
    "DE": {
        "name": "Delaware",
        "status": "none",
        "programs": [],
        "summary": "Delaware has no statewide EPR programs, though it participates in regional electronics collection efforts.",
        "key_dates": [],
    },
    "FL": {
        "name": "Florida",
        "status": "none",
        "programs": [],
        "summary": "Florida has no statewide EPR programs for packaging, electronics, paint, or tires.",
        "key_dates": [],
    },
    "GA": {
        "name": "Georgia",
        "status": "none",
        "programs": [],
        "summary": "Georgia has no statewide EPR programs.",
        "key_dates": [],
    },
    "HI": {
        "name": "Hawaii",
        "status": "limited",
        "programs": [
            "Electronics — Hawaii E-Cycles program (manufacturer registration and take-back)",
            "Paint — PaintCare program",
        ],
        "summary": (
            "Hawaii operates electronics and paint EPR programs. The state has considered packaging EPR "
            "legislation but has not enacted it."
        ),
        "key_dates": [
            "2008 — Electronics take-back law enacted",
            "2015 — PaintCare program launched",
        ],
    },
    "ID": {
        "name": "Idaho",
        "status": "none",
        "programs": [],
        "summary": "Idaho has no statewide EPR programs.",
        "key_dates": [],
    },
    "IL": {
        "name": "Illinois",
        "status": "proposed",
        "programs": [
            "Packaging EPR — bills introduced in multiple sessions (not yet enacted)",
            "Electronics — Illinois E-Waste Take-Back law (2008, limited scope)",
        ],
        "summary": (
            "Illinois enacted a limited electronics take-back law in 2008. Comprehensive packaging EPR bills have "
            "been introduced in recent legislative sessions but have not advanced to passage."
        ),
        "key_dates": [
            "2008 — Electronics take-back law enacted (limited manufacturer scope)",
            "2023 — Packaging EPR bill introduced (SB 1555)",
            "2024 — Packaging EPR bill reintroduced (pending)",
        ],
    },
    "IN": {
        "name": "Indiana",
        "status": "none",
        "programs": [],
        "summary": "Indiana has no statewide EPR programs.",
        "key_dates": [],
    },
    "IA": {
        "name": "Iowa",
        "status": "none",
        "programs": [],
        "summary": "Iowa has no statewide EPR programs.",
        "key_dates": [],
    },
    "KS": {
        "name": "Kansas",
        "status": "none",
        "programs": [],
        "summary": "Kansas has no statewide EPR programs.",
        "key_dates": [],
    },
    "KY": {
        "name": "Kentucky",
        "status": "none",
        "programs": [],
        "summary": "Kentucky has no statewide EPR programs.",
        "key_dates": [],
    },
    "LA": {
        "name": "Louisiana",
        "status": "none",
        "programs": [],
        "summary": "Louisiana has no statewide EPR programs.",
        "key_dates": [],
    },
    "ME": {
        "name": "Maine",
        "status": "comprehensive",
        "programs": [
            "Packaging EPR — LD 1541 (2021): An Act to Support and Improve Municipal Recycling Programs (first in US)",
            "Electronics — Maine E-Cycles program (manufacturer take-back mandate, 2006)",
            "Paint — PaintCare program",
            "Mercury-containing products — product stewardship law",
        ],
        "summary": (
            "Maine made history in 2021 by becoming the first US state to enact packaging EPR legislation (LD 1541). "
            "The law requires producers to fund municipal recycling programs. Maine also has one of the oldest "
            "electronics take-back mandates in the country and active paint stewardship."
        ),
        "key_dates": [
            "2006 — Electronics take-back law enacted (one of first in US)",
            "Jul 2021 — LD 1541 signed — first US packaging EPR law",
            "2024 — Producer Responsibility Organization established",
            "2025 — Producer fees to municipalities begin phasing in",
        ],
    },
    "MD": {
        "name": "Maryland",
        "status": "proposed",
        "programs": [
            "Packaging EPR — bills introduced in recent sessions (not yet enacted)",
            "Paint — PaintCare program (limited county participation)",
        ],
        "summary": (
            "Maryland has active packaging EPR legislation moving through the General Assembly. "
            "PaintCare operates in several counties. No comprehensive statewide EPR law has been enacted yet."
        ),
        "key_dates": [
            "2022 — Packaging EPR bill introduced",
            "2024 — Revised packaging EPR bill reintroduced (HB 1124)",
            "2025 — Further legislative activity expected",
        ],
    },
    "MA": {
        "name": "Massachusetts",
        "status": "proposed",
        "programs": [
            "Electronics — MassDEP manufacturer registration program (limited scope)",
            "Packaging EPR — bills introduced, not yet enacted",
        ],
        "summary": (
            "Massachusetts has a limited electronics manufacturer registration requirement. Comprehensive packaging "
            "EPR bills have been filed in multiple sessions. The state has not yet enacted broad EPR legislation."
        ),
        "key_dates": [
            "2010 — Electronics manufacturer registration enacted",
            "2023 — Packaging EPR bill introduced (SD 1955)",
            "2025 — Legislative activity ongoing",
        ],
    },
    "MI": {
        "name": "Michigan",
        "status": "none",
        "programs": [],
        "summary": "Michigan has no statewide EPR programs, though proposals have been discussed.",
        "key_dates": [],
    },
    "MN": {
        "name": "Minnesota",
        "status": "limited",
        "programs": [
            "Electronics — Minnesota E-Cycles program (manufacturer take-back, 2007)",
            "Paint — PaintCare program",
        ],
        "summary": (
            "Minnesota has established EPR programs for electronics and paint. A packaging EPR bill passed the "
            "House in 2023 but stalled in the Senate. The legislature continues to consider broader EPR expansion."
        ),
        "key_dates": [
            "2007 — Electronics take-back law enacted",
            "2014 — PaintCare program launched",
            "2023 — Packaging EPR bill passed MN House (stalled in Senate)",
            "2025 — Packaging EPR legislation reintroduced",
        ],
    },
    "MS": {
        "name": "Mississippi",
        "status": "none",
        "programs": [],
        "summary": "Mississippi has no statewide EPR programs.",
        "key_dates": [],
    },
    "MO": {
        "name": "Missouri",
        "status": "none",
        "programs": [],
        "summary": "Missouri has no statewide EPR programs.",
        "key_dates": [],
    },
    "MT": {
        "name": "Montana",
        "status": "none",
        "programs": [],
        "summary": "Montana has no statewide EPR programs.",
        "key_dates": [],
    },
    "NE": {
        "name": "Nebraska",
        "status": "none",
        "programs": [],
        "summary": "Nebraska has no statewide EPR programs.",
        "key_dates": [],
    },
    "NV": {
        "name": "Nevada",
        "status": "none",
        "programs": [],
        "summary": "Nevada has no statewide EPR programs.",
        "key_dates": [],
    },
    "NH": {
        "name": "New Hampshire",
        "status": "none",
        "programs": [],
        "summary": "New Hampshire has no statewide EPR programs, though regional initiatives have been explored.",
        "key_dates": [],
    },
    "NJ": {
        "name": "New Jersey",
        "status": "proposed",
        "programs": [
            "Packaging EPR — bills introduced in multiple sessions (A4978/S3233 and similar)",
            "Electronics — limited manufacturer registration requirements",
        ],
        "summary": (
            "New Jersey has active packaging EPR bills progressing through the legislature. The state enacted "
            "a plastic bag ban in 2022 and has strong political momentum for broader EPR, but packaging EPR has "
            "not yet been signed into law."
        ),
        "key_dates": [
            "2022 — Plastic bag ban enacted",
            "2022 — Packaging EPR bill introduced (A4978)",
            "2024 — Packaging EPR bill advanced in committee",
            "2025 — Legislative activity ongoing",
        ],
    },
    "NM": {
        "name": "New Mexico",
        "status": "none",
        "programs": [],
        "summary": "New Mexico has no statewide EPR programs.",
        "key_dates": [],
    },
    "NY": {
        "name": "New York",
        "status": "comprehensive",
        "programs": [
            "Packaging EPR — NY Packaging Reduction and Recycling Infrastructure Act (signed Dec 2022 — first comprehensive packaging EPR in a major US state)",
            "Electronics — Electronic Equipment Recycling and Reuse Act (2010)",
            "Paint — PaintCare program",
        ],
        "summary": (
            "New York enacted the Packaging Reduction and Recycling Infrastructure Act in December 2022, one of "
            "the most significant packaging EPR laws in US history. The law requires producers to reduce packaging "
            "and fund municipal recycling. New York also has long-standing electronics and paint take-back programs."
        ),
        "key_dates": [
            "2010 — Electronic Equipment Recycling and Reuse Act enacted",
            "2013 — PaintCare program launched",
            "Dec 2022 — Packaging Reduction and Recycling Infrastructure Act signed",
            "2025 — Producer Responsibility Organization formation deadline",
            "2027 — Packaging reduction targets begin",
        ],
    },
    "NC": {
        "name": "North Carolina",
        "status": "none",
        "programs": [],
        "summary": "North Carolina has no statewide EPR programs.",
        "key_dates": [],
    },
    "ND": {
        "name": "North Dakota",
        "status": "none",
        "programs": [],
        "summary": "North Dakota has no statewide EPR programs.",
        "key_dates": [],
    },
    "OH": {
        "name": "Ohio",
        "status": "none",
        "programs": [],
        "summary": "Ohio has no statewide EPR programs.",
        "key_dates": [],
    },
    "OK": {
        "name": "Oklahoma",
        "status": "none",
        "programs": [],
        "summary": "Oklahoma has no statewide EPR programs.",
        "key_dates": [],
    },
    "OR": {
        "name": "Oregon",
        "status": "comprehensive",
        "programs": [
            "Packaging EPR — HB 3065 (2021): Plastic Pollution and Recycling Modernization Act",
            "Electronics — Oregon E-Cycles program (manufacturer take-back, 2007)",
            "Paint — PaintCare program",
        ],
        "summary": (
            "Oregon enacted its Plastic Pollution and Recycling Modernization Act in 2021, requiring producers "
            "to fund a statewide recycling system. Oregon was among the earliest adopters of electronics EPR "
            "and has run PaintCare for years."
        ),
        "key_dates": [
            "2007 — Oregon E-Cycles electronics take-back program launched",
            "2011 — PaintCare program launched",
            "Jun 2021 — HB 3065 (packaging EPR) signed into law",
            "2025 — Producer Responsibility Organization operational",
            "2028 — Minimum recycling rates required",
        ],
    },
    "PA": {
        "name": "Pennsylvania",
        "status": "none",
        "programs": [],
        "summary": "Pennsylvania has no statewide EPR programs, though pilot programs and discussions are ongoing.",
        "key_dates": [],
    },
    "RI": {
        "name": "Rhode Island",
        "status": "limited",
        "programs": [
            "Electronics — Rhode Island E-Cycles program (manufacturer take-back)",
            "Paint — PaintCare program",
        ],
        "summary": (
            "Rhode Island has EPR programs for electronics and paint. Packaging EPR has been discussed "
            "but no bill has been enacted."
        ),
        "key_dates": [
            "2008 — Electronics take-back law enacted",
            "2015 — PaintCare program launched",
        ],
    },
    "SC": {
        "name": "South Carolina",
        "status": "none",
        "programs": [],
        "summary": "South Carolina has no statewide EPR programs.",
        "key_dates": [],
    },
    "SD": {
        "name": "South Dakota",
        "status": "none",
        "programs": [],
        "summary": "South Dakota has no statewide EPR programs.",
        "key_dates": [],
    },
    "TN": {
        "name": "Tennessee",
        "status": "none",
        "programs": [],
        "summary": "Tennessee has no statewide EPR programs.",
        "key_dates": [],
    },
    "TX": {
        "name": "Texas",
        "status": "none",
        "programs": [],
        "summary": "Texas has no statewide EPR programs for packaging, electronics, paint, or tires.",
        "key_dates": [],
    },
    "UT": {
        "name": "Utah",
        "status": "none",
        "programs": [],
        "summary": "Utah has no statewide EPR programs.",
        "key_dates": [],
    },
    "VT": {
        "name": "Vermont",
        "status": "limited",
        "programs": [
            "Electronics — Vermont E-Cycles program (manufacturer take-back, 2010)",
            "Paint — PaintCare program",
        ],
        "summary": (
            "Vermont has long-standing EPR programs for electronics and paint. The state has explored packaging "
            "EPR but has not yet enacted legislation. Vermont's small size and progressive policy environment "
            "make it an active participant in EPR policy discussions."
        ),
        "key_dates": [
            "2010 — Electronics take-back law enacted",
            "2014 — PaintCare program launched",
            "2024 — Packaging EPR feasibility study underway",
        ],
    },
    "VA": {
        "name": "Virginia",
        "status": "none",
        "programs": [],
        "summary": "Virginia has no statewide EPR programs, though paint stewardship discussions are ongoing.",
        "key_dates": [],
    },
    "WA": {
        "name": "Washington",
        "status": "comprehensive",
        "programs": [
            "Packaging EPR — HB 1131 (2024): Recycling Modernization Act (packaging producer responsibility)",
            "Electronics — Washington E-Cycles program (manufacturer take-back, 2006)",
            "Paint — PaintCare program",
            "Tires — Washington Tire Recycling Program (retailer collection mandate)",
        ],
        "summary": (
            "Washington enacted landmark packaging EPR legislation in 2024 (HB 1131), joining the growing list "
            "of states with comprehensive producer responsibility laws. Washington has had electronics and paint "
            "take-back programs for nearly two decades and operates one of the country's most effective tire "
            "recycling programs."
        ),
        "key_dates": [
            "2006 — Washington E-Cycles electronics program launched (one of first in US)",
            "2010 — PaintCare program launched",
            "2013 — Tire Recycling Program strengthened",
            "Mar 2024 — HB 1131 (packaging EPR) signed into law",
            "2026 — Producer Responsibility Organization operational",
        ],
    },
    "WV": {
        "name": "West Virginia",
        "status": "none",
        "programs": [],
        "summary": "West Virginia has no statewide EPR programs.",
        "key_dates": [],
    },
    "WI": {
        "name": "Wisconsin",
        "status": "none",
        "programs": [],
        "summary": "Wisconsin has no statewide EPR programs.",
        "key_dates": [],
    },
    "WY": {
        "name": "Wyoming",
        "status": "none",
        "programs": [],
        "summary": "Wyoming has no statewide EPR programs.",
        "key_dates": [],
    },
}


# Public export alias for use by excel_exporter and other modules
_EPR_STATE_DATA = _EPR_STATES


def _escape_js(text: str) -> str:
    """Escape a string for safe embedding in a JS string literal."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _activity_class(abbr: str, activity_counts: Optional[Dict[str, int]]) -> str:
    """Return an activity CSS class based on article count for this jurisdiction."""
    if not activity_counts:
        return ""
    count = activity_counts.get(abbr, 0)
    if count == 0:
        return ""
    elif count <= 2:
        return " activity-1"
    elif count <= 5:
        return " activity-2"
    else:
        return " activity-3"


def _build_state_cells(states: dict, activity_counts: Optional[Dict[str, int]] = None) -> str:
    """Return HTML div elements for every state cell."""
    cells = []
    for abbr, (row, col) in _STATE_GRID.items():
        state = states.get(abbr)
        if not state:
            continue
        status = state.get("status", "none")
        color = _STATUS_COLORS.get(status, _STATUS_COLORS["none"])
        act_class = _activity_class(abbr, activity_counts)

        cells.append(
            f'<div class="state-cell status-{status}{act_class}" '
            f'style="grid-row:{row + 1};grid-column:{col + 1};background-color:{color};" '
            f'data-abbr="{abbr}" '
            f'onclick="showDetail(\'{abbr}\')" '
            f'title="{state["name"]}">'
            f'{abbr}'
            f'</div>'
        )
    return "\n".join(cells)


def _build_state_js_data(states: dict) -> str:
    """Return a JS object literal containing all state data."""
    entries = []
    for abbr, state in states.items():
        programs_js = json.dumps(state.get("programs", []))
        key_dates_js = json.dumps(state.get("key_dates", []))
        entries.append(
            f'  "{abbr}": {{'
            f'"name": "{_escape_js(state["name"])}", '
            f'"status": "{state["status"]}", '
            f'"programs": {programs_js}, '
            f'"summary": "{_escape_js(state.get("summary", ""))}", '
            f'"key_dates": {key_dates_js}'
            f'}}'
        )
    return "{\n" + ",\n".join(entries) + "\n}"


def generate_epr_map(output_path: Path = None, activity_counts: Optional[Dict[str, int]] = None) -> Path:
    """Generate the interactive EPR state map HTML. Returns the output path."""
    today = date.today().strftime("%Y-%m-%d")

    if output_path is None:
        output_path = Config.DATA_DIR / f"epr_map_{today}.html"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    states = _EPR_STATES
    last_updated = today

    state_cells_html = _build_state_cells(states, activity_counts=activity_counts)
    state_js_data = _build_state_js_data(states)

    # Build legend items
    legend_items = []
    for status, color in _STATUS_COLORS.items():
        legend_items.append(
            f'<div class="legend-item">'
            f'<span class="legend-swatch" style="background:{color};"></span>'
            f'<span class="legend-label">{_STATUS_LABELS[status]}</span>'
            f'</div>'
        )
    legend_html = "\n".join(legend_items)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EPR State Tracker</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: #F0F4F8;
      color: #2D3748;
      font-size: 14px;
      line-height: 1.5;
    }}

    /* ---- Header ---- */
    .page-header {{
      background: linear-gradient(135deg, #0A2540 0%, #1B4B82 100%);
      padding: 20px 32px 16px;
    }}
    .page-header .brand {{
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: #7EC8E3;
      margin: 0 0 4px;
    }}
    .page-header h1 {{
      font-size: 20px;
      font-weight: 800;
      color: #fff;
      margin: 0 0 4px;
    }}
    .page-header .sub {{
      font-size: 12px;
      color: #A8CBE8;
      margin: 0;
    }}

    /* ---- Layout ---- */
    .page-body {{
      display: flex;
      gap: 24px;
      padding: 24px 32px;
      align-items: flex-start;
    }}

    /* ---- Map panel ---- */
    .map-panel {{
      flex: 1 1 auto;
      min-width: 0;
    }}

    .map-title {{
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: #718096;
      margin: 0 0 12px;
    }}

    /* CSS Grid cartogram — 9 rows x 12 cols, identical to PFAS map */
    .state-grid {{
      display: grid;
      grid-template-columns: repeat(12, 50px);
      grid-template-rows: repeat(9, 50px);
      gap: 4px;
      width: fit-content;
    }}

    .state-cell {{
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 800;
      color: #fff;
      cursor: pointer;
      position: relative;
      transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease;
      user-select: none;
      letter-spacing: 0.5px;
    }}
    .state-cell:hover {{
      transform: scale(1.12);
      box-shadow: 0 4px 12px rgba(0,0,0,0.20);
      z-index: 10;
      filter: brightness(1.08);
    }}
    .state-cell.active {{
      transform: scale(1.15);
      box-shadow: 0 0 0 3px #fff, 0 0 0 5px #1B4B82;
      z-index: 20;
    }}
    .status-none {{
      color: #4A6079;
    }}
    .status-proposed {{
      color: #1B4B82;
    }}

    /* ---- Activity heat layer ---- */
    .activity-1 {{ box-shadow: inset 0 -3px 0 #DD6B20; }}
    .activity-2 {{ box-shadow: inset 0 -3px 0 #C05621; }}
    .activity-3 {{ box-shadow: inset 0 -3px 0 #9C4221; }}

    /* ---- Download button ---- */
    .download-btn {{
      display: inline-block;
      background: #2C2C2C;
      color: white;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 10px 20px;
      text-decoration: none;
      border-radius: 2px;
      margin-bottom: 16px;
    }}

    /* ---- Legend ---- */
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px 20px;
      margin-top: 16px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .legend-swatch {{
      width: 14px;
      height: 14px;
      border-radius: 3px;
      flex-shrink: 0;
      border: 1px solid rgba(0,0,0,0.08);
    }}
    .legend-label {{
      font-size: 12px;
      color: #4A5568;
    }}

    /* ---- Detail panel ---- */
    .detail-panel {{
      flex: 0 0 310px;
      background: #fff;
      border: 1px solid #C9DCF0;
      border-radius: 8px;
      padding: 20px;
      min-height: 200px;
      transition: opacity 0.2s ease;
      position: sticky;
      top: 24px;
    }}

    .detail-empty {{
      color: #A0AEC0;
      font-style: italic;
      font-size: 13px;
      text-align: center;
      padding: 40px 0;
    }}

    .detail-abbr {{
      font-size: 28px;
      font-weight: 900;
      color: #0A2540;
      line-height: 1;
      margin: 0 0 2px;
    }}
    .detail-name {{
      font-size: 16px;
      font-weight: 700;
      color: #2D3748;
      margin: 0 0 8px;
    }}
    .detail-status-badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #fff;
      margin-bottom: 14px;
    }}
    .detail-status-badge.badge-none {{
      color: #4A5568;
    }}
    .detail-status-badge.badge-proposed {{
      color: #1B4B82;
    }}

    .detail-section-label {{
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: #A0AEC0;
      margin: 14px 0 4px;
    }}
    .detail-summary {{
      font-size: 13px;
      color: #4A5568;
      line-height: 1.6;
      margin: 0;
    }}
    .detail-programs {{
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .detail-programs li {{
      font-size: 12px;
      color: #4A5568;
      padding: 4px 0;
      border-bottom: 1px solid #EDF2F7;
      line-height: 1.5;
    }}
    .detail-programs li:last-child {{
      border-bottom: none;
    }}
    .detail-programs li::before {{
      content: "▸ ";
      color: #4A9EC4;
      font-size: 10px;
    }}
    .detail-dates {{
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .detail-dates li {{
      font-size: 12px;
      color: #4A5568;
      padding: 3px 0;
      border-bottom: 1px solid #F7FAFC;
      line-height: 1.5;
    }}
    .detail-dates li:last-child {{
      border-bottom: none;
    }}

    /* ---- Footer ---- */
    .page-footer {{
      padding: 12px 32px;
      border-top: 1px solid #C9DCF0;
      font-size: 11px;
      color: #A0AEC0;
    }}
  </style>
</head>
<body>

<div class="page-header">
  <p class="brand">Compliance Intelligence</p>
  <h1>EPR State Tracker</h1>
  <p class="sub">Extended Producer Responsibility laws covering packaging, electronics, paint &amp; tires &nbsp;&middot;&nbsp; Last updated: {last_updated}</p>
</div>

<div class="page-body">

  <!-- Map -->
  <div class="map-panel">
    <a class="download-btn" href="./epr-tracker.xlsx" download>&#8595; Download Excel</a>
    <p class="map-title">Click any state for details</p>
    <div class="state-grid" id="stateGrid">
{state_cells_html}
    </div>

    <div class="legend">
{legend_html}
      <div class="legend-item">
        <span class="legend-swatch" style="background:#E8EDF0;box-shadow:inset 0 -3px 0 #DD6B20;"></span>
        <span class="legend-label">Activity this week (amber = articles mentioning this state)</span>
      </div>
    </div>
  </div>

  <!-- Detail panel -->
  <div class="detail-panel" id="detailPanel">
    <div class="detail-empty" id="detailEmpty">Select a state to see its EPR programs</div>
    <div id="detailContent" style="display:none;"></div>
  </div>

</div>

<div class="page-footer">
  Data current as of {last_updated}. This tracker covers enacted and proposed state EPR laws for packaging/plastics,
  electronics/e-waste, paint, and tires. Program scope and deadlines vary by state. Verify compliance obligations
  with legal counsel before making business decisions.
</div>

<script>
var STATE_DATA = {state_js_data};

var STATUS_COLORS = {{
  "comprehensive": "#1B6CA8",
  "limited":       "#4A9EC4",
  "proposed":      "#A8D4E8",
  "none":          "#E8EDF0"
}};

var STATUS_LABELS = {{
  "comprehensive": "Comprehensive Programs",
  "limited":       "Limited Programs (1-2)",
  "proposed":      "Proposed Legislation",
  "none":          "No EPR Programs"
}};

var activeAbbr = null;

function showDetail(abbr) {{
  var state = STATE_DATA[abbr];
  if (!state) return;

  // Toggle active cell highlight
  if (activeAbbr) {{
    var prev = document.querySelector('[data-abbr="' + activeAbbr + '"]');
    if (prev) prev.classList.remove('active');
  }}
  activeAbbr = abbr;
  var cell = document.querySelector('[data-abbr="' + abbr + '"]');
  if (cell) cell.classList.add('active');

  var color = STATUS_COLORS[state.status] || '#E8EDF0';
  var statusLabel = STATUS_LABELS[state.status] || state.status;

  // Badge text colour: dark for light-background statuses
  var badgeExtraClass = (state.status === 'none' || state.status === 'proposed') ? ' badge-' + state.status : '';

  // Build programs list
  var programsHtml = '';
  if (state.programs && state.programs.length > 0) {{
    programsHtml = '<p class="detail-section-label">Active &amp; Proposed Programs</p><ul class="detail-programs">';
    state.programs.forEach(function(p) {{
      programsHtml += '<li>' + escapeHtml(p) + '</li>';
    }});
    programsHtml += '</ul>';
  }}

  // Build dates list
  var datesHtml = '';
  if (state.key_dates && state.key_dates.length > 0) {{
    datesHtml = '<p class="detail-section-label">Key Dates</p><ul class="detail-dates">';
    state.key_dates.forEach(function(d) {{
      datesHtml += '<li>' + escapeHtml(d) + '</li>';
    }});
    datesHtml += '</ul>';
  }}

  var html = '<div class="detail-abbr">' + abbr + '</div>'
    + '<div class="detail-name">' + escapeHtml(state.name) + '</div>'
    + '<span class="detail-status-badge' + badgeExtraClass + '" style="background:' + color + ';">'
    + escapeHtml(statusLabel)
    + '</span>'
    + '<p class="detail-section-label">Overview</p>'
    + '<p class="detail-summary">' + escapeHtml(state.summary) + '</p>'
    + programsHtml
    + datesHtml;

  document.getElementById('detailEmpty').style.display = 'none';
  var content = document.getElementById('detailContent');
  content.style.display = 'block';
  content.innerHTML = html;
}}

function escapeHtml(str) {{
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}}

// Auto-select CA on load as a high-interest state
window.addEventListener('DOMContentLoaded', function() {{
  showDetail('CA');
}});
</script>

</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    logger.info(f"EPR state map written to: {output_path}")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = generate_epr_map()
    print(f"Map generated: {path}")
