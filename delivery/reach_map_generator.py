"""Generate an interactive EU REACH country compliance map as a self-contained HTML file."""
from __future__ import annotations
import logging
from datetime import date
from pathlib import Path
from typing import Optional, Dict

from config.settings import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grid layout: (grid-row, grid-col) — 1-indexed for CSS grid-row/grid-column
# Covers EU27 + UK + Norway + Iceland + Liechtenstein + Switzerland (~32 countries)
# Laid out to roughly reflect European geography as a cartogram.
# ---------------------------------------------------------------------------
_COUNTRY_GRID: dict[str, tuple[int, int]] = {
    # Row 1: Iceland, Norway, Sweden, Finland, Estonia
    "IS": (1, 1), "NO": (1, 2), "SE": (1, 3), "FI": (1, 4), "EE": (1, 5),
    # Row 2: Ireland, UK, Denmark, Latvia
    "IE": (2, 1), "GB": (2, 2), "DK": (2, 3),              "LV": (2, 5),
    # Row 3: Netherlands, Belgium, Germany, Lithuania, Poland
              "NL": (3, 2), "BE": (3, 3), "DE": (3, 4), "LT": (3, 5), "PL": (3, 6),
    # Row 4: Luxembourg, France, Austria, Czech Republic, Slovakia, Hungary, Romania
              "LU": (4, 2), "FR": (4, 3), "AT": (4, 4), "CZ": (4, 5), "SK": (4, 6), "HU": (4, 7), "RO": (4, 8),
    # Row 5: Portugal, Spain, Switzerland, Slovenia, Croatia
    "PT": (5, 1), "ES": (5, 2), "CH": (5, 3),              "SI": (5, 5), "HR": (5, 6),
    # Row 6: Italy, Serbia (not included), Bulgaria
                            "IT": (6, 3),                                               "BG": (6, 7),
    # Row 7: Malta, Albania (not EU/EEA—omit), Greece
                            "MT": (7, 3),                                 "GR": (7, 7),
    # Row 8: Cyprus
                                                                          "CY": (8, 7),
}

# ---------------------------------------------------------------------------
# Status colours — greens, distinct from PFAS (reds) and EPR (blues)
# ---------------------------------------------------------------------------
_STATUS_COLORS: dict[str, str] = {
    "priority": "#1A5C38",   # dark green
    "high":     "#2E8B57",   # medium green
    "monitor":  "#7CB88A",   # light green
    "standard": "#C8E6D0",   # very pale green
}

_STATUS_LABELS: dict[str, str] = {
    "priority": "Priority — High Enforcement & Supplier Exposure",
    "high":     "High — Strong Enforcement or Supplier Base",
    "monitor":  "Monitor — Moderate Relevance",
    "standard": "Standard — Full REACH, Lower Direct Relevance",
}

