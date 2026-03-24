"""Regulation Registry Populator — seeds and maintains the regulations table.

Two modes:
1. seed_from_pfas_state_data() — one-time seed from config/pfas_state_data.json
2. extract_from_pipeline() — post-pipeline extraction from Stage 2 summaries
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from subscribers.db import (
    upsert_regulation,
    add_regulation_event,
    get_regulation_count,
)

logger = logging.getLogger(__name__)

_STATE_DATA_PATH = Path(__file__).parent.parent / "config" / "pfas_state_data.json"

# Map pfas_state_data.json status values to regulation status values
_STATUS_MAP = {
    "comprehensive": "enacted",
    "limited": "enacted",
    "proposed": "proposed",
    "none": "monitoring",
}


def _parse_date(date_str: str) -> Optional[str]:
    """Try to parse a date string into YYYY-MM-DD format.

    Handles formats like:
    - "Jan 1, 2025"
    - "Jul 1, 2026"
    - "Dec 31, 2024"
    - "2028" (returns 2028-01-01)
    - "Oct 2021" (returns 2021-10-01)
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    # Full date: "Jan 1, 2025" or "January 1, 2025"
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Month + year: "Oct 2021" or "July 2026"
    for fmt in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-01")
        except ValueError:
            continue

    # Year only: "2028"
    if re.match(r"^\d{4}$", date_str):
        return f"{date_str}-01-01"

    return None


def _extract_date_from_key_date(key_date_str: str) -> tuple[Optional[str], str]:
    """Extract a date and description from a key_dates entry.

    Format: "Jan 1, 2025: Description here"
    Returns: (parsed_date, description)
    """
    # Try splitting on first colon that follows a date-like pattern
    match = re.match(r"^(.+?):\s*(.+)$", key_date_str)
    if match:
        date_part = match.group(1).strip()
        desc_part = match.group(2).strip()
        parsed = _parse_date(date_part)
        if parsed:
            return parsed, desc_part
        # Date parse failed — might be "Pending: ..." or "Ongoing: ..."
        return None, key_date_str

    return None, key_date_str


def _classify_event_type(description: str) -> str:
    """Classify a key_date description into an event type."""
    desc_lower = description.lower()
    if any(w in desc_lower for w in ["ban on", "ban effective", "prohibition", "prohibit"]):
        return "ban_effective"
    if any(w in desc_lower for w in ["registration", "reporting", "disclosure", "labeling"]):
        return "reporting_deadline"
    if any(w in desc_lower for w in ["mcl", "drinking water", "contaminant level"]):
        return "standard_effective"
    if any(w in desc_lower for w in ["signed", "enacted", "effective"]):
        return "enacted"
    if any(w in desc_lower for w in ["proposed", "introduced", "pending", "in committee"]):
        return "proposed"
    if any(w in desc_lower for w in ["phase", "expanded", "broader"]):
        return "phase_effective"
    if "firefighting" in desc_lower or "foam" in desc_lower:
        return "ban_effective"
    return "milestone"


