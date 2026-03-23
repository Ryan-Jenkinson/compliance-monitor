"""Generate an interactive PFAS state compliance map as a self-contained HTML file."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent.parent / "config" / "pfas_state_data.json"
_DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "state_maps" / "pfas_map.html"

# Grid layout: (grid-row, grid-col) — 0-indexed, 9 rows x 12 cols
# Row 0: ME
# Row 1: VT, NH
# Row 2: WA MT ND MN .. WI MI .. NY MA RI CT
# Row 3: OR ID WY SD IA IL IN OH PA NJ
# Row 4: CA NV UT CO NE MO KY WV VA MD DE
# Row 5: .. AZ NM .. KS TN NC SC
# Row 6: .. .. .. OK AR MS GA AL
# Row 7: .. .. .. TX LA .. .. .. FL
# Row 8: AK HI
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
    "comprehensive": "#C53030",
    "limited":       "#D69E2E",
    "proposed":      "#3182CE",
    "none":          "#CBD5E0",
}

_STATUS_LABELS: dict[str, str] = {
    "comprehensive": "Comprehensive Law",
    "limited":       "Limited / Partial Law",
    "proposed":      "Proposed Legislation",
    "none":          "No Significant Law",
}


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
        is_home = "HOME STATE" in state.get("company_note", "")
        home_dot = '<span class="home-dot"></span>' if is_home else ""
        act_class = _activity_class(abbr, activity_counts)

        # Build tooltip data attribute (used by JS click handler)
        cells.append(
            f'<div class="state-cell status-{status}{act_class}" '
            f'style="grid-row:{row + 1};grid-column:{col + 1};background-color:{color};" '
            f'data-abbr="{abbr}" '
            f'onclick="showDetail(\'{abbr}\')" '
            f'title="{state["name"]}">'
            f'{home_dot}'
            f'{abbr}'
            f'</div>'
        )
    return "\n".join(cells)


def _build_state_js_data(states: dict) -> str:
    """Return a JS object literal containing all state data."""
    entries = []
    for abbr, state in states.items():
        laws_js = json.dumps(state.get("laws", []))
        key_dates_js = json.dumps(state.get("key_dates", []))
        entries.append(
            f'  "{abbr}": {{'
            f'"name": "{_escape_js(state["name"])}", '
            f'"status": "{state["status"]}", '
            f'"laws": {laws_js}, '
            f'"summary": "{_escape_js(state.get("summary", ""))}", '
            f'"key_dates": {key_dates_js}, '
            f'"company_note": "{_escape_js(state.get("company_note", ""))}"'
            f'}}'
        )
    return "{\n" + ",\n".join(entries) + "\n}"


def generate_pfas_map(output_path: Path = None, activity_counts: Optional[Dict[str, int]] = None) -> Path:
    """Generate the interactive PFAS state map HTML. Returns the output path."""
    if output_path is None:
        output_path = _DEFAULT_OUTPUT

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(_DATA_PATH) as f:
        data = json.load(f)

    states = data["states"]
    last_updated = data.get("last_updated", "unknown")

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
  <title>PFAS State Compliance Tracker</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: #F4F5F7;
      color: #2D3748;
      font-size: 14px;
      line-height: 1.5;
    }}

    /* ---- Header ---- */
    .page-header {{
      background: linear-gradient(135deg, #0D1B2E 0%, #1A3050 100%);
      padding: 20px 32px 16px;
    }}
    .page-header .brand {{
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: #C4A55A;
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
      color: #8BAAC8;
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

    /* CSS Grid cartogram */
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
      box-shadow: 0 4px 12px rgba(0,0,0,0.25);
      z-index: 10;
      filter: brightness(1.1);
    }}
    .state-cell.active {{
      transform: scale(1.15);
      box-shadow: 0 0 0 3px #fff, 0 0 0 5px #1A3050;
      z-index: 20;
    }}
    .status-none {{
      color: #4A5568;
    }}

    /* Home state dot */
    .home-dot {{
      position: absolute;
      top: 5px;
      right: 5px;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #C4A55A;
      border: 1px solid rgba(255,255,255,0.8);
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
    }}
    .legend-label {{
      font-size: 12px;
      color: #4A5568;
    }}

    .home-note {{
      margin-top: 10px;
      font-size: 11px;
      color: #718096;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .home-note-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #C4A55A;
      flex-shrink: 0;
    }}

    /* ---- Detail panel ---- */
    .detail-panel {{
      flex: 0 0 300px;
      background: #fff;
      border: 1px solid #E2E8F0;
      border-radius: 8px;
      padding: 20px;
      min-height: 200px;
      transition: opacity 0.2s ease;
      position: sticky;
      top: 24px;
      position: relative;
    }}
    .detail-close {{ display: none; }}
    .detail-overlay {{ display: none; }}

    @media (max-width: 768px) {{
      .page-body {{ flex-direction: column; }}
      .detail-overlay {{
        display: block;
        visibility: hidden;
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.5);
        z-index: 999;
        opacity: 0;
        transition: opacity 0.2s ease;
      }}
      .detail-overlay.open {{ visibility: visible; opacity: 1; }}
      .detail-panel {{
        display: none !important;
        position: fixed !important;
        bottom: 0 !important; left: 0 !important; right: 0 !important;
        top: auto !important;
        width: 100% !important;
        max-height: 65vh;
        overflow-y: auto;
        z-index: 1000;
        border-radius: 12px 12px 0 0 !important;
        box-shadow: 0 -4px 24px rgba(0,0,0,0.2);
        padding: 20px 20px 32px;
      }}
      .detail-panel.open {{ display: block !important; }}
      .detail-close {{
        display: block;
        position: absolute;
        top: 12px; right: 14px;
        font-size: 22px; line-height: 1;
        cursor: pointer;
        color: #718096;
        background: none; border: none; padding: 4px;
        z-index: 1001;
      }}
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
      color: #1A2B3C;
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
    .detail-laws {{
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .detail-laws li {{
      font-size: 12px;
      color: #4A5568;
      padding: 2px 0;
    }}
    .detail-laws li::before {{
      content: "§ ";
      color: #A0AEC0;
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
    .company-note {{
      background: #FFFBEB;
      border-left: 3px solid #D69E2E;
      border-radius: 0 4px 4px 0;
      padding: 10px 12px;
      font-size: 12px;
      color: #744210;
      line-height: 1.5;
      margin-top: 4px;
    }}
    .company-note strong {{
      display: block;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #975A16;
      margin-bottom: 4px;
    }}

    /* ---- Footer ---- */
    .page-footer {{
      padding: 12px 32px;
      border-top: 1px solid #E2E8F0;
      font-size: 11px;
      color: #A0AEC0;
    }}

    /* ---- Activity heat layer ---- */
    .activity-1 {{ box-shadow: inset 0 -3px 0 #DD6B20; }}
    .activity-2 {{ box-shadow: inset 0 -3px 0 #C05621; }}
    .activity-3 {{ box-shadow: inset 0 -3px 0 #9C4221; }}

    /* ---- Download button ---- */
    .download-btn {{
      display: inline-block;
      background: #2C3748;
      color: #fff;
      font-family: -apple-system, sans-serif;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 1px;
      text-transform: uppercase;
      padding: 7px 14px;
      text-decoration: none;
      border-radius: 3px;
      margin-top: 8px;
    }}

    /* ---- Site nav ---- */
    .site-nav {{
      background: #0A1628;
      border-bottom: 1px solid #162540;
      padding: 7px 32px;
      display: flex;
      align-items: center;
      gap: 4px;
      flex-wrap: wrap;
    }}
    .nav-section {{
      color: #3A5070;
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 0 6px 0 2px;
    }}
    .nav-sep {{
      width: 1px;
      height: 14px;
      background: #1E3050;
      margin: 0 8px;
    }}
    .nav-item {{
      color: #6A8CAA;
      font-size: 11px;
      font-weight: 500;
      text-decoration: none;
      padding: 3px 9px;
      border-radius: 2px;
      transition: background 0.12s, color 0.12s;
    }}
    .nav-item:hover {{ background: rgba(255,255,255,0.07); color: #CBD5E0; }}
    .nav-item.active {{ background: rgba(196,165,90,0.14); color: #C4A55A; font-weight: 600; }}
  </style>
</head>
<body>

<div class="page-header">
  <p class="brand">Compliance Intelligence</p>
  <h1>PFAS State Compliance Tracker</h1>
  <p class="sub">Interactive map of US state PFAS laws &amp; restrictions &nbsp;&middot;&nbsp; Last updated: {last_updated}</p>
  <a class="download-btn" href="./pfas-tracker.xlsx" download>&#8595; Download Excel</a>
  <a class="download-btn" href="./pfas-timeline.html" style="margin-left:8px;">&#9201; Deadline Timeline</a>
</div>
<nav class="site-nav">
  <span class="nav-section">Maps</span>
  <a href="./index.html" class="nav-item active">PFAS</a>
  <a href="./epr-map.html" class="nav-item">EPR</a>
  <a href="./reach-map.html" class="nav-item">REACH</a>
  <div class="nav-sep"></div>
  <span class="nav-section">Timelines</span>
  <a href="./pfas-timeline.html" class="nav-item">PFAS</a>
  <a href="./epr-timeline.html" class="nav-item">EPR</a>
  <a href="./reach-timeline.html" class="nav-item">REACH</a>
  <a href="./tsca-timeline.html" class="nav-item">TSCA</a>
  <a href="./deadline-timeline.html" class="nav-item">All Topics</a>
</nav>

<div class="page-body">

  <!-- Map -->
  <div class="map-panel">
    <p class="map-title">Click any state for details</p>
    <div class="state-grid" id="stateGrid">
{state_cells_html}
    </div>

    <div class="legend">
{legend_html}
    </div>

    <div class="home-note">
      <span class="home-note-dot"></span>
      <span>Gold dot = MN — subject to Amara's Law</span>
    </div>
  </div>

  <!-- Detail panel -->
  <div class="detail-overlay" id="detailOverlay" onclick="closeDetail()"></div>
  <div class="detail-panel" id="detailPanel">
    <button class="detail-close" onclick="closeDetail()" aria-label="Close">&#x2715;</button>
    <div class="detail-empty" id="detailEmpty">Select a state to see details</div>
    <div id="detailContent" style="display:none;"></div>
  </div>

</div>

<div class="page-footer">
  Data current as of {last_updated}. This tracker covers enacted and proposed state PFAS product laws;
  it does not cover federal EPA rules. Verify compliance status with legal counsel before making compliance decisions.
</div>

<script>
var STATE_DATA = {state_js_data};

var STATUS_COLORS = {{
  "comprehensive": "#C53030",
  "limited":       "#D69E2E",
  "proposed":      "#3182CE",
  "none":          "#CBD5E0"
}};

var STATUS_LABELS = {{
  "comprehensive": "Comprehensive Law",
  "limited":       "Limited / Partial Law",
  "proposed":      "Proposed Legislation",
  "none":          "No Significant Law"
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

  var color = STATUS_COLORS[state.status] || '#CBD5E0';
  var statusLabel = STATUS_LABELS[state.status] || state.status;

  // Build laws list
  var lawsHtml = '';
  if (state.laws && state.laws.length > 0) {{
    lawsHtml = '<p class="detail-section-label">Enacted Laws</p><ul class="detail-laws">';
    state.laws.forEach(function(l) {{
      lawsHtml += '<li>' + escapeHtml(l) + '</li>';
    }});
    lawsHtml += '</ul>';
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

  // Company note
  var noteHtml = '';
  if (state.company_note) {{
    noteHtml = '<p class="detail-section-label">Company Relevance</p>'
      + '<div class="company-note"><strong>Compliance Note</strong>' + escapeHtml(state.company_note) + '</div>';
  }}

  var summaryHtml = (state.status !== 'none' && state.summary)
    ? '<p class="detail-section-label">Summary</p><p class="detail-summary">' + escapeHtml(state.summary) + '</p>'
    : '';

  var html = '<div class="detail-abbr">' + abbr + '</div>'
    + '<div class="detail-name">' + escapeHtml(state.name) + '</div>'
    + '<span class="detail-status-badge" style="background:' + color + ';">' + escapeHtml(statusLabel) + '</span>'
    + summaryHtml
    + lawsHtml
    + datesHtml
    + noteHtml;

  document.getElementById('detailEmpty').style.display = 'none';
  var content = document.getElementById('detailContent');
  content.style.display = 'block';
  content.innerHTML = html;

  if (window.innerWidth <= 768) {{
    document.getElementById('detailPanel').classList.add('open');
    document.getElementById('detailOverlay').classList.add('open');
  }}
}}

function closeDetail() {{
  document.getElementById('detailPanel').classList.remove('open');
  document.getElementById('detailOverlay').classList.remove('open');
}}

function escapeHtml(str) {{
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}}

// Auto-select MN on load (home state)
window.addEventListener('DOMContentLoaded', function() {{
  showDetail('MN');
}});
</script>

</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    logger.info(f"PFAS state map written to: {output_path}")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = generate_pfas_map()
    print(f"Map generated: {path}")
