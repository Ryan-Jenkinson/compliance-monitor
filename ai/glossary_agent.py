"""
Glossary / Abbreviation Dictionary Agent.

Maintains a regulatory abbreviation dictionary:
  - Seeded with 80+ common regulatory terms on first run
  - Weekly Claude pass extracts new abbreviations from recent articles
  - Saves data/glossary.json (structured) + data/glossary.html (standalone page)

Run via: python run.py --glossary  (or auto weekly on Sundays)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .claude_client import ClaudeClient
from config.settings import Config

logger = logging.getLogger(__name__)

_DATA_DIR = Path(Config.DATA_DIR)
_GLOSSARY_JSON = _DATA_DIR / "glossary.json"
_GLOSSARY_HTML = _DATA_DIR / "glossary.html"

# ── Seed dictionary ──────────────────────────────────────────────────────────

SEED_TERMS: list[dict] = [
    # Regulatory frameworks
    {"abbr": "PFAS", "full": "Per- and Polyfluoroalkyl Substances", "category": "Chemicals", "description": "A group of thousands of man-made chemicals used in many industries and consumer products. Known as 'forever chemicals' due to persistence in the environment."},
    {"abbr": "EPR", "full": "Extended Producer Responsibility", "category": "Packaging", "description": "A policy approach where producers are given significant responsibility for the treatment or disposal of post-consumer products."},
    {"abbr": "REACH", "full": "Registration, Evaluation, Authorisation and Restriction of Chemicals", "category": "EU Regulation", "description": "EU chemical regulation that manages the risks posed by chemicals. Requires companies to register substances and provide safety data."},
    {"abbr": "TSCA", "full": "Toxic Substances Control Act", "category": "US Federal", "description": "US federal law regulating the introduction of new or already existing chemicals. Administered by the EPA."},
    {"abbr": "SVHC", "full": "Substance of Very High Concern", "category": "EU Regulation", "description": "Substances identified under REACH as having serious and often irreversible effects on human health or the environment. Placed on the REACH Candidate List."},
    {"abbr": "PFOA", "full": "Perfluorooctanoic Acid", "category": "Chemicals", "description": "A synthetic perfluorocarbon that is a PFAS compound. Used in manufacturing of fluoropolymers. Now largely phased out in the US."},
    {"abbr": "PFOS", "full": "Perfluorooctane Sulfonate", "category": "Chemicals", "description": "A PFAS compound formerly used in Scotchgard and firefighting foam. Listed as a persistent organic pollutant under the Stockholm Convention."},
    {"abbr": "PTFE", "full": "Polytetrafluoroethylene", "category": "Chemicals", "description": "A synthetic fluoropolymer used extensively as a coating (e.g., Teflon). A PFAS-adjacent compound under scrutiny in some regulatory frameworks."},
    {"abbr": "MCL", "full": "Maximum Contaminant Level", "category": "Water / EPA", "description": "The highest level of a contaminant that is allowed in drinking water. Set by the EPA under the Safe Drinking Water Act."},
    {"abbr": "MCLG", "full": "Maximum Contaminant Level Goal", "category": "Water / EPA", "description": "A non-enforceable public health goal for contaminants in drinking water. Often zero for carcinogens."},
    {"abbr": "SDWA", "full": "Safe Drinking Water Act", "category": "US Federal", "description": "The primary federal law ensuring safe drinking water. EPA sets standards for drinking water quality."},
    {"abbr": "CERCLA", "full": "Comprehensive Environmental Response, Compensation, and Liability Act", "category": "US Federal", "description": "Also known as Superfund. Governs cleanup of contaminated sites."},
    {"abbr": "RCRA", "full": "Resource Conservation and Recovery Act", "category": "US Federal", "description": "US federal law governing the disposal of solid and hazardous waste."},
    {"abbr": "FIFRA", "full": "Federal Insecticide, Fungicide, and Rodenticide Act", "category": "US Federal", "description": "US federal statute that governs the distribution, sale, and use of pesticides."},
    {"abbr": "CAA", "full": "Clean Air Act", "category": "US Federal", "description": "US federal law regulating air emissions from stationary and mobile sources."},
    {"abbr": "CWA", "full": "Clean Water Act", "category": "US Federal", "description": "The primary federal law governing water pollution in the US."},

    # Agencies
    {"abbr": "EPA", "full": "Environmental Protection Agency", "category": "US Agency", "description": "US federal agency responsible for environmental protection and enforcement of environmental laws."},
    {"abbr": "ECHA", "full": "European Chemicals Agency", "category": "EU Agency", "description": "EU agency that manages the technical, scientific, and administrative aspects of REACH and other EU chemical legislation."},
    {"abbr": "OEHHA", "full": "Office of Environmental Health Hazard Assessment", "category": "CA Agency", "description": "California agency responsible for the scientific and policy functions of the California Environmental Protection Agency, including administering Prop 65."},
    {"abbr": "DTSC", "full": "Department of Toxic Substances Control", "category": "CA Agency", "description": "California state department responsible for regulating hazardous waste and toxic substances."},
    {"abbr": "DEQ", "full": "Department of Environmental Quality", "category": "State Agency", "description": "State-level environmental agency (Oregon, Michigan, Idaho, Montana). Enforces state environmental regulations."},
    {"abbr": "MPCA", "full": "Minnesota Pollution Control Agency", "category": "MN Agency", "description": "Minnesota state agency responsible for environmental protection, including PFAS water standards."},
    {"abbr": "USEPA", "full": "United States Environmental Protection Agency", "category": "US Agency", "description": "Same as EPA — U.S. Environmental Protection Agency."},
    {"abbr": "OSHA", "full": "Occupational Safety and Health Administration", "category": "US Agency", "description": "US federal agency ensuring safe and healthful working conditions."},
    {"abbr": "CPSC", "full": "Consumer Product Safety Commission", "category": "US Agency", "description": "US independent agency protecting the public from unreasonable risks of injury or death from consumer products."},
    {"abbr": "FDA", "full": "Food and Drug Administration", "category": "US Agency", "description": "US federal agency responsible for protecting public health through food, drug, and device safety."},
    {"abbr": "CBP", "full": "Customs and Border Protection", "category": "US Agency", "description": "US agency that enforces trade laws including the Uyghur Forced Labor Prevention Act (UFLPA) through import detention orders."},
    {"abbr": "SEC", "full": "Securities and Exchange Commission", "category": "US Agency", "description": "US federal agency overseeing securities markets, including Conflict Minerals reporting (Dodd-Frank Section 1502)."},

    # Legislation / Directives
    {"abbr": "SB", "full": "Senate Bill", "category": "Legislative", "description": "A bill introduced in the state or US Senate. E.g., CA SB 54 (plastic packaging)."},
    {"abbr": "AB", "full": "Assembly Bill", "category": "Legislative", "description": "A bill introduced in the state Assembly (lower chamber)."},
    {"abbr": "HB", "full": "House Bill", "category": "Legislative", "description": "A bill introduced in the state or US House of Representatives."},
    {"abbr": "SF", "full": "Senate File", "category": "Legislative", "description": "A bill introduced in certain state Senates (e.g., Minnesota SF)."},
    {"abbr": "HF", "full": "House File", "category": "Legislative", "description": "A bill introduced in certain state Houses (e.g., Minnesota HF)."},
    {"abbr": "UFLPA", "full": "Uyghur Forced Labor Prevention Act", "category": "US Federal", "description": "US law creating a rebuttable presumption that goods made in Xinjiang involve forced labor, prohibiting their import."},
    {"abbr": "CSDDD", "full": "Corporate Sustainability Due Diligence Directive", "category": "EU Directive", "description": "EU directive requiring large companies to conduct due diligence on human rights and environmental impacts in their value chains."},
    {"abbr": "CSRD", "full": "Corporate Sustainability Reporting Directive", "category": "EU Directive", "description": "EU directive requiring large companies to report on sustainability impacts, risks, and opportunities."},
    {"abbr": "ESRS", "full": "European Sustainability Reporting Standards", "category": "EU Regulation", "description": "Reporting standards under CSRD specifying how companies should disclose sustainability information."},
    {"abbr": "EUDR", "full": "EU Deforestation Regulation", "category": "EU Regulation", "description": "EU regulation prohibiting companies from placing certain commodities/products associated with deforestation on the EU market."},
    {"abbr": "RoHS", "full": "Restriction of Hazardous Substances", "category": "EU Directive", "description": "EU directive restricting hazardous substances in electrical and electronic equipment."},
    {"abbr": "WEEE", "full": "Waste Electrical and Electronic Equipment", "category": "EU Directive", "description": "EU directive setting collection, recycling, and recovery targets for electrical goods."},
    {"abbr": "POPs", "full": "Persistent Organic Pollutants", "category": "International", "description": "Chemicals that persist in the environment, accumulate in living organisms, and pose risks to human health. Regulated under the Stockholm Convention."},
    {"abbr": "Prop 65", "full": "California Safe Drinking Water and Toxic Enforcement Act of 1986", "category": "CA Law", "description": "California law requiring businesses to provide warnings before knowingly exposing anyone to listed chemicals. Enforced by 60-day notice actions."},

    # Programs / Lists
    {"abbr": "SNAP", "full": "Significant New Alternatives Policy", "category": "EPA Program", "description": "EPA program that evaluates substitutes for ozone-depleting substances under the Clean Air Act."},
    {"abbr": "ANPRM", "full": "Advanced Notice of Proposed Rulemaking", "category": "Regulatory Process", "description": "An early-stage regulatory notice inviting public comment before a formal proposed rule is published."},
    {"abbr": "NPRM", "full": "Notice of Proposed Rulemaking", "category": "Regulatory Process", "description": "A formal regulatory document published in the Federal Register inviting public comment on a proposed rule."},
    {"abbr": "NOFA", "full": "Notice of Funding Availability", "category": "Regulatory Process", "description": "Announcement of grant or funding opportunities from a federal or state agency."},
    {"abbr": "FR", "full": "Federal Register", "category": "Publication", "description": "The official journal of the federal government of the United States, containing government agency rules, proposed rules, and public notices."},
    {"abbr": "CFR", "full": "Code of Federal Regulations", "category": "Publication", "description": "The codification of rules published by the executive departments and agencies of the federal government."},
    {"abbr": "USC", "full": "United States Code", "category": "Publication", "description": "The codification of general and permanent laws of the United States."},
    {"abbr": "ICS", "full": "Integrated Chemical Strategy", "category": "EU Regulation", "description": "EU strategy for a mix of chemicals regulations to achieve a toxic-free environment."},
    {"abbr": "SCIP", "full": "Substances of Concern In articles as such or in complex objects (Products)", "category": "EU Regulation", "description": "ECHA database for articles containing SVHC in concentration above 0.1% w/w."},
    {"abbr": "SDS", "full": "Safety Data Sheet", "category": "Chemical Safety", "description": "Document listing hazard information, handling, storage, and emergency procedures for a substance. Required under GHS/REACH."},
    {"abbr": "GHS", "full": "Globally Harmonized System of Classification and Labelling of Chemicals", "category": "International", "description": "International system for standardizing chemical hazard communication."},

    # Supply chain / minerals
    {"abbr": "3TG", "full": "Tin, Tantalum, Tungsten, and Gold", "category": "Conflict Minerals", "description": "The four minerals covered by Dodd-Frank Section 1502 (Conflict Minerals Rule). Required to be reported on SEC Form SD."},
    {"abbr": "CMRT", "full": "Conflict Minerals Reporting Template", "category": "Conflict Minerals", "description": "Standardized industry template for reporting conflict minerals due diligence, maintained by the Responsible Minerals Initiative (RMI)."},
    {"abbr": "RMI", "full": "Responsible Minerals Initiative", "category": "Industry Body", "description": "Organization providing tools and resources to companies for conducting responsible mineral sourcing due diligence."},
    {"abbr": "RMAP", "full": "Responsible Minerals Assurance Process", "category": "Conflict Minerals", "description": "Audit program operated by RMI to assess smelter/refiner compliance with responsible sourcing standards."},
    {"abbr": "DRC", "full": "Democratic Republic of Congo", "category": "Geography", "description": "Central African country; conflict minerals legislation focuses on minerals originating from DRC and adjoining countries."},
    {"abbr": "OECD", "full": "Organisation for Economic Co-operation and Development", "category": "International", "description": "International organization providing guidance on responsible business conduct including the Due Diligence Guidance for Responsible Supply Chains of Minerals."},

    # Packaging / EPR
    {"abbr": "PRO", "full": "Producer Responsibility Organization", "category": "EPR", "description": "A non-profit or industry body established to implement EPR programs on behalf of producers."},
    {"abbr": "PCR", "full": "Post-Consumer Recycled (content)", "category": "Packaging", "description": "Material recycled from products after use by consumers. Many EPR laws set minimum PCR content requirements."},
    {"abbr": "PIR", "full": "Post-Industrial Recycled (content)", "category": "Packaging", "description": "Manufacturing waste recycled back into production. Distinct from PCR for regulatory purposes."},
    {"abbr": "SUP", "full": "Single-Use Plastics", "category": "Packaging", "description": "Plastic items intended to be used only once. Subject to bans and restrictions in many jurisdictions."},
    {"abbr": "PFAS-free", "full": "Free from Per- and Polyfluoroalkyl Substances", "category": "Packaging", "description": "Descriptor used in packaging regulations (e.g., food contact materials) prohibiting intentional addition of PFAS."},

    # Standards bodies
    {"abbr": "ANSI", "full": "American National Standards Institute", "category": "Standards", "description": "Non-profit organization overseeing development of voluntary consensus standards for products, services, processes, systems, and personnel in the US."},
    {"abbr": "ASTM", "full": "American Society for Testing and Materials", "category": "Standards", "description": "International standards organization developing and publishing voluntary consensus technical standards."},
    {"abbr": "ISO", "full": "International Organization for Standardization", "category": "Standards", "description": "Independent international organization that develops and publishes international standards."},
    {"abbr": "IEC", "full": "International Electrotechnical Commission", "category": "Standards", "description": "International standards organization preparing and publishing international standards for electrical and electronic technologies."},

    # General compliance
    {"abbr": "EHS", "full": "Environment, Health and Safety", "category": "Compliance", "description": "Discipline concerned with protecting workers, the public, and the environment. Common abbreviation in manufacturing and compliance contexts."},
    {"abbr": "ESG", "full": "Environmental, Social and Governance", "category": "Compliance", "description": "Framework for assessing a company's business practices and performance on sustainability and ethical issues."},
    {"abbr": "GHG", "full": "Greenhouse Gas", "category": "Climate", "description": "Gases that trap heat in the atmosphere. Includes CO2, methane, nitrous oxide, and fluorinated gases."},
    {"abbr": "VOC", "full": "Volatile Organic Compound", "category": "Air Quality", "description": "Organic chemicals with high vapor pressure at room temperature. Regulated under the Clean Air Act for air quality impacts."},
    {"abbr": "HAP", "full": "Hazardous Air Pollutant", "category": "Air Quality", "description": "Pollutants known or suspected to cause cancer or other serious health effects. Listed under the Clean Air Act."},
    {"abbr": "NAAQS", "full": "National Ambient Air Quality Standards", "category": "Air Quality", "description": "EPA standards for outdoor air quality for six principal pollutants (criteria pollutants)."},
    {"abbr": "SPCC", "full": "Spill Prevention, Control, and Countermeasure", "category": "EPA Program", "description": "EPA program requiring facilities to develop plans to prevent oil spills into navigable waters."},
    {"abbr": "TRI", "full": "Toxics Release Inventory", "category": "EPA Program", "description": "EPA program tracking release and management of toxic chemicals by US facilities. Requires annual Form R reporting."},
    {"abbr": "NAICS", "full": "North American Industry Classification System", "category": "Classification", "description": "Standard used by federal statistical agencies to classify business establishments."},
]


# ── DB / JSON persistence ─────────────────────────────────────────────────────

def load_glossary() -> list[dict]:
    """Load glossary from JSON file; seed if empty."""
    if _GLOSSARY_JSON.exists():
        try:
            data = json.loads(_GLOSSARY_JSON.read_text())
            if data:
                return data
        except Exception:
            pass
    return []


def save_glossary(terms: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _GLOSSARY_JSON.write_text(json.dumps(terms, indent=2, ensure_ascii=False))


def _seed_if_empty() -> list[dict]:
    """Return current glossary, seeding with SEED_TERMS if empty."""
    existing = load_glossary()
    if existing:
        return existing
    logger.info("Glossary: seeding with %d terms", len(SEED_TERMS))
    save_glossary(SEED_TERMS)
    return list(SEED_TERMS)


# ── Claude extraction ─────────────────────────────────────────────────────────

_SYSTEM = """You are a regulatory compliance expert for a US windows/doors manufacturer.
Extract abbreviations and technical terms from regulatory text. Be precise and comprehensive."""

_PROMPT = """Review these recent regulatory compliance article summaries and extract any abbreviations or technical terms NOT already in our glossary.