def seed_from_pfas_state_data() -> dict:
    """Seed the regulations table from config/pfas_state_data.json.

    Returns summary stats: {regulations_added, events_added, states_processed}
    """
    if not _STATE_DATA_PATH.exists():
        logger.warning(f"PFAS state data not found: {_STATE_DATA_PATH}")
        return {"regulations_added": 0, "events_added": 0, "states_processed": 0}

    data = json.loads(_STATE_DATA_PATH.read_text())
    states = data.get("states", {})

    reg_count = 0
    event_count = 0
    states_processed = 0

    for code, state_info in states.items():
        state_name = state_info.get("name", code)
        status = state_info.get("status", "none")
        laws = state_info.get("laws", [])
        key_dates = state_info.get("key_dates", [])
        summary = state_info.get("summary", "")

        if not laws and status == "none":
            # Still create a monitoring entry for states with no laws
            reg_id = upsert_regulation(
                topic="PFAS",
                jurisdiction=state_name,
                regulation_name=f"{state_name} — No PFAS legislation",
                current_status="monitoring",
            )
            reg_count += 1
            states_processed += 1
            continue

        # Create one regulation per law
        for law_name in laws:
            reg_status = _STATUS_MAP.get(status, "monitoring")

            # Find the earliest effective date from key_dates for this law
            effective = None
            for kd in key_dates:
                event_date, desc = _extract_date_from_key_date(kd)
                if event_date and law_name.split("(")[0].strip().lower() in kd.lower():
                    if not effective or event_date < effective:
                        effective = event_date

            reg_id = upsert_regulation(
                topic="PFAS",
                jurisdiction=state_name,
                regulation_name=law_name,
                current_status=reg_status,
                effective_date=effective,
            )
            reg_count += 1

            # Add events from key_dates
            for kd in key_dates:
                event_date, desc = _extract_date_from_key_date(kd)
                event_type = _classify_event_type(desc)
                add_regulation_event(
                    regulation_id=reg_id,
                    event_type=event_type,
                    event_date=event_date,
                    description=desc,
                )
                event_count += 1

        states_processed += 1

    logger.info(
        f"PFAS state data seed complete: {reg_count} regulations, "
        f"{event_count} events across {states_processed} states"
    )
    return {
        "regulations_added": reg_count,
        "events_added": event_count,
        "states_processed": states_processed,
    }


