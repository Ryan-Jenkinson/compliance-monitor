"""
Generate a standalone PFAS Legislative Intelligence preview map.
Shows US states with any PFAS legislative activity — from early discussions
through enacted-and-watching — for legal team engagement prioritization.

Data source: pfas_intel_pipeline.py output or fallback to direct Claude call.
Preview only — not pushed to GitHub Pages.
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "state_maps" / "pfas_proposed_preview.html"
_PIPELINE_RESULT = Path(__file__).parent.parent / "data" / "cache" / "claude" / "pfas_legislative_intel_result.json"

# Same grid layout as the PFAS compliance map
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

# Expanded stage taxonomy — from earliest signals to enacted-watching
_STAGE_COLORS = {
    "pre_discussion":    "#6B7280",   # warm gray — early signals, advocacy targeting
    "discussion":        "#9333EA",   # violet — hearings, task forces, study commissions
    "rulemaking":        "#DC2626",   # red — active rulemaking proceedings
    "introduced":        "#2563EB",   # blue — bill filed
    "committee":         "#7C3AED",   # purple — in committee
    "passed_one":        "#D97706",   # amber — passed one chamber
    "advanced":          "#EA580C",   # orange — near final passage
    "enacted_watching":  "#059669",   # green — enacted, open comment/implementation
    "none":              "#CBD5E0",   # light gray
}

_STAGE_LABELS = {
    "pre_discussion":    "Early Signals / Pre-Discussion",
    "discussion":        "Active Discussion / Task Force",
    "rulemaking":        "Rulemaking In Progress",
    "introduced":        "Bill Introduced",
    "committee":         "In Committee",
    "passed_one":        "Passed One Chamber",
    "advanced":          "Near Passage",
    "enacted_watching":  "Enacted — Watching Implementation",
    "none":              "No Activity Detected",
}

# Confidence badge colors
_CONFIDENCE_COLORS = {
    "high":   "#059669",
    "medium": "#D97706",
    "low":    "#9CA3AF",
}


def _escape_js(text: str) -> str:
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _load_pipeline_data() -> dict:
    """Load data from the intelligence pipeline result file."""
    if _PIPELINE_RESULT.exists():
        try:
            data = json.loads(_PIPELINE_RESULT.read_text())
            if data.get("states"):
                logger.info(f"Loaded pipeline result: {len(data['states'])} states")
                return data
        except Exception as e:
            logger.warning(f"Failed to load pipeline result: {e}")
    return {}


def _build_cells(states: dict) -> str:
    cells = []
    for abbr, (row, col) in _STATE_GRID.items():
        state = states.get(abbr, {})
        stage = state.get("stage", "none")
        color = _STAGE_COLORS.get(stage, _STAGE_COLORS["none"])
        confidence = state.get("confidence", "")

        # Add confidence indicator dot
        conf_dot = ""
        if confidence and stage != "none":
            conf_color = _CONFIDENCE_COLORS.get(confidence, "")
            if conf_color:
                conf_dot = (
                    f'<span style="position:absolute;top:3px;right:3px;'
                    f'width:6px;height:6px;border-radius:50%;'
                    f'background:{conf_color};border:1px solid rgba(255,255,255,0.6);"></span>'
                )

        cells.append(
            f'<div class="state-cell stage-{stage}" '
            f'style="grid-row:{row+1};grid-column:{col+1};background-color:{color};" '
            f'data-abbr="{abbr}" '
            f'onclick="showDetail(\'{abbr}\')" '
            f'title="{state.get("name", abbr)}">'
            f'{conf_dot}'
            f'{abbr}'
            f'</div>'
        )
    return "\n".join(cells)


def _build_js_data(states: dict) -> str:
    entries = []
    for abbr, state in states.items():
        bills_js = json.dumps(state.get("bills", []))
        evidence_js = json.dumps(state.get("evidence_sources", []))
        entries.append(
            f'  "{abbr}": {{'
            f'"name": "{_escape_js(state.get("name", abbr))}", '
            f'"stage": "{state.get("stage", "none")}", '
            f'"bills": {bills_js}, '
            f'"summary": "{_escape_js(state.get("summary", ""))}", '
            f'"scope": "{_escape_js(state.get("scope", ""))}", '
            f'"company_relevance": "{_escape_js(state.get("company_relevance", ""))}", '
            f'"company_impact": "{_escape_js(state.get("company_impact", ""))}", '
            f'"session": "{_escape_js(state.get("session", ""))}", '
            f'"engagement_note": "{_escape_js(state.get("engagement_note", ""))}", '
            f'"confidence": "{state.get("confidence", "")}", '
            f'"evidence_sources": {evidence_js}'
            f'}}'
        )
    return "{\n" + ",\n".join(entries) + "\n}"


def generate_pfas_proposed_map(output_path: Path = None) -> Path:
    if output_path is None:
        output_path = _DEFAULT_OUTPUT
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Try pipeline data first, then fall back to direct Claude call
    data = _load_pipeline_data()
    if not data:
        logger.info("No pipeline data found. Run pfas_intel_pipeline.py first.")
        return output_path

    states = data.get("states", {})
    generated = data.get("generated", "2026-03-23")
    pipeline_version = data.get("pipeline_version", "unknown")

    state_cells_html = _build_cells(states)
    state_js_data = _build_js_data(states)

    # Legend — only show stages that actually appear in the data
    used_stages = set(s.get("stage", "none") for s in states.values())
    legend_items = []
    for stage, color in _STAGE_COLORS.items():
        if stage == "none" or stage not in used_stages:
            continue
        legend_items.append(
            f'<div class="legend-item">'
            f'<span class="legend-swatch" style="background:{color};"></span>'
            f'<span class="legend-label">{_STAGE_LABELS[stage]}</span>'
            f'</div>'
        )
    legend_html = "\n".join(legend_items)

    active_count = sum(1 for s in states.values() if s.get("stage", "none") != "none")

    # Count by stage for stats
    by_stage: dict[str, int] = {}
    for s in states.values():
        stage = s.get("stage", "none")
        if stage != "none":
            by_stage[stage] = by_stage.get(stage, 0) + 1

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PFAS Legislative Intelligence — Preview</title>
  <script src="https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: #F0F2F5;
      color: #2D3748;
      font-size: 14px;
      line-height: 1.5;
    }}

    /* ---- Preview banner ---- */
    .preview-banner {{
      background: linear-gradient(90deg, #7C2D12 0%, #92400E 100%);
      color: #FFF3CD;
      text-align: center;
      padding: 8px 24px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.3px;
    }}
    .preview-banner strong {{
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 1.5px;
    }}

    /* ---- Header ---- */
    .page-header {{
      background: #fff;
      border-bottom: 1px solid #E2E8F0;
      padding: 24px 32px 20px;
    }}
    .page-header .header-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }}
    .page-header .brand {{
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: #7C3AED;
      margin: 0 0 6px;
    }}
    .page-header h1 {{
      font-size: 24px;
      font-weight: 800;
      color: #111827;
      margin: 0 0 6px;
    }}
    .export-btn {{
      background: #2563EB;
      color: #fff;
      border: none;
      padding: 10px 20px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      letter-spacing: 0.3px;
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      transition: background 0.15s;
    }}
    .export-btn:hover {{ background: #1D4ED8; }}
    .export-btn svg {{ width: 16px; height: 16px; fill: currentColor; }}
    .page-header .sub {{
      font-size: 13px;
      color: #4B5563;
      margin: 0 0 4px;
    }}
    .page-header .intent-note {{
      font-size: 12px;
      color: #6B7280;
      margin: 10px 0 0;
      max-width: 720px;
      line-height: 1.6;
    }}

    /* ---- Stats bar ---- */
    .stats-bar {{
      background: #F8FAFC;
      border-bottom: 1px solid #E2E8F0;
      padding: 10px 32px;
      display: flex;
      gap: 24px;
      flex-wrap: wrap;
    }}
    .stat-chip {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: #6B7280;
    }}
    .stat-chip strong {{
      color: #111827;
      font-weight: 700;
      font-size: 16px;
    }}
    .stat-dot {{
      width: 10px;
      height: 10px;
      border-radius: 2px;
      flex-shrink: 0;
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
      filter: brightness(1.15);
    }}
    .state-cell.active {{
      transform: scale(1.15);
      box-shadow: 0 0 0 3px #fff, 0 0 0 5px #7C3AED;
      z-index: 20;
    }}
    .stage-none {{
      color: #718096;
    }}
    .stage-pre_discussion {{
      opacity: 0.85;
    }}

    /* ---- Legend ---- */
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
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

    /* Confidence legend */
    .confidence-legend {{
      margin-top: 10px;
      display: flex;
      gap: 14px;
      align-items: center;
    }}
    .confidence-legend .cl-label {{
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #A0AEC0;
    }}
    .confidence-legend .cl-item {{
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: #718096;
    }}
    .confidence-legend .cl-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }}

    /* ---- Detail panel ---- */
    .detail-panel {{
      flex: 0 0 340px;
      background: #fff;
      border: 1px solid #E2E8F0;
      border-radius: 8px;
      padding: 20px;
      min-height: 280px;
      position: sticky;
      top: 24px;
      max-height: calc(100vh - 48px);
      overflow-y: auto;
    }}
    .detail-close {{ display: none; }}
    .detail-overlay {{ display: none; }}

    @media (max-width: 800px) {{
      .page-body {{ flex-direction: column; }}
      .detail-overlay {{
        display: block; visibility: hidden;
        position: fixed; inset: 0;
        background: rgba(0,0,0,0.5); z-index: 999;
        opacity: 0; transition: opacity 0.2s;
      }}
      .detail-overlay.open {{ visibility: visible; opacity: 1; }}
      .detail-panel {{
        display: none !important;
        position: fixed !important;
        bottom: 0 !important; left: 0 !important; right: 0 !important;
        top: auto !important; width: 100% !important;
        max-height: 65vh; overflow-y: auto;
        z-index: 1000; border-radius: 12px 12px 0 0 !important;
        box-shadow: 0 -4px 24px rgba(0,0,0,0.2);
        padding: 20px 20px 32px;
      }}
      .detail-panel.open {{ display: block !important; }}
      .detail-close {{
        display: block; position: absolute;
        top: 12px; right: 14px;
        font-size: 22px; cursor: pointer;
        color: #718096; background: none; border: none; padding: 4px; z-index: 1001;
      }}
    }}

    .detail-empty {{
      color: #A0AEC0; font-style: italic; font-size: 13px;
      text-align: center; padding: 40px 0;
    }}

    .detail-abbr {{
      font-size: 28px; font-weight: 900; color: #1A2B3C;
      line-height: 1; margin: 0 0 2px;
    }}
    .detail-name {{
      font-size: 16px; font-weight: 700; color: #2D3748; margin: 0 0 8px;
    }}
    .detail-badges {{
      display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px;
    }}
    .detail-badge {{
      display: inline-block; padding: 3px 10px; border-radius: 4px;
      font-size: 10px; font-weight: 800; letter-spacing: 1px;
      text-transform: uppercase; color: #fff;
    }}
    .confidence-badge {{
      display: inline-block; padding: 3px 8px; border-radius: 4px;
      font-size: 9px; font-weight: 700; letter-spacing: 1px;
      text-transform: uppercase; border: 1px solid;
    }}
    .detail-section-label {{
      font-size: 10px; font-weight: 800; letter-spacing: 1.5px;
      text-transform: uppercase; color: #A0AEC0; margin: 14px 0 4px;
    }}
    .detail-summary {{
      font-size: 13px; color: #4A5568; line-height: 1.6; margin: 0;
    }}
    .detail-bills {{
      margin: 0; padding: 0; list-style: none;
    }}
    .detail-bills li {{
      font-size: 12px; color: #4A5568; padding: 4px 0;
      border-bottom: 1px solid #F7FAFC;
    }}
    .detail-bills li::before {{
      content: "\\00A7  "; color: #A0AEC0; font-weight: 700;
    }}
    .scope-tag {{
      display: inline-block; background: #EBF8FF; color: #1E40AF;
      padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600;
      margin: 2px 2px 0 0;
    }}
    .engagement-box {{
      background: #F0FFF4; border-left: 3px solid #059669;
      border-radius: 0 4px 4px 0; padding: 10px 12px;
      font-size: 12px; color: #065F46; line-height: 1.6; margin-top: 4px;
    }}
    .engagement-box strong {{
      display: block; font-size: 10px; font-weight: 800;
      letter-spacing: 1px; text-transform: uppercase;
      color: #047857; margin-bottom: 4px;
    }}
    .evidence-list {{
      margin: 0; padding: 0; list-style: none;
    }}
    .evidence-list li {{
      font-size: 11px; color: #718096; padding: 2px 0;
    }}
    .evidence-list li::before {{
      content: "\\2022  "; color: #A0AEC0;
    }}

    /* Company relevance badges */
    .relevance-badge {{
      display: inline-block; padding: 3px 8px; border-radius: 4px;
      font-size: 9px; font-weight: 700; letter-spacing: 1px;
      text-transform: uppercase; border: 1px solid;
    }}
    .relevance-high {{ color: #DC2626; border-color: #DC2626; background: #FEF2F2; }}
    .relevance-medium {{ color: #D97706; border-color: #D97706; background: #FFFBEB; }}
    .relevance-low {{ color: #6B7280; border-color: #D1D5DB; background: #F9FAFB; }}
    .company-impact-box {{
      background: #FFF7ED; border-left: 3px solid #EA580C;
      border-radius: 0 4px 4px 0; padding: 10px 12px;
      font-size: 12px; color: #9A3412; line-height: 1.6; margin-top: 4px;
    }}
    .company-impact-box strong {{
      display: block; font-size: 10px; font-weight: 800;
      letter-spacing: 1px; text-transform: uppercase;
      color: #C2410C; margin-bottom: 4px;
    }}

    /* ---- Footer ---- */
    .page-footer {{
      padding: 14px 32px; border-top: 1px solid #E2E8F0;
      font-size: 11px; color: #A0AEC0; line-height: 1.6;
    }}
  </style>
</head>
<body>

<div class="preview-banner">
  <strong>Preview Only</strong> &mdash; Internal legal engagement tool. Not published. Data from deep scrape of {len(states)} sources + AI analysis. Always verify against state legislature databases before engaging.
</div>

<div class="page-header">
  <div class="header-top">
    <div>
      <p class="brand">PFAS Legislative Intelligence</p>
      <h1>State PFAS Activity &amp; Engagement Map</h1>
      <p class="sub">{active_count} states with detected PFAS activity &nbsp;&middot;&nbsp; From early advocacy signals through active legislation</p>
    </div>
    <button class="export-btn" onclick="exportToExcel()">
      <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm4 18H6V4h7v5h5v11zM8 15.01l1.41 1.41L11 14.84V20h2v-5.16l1.59 1.59L16 15.01 12.01 11 8 15.01z"/></svg>
      Export to Excel
    </button>
  </div>
  <p class="intent-note">
    This map captures the full spectrum of PFAS legislative activity — not just introduced bills,
    but also pre-discussion signals like advocacy campaigns, AG investigations, study commissions,
    and rulemaking proceedings. States are color-coded by their most advanced stage of activity.
    Corner dots indicate evidence confidence (green = high, amber = medium, gray = low).
    Company relevance is scored against windows/doors manufacturing (direct materials + MRO).
  </p>
</div>

<div class="stats-bar">
  {"".join(f'<div class="stat-chip"><span class="stat-dot" style="background:{_STAGE_COLORS[stage]};"></span><strong>{count}</strong> {_STAGE_LABELS[stage]}</div>' for stage, count in sorted(by_stage.items(), key=lambda x: list(_STAGE_COLORS.keys()).index(x[0])))}
</div>

<div class="page-body">

  <div class="map-panel">
    <p class="map-title">Click any state for details &amp; engagement guidance</p>
    <div class="state-grid" id="stateGrid">
{state_cells_html}
    </div>

    <div class="legend">
{legend_html}
    </div>

    <div class="confidence-legend">
      <span class="cl-label">Confidence:</span>
      <span class="cl-item"><span class="cl-dot" style="background:#059669;"></span> High (direct evidence)</span>
      <span class="cl-item"><span class="cl-dot" style="background:#D97706;"></span> Medium (partial + inference)</span>
      <span class="cl-item"><span class="cl-dot" style="background:#9CA3AF;"></span> Low (weak signals)</span>
    </div>
  </div>

  <div class="detail-overlay" id="detailOverlay" onclick="closeDetail()"></div>
  <div class="detail-panel" id="detailPanel">
    <button class="detail-close" onclick="closeDetail()">&#x2715;</button>
    <div class="detail-empty" id="detailEmpty">Select a state to see details</div>
    <div id="detailContent" style="display:none;"></div>
  </div>

</div>

<div class="page-footer">
  Generated {generated} &middot; Pipeline: {pipeline_version} &middot;
  Sources: law firm blogs, advocacy orgs, legal news, state agencies, EWG, existing PFAS scrapers + AI analysis.
  Legislative status changes frequently. Verify against official state legislature records before taking action.
  This page is a preview and is not part of the published compliance dashboard.
</div>

<script>
var STATE_DATA = {state_js_data};

var STAGE_COLORS = {json.dumps(_STAGE_COLORS)};
var STAGE_LABELS = {json.dumps(_STAGE_LABELS)};
var CONF_COLORS = {json.dumps(_CONFIDENCE_COLORS)};

var activeAbbr = null;

function showDetail(abbr) {{
  var state = STATE_DATA[abbr];
  if (!state) return;

  if (activeAbbr) {{
    var prev = document.querySelector('[data-abbr="' + activeAbbr + '"]');
    if (prev) prev.classList.remove('active');
  }}
  activeAbbr = abbr;
  var cell = document.querySelector('[data-abbr="' + abbr + '"]');
  if (cell) cell.classList.add('active');

  var color = STAGE_COLORS[state.stage] || '#CBD5E0';
  var stageLabel = STAGE_LABELS[state.stage] || state.stage;

  // Build badges
  var badgesHtml = '<div class="detail-badges">';
  badgesHtml += '<span class="detail-badge" style="background:' + color + ';">' + esc(stageLabel) + '</span>';
  if (state.confidence) {{
    var confColor = CONF_COLORS[state.confidence] || '#9CA3AF';
    badgesHtml += '<span class="confidence-badge" style="color:' + confColor + ';border-color:' + confColor + ';">'
      + esc(state.confidence) + ' confidence</span>';
  }}
  if (state.company_relevance) {{
    badgesHtml += '<span class="relevance-badge relevance-' + state.company_relevance + '">'
      + esc(state.company_relevance) + ' relevance</span>';
  }}
  badgesHtml += '</div>';

  if (state.stage === 'none') {{
    var html = '<div class="detail-abbr">' + abbr + '</div>'
      + '<div class="detail-name">' + esc(state.name || abbr) + '</div>'
      + badgesHtml
      + '<p style="font-size:13px;color:#A0AEC0;margin-top:8px;">'
      + (state.summary ? esc(state.summary) : 'No PFAS legislative activity detected for this state.') + '</p>';
    setContent(html);
    return;
  }}

  var summaryHtml = state.summary
    ? '<p class="detail-section-label">Intelligence Summary</p><p class="detail-summary">' + esc(state.summary) + '</p>'
    : '';

  var billsHtml = '';
  if (state.bills && state.bills.length) {{
    billsHtml = '<p class="detail-section-label">Bills / Actions</p><ul class="detail-bills">';
    state.bills.forEach(function(b) {{ billsHtml += '<li>' + esc(b) + '</li>'; }});
    billsHtml += '</ul>';
  }}

  var scopeHtml = '';
  if (state.scope) {{
    scopeHtml = '<p class="detail-section-label">Scope</p><div>';
    state.scope.split(',').forEach(function(s) {{
      s = s.trim();
      if (s) scopeHtml += '<span class="scope-tag">' + esc(s) + '</span>';
    }});
    scopeHtml += '</div>';
  }}

  var companyHtml = '';
  if (state.company_impact) {{
    companyHtml = '<p class="detail-section-label">Impact on Our Business</p>'
      + '<div class="company-impact-box"><strong>Windows &amp; Doors Mfg Impact</strong>' + esc(state.company_impact) + '</div>';
  }}

  var engageHtml = '';
  if (state.engagement_note) {{
    engageHtml = '<p class="detail-section-label">Engagement Guidance</p>'
      + '<div class="engagement-box"><strong>Action Window</strong>' + esc(state.engagement_note) + '</div>';
  }}

  var evidenceHtml = '';
  if (state.evidence_sources && state.evidence_sources.length) {{
    evidenceHtml = '<p class="detail-section-label">Evidence Sources</p><ul class="evidence-list">';
    state.evidence_sources.forEach(function(s) {{ evidenceHtml += '<li>' + esc(s) + '</li>'; }});
    evidenceHtml += '</ul>';
  }}

  var html = '<div class="detail-abbr">' + abbr + '</div>'
    + '<div class="detail-name">' + esc(state.name || abbr) + '</div>'
    + badgesHtml + summaryHtml + billsHtml + scopeHtml + companyHtml + engageHtml + evidenceHtml;

  setContent(html);
}}

function setContent(html) {{
  document.getElementById('detailEmpty').style.display = 'none';
  var content = document.getElementById('detailContent');
  content.style.display = 'block';
  content.innerHTML = html;
  if (window.innerWidth <= 800) {{
    document.getElementById('detailPanel').classList.add('open');
    document.getElementById('detailOverlay').classList.add('open');
  }}
}}

function closeDetail() {{
  document.getElementById('detailPanel').classList.remove('open');
  document.getElementById('detailOverlay').classList.remove('open');
}}

function esc(str) {{
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function exportToExcel() {{
  // Build flat rows for pivot table / PowerBI
  var rows = [];
  var stageOrder = ['enacted_watching','advanced','passed_one','committee','introduced','rulemaking','discussion','pre_discussion','none'];

  Object.keys(STATE_DATA).sort().forEach(function(abbr) {{
    var s = STATE_DATA[abbr];
    var bills = (s.bills || []);

    if (bills.length === 0) {{
      // One row per state even if no bills
      rows.push({{
        'State': abbr,
        'State Name': s.name || abbr,
        'Stage': STAGE_LABELS[s.stage] || s.stage || 'None',
        'Stage Code': s.stage || 'none',
        'Stage Sort Order': stageOrder.indexOf(s.stage || 'none'),
        'Bill Number': '',
        'Scope': s.scope || '',
        'Company Relevance': s.company_relevance || '',
        'Company Impact': (s.company_impact || '').replace(/\\n/g, ' '),
        'Confidence': s.confidence || '',
        'Session': s.session || '',
        'Summary': (s.summary || '').replace(/\\n/g, ' '),
        'Engagement Guidance': (s.engagement_note || '').replace(/\\n/g, ' '),
        'Evidence Sources': (s.evidence_sources || []).join('; '),
        'Generated Date': '{generated}',
      }});
    }} else {{
      // One row per bill for granular pivot
      bills.forEach(function(bill) {{
        rows.push({{
          'State': abbr,
          'State Name': s.name || abbr,
          'Stage': STAGE_LABELS[s.stage] || s.stage || 'None',
          'Stage Code': s.stage || 'none',
          'Stage Sort Order': stageOrder.indexOf(s.stage || 'none'),
          'Bill Number': bill,
          'Scope': s.scope || '',
          'Company Relevance': s.company_relevance || '',
          'Company Impact': (s.company_impact || '').replace(/\\n/g, ' '),
          'Confidence': s.confidence || '',
          'Session': s.session || '',
          'Summary': (s.summary || '').replace(/\\n/g, ' '),
          'Engagement Guidance': (s.engagement_note || '').replace(/\\n/g, ' '),
          'Evidence Sources': (s.evidence_sources || []).join('; '),
          'Generated Date': '{generated}',
        }});
      }});
    }}
  }});

  // Summary sheet — one row per state
  var summaryRows = [];
  Object.keys(STATE_DATA).sort().forEach(function(abbr) {{
    var s = STATE_DATA[abbr];
    summaryRows.push({{
      'State': abbr,
      'State Name': s.name || abbr,
      'Stage': STAGE_LABELS[s.stage] || s.stage || 'None',
      'Stage Code': s.stage || 'none',
      'Number of Bills': (s.bills || []).length,
      'Bills': (s.bills || []).join(', '),
      'Scope': s.scope || '',
      'Company Relevance': s.company_relevance || '',
      'Company Impact': (s.company_impact || '').replace(/\\n/g, ' '),
      'Confidence': s.confidence || '',
      'Session': s.session || '',
      'Summary': (s.summary || '').replace(/\\n/g, ' '),
      'Engagement Guidance': (s.engagement_note || '').replace(/\\n/g, ' '),
      'Evidence Sources': (s.evidence_sources || []).join('; '),
    }});
  }});

  var wb = XLSX.utils.book_new();

  // Sheet 1: State Summary (one row per state)
  var ws1 = XLSX.utils.json_to_sheet(summaryRows);
  // Set column widths
  ws1['!cols'] = [
    {{wch:6}}, {{wch:18}}, {{wch:28}}, {{wch:18}}, {{wch:10}}, {{wch:40}},
    {{wch:25}}, {{wch:15}}, {{wch:50}}, {{wch:12}}, {{wch:10}},
    {{wch:60}}, {{wch:60}}, {{wch:40}},
  ];
  XLSX.utils.book_append_sheet(wb, ws1, 'State Summary');

  // Sheet 2: Bill Detail (one row per bill — pivot table ready)
  var ws2 = XLSX.utils.json_to_sheet(rows);
  ws2['!cols'] = [
    {{wch:6}}, {{wch:18}}, {{wch:28}}, {{wch:18}}, {{wch:6}}, {{wch:18}},
    {{wch:25}}, {{wch:15}}, {{wch:50}}, {{wch:12}}, {{wch:10}},
    {{wch:60}}, {{wch:60}}, {{wch:40}}, {{wch:12}},
  ];
  XLSX.utils.book_append_sheet(wb, ws2, 'Bill Detail');

  // Sheet 3: Pivot-ready fields reference
  var pivotRef = [
    {{ 'Field': 'State', 'Type': 'Dimension', 'Description': 'Two-letter state abbreviation', 'Pivot Use': 'Row label or filter' }},
    {{ 'Field': 'State Name', 'Type': 'Dimension', 'Description': 'Full state name', 'Pivot Use': 'Row label' }},
    {{ 'Field': 'Stage', 'Type': 'Dimension', 'Description': 'Legislative stage (human-readable)', 'Pivot Use': 'Column label or filter' }},
    {{ 'Field': 'Stage Code', 'Type': 'Dimension', 'Description': 'Stage machine code', 'Pivot Use': 'For programmatic sorting' }},
    {{ 'Field': 'Stage Sort Order', 'Type': 'Measure', 'Description': 'Sort order: 0=enacted to 8=none', 'Pivot Use': 'Sort by this for stage progression' }},
    {{ 'Field': 'Bill Number', 'Type': 'Dimension', 'Description': 'Bill identifier (e.g. HB 123)', 'Pivot Use': 'Row label for bill-level analysis' }},
    {{ 'Field': 'Scope', 'Type': 'Dimension', 'Description': 'What the legislation covers', 'Pivot Use': 'Filter by scope category' }},
    {{ 'Field': 'Company Relevance', 'Type': 'Dimension', 'Description': 'high/medium/low relevance to windows/doors mfg', 'Pivot Use': 'Filter or color code' }},
    {{ 'Field': 'Company Impact', 'Type': 'Text', 'Description': 'How this affects our business specifically', 'Pivot Use': 'Detail text' }},
    {{ 'Field': 'Confidence', 'Type': 'Dimension', 'Description': 'Evidence confidence level', 'Pivot Use': 'Filter or color code' }},
    {{ 'Field': 'Session', 'Type': 'Dimension', 'Description': 'Legislative session year', 'Pivot Use': 'Filter by session' }},
    {{ 'Field': 'Summary', 'Type': 'Text', 'Description': 'Intelligence summary', 'Pivot Use': 'Detail text' }},
    {{ 'Field': 'Engagement Guidance', 'Type': 'Text', 'Description': 'What action to take', 'Pivot Use': 'Detail text' }},
    {{ 'Field': 'Evidence Sources', 'Type': 'Text', 'Description': 'Semicolon-separated source list', 'Pivot Use': 'Reference' }},
  ];
  var ws3 = XLSX.utils.json_to_sheet(pivotRef);
  ws3['!cols'] = [{{wch:22}}, {{wch:12}}, {{wch:50}}, {{wch:40}}];
  XLSX.utils.book_append_sheet(wb, ws3, 'Field Reference');

  XLSX.writeFile(wb, 'PFAS_Legislative_Intel_{generated}.xlsx');
}}
</script>

</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    logger.info(f"PFAS legislative intelligence map written to: {output_path}")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = generate_pfas_proposed_map()
    print(f"Map generated: {path}")
