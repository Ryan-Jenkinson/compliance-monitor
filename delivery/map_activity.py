"""Count article mentions per state/country for map heat layer."""
from __future__ import annotations
import re
from typing import Dict, List

# US state name → abbreviation mapping
_US_STATES: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}

# EU/REACH country name → code mapping
_EU_COUNTRIES: Dict[str, str] = {
    "germany": "DE", "france": "FR", "italy": "IT", "spain": "ES",
    "netherlands": "NL", "belgium": "BE", "poland": "PL", "sweden": "SE",
    "austria": "AT", "denmark": "DK", "finland": "FI", "czech republic": "CZ",
    "czechia": "CZ", "romania": "RO", "hungary": "HU", "portugal": "PT",
    "greece": "GR", "slovakia": "SK", "ireland": "IE", "croatia": "HR",
    "slovenia": "SI", "bulgaria": "BG", "luxembourg": "LU", "estonia": "EE",
    "latvia": "LV", "lithuania": "LT", "cyprus": "CY", "malta": "MT",
    "switzerland": "CH", "norway": "NO", "iceland": "IS", "united kingdom": "GB",
    "uk": "GB", "britain": "GB",
}


def count_us_state_activity(articles: List[dict]) -> Dict[str, int]:
    """Count how many articles mention each US state. Returns {state_abbr: count}."""
    counts: Dict[str, int] = {}
    for article in articles:
        text = (
            (article.get("title") or "") + " " + (article.get("snippet") or "")
        ).lower()
        seen_in_article: set = set()
        for name, abbr in _US_STATES.items():
            if re.search(r'\b' + re.escape(name) + r'\b', text):
                seen_in_article.add(abbr)
        # Also check two-letter abbreviations in context (e.g. "MN PRISM", "CA law")
        for abbr in ["MN", "CA", "ME", "OR", "CO", "WA", "NY", "PA", "WI", "MI",
                     "IL", "OH", "VA", "NC", "TX", "FL", "GA", "AZ", "NV", "UT"]:
            pattern = r'\b' + abbr + r'\b'
            if re.search(pattern, (article.get("title") or "") + " " + (article.get("snippet") or "")):
                seen_in_article.add(abbr)
        for abbr in seen_in_article:
            counts[abbr] = counts.get(abbr, 0) + 1
    return counts


def count_eu_country_activity(articles: List[dict]) -> Dict[str, int]:
    """Count how many articles mention each EU country. Returns {country_code: count}."""
    counts: Dict[str, int] = {}
    for article in articles:
        text = (
            (article.get("title") or "") + " " + (article.get("snippet") or "")
        ).lower()
        seen_in_article: set = set()
        for name, code in _EU_COUNTRIES.items():
            if re.search(r'\b' + re.escape(name) + r'\b', text):
                seen_in_article.add(code)
        for code in seen_in_article:
            counts[code] = counts.get(code, 0) + 1
    return counts


def activity_to_opacity(count: int, max_count: int) -> float:
    """Convert article count to opacity multiplier (0.0 to 1.0). 0 articles = 0.0 opacity."""
    if max_count == 0 or count == 0:
        return 0.0
    # Scale: 1 article = 0.3, max = 1.0
    return min(1.0, 0.3 + 0.7 * (count / max_count))