def seed_new_topic_regulations() -> dict:
    """Seed known regulations for Prop 65, Conflict Minerals, and Forced Labor."""
    new_topic_regs = [
        # Prop 65 — California OEHHA
        {
            "topic": "Prop65",
            "jurisdiction": "California",
            "regulation_name": "Proposition 65 (Safe Drinking Water and Toxic Enforcement Act of 1986)",
            "current_status": "enacted",
            "effective_date": "1987-02-27",
            "events": [
                ("enacted", "1987-02-27", "Prop 65 takes effect — businesses must warn before knowingly exposing individuals to listed chemicals"),
                ("milestone", "2018-08-30", "Updated warning language requirement takes effect — new Prop 65 warning format required"),
                ("milestone", "2025-01-01", "Over 900 chemicals on the Prop 65 list including PFOA, PFOS, lead, cadmium, phthalates"),
            ],
        },
        {
            "topic": "Prop65",
            "jurisdiction": "California",
            "regulation_name": "OEHHA — PFAS Listings (Prop 65)",
            "current_status": "enacted",
            "effective_date": "2021-11-19",
            "events": [
                ("enacted", "2021-11-19", "PFOA listed as a Prop 65 reproductive toxicant"),
                ("enacted", "2022-04-01", "PFOS listed as a Prop 65 reproductive toxicant"),
                ("milestone", "2023-01-01", "Grace period for PFOA/PFOS warnings expires — labels required on covered products sold in CA"),
            ],
        },
        {
            "topic": "Prop65",
            "jurisdiction": "California",
            "regulation_name": "Prop 65 — Lead in Consumer Products",
            "current_status": "enacted",
            "events": [
                ("enacted", "1988-01-01", "Lead listed as both a carcinogen and reproductive toxicant under Prop 65"),
                ("milestone", "2024-01-01", "NSRL for inorganic lead: 0.5 micrograms/day — enforced via private plaintiff actions"),
            ],
        },
        # Conflict Minerals — Federal SEC
        {
            "topic": "ConflictMinerals",
            "jurisdiction": "Federal",
            "regulation_name": "Dodd-Frank Section 1502 — Conflict Minerals Rule (SEC)",
            "current_status": "enacted",
            "effective_date": "2013-01-01",
            "events": [
                ("enacted", "2012-08-22", "SEC adopts final conflict minerals rule under Dodd-Frank Section 1502"),
                ("reporting_deadline", "2013-11-04", "First Form SD conflict minerals reports due to SEC"),
                ("milestone", "2017-04-07", "Court upholds constitutionality of disclosure requirement (D.C. Circuit)"),
                ("reporting_deadline", "2025-05-31", "Annual Form SD due date — conflict minerals report for prior calendar year"),
            ],
        },
        {
            "topic": "ConflictMinerals",
            "jurisdiction": "EU",
            "regulation_name": "EU Conflict Minerals Regulation (EU 2017/821)",
            "current_status": "enacted",
            "effective_date": "2021-01-01",
            "events": [
                ("enacted", "2017-05-17", "EU Conflict Minerals Regulation adopted — mandatory due diligence for EU importers of 3TG"),
                ("enacted", "2021-01-01", "Regulation fully applicable — all EU importers above thresholds must comply with OECD DD Guidance"),
            ],
        },
        {
            "topic": "ConflictMinerals",
            "jurisdiction": "EU",
            "regulation_name": "EU Corporate Sustainability Due Diligence Directive (CSDDD)",
            "current_status": "enacted",
            "effective_date": "2024-07-25",
            "events": [
                ("enacted", "2024-07-25", "CSDDD enters into force — mandatory human rights and environmental due diligence for large companies"),
                ("reporting_deadline", "2026-07-26", "Member states must transpose CSDDD into national law"),
                ("reporting_deadline", "2027-01-01", "Phase 1: Large EU companies (>5,000 employees, >1.5B turnover) must comply"),
                ("reporting_deadline", "2028-01-01", "Phase 2: Smaller large companies (>3,000 employees) must comply"),
                ("reporting_deadline", "2029-01-01", "Phase 3: Full scope companies (>1,000 employees) must comply"),
            ],
        },
        # Forced Labor — Federal UFLPA
        {
            "topic": "ForcedLabor",
            "jurisdiction": "Federal",
            "regulation_name": "Uyghur Forced Labor Prevention Act (UFLPA)",
            "current_status": "enacted",
            "effective_date": "2022-06-21",
            "events": [
                ("enacted", "2021-12-23", "UFLPA signed into law — rebuttable presumption that goods produced in Xinjiang involve forced labor"),
                ("enacted", "2022-06-21", "UFLPA enforcement begins — CBP begins detaining goods with Xinjiang nexus"),
                ("milestone", "2022-06-17", "DHS publishes UFLPA Strategy and initial Entity List"),
                ("milestone", "2024-01-01", "Entity List expanded — additional solar, polysilicon, cotton, aluminum companies added"),
                ("milestone", "2025-01-01", "Over 70 entities on UFLPA Entity List across cotton, polysilicon, tomatoes, silica sectors"),
            ],
        },
        {
            "topic": "ForcedLabor",
            "jurisdiction": "Federal",
            "regulation_name": "CBP Withhold Release Orders — Forced Labor",
            "current_status": "active",
            "events": [
                ("milestone", "2022-01-01", "CBP issued 52 Withhold Release Orders (WROs) in effect — ongoing enforcement mechanism prior to UFLPA"),
                ("milestone", "2024-01-01", "CBP has processed over 8,000 UFLPA shipment detentions since June 2022"),
            ],
        },
        {
            "topic": "ForcedLabor",
            "jurisdiction": "California",
            "regulation_name": "California Transparency in Supply Chains Act (SB 657)",
            "current_status": "enacted",
            "effective_date": "2012-01-01",
            "events": [
                ("enacted", "2010-09-30", "SB 657 signed — requires retailers and manufacturers with >$100M global revenue and California operations to disclose supply chain anti-slavery efforts"),
                ("enacted", "2012-01-01", "SB 657 disclosure requirements take effect"),
            ],
        },
        {
            "topic": "ForcedLabor",
            "jurisdiction": "Federal",
            "regulation_name": "Tariff Act Section 307 — Forced Labor Import Ban",
            "current_status": "enacted",
            "effective_date": "1930-06-17",
            "events": [
                ("enacted", "1930-06-17", "Tariff Act Section 307 — prohibits importation of goods made with forced labor (foundational law UFLPA builds on)"),
                ("milestone", "2016-02-24", "Trade Facilitation and Trade Enforcement Act removes consumptive demand exception — Section 307 fully enforceable"),
            ],
        },
    ]

    reg_count = 0
    event_count = 0

    for reg_data in new_topic_regs:
        reg_id = upsert_regulation(
            topic=reg_data["topic"],
            jurisdiction=reg_data["jurisdiction"],
            regulation_name=reg_data["regulation_name"],
            current_status=reg_data["current_status"],
            effective_date=reg_data.get("effective_date"),
        )
        reg_count += 1

        for event in reg_data.get("events", []):
            event_type, event_date, description = event
            add_regulation_event(
                regulation_id=reg_id,
                event_type=event_type,
                event_date=event_date,
                description=description,
            )
            event_count += 1

    logger.info(f"New topic regulation seed: {reg_count} regulations, {event_count} events")
    return {"regulations_added": reg_count, "events_added": event_count}