EXISTING ABBREVIATIONS (do not repeat these):
{existing_abbrs}

RECENT ARTICLE CONTENT:
{article_text}

Extract new abbreviations and return JSON:
[
  {{
    "abbr": "ABBREVIATION",
    "full": "Full expanded text",
    "category": "One of: Chemicals|US Federal|EU Regulation|EU Directive|US Agency|EU Agency|State Agency|CA Agency|Legislative|Regulatory Process|Packaging|EPR|Conflict Minerals|Supply Chain|Standards|Compliance|Climate|Air Quality|Water / EPA|Industry Body|International|Publication|Classification|Other",
    "description": "1-2 sentence plain English explanation relevant to a windows/doors manufacturer"
  }}
]

Rules:
- Only include abbreviations that appear in the article text
- Skip common English words used as abbreviations (e.g. "US", "EU" are fine, "a", "an" are not)
- Skip proper names and company names
- Return [] if nothing new found
- Return JSON array only, no other text"""


def _extract_from_articles(articles: list[dict], existing: list[dict]) -> list[dict]:
    """Use Claude to extract new abbreviations from article summaries."""
    existing_abbrs = sorted(set(t["abbr"] for t in existing))

    # Build article text from summaries (first 30 articles, truncated)
    texts = []
    for art in articles[:30]:
        headline = art.get("headline", "")
        summary = art.get("summary", "")[:300]
        if headline or summary:
            texts.append(f"• {headline}: {summary}")
    article_text = "\n".join(texts[:50])

    if not article_text.strip():
        return []

    client = ClaudeClient()
    cache_key = f"glossary_extract_{date.today().isoformat()}"
    try:
        prompt = _PROMPT.format(
            existing_abbrs=", ".join(existing_abbrs[:150]),
            article_text=article_text[:4000],
        )
        response = client.complete_haiku(prompt, system=_SYSTEM, cache_key=cache_key)
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        new_terms = json.loads(text.strip())
        if isinstance(new_terms, list):
            return new_terms
    except Exception as e:
        logger.warning("Glossary extraction failed: %s", e)
    return []


# ── HTML render ───────────────────────────────────────────────────────────────

def _write_html(terms: list[dict], today: str) -> None:
    # Group by category, sort alphabetically within each
    by_cat: dict[str, list[dict]] = {}
    for t in sorted(terms, key=lambda x: x["abbr"].upper()):
        cat = t.get("category", "Other")
        by_cat.setdefault(cat, []).append(t)

    cat_order = [
        "Chemicals", "US Federal", "EU Regulation", "EU Directive",
        "US Agency", "EU Agency", "CA Agency", "State Agency",
        "Legislative", "Regulatory Process", "Packaging", "EPR",
        "Conflict Minerals", "Supply Chain", "Water / EPA", "Air Quality",
        "Climate", "Standards", "Industry Body", "International",
        "Publication", "Classification", "Compliance", "Other",
    ]
    ordered_cats = [c for c in cat_order if c in by_cat]
    ordered_cats += [c for c in sorted(by_cat) if c not in ordered_cats]

    # Nav links
    nav_links = " &nbsp;·&nbsp; ".join(
        f'<a href="#{cat.lower().replace(" ", "-").replace("/", "")}">{cat}</a>'
        for cat in ordered_cats
    )

    # Category sections
    sections = ""
    for cat in ordered_cats:
        cat_id = cat.lower().replace(" ", "-").replace("/", "")
        rows = "".join(
            f'<tr>'
            f'<td style="font-family:monospace;font-weight:700;font-size:13px;color:#0A5954;'
            f'padding:8px 16px 8px 0;white-space:nowrap;vertical-align:top;">{t["abbr"]}</td>'
            f'<td style="font-size:12px;font-weight:600;color:#111827;padding:8px 16px 8px 0;vertical-align:top;">{t["full"]}</td>'
            f'<td style="font-size:11px;color:#6b7280;padding:8px 0;line-height:1.5;">{t.get("description","")}</td>'
            f'</tr>'
            for t in by_cat[cat]
        )
        sections += (
            f'<h2 id="{cat_id}" style="font-size:13px;font-weight:700;color:#374151;'
            f'margin:28px 0 8px;padding-bottom:6px;border-bottom:2px solid #E5E7EB;'
            f'letter-spacing:.04em;text-transform:uppercase;">{cat}</h2>'
            f'<table style="width:100%;border-collapse:collapse;">{rows}</table>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Regulatory Abbreviation Dictionary</title>
<style>
  body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width: 1000px; margin: 32px auto; padding: 0 20px; color: #111827; }}
  h1 {{ font-size: 22px; color: #0A5954; margin-bottom: 4px; }}
  .meta {{ font-size: 12px; color: #6b7280; margin-bottom: 20px; }}
  .nav {{ font-size: 11px; color: #6b7280; margin-bottom: 24px; line-height: 2; }}
  .nav a {{ color: #0A5954; text-decoration: none; }}
  .nav a:hover {{ text-decoration: underline; }}
  tr:hover td {{ background: #f9fafb; }}
  .search {{ width: 100%; max-width: 400px; padding: 6px 12px; font-size: 13px;
             border: 1px solid #D1D5DB; border-radius: 4px; margin-bottom: 16px; }}
</style>
</head><body>
<h1>Regulatory Abbreviation Dictionary</h1>
<div class="meta">
  {len(terms)} terms &nbsp;·&nbsp; Updated {today} &nbsp;·&nbsp;
  <a href="dashboard.html" style="color:#0A5954;">&#8592; Dashboard</a>
</div>
<input class="search" type="text" placeholder="Search terms..." oninput="filterTerms(this.value)">
<div class="nav">{nav_links}</div>
<div id="content">{sections}</div>
<script>
function filterTerms(q) {{
  q = q.toLowerCase().trim();
  document.querySelectorAll('tr').forEach(function(tr) {{
    var text = tr.textContent.toLowerCase();
    tr.style.display = (!q || text.includes(q)) ? '' : 'none';
  }});
  document.querySelectorAll('h2').forEach(function(h) {{
    var tbl = h.nextElementSibling;
    if (!tbl) return;
    var visible = Array.from(tbl.querySelectorAll('tr')).some(function(r) {{ return r.style.display !== 'none'; }});
    h.style.display = visible ? '' : 'none';
  }});
}}
</script>
</body></html>"""

    _GLOSSARY_HTML.write_text(html, encoding="utf-8")
    logger.info("Glossary HTML written: %s (%d terms)", _GLOSSARY_HTML, len(terms))