# ---------------------------------------------------------------------------
# Country data
# ---------------------------------------------------------------------------
_COUNTRY_DATA: dict[str, dict] = {
    "DE": {
        "name": "Germany",
        "status": "priority",
        "enforcement_body": "Federal Environment Agency (Umweltbundesamt, UBA) + State Authorities (LÄ)",
        "supplier_relevance": "Primary",
        "key_notes": (
            "Germany has the most rigorous REACH enforcement in Europe, with UBA coordinating across 16 Länder "
            "authorities that conduct frequent substance restriction inspections and downstream user audits. "
            "As a primary hub for industrial equipment manufacturing (machinery, chemicals, precision components), "
            "supplier SVHC communication obligations are extensive and actively enforced."
        ),
        "uk_reach_note": None,
    },
    "IT": {
        "name": "Italy",
        "status": "priority",
        "enforcement_body": "Ministry of Environment and Energy Security (MASE) / ISPRA + Regional ARPA agencies",
        "supplier_relevance": "Primary",
        "key_notes": (
            "Italy is a major industrial equipment supplier (machine tools, automation, specialty chemicals) "
            "and applies REACH through a network of regional environmental agencies (ARPA) that conduct "
            "market surveillance. Enforcement intensity has increased markedly since 2020."
        ),
        "uk_reach_note": None,
    },
    "NL": {
        "name": "Netherlands",
        "status": "priority",
        "enforcement_body": "Netherlands Food and Consumer Product Safety Authority (NVWA) / Human Environment and Transport Inspectorate (ILT)",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "The Netherlands operates one of Europe's most proactive REACH enforcement programs via ILT "
            "and NVWA, with a strong focus on import/port-of-entry checks at Rotterdam. "
            "Also a significant chemicals and precision engineering supply chain hub."
        ),
        "uk_reach_note": None,
    },
    "CH": {
        "name": "Switzerland",
        "status": "priority",
        "enforcement_body": "Federal Office for the Environment (BAFU/FOEN) + Cantonal Enforcement",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "Switzerland autonomously mirrors EU REACH through the Swiss ChemO (Chemicals Ordinance), "
            "updated in close alignment with EU revisions. As a major precision machinery and specialty "
            "chemicals supplier, Swiss counterparts in supply chains require the same SVHC documentation "
            "as EU-based suppliers. Enforcement is thorough at both federal and cantonal levels."
        ),
        "uk_reach_note": None,
    },
    "AT": {
        "name": "Austria",
        "status": "priority",
        "enforcement_body": "Federal Environment Agency (Umweltbundesamt Austria) + District Authorities",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "Austria enforces REACH diligently through district-level authorities with federal coordination. "
            "A significant supplier of hydraulic components, specialty metals, and automation equipment "
            "relevant to US industrial manufacturers."
        ),
        "uk_reach_note": None,
    },
    "FR": {
        "name": "France",
        "status": "high",
        "enforcement_body": "ANSES (National Agency for Food, Environmental and Occupational Health & Safety) + DGCCRF",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "France enforces REACH through ANSES for substance evaluation and DGCCRF for market "
            "surveillance. France is an active participant in SVHC restriction proposals at ECHA. "
            "Notable supplier of aerospace components, specialty chemicals, and industrial materials."
        ),
        "uk_reach_note": None,
    },
    "SE": {
        "name": "Sweden",
        "status": "high",
        "enforcement_body": "Swedish Chemicals Agency (KEMI)",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "KEMI is one of Europe's most active national REACH enforcement authorities and a frequent "
            "initiator of SVHC listings at ECHA. Sweden has a strong industrial engineering sector "
            "(bearings, cutting tools, specialty coatings) with relevant REACH compliance obligations."
        ),
        "uk_reach_note": None,
    },
    "BE": {
        "name": "Belgium",
        "status": "high",
        "enforcement_body": "Federal Public Service Health, Food Chain Safety and Environment (FPS Environment)",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "Belgium enforces REACH through FPS Environment and regional agencies (OVAM, SPAQuE, IBGE). "
            "Hosts several major chemical distributors and is an important hub for specialty chemicals "
            "supply chains into EU markets."
        ),
        "uk_reach_note": None,
    },
    "CZ": {
        "name": "Czech Republic",
        "status": "high",
        "enforcement_body": "Czech Environmental Inspectorate (CEI) / Czech Hydrometeorological Institute (CHMI)",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "Czech Republic has emerged as a significant Central European manufacturing hub (automotive "
            "components, precision machining) with growing REACH enforcement activity by CEI. "
            "Compliance documentation requirements are actively spot-checked."
        ),
        "uk_reach_note": None,
    },
    "GB": {
        "name": "United Kingdom",
        "status": "high",
        "enforcement_body": "Health and Safety Executive (HSE) — UK REACH administrator",
        "supplier_relevance": "Secondary",
        "key_notes": (
            "Post-Brexit, the UK operates UK REACH as a separate regulatory system from EU REACH, "
            "administered by HSE. While UK REACH was initially closely aligned with EU REACH, "
            "requirements are diverging over time — notably on SVHC lists, registration deadlines, "
            "and substance restrictions. Suppliers must maintain dual compliance if selling into both "
            "UK and EU markets."
        ),
        "uk_reach_note": (
            "Post-Brexit: UK operates UK REACH (separate from EU REACH, administered by HSE). "
            "Requirements are diverging — suppliers must maintain dual compliance."
        ),
    },
    "DK": {
        "name": "Denmark",
        "status": "high",
        "enforcement_body": "Danish Environmental Protection Agency (Miljøstyrelsen, MST)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Denmark is a proactive REACH enforcement country and frequent ECHA contributor on "
            "substance restriction proposals. MST conducts regular market surveillance of articles "
            "and preparations. Lower direct supplier relevance for US industrial equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
    "FI": {
        "name": "Finland",
        "status": "high",
        "enforcement_body": "Finnish Safety and Chemicals Agency (Tukes)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Tukes enforces REACH with focus on consumer articles and industrial chemicals. "
            "Finland is active in ECHA enforcement forums. Supplier relevance for US industrial "
            "manufacturers is generally lower than core Western European countries."
        ),
        "uk_reach_note": None,
    },
    "ES": {
        "name": "Spain",
        "status": "monitor",
        "enforcement_body": "Ministry for Ecological Transition (MITECO) + Regional Autonomous Community authorities",
        "supplier_relevance": "Low",
        "key_notes": (
            "REACH enforcement in Spain is shared between MITECO at the national level and 17 autonomous "
            "community authorities, leading to some variability in enforcement intensity. "
            "Growing industrial base but lower direct supplier relevance for US heavy industry."
        ),
        "uk_reach_note": None,
    },
    "PL": {
        "name": "Poland",
        "status": "monitor",
        "enforcement_body": "Chief Inspectorate for Environmental Protection (GIOŚ) + Bureau for Chemical Substances",
        "supplier_relevance": "Low",
        "key_notes": (
            "Poland has strengthened REACH enforcement in recent years through GIOŚ. Growing "
            "manufacturing sector (automotive, electronics assembly) creates increasing downstream "
            "user obligations, but direct supplier relevance for US industrial manufacturers remains moderate."
        ),
        "uk_reach_note": None,
    },
    "HU": {
        "name": "Hungary",
        "status": "monitor",
        "enforcement_body": "National Directorate General for Disaster Management (BM OKF) / National Public Health Center",
        "supplier_relevance": "Low",
        "key_notes": (
            "Hungary enforces REACH through multiple agencies with varying focus areas. "
            "Enforcement intensity is moderate; growing automotive and electronics manufacturing "
            "sector increases REACH compliance activity."
        ),
        "uk_reach_note": None,
    },
    "SK": {
        "name": "Slovakia",
        "status": "monitor",
        "enforcement_body": "Slovak Environment Inspectorate (SEI)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Slovakia enforces REACH via SEI. Automotive manufacturing dominates the industrial "
            "base. REACH compliance is monitored but enforcement intensity is moderate compared "
            "to Western European counterparts."
        ),
        "uk_reach_note": None,
    },
    "RO": {
        "name": "Romania",
        "status": "monitor",
        "enforcement_body": "National Environmental Guard (Garda Națională de Mediu)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Romania enforces REACH through the National Environmental Guard. Enforcement capacity "
            "is developing; compliance levels are improving with EU-funded support programs. "
            "Lower direct supplier relevance for US industrial equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
    "SI": {
        "name": "Slovenia",
        "status": "monitor",
        "enforcement_body": "Inspectorate of the Republic of Slovenia for Agriculture, Forestry, Hunting and Food (UVHVVR) + Environment Agency (ARSO)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Slovenia applies REACH through ARSO and sectoral inspectorates. A small but organized "
            "regulatory environment. Supplier relevance for US industrial manufacturers is low."
        ),
        "uk_reach_note": None,
    },
    "HR": {
        "name": "Croatia",
        "status": "monitor",
        "enforcement_body": "Ministry of Economy and Sustainable Development / Croatian Environment Agency (HAOP)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Croatia has been implementing REACH since EU accession in 2013. Enforcement infrastructure "
            "continues to mature. Supplier relevance for US industrial manufacturers is low."
        ),
        "uk_reach_note": None,
    },
    "PT": {
        "name": "Portugal",
        "status": "monitor",
        "enforcement_body": "Portuguese Environment Agency (APA) + General Inspectorate of Agriculture, Sea, Environment and Land Use (IGAMAOT)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Portugal enforces REACH through APA and IGAMAOT. Enforcement activity is moderate. "
            "Limited direct supplier relevance for US heavy industrial manufacturers."
        ),
        "uk_reach_note": None,
    },
    "IE": {
        "name": "Ireland",
        "status": "monitor",
        "enforcement_body": "Health and Safety Authority (HSA) + Environmental Protection Agency (EPA Ireland)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Ireland enforces REACH through HSA (for workplace chemicals) and EPA (environmental aspects). "
            "Strong pharmaceutical and medtech sectors, but lower relevance for heavy industrial "
            "equipment supply chains."
        ),
        "uk_reach_note": None,
    },
    "NO": {
        "name": "Norway",
        "status": "monitor",
        "enforcement_body": "Norwegian Environment Agency (Miljødirektoratet) + Norwegian Labour and Welfare Administration",
        "supplier_relevance": "Low",
        "key_notes": (
            "Norway participates in REACH via the EEA Agreement — EU REACH applies with a slight "
            "delay in adoption of new regulations through the EEA Joint Committee process. "
            "The Norwegian Environment Agency enforces REACH domestically. Norway is an active "
            "participant in ECHA committees. Note: participation is via EEA, not as an EU member."
        ),
        "uk_reach_note": None,
    },
    "IS": {
        "name": "Iceland",
        "status": "monitor",
        "enforcement_body": "Environment Agency of Iceland (Umhverfisstofnun)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Iceland participates in REACH via the EEA Agreement — EU REACH applies but with "
            "a procedural delay through EEA Joint Committee incorporation. Enforcement is handled "
            "by the Environment Agency of Iceland. Supplier relevance for US industrial manufacturers "
            "is minimal. Note: participation is via EEA, not as an EU member."
        ),
        "uk_reach_note": None,
    },
    "LI": {
        "name": "Liechtenstein",
        "status": "monitor",
        "enforcement_body": "Office of Environment (Amt für Umwelt, AUL)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Liechtenstein participates in REACH via the EEA Agreement. Given its customs union "
            "with Switzerland, in practice Liechtenstein entities often coordinate REACH compliance "
            "with Swiss counterparts. AUL enforces domestically. Very low supplier relevance for "
            "US manufacturers. Note: participation is via EEA, not as an EU member."
        ),
        "uk_reach_note": None,
    },
    "LT": {
        "name": "Lithuania",
        "status": "standard",
        "enforcement_body": "Environmental Protection Inspectorate under the Ministry of Environment",
        "supplier_relevance": "Low",
        "key_notes": (
            "Lithuania enforces REACH through the Environmental Protection Inspectorate. "
            "Full EU REACH applies; enforcement capacity is developing. "
            "Supplier relevance for US industrial manufacturers is low."
        ),
        "uk_reach_note": None,
    },
    "LV": {
        "name": "Latvia",
        "status": "standard",
        "enforcement_body": "State Environmental Service (Valsts vides dienests, VVD)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Latvia enforces REACH through the State Environmental Service. Full EU REACH applies; "
            "enforcement is developing. Low supplier relevance for US industrial equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
    "EE": {
        "name": "Estonia",
        "status": "standard",
        "enforcement_body": "Environmental Inspectorate (Keskkonnainspektsioon)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Estonia enforces REACH through the Environmental Inspectorate. Full EU REACH applies. "
            "Low supplier relevance for US industrial equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
    "LU": {
        "name": "Luxembourg",
        "status": "standard",
        "enforcement_body": "Administration of Environment (Administration de l'environnement)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Luxembourg enforces REACH through its Administration de l'environnement. Full EU REACH "
            "applies. Low supplier relevance; Luxembourg's economy is dominated by financial services."
        ),
        "uk_reach_note": None,
    },
    "MT": {
        "name": "Malta",
        "status": "standard",
        "enforcement_body": "Environment and Resources Authority (ERA Malta)",
        "supplier_relevance": "Low",
        "key_notes": (
            "Malta enforces REACH through ERA. Full EU REACH applies. Very low supplier relevance "
            "for US industrial equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
    "CY": {
        "name": "Cyprus",
        "status": "standard",
        "enforcement_body": "Department of Labour Inspection / Department of Environment",
        "supplier_relevance": "Low",
        "key_notes": (
            "Cyprus enforces REACH through the Department of Labour Inspection and Department of "
            "Environment. Full EU REACH applies. Very low supplier relevance for US industrial "
            "equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
    "BG": {
        "name": "Bulgaria",
        "status": "standard",
        "enforcement_body": "Executive Environment Agency (ExEA) / Ministry of Environment and Water",
        "supplier_relevance": "Low",
        "key_notes": (
            "Bulgaria enforces REACH through ExEA. Full EU REACH applies; enforcement capacity "
            "continues to develop. Low supplier relevance for US industrial manufacturers."
        ),
        "uk_reach_note": None,
    },
    "GR": {
        "name": "Greece",
        "status": "standard",
        "enforcement_body": "General Chemical State Laboratory (GCSL) / Ministry of Environment and Energy",
        "supplier_relevance": "Low",
        "key_notes": (
            "Greece enforces REACH through the General Chemical State Laboratory. Full EU REACH "
            "applies. Low supplier relevance for US heavy industrial equipment manufacturers."
        ),
        "uk_reach_note": None,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_js(text: str) -> str:
    """Escape a string for safe embedding in a JS string literal."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _activity_class(code: str, activity_counts: Optional[Dict[str, int]]) -> str:
    """Return an activity CSS class based on article count."""
    if not activity_counts:
        return ""
    count = activity_counts.get(code, 0)
    if count == 0:
        return ""
    elif count <= 2:
        return " activity-1"
    elif count <= 5:
        return " activity-2"
    else:
        return " activity-3"


def _build_country_cells(activity_counts: Optional[Dict[str, int]] = None) -> str:
    """Return HTML div elements for every country cell."""
    cells = []
    for code, (row, col) in _COUNTRY_GRID.items():
        country = _COUNTRY_DATA.get(code)
        if not country:
            continue
        status = country.get("status", "standard")
        color = _STATUS_COLORS.get(status, _STATUS_COLORS["standard"])
        text_color = "#fff" if status in ("priority", "high", "monitor") else "#2D5A3D"
        act_class = _activity_class(code, activity_counts)
        cells.append(
            f'<div class="country-cell status-{status}{act_class}" '
            f'style="grid-row:{row};grid-column:{col};background-color:{color};color:{text_color};" '
            f'data-code="{code}" '
            f'onclick="showDetail(\'{code}\')" '
            f'title="{country["name"]}">'
            f'{code}'
            f'</div>'
        )
    return "\n".join(cells)


# Export for excel_exporter.py
_REACH_COUNTRY_DATA = _COUNTRY_DATA


def _build_country_js_data() -> str:
    """Return a JS object literal containing all country data."""
    import json
    entries = []
    for code, country in _COUNTRY_DATA.items():
        uk_note = country.get("uk_reach_note") or ""
        entries.append(
            f'  "{code}": {{'
            f'"name": "{_escape_js(country["name"])}", '
            f'"status": "{country["status"]}", '
            f'"enforcement_body": "{_escape_js(country["enforcement_body"])}", '
            f'"supplier_relevance": "{_escape_js(country["supplier_relevance"])}", '
            f'"key_notes": "{_escape_js(country["key_notes"])}", '
            f'"uk_reach_note": "{_escape_js(uk_note)}"'
            f'}}'
        )
    return "{\n" + ",\n".join(entries) + "\n}"


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_reach_map(activity_counts: Optional[Dict[str, int]] = None) -> Path:
    """Generate the interactive EU REACH country map HTML. Returns the output path."""
    today = date.today().strftime("%Y-%m-%d")
    output_path = Config.DATA_DIR / f"reach_map_{today}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    country_cells_html = _build_country_cells(activity_counts=activity_counts)
    country_js_data = _build_country_js_data()

    # Build legend items
    legend_items = []
    for status, color in _STATUS_COLORS.items():
        text_color = "#fff" if status in ("priority", "high", "monitor") else "#2D5A3D"
        legend_items.append(
            f'<div class="legend-item">'
            f'<span class="legend-swatch" style="background:{color};border:1px solid #A8C8B0;"></span>'
            f'<span class="legend-label">{_STATUS_LABELS[status]}</span>'
            f'</div>'
        )
    legend_html = "\n".join(legend_items)

    # Calculate grid dimensions from data
    max_col = max(col for (_, col) in _COUNTRY_GRID.values())
    max_row = max(row for (row, _) in _COUNTRY_GRID.values())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>EU REACH Tracker</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: #F4F6F5;
      color: #2D3748;
      font-size: 14px;
      line-height: 1.5;
    }}

    /* ---- Header ---- */
    .page-header {{
      background: linear-gradient(135deg, #0D2318 0%, #1A4A2E 100%);
      padding: 20px 32px 16px;
    }}
    .page-header .brand {{
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: #7CB88A;
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
      color: #9FC9AA;
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

    /* CSS Grid cartogram — 52px × 42px cells */
    .country-grid {{
      display: grid;
      grid-template-columns: repeat({max_col}, 52px);
      grid-template-rows: repeat({max_row}, 42px);
      gap: 4px;
      width: fit-content;
    }}

    .country-cell {{
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 800;
      cursor: pointer;
      position: relative;
      transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease;
      user-select: none;
      letter-spacing: 0.5px;
    }}
    .country-cell:hover {{
      transform: scale(1.12);
      box-shadow: 0 4px 12px rgba(0,0,0,0.25);
      z-index: 10;
      filter: brightness(1.08);
    }}
    .country-cell.active {{
      transform: scale(1.15);
      box-shadow: 0 0 0 3px #fff, 0 0 0 5px #1A4A2E;
      z-index: 20;
    }}

    /* ---- Legend ---- */
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 20px;
      margin-top: 18px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 7px;
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

    .eea-note {{
      margin-top: 10px;
      font-size: 11px;
      color: #718096;
      font-style: italic;
    }}

    /* ---- Detail panel ---- */
    .detail-panel {{
      flex: 0 0 320px;
      background: #fff;
      border: 1px solid #D4E6DA;
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

    .detail-code {{
      font-size: 28px;
      font-weight: 900;
      color: #1A3325;
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
    .detail-status-badge.standard {{
      color: #2D5A3D;
      border: 1px solid #A8C8B0;
    }}

    .detail-section-label {{
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: #A0AEC0;
      margin: 14px 0 4px;
    }}
    .detail-text {{
      font-size: 13px;
      color: #4A5568;
      line-height: 1.6;
      margin: 0;
    }}

    /* Supplier relevance pill */
    .supplier-pill {{
      display: inline-block;
      padding: 2px 10px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 700;
    }}
    .supplier-primary   {{ background: #C6F6D5; color: #22543D; }}
    .supplier-secondary {{ background: #E9F5EC; color: #276749; }}
    .supplier-low       {{ background: #F0F4F1; color: #5A7A63; }}

    /* UK REACH warning box */
    .uk-reach-box {{
      background: #FFF8E7;
      border-left: 3px solid #D69E2E;
      border-radius: 0 4px 4px 0;
      padding: 10px 12px;
      font-size: 12px;
      color: #744210;
      line-height: 1.5;
      margin-top: 4px;
    }}
    .uk-reach-box strong {{
      display: block;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #975A16;
      margin-bottom: 4px;
    }}

    /* EEA note box */
    .eea-box {{
      background: #EBF5EE;
      border-left: 3px solid #2E8B57;
      border-radius: 0 4px 4px 0;
      padding: 10px 12px;
      font-size: 12px;
      color: #1A4A2E;
      line-height: 1.5;
      margin-top: 4px;
    }}
    .eea-box strong {{
      display: block;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: #1A5C38;
      margin-bottom: 4px;
    }}

    /* ---- Footer ---- */
    .page-footer {{
      padding: 12px 32px;
      border-top: 1px solid #D4E6DA;
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
      background: #0D2318;
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
  <h1>EU REACH Tracker</h1>
  <p class="sub">Enforcement intensity &amp; supplier exposure by country &nbsp;&middot;&nbsp; Generated: {today}</p>
  <a class="download-btn" href="./reach-tracker.xlsx" download>&#8595; Download Excel</a>
  <a class="download-btn" href="./reach-timeline.html" style="margin-left:8px;">&#9201; Deadline Timeline</a>
</div>
<nav class="site-nav">
  <span class="nav-section">Maps</span>
  <a href="./index.html" class="nav-item">PFAS</a>
  <a href="./epr-map.html" class="nav-item">EPR</a>
  <a href="./reach-map.html" class="nav-item active">REACH</a>
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
    <p class="map-title">Click any country for details</p>
    <div class="country-grid" id="countryGrid">
{country_cells_html}
    </div>

    <div class="legend">
{legend_html}
    </div>

    <p class="eea-note">IS / NO / LI participate via EEA Agreement (not EU members). CH mirrors REACH via Swiss ChemO.</p>
  </div>

  <!-- Detail panel -->
  <div class="detail-overlay" id="detailOverlay" onclick="closeDetail()"></div>
  <div class="detail-panel" id="detailPanel">
    <button class="detail-close" onclick="closeDetail()" aria-label="Close">&#x2715;</button>
    <div class="detail-empty" id="detailEmpty">Select a country to see details</div>
    <div id="detailContent" style="display:none;"></div>
  </div>

</div>

<div class="page-footer">
  Data current as of {today}. Covers EU27 + UK + EEA (NO, IS, LI) + Switzerland.
  UK REACH is a separate post-Brexit system diverging from EU REACH.
  EEA countries apply EU REACH via EEA Joint Committee incorporation (with procedural delay).
  Verify compliance obligations with legal counsel before making compliance decisions.
</div>

<script>
var COUNTRY_DATA = {country_js_data};

var STATUS_COLORS = {{
  "priority": "#1A5C38",
  "high":     "#2E8B57",
  "monitor":  "#7CB88A",
  "standard": "#C8E6D0"
}};

var STATUS_LABELS = {{
  "priority": "Priority",
  "high":     "High",
  "monitor":  "Monitor",
  "standard": "Standard"
}};

var EEA_COUNTRIES = {{"IS": true, "NO": true, "LI": true}};

var activeCode = null;

function showDetail(code) {{
  var country = COUNTRY_DATA[code];
  if (!country) return;

  // Toggle active cell highlight
  if (activeCode) {{
    var prev = document.querySelector('[data-code="' + activeCode + '"]');
    if (prev) prev.classList.remove('active');
  }}
  activeCode = code;
  var cell = document.querySelector('[data-code="' + code + '"]');
  if (cell) cell.classList.add('active');

  var color = STATUS_COLORS[country.status] || '#C8E6D0';
  var statusLabel = STATUS_LABELS[country.status] || country.status;
  var badgeClass = country.status === 'standard' ? ' standard' : '';
  var badgeStyle = country.status === 'standard'
    ? 'background:#C8E6D0;'
    : 'background:' + color + ';';

  // Supplier relevance pill class
  var relClass = 'supplier-low';
  if (country.supplier_relevance === 'Primary')   relClass = 'supplier-primary';
  if (country.supplier_relevance === 'Secondary') relClass = 'supplier-secondary';

  // UK REACH box
  var ukHtml = '';
  if (country.uk_reach_note) {{
    ukHtml = '<p class="detail-section-label">UK REACH Alert</p>'
      + '<div class="uk-reach-box"><strong>Post-Brexit Divergence</strong>'
      + escapeHtml(country.uk_reach_note)
      + '</div>';
  }}

  // EEA participation box
  var eeaHtml = '';
  if (EEA_COUNTRIES[code]) {{
    eeaHtml = '<div class="eea-box"><strong>EEA Participation</strong>'
      + 'This country participates in EU REACH via the EEA Agreement — not as an EU member. '
      + 'REACH applies but new regulations are incorporated with a procedural delay through the EEA Joint Committee.'
      + '</div>';
  }}

  var notesHtml = (country.status !== 'standard' && country.key_notes)
    ? '<p class="detail-section-label">Notes</p><p class="detail-text">' + escapeHtml(country.key_notes) + '</p>'
    : '';

  var html = '<div class="detail-code">' + code + '</div>'
    + '<div class="detail-name">' + escapeHtml(country.name) + '</div>'
    + '<span class="detail-status-badge' + badgeClass + '" style="' + badgeStyle + '">'
    + escapeHtml(statusLabel) + '</span>'
    + eeaHtml
    + ukHtml
    + '<p class="detail-section-label">Enforcement Body</p>'
    + '<p class="detail-text">' + escapeHtml(country.enforcement_body) + '</p>'
    + '<p class="detail-section-label">Supplier Relevance</p>'
    + '<span class="supplier-pill ' + relClass + '">' + escapeHtml(country.supplier_relevance) + '</span>'
    + notesHtml;

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

// Auto-select Germany on load
window.addEventListener('DOMContentLoaded', function() {{
  showDetail('DE');
}});
</script>

</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
    logger.info(f"EU REACH map written to: {output_path}")
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = generate_reach_map()
    print(f"Map generated: {path}")