def seed_federal_regulations() -> dict:
    """Seed known federal regulations (EPA, TSCA, REACH) into the registry.

    These are well-known regulations that don't come from pfas_state_data.json.
    """
    federal_regs = [
        # EPA PFAS
        {
            "topic": "PFAS",
            "jurisdiction": "Federal",
            "regulation_name": "EPA PFAS National Primary Drinking Water Regulation (NPDWR)",
            "current_status": "enacted",
            "effective_date": "2024-04-10",
            "events": [
                ("enacted", "2024-04-10", "EPA finalizes NPDWR for 6 PFAS: PFOA 4ppt, PFOS 4ppt, PFHxS/PFNA/HFPO-DA 10ppt, mixture 1.0 Hazard Index"),
                ("reporting_deadline", "2027-04-10", "Public water systems must complete initial monitoring"),
                ("ban_effective", "2029-04-10", "Full compliance deadline for all public water systems"),
            ],
        },
        {
            "topic": "PFAS",
            "jurisdiction": "Federal",
            "regulation_name": "EPA PFAS CERCLA Hazardous Substance Designation",
            "current_status": "enacted",
            "effective_date": "2024-07-18",
            "events": [
                ("enacted", "2024-07-18", "PFOA and PFOS designated as CERCLA hazardous substances"),
                ("milestone", "2025-01-18", "Enforcement provisions take full effect"),
            ],
        },
        # TSCA
        {
            "topic": "TSCA",
            "jurisdiction": "Federal",
            "regulation_name": "TSCA Section 6 — Risk Evaluations (EPA)",
            "current_status": "enacted",
            "events": [
                ("milestone", "2024-01-01", "EPA completing risk evaluations for first 10 high-priority substances"),
                ("milestone", "2024-12-01", "EPA proposed ban on chrysotile asbestos under TSCA Section 6"),
            ],
        },
        {
            "topic": "TSCA",
            "jurisdiction": "Federal",
            "regulation_name": "TSCA Section 8(a)(7) — PFAS Reporting Rule",
            "current_status": "enacted",
            "effective_date": "2024-11-13",
            "events": [
                ("enacted", "2024-11-13", "Final rule requires manufacturers/importers to report PFAS use since 2011"),
                ("reporting_deadline", "2025-05-08", "Original reporting deadline (extended to 2025-07-11)"),
                ("reporting_deadline", "2025-07-11", "Extended reporting deadline for PFAS manufacturers/importers"),
            ],
        },
        # EPR
        {
            "topic": "EPR",
            "jurisdiction": "California",
            "regulation_name": "SB 54 — Plastic Pollution Prevention and Packaging Producer Responsibility Act",
            "current_status": "enacted",
            "effective_date": "2024-01-01",
            "events": [
                ("enacted", "2022-06-30", "SB 54 signed by Governor Newsom"),
                ("reporting_deadline", "2024-01-01", "Producer registration with CalRecycle PRO begins"),
                ("milestone", "2027-01-01", "Source reduction targets begin (25% reduction by 2032)"),
                ("ban_effective", "2032-01-01", "65% of single-use packaging must be recyclable or compostable"),
            ],
        },
        {
            "topic": "EPR",
            "jurisdiction": "Maine",
            "regulation_name": "LD 1541 — Extended Producer Responsibility for Packaging",
            "current_status": "enacted",
            "effective_date": "2024-07-01",
            "events": [
                ("enacted", "2021-07-13", "LD 1541 signed — first US state EPR for packaging law"),
                ("reporting_deadline", "2024-07-01", "Producer registration required"),
                ("milestone", "2026-01-01", "Fee obligations begin for producers"),
            ],
        },
        {
            "topic": "EPR",
            "jurisdiction": "Oregon",
            "regulation_name": "SB 582 — Plastic Pollution and Recycling Modernization Act",
            "current_status": "enacted",
            "effective_date": "2025-07-01",
            "events": [
                ("enacted", "2021-08-06", "SB 582 signed"),
                ("reporting_deadline", "2025-07-01", "Producer responsibility organization begins operations"),
            ],
        },
        {
            "topic": "EPR",
            "jurisdiction": "Colorado",
            "regulation_name": "HB 22-1355 — Producer Responsibility for Statewide Recycling",
            "current_status": "enacted",
            "effective_date": "2025-07-01",
            "events": [
                ("enacted", "2022-06-03", "HB 22-1355 signed"),
                ("reporting_deadline", "2025-07-01", "PRO advisory board and needs assessment due"),
                ("milestone", "2026-01-01", "Producer fee assessments begin"),
            ],
        },
        # REACH
        {
            "topic": "REACH",
            "jurisdiction": "EU",
            "regulation_name": "EU REACH Regulation (EC 1907/2006)",
            "current_status": "enacted",
            "effective_date": "2007-06-01",
            "events": [
                ("enacted", "2007-06-01", "REACH regulation enters into force"),
                ("milestone", "2025-01-01", "SVHC Candidate List contains 240+ substances"),
            ],
        },
        {
            "topic": "REACH",
            "jurisdiction": "EU",
            "regulation_name": "EU PFAS Universal Restriction Proposal (ECHA)",
            "current_status": "proposed",
            "events": [
                ("proposed", "2023-02-07", "ECHA publishes universal PFAS restriction proposal from 5 EU countries"),
                ("milestone", "2025-06-01", "RAC/SEAC opinions expected on restriction dossier"),
                ("milestone", "2027-01-01", "Earliest possible adoption if proposal advances (estimated)"),
            ],
        },
    ]

    reg_count = 0
    event_count = 0

    for reg_data in federal_regs:
        reg_id = upsert_regulation(
            topic=reg_data["topic"],
            jurisdiction=reg_data["jurisdiction"],
            regulation_name=reg_data["regulation_name"],
            current_status=reg_data["current_status"],
            effective_date=reg_data.get("effective_date"),
        )
        reg_count += 1

        for event in reg_data.get("events", []):
            event_type, event_date, description = event
            add_regulation_event(
                regulation_id=reg_id,
                event_type=event_type,
                event_date=event_date,
                description=description,
            )
            event_count += 1

    logger.info(f"Federal regulation seed: {reg_count} regulations, {event_count} events")
    return {"regulations_added": reg_count, "events_added": event_count}