# ── Main entry ────────────────────────────────────────────────────────────────

def run_glossary_agent(
    pipeline_output: Optional[dict] = None,
    force: bool = False,
) -> list[dict]:
    """
    Maintain the abbreviation glossary.
    - Seeds from SEED_TERMS on first run
    - Extracts new terms from pipeline_output articles (if provided)
    - Writes glossary.html
    Returns the current term list.
    """
    terms = _seed_if_empty()
    today = date.today().isoformat()

    # Extract new terms from articles if pipeline output provided
    if pipeline_output:
        all_articles = []
        for topic_data in pipeline_output.get("topics", []):
            all_articles.extend(topic_data.get("developments", []))

        if all_articles:
            new_terms = _extract_from_articles(all_articles, terms)
            if new_terms:
                # Deduplicate by abbr (case-insensitive)
                existing_abbrs = {t["abbr"].upper() for t in terms}
                added = 0
                for nt in new_terms:
                    if nt.get("abbr") and nt["abbr"].upper() not in existing_abbrs:
                        terms.append(nt)
                        existing_abbrs.add(nt["abbr"].upper())
                        added += 1
                if added:
                    logger.info("Glossary: added %d new terms from articles", added)
                    save_glossary(terms)

    _write_html(terms, today)
    return terms


def get_glossary() -> list[dict]:
    """Return current glossary terms, seeding if empty."""
    return _seed_if_empty()