def seed_all() -> dict:
    """Run all seed functions. Safe to run multiple times (upserts)."""
    from subscribers.db import init_db, get_regulation_count

    init_db()

    before = get_regulation_count()
    pfas_stats = seed_from_pfas_state_data()
    federal_stats = seed_federal_regulations()
    new_topic_stats = seed_new_topic_regulations()
    after = get_regulation_count()

    total = {
        "regulations_before": before,
        "regulations_after": after,
        "new_regulations": after - before,
        "pfas_state_data": pfas_stats,
        "federal": federal_stats,
        "new_topics": new_topic_stats,
    }
    logger.info(f"Registry seed complete: {before} → {after} regulations")
    return total


def extract_from_pipeline(topic_summaries: list[dict]) -> int:
    """Extract regulation records from Stage 2 pipeline output.

    Looks for developments that reference specific regulations, laws, or rules
    and upserts them into the registry. Lightweight — no Claude call needed,
    just pattern matching on the structured pipeline output.

    Returns count of regulations processed.
    """
    count = 0

    for ts in topic_summaries:
        topic = ts.get("topic", "")
        for dev in ts.get("developments", []):
            headline = dev.get("headline", "")
            summary = dev.get("summary", "")
            url = dev.get("url", "")
            urgency = dev.get("urgency", "MEDIUM")

            # Look for jurisdiction + law name patterns
            jurisdiction, reg_name = _extract_regulation_from_text(headline, summary, topic)
            if not jurisdiction or not reg_name:
                continue

            # Determine status from urgency and language
            status = _infer_status(summary, urgency)

            # Extract date if mentioned
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", dev.get("date", "") or "")
            effective = date_match.group(1) if date_match else None

            reg_id = upsert_regulation(
                topic=topic,
                jurisdiction=jurisdiction,
                regulation_name=reg_name,
                current_status=status,
                effective_date=effective,
                source_url=url,
            )

            # Add the development as an event
            add_regulation_event(
                regulation_id=reg_id,
                event_type="article_mention",
                event_date=dev.get("date"),
                description=headline,
                source_url=url,
            )
            count += 1

    if count:
        logger.info(f"Pipeline extraction: {count} regulation records updated")
    return count


def _extract_regulation_from_text(headline: str, summary: str, topic: str) -> tuple[Optional[str], Optional[str]]:
    """Try to extract jurisdiction and regulation name from article text."""
    text = f"{headline} {summary}"

    # Common US state names
    states = {
        "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
        "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
        "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
        "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
        "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
        "New Hampshire", "New Jersey", "New Mexico", "New York",
        "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
        "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
        "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
        "West Virginia", "Wisconsin", "Wyoming",
    }

    # Find jurisdiction
    jurisdiction = None
    if any(w in text.lower() for w in ["federal", "epa", "tsca", "cercla"]):
        jurisdiction = "Federal"
    elif any(w in text.lower() for w in ["eu ", "echa", "reach", "european"]):
        jurisdiction = "EU"
    else:
        for state in states:
            if state in text:
                jurisdiction = state
                break

    if not jurisdiction:
        return None, None

    # Find bill/law reference patterns: "HB 123", "SB 54", "AB 1200", "LD 1503", etc.
    bill_match = re.search(
        r"(?:H\.?B\.?|S\.?B\.?|A\.?B\.?|L\.?D\.?|H\.?R\.?|P\.?A\.?)\s*\d+[-\w]*",
        text, re.IGNORECASE
    )
    if bill_match:
        return jurisdiction, bill_match.group(0).strip()

    # Named acts
    act_match = re.search(r"(?:the\s+)?([A-Z][\w\s'-]+(?:Act|Law|Rule|Regulation|Order))", text)
    if act_match:
        return jurisdiction, act_match.group(1).strip()

    # Fall back to using the headline as the regulation name
    if jurisdiction and len(headline) < 80:
        return jurisdiction, headline

    return None, None


def _infer_status(summary: str, urgency: str) -> str:
    """Infer regulation status from summary text and urgency."""
    lower = summary.lower()
    if any(w in lower for w in ["enacted", "signed", "effective", "in effect", "finalized"]):
        return "enacted"
    if any(w in lower for w in ["proposed", "introduced", "in committee", "pending"]):
        return "proposed"
    if any(w in lower for w in ["rulemaking", "comment period", "draft"]):
        return "rulemaking"
    if urgency == "HIGH":
        return "active"
    return "active"


def get_regulation_status_summary() -> dict:
    """
    Return per-topic regulation counts and upcoming effective dates.
    Used by the dashboard status matrix.

    Returns:
        {
          "counts": {"PFAS": 72, "EPR": 5, ...},
          "upcoming": [...],   # regulations with future effective_date
          "total": 100,
        }
    """
    from subscribers.db import get_connection
    conn = get_connection()

    rows = conn.execute(
        "SELECT topic, COUNT(*) as cnt FROM regulations GROUP BY topic"
    ).fetchall()
    counts = {r["topic"]: r["cnt"] for r in rows}

    today = date.today().isoformat()
    upcoming = conn.execute(
        """SELECT topic, regulation_name, effective_date, current_status
           FROM regulations
           WHERE effective_date >= ?
           ORDER BY effective_date ASC
           LIMIT 10""",
        (today,)
    ).fetchall()
    conn.close()

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "upcoming": [dict(r) for r in upcoming],
    }


def get_key_regulation_milestones(limit: int = 12) -> list[dict]:
    """
    Return the most important upcoming regulation milestones for the dashboard
    status cards. Joins regulations with their next future event.

    Returns list of dicts:
        {topic, regulation_name, jurisdiction, current_status,
         next_event_type, next_event_date, next_event_desc, days_until,
         source_url}
    """
    from subscribers.db import get_connection
    today_str = date.today().isoformat()
    today_d = date.today()

    conn = get_connection()

    # Fetch regulations with at least one future event
    rows = conn.execute(
        """
        SELECT
            r.id, r.topic, r.regulation_name, r.jurisdiction,
            r.current_status, r.source_url,
            e.event_type, e.event_date, e.description
        FROM regulations r
        JOIN regulation_events e ON e.regulation_id = r.id
        WHERE e.event_date >= ?
          AND e.event_type != 'article_mention'
          AND r.topic NOT IN ('PFAS')   -- exclude per-state PFAS clutter
        ORDER BY e.event_date ASC
        """,
        (today_str,)
    ).fetchall()

    # Also include PFAS Federal/California/Minnesota regulations (not all 98 states)
    pfas_rows = conn.execute(
        """
        SELECT
            r.id, r.topic, r.regulation_name, r.jurisdiction,
            r.current_status, r.source_url,
            e.event_type, e.event_date, e.description
        FROM regulations r
        JOIN regulation_events e ON e.regulation_id = r.id
        WHERE e.event_date >= ?
          AND e.event_type != 'article_mention'
          AND r.topic = 'PFAS'
          AND r.jurisdiction IN ('Federal', 'California', 'Minnesota', 'Washington')
        ORDER BY e.event_date ASC
        """,
        (today_str,)
    ).fetchall()

    all_rows = list(rows) + list(pfas_rows)

    # Deduplicate: one entry per regulation_id (take the soonest future event)
    seen: set = set()
    milestones = []
    for row in sorted(all_rows, key=lambda r: r["event_date"] or "9999"):
        reg_id = row["id"]
        if reg_id in seen:
            continue
        seen.add(reg_id)

        event_date_str = row["event_date"]
        try:
            event_date_d = date.fromisoformat(event_date_str)
            days_until = (event_date_d - today_d).days
        except Exception:
            days_until = None

        milestones.append({
            "topic": row["topic"],
            "regulation_name": row["regulation_name"],
            "jurisdiction": row["jurisdiction"],
            "current_status": row["current_status"] or "",
            "next_event_type": row["event_type"],
            "next_event_date": event_date_str,
            "next_event_desc": row["description"] or "",
            "days_until": days_until,
            "source_url": row["source_url"] or "",
        })

        if len(milestones) >= limit:
            break

    conn.close()
    return milestones


# CLI entry point for seeding
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = seed_all()
    print(json.dumps(result, indent=2))
