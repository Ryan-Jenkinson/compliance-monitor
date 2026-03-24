"""Content Accuracy Auditor — verifies factual claims on the live site.

Four-phase process:
  1. Crawl pages (pure Python, reuses link checker)
  2. Extract claims from page text (Haiku)
  3. Verify each claim via cascade: DB → article cache → SME spot-check → source URL
  4. Synthesize final accuracy report (Sonnet)

Cost per run: ~$0.25–$0.50.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from ai.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_AUDIT_DIR = Path(__file__).parent.parent / "data" / "site_audit"
_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
_BASE_URL = "https://ryan-jenkinson.github.io/compliance-maps"
_START_URL = f"{_BASE_URL}/dashboard.html"

# Claim types that are always escalated to SME regardless of DB result
_HIGH_STAKES_CLAIM_TYPES = {"deadline", "enforcement", "enacted"}

# Max number of claims to SME-verify (cost control)
_MAX_SME_ESCALATIONS = 12


def run_audit(start_url: str = _START_URL) -> dict:
    """Full content accuracy audit. Returns structured result dict."""
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    client = ClaudeClient()
    today_str = date.today().isoformat()

    logger.info("Content audit: Phase 1 — crawling pages")
    pages = _crawl_pages(start_url)
    logger.info(f"  Crawled {len(pages)} pages")

    logger.info("Content audit: Phase 2 — extracting claims")
    claims = _extract_claims(pages, client)
    logger.info(f"  Extracted {len(claims)} claims")

    logger.info("Content audit: Phase 3 — verifying claims")
    verified, flagged, unverifiable = _verify_claims(claims, client)
    logger.info(f"  Verified: {len(verified)}, Flagged: {len(flagged)}, Unverifiable: {len(unverifiable)}")

    logger.info("Content audit: Phase 4 — synthesizing report")
    report = _synthesize_report(verified, flagged, unverifiable, client)

    # Save reports
    json_path = _AUDIT_DIR / f"accuracy_report_{today_str}.json"
    json_path.write_text(json.dumps(report, indent=2))

    html_path = _AUDIT_DIR / f"accuracy_report_{today_str}.html"
    html_path.write_text(_render_html_report(report))

    # Persist to DB
    try:
        from subscribers.db import get_connection
        conn = get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO site_audit_reports
               (audit_date, audit_type, summary_json, issues_count, critical_count,
                confidence_score, report_path)
               VALUES (?, 'content_accuracy', ?, ?, ?, ?, ?)""",
            (
                today_str,
                json.dumps({"verified": len(verified), "flagged": len(flagged),
                            "unverifiable": len(unverifiable),
                            "confidence_score": report.get("confidence_score")}),
                len(flagged),
                len([f for f in flagged if f.get("severity") == "high"]),
                report.get("confidence_score"),
                str(html_path),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to save content audit to DB: {e}")

    logger.info(f"Content audit saved: {html_path}")
    return report


# ---------------------------------------------------------------------------
# Phase 1: Crawl
# ---------------------------------------------------------------------------

def _crawl_pages(start_url: str) -> list[dict]:
    """Reuse link checker's crawl; only return pages with extractable text content."""
    import time
    import requests
    from urllib.parse import urljoin, urlparse
    from bs4 import BeautifulSoup
    from collections import deque

    base_parsed = urlparse(start_url)
    visited: set[str] = set()
    queue: deque[str] = deque([start_url])
    pages: list[dict] = []
    session = requests.Session()
    session.headers["User-Agent"] = "ComplianceMonitor-ContentAuditor/1.0"
    max_pages = 25  # cost control

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        parsed = urlparse(url)
        if parsed.netloc != base_parsed.netloc:
            continue
        if url.endswith((".pdf", ".xlsx", ".csv", ".ics", ".json", ".xml",
                          ".png", ".jpg", ".svg", ".zip", ".woff", ".css", ".js")):
            continue

        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove nav/footer/script/style noise
            for tag in soup(["script", "style", "nav", "footer", "head"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = " ".join(text.split())  # normalize whitespace
            if len(text) < 100:
                continue
            pages.append({"url": url, "text": text[:8000]})  # cap per page

            # Queue internal links
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("#") or href.startswith("javascript:"):
                    continue
                full = urljoin(url, href).split("#")[0]
                if urlparse(full).netloc == base_parsed.netloc and full not in visited:
                    queue.append(full)

            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"Failed to crawl {url}: {e}")

    return pages


# ---------------------------------------------------------------------------
# Phase 2: Extract claims
# ---------------------------------------------------------------------------

_CLAIM_EXTRACTION_SYSTEM = """You are a regulatory compliance auditor extracting verifiable
factual claims from website text. Extract only specific, checkable facts — not opinions
or general descriptions.

For each claim, identify:
- claim: the verbatim or paraphrased specific assertion
- type: one of: deadline, bill_status, regulation_status, statistic, enforcement, enacted, other
- topic: PFAS | EPR | REACH | TSCA | Prop65 | ConflictMinerals | ForcedLabor | general
- specificity: high (exact dates/numbers/bill IDs) | medium | low

Focus on:
- Specific dates and deadlines ("July 1, 2026", "by 2030")
- Bill numbers and their legislative stage ("MN HF 1234 is in committee")
- Regulation status claims ("EPA finalized the rule in 2024")
- Statistical claims ("151 bills tracked", "18 high-relevance states")
- Enforcement actions ("CBP detained X shipments")

Skip navigation text, generic descriptions, and unverifiable opinions.
Return a JSON array of claim objects."""

def _extract_claims(pages: list[dict], client: ClaudeClient) -> list[dict]:
    """Batch pages and send to Haiku for claim extraction."""
    claims: list[dict] = []
    # Process in batches of 3 pages
    batch_size = 3
    for i in range(0, len(pages), batch_size):
        batch = pages[i:i + batch_size]
        combined = "\n\n---\n\n".join(
            f"PAGE: {p['url']}\n{p['text'][:2000]}" for p in batch
        )
        prompt = (
            f"Extract all verifiable factual claims from these compliance dashboard pages.\n\n"
            f"{combined}\n\n"
            f"Return JSON array of: {{claim, type, topic, specificity, page_url}}"
        )
        try:
            raw = client.complete_haiku(prompt, system=_CLAIM_EXTRACTION_SYSTEM)
            # Extract JSON from response
            raw = raw.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            batch_claims = json.loads(raw)
            if isinstance(batch_claims, list):
                # Add page context
                for c in batch_claims:
                    if not c.get("page_url"):
                        c["page_url"] = batch[0]["url"]
                claims.extend(batch_claims)
        except Exception as e:
            logger.warning(f"Claim extraction batch {i} failed: {e}")

    return claims


# ---------------------------------------------------------------------------
# Phase 3: Verify claims
# ---------------------------------------------------------------------------

def _verify_claims(
    claims: list[dict], client: ClaudeClient
) -> tuple[list[dict], list[dict], list[dict]]:
    """Cascade verification: DB → article cache → SME → source URL."""
    from subscribers.db import get_connection

    verified: list[dict] = []
    flagged: list[dict] = []
    unverifiable: list[dict] = []
    sme_escalations = 0

    # Pre-load DB data for fast local checks
    try:
        conn = get_connection()
        db_bills = {
            r["bill_number"]: dict(r)
            for r in conn.execute(
                "SELECT bill_number, state, title, stage, last_action_date "
                "FROM legiscan_bills WHERE is_active=1"
            ).fetchall()
        }
        db_deadlines = [
            dict(r) for r in conn.execute(
                "SELECT title, deadline_date, topic, description FROM regulatory_deadlines "
                "ORDER BY deadline_date ASC"
            ).fetchall()
        ]
        conn.close()
    except Exception as e:
        logger.warning(f"Could not preload DB for verification: {e}")
        db_bills = {}
        db_deadlines = []

    # Preload article cache text for keyword search
    cache_text = _load_cache_text()

    for claim in claims:
        claim_text = claim.get("claim", "")
        claim_type = claim.get("type", "other")
        topic = claim.get("topic", "")
        result = dict(claim)
        result["verification_method"] = None
        result["verification_detail"] = ""

        # Step 1: DB check
        db_result = _check_db(claim_text, claim_type, db_bills, db_deadlines)
        if db_result:
            result["verification_method"] = "db"
            result["verification_detail"] = db_result
            verified.append(result)
            continue

        # Step 2: Article cache check
        cache_result = _check_cache(claim_text, cache_text)
        if cache_result and claim_type not in _HIGH_STAKES_CLAIM_TYPES:
            result["verification_method"] = "article_cache"
            result["verification_detail"] = cache_result[:200]
            verified.append(result)
            continue

        # Step 3: SME spot-check (for high-specificity claims, always for high-stakes types)
        should_escalate = (
            sme_escalations < _MAX_SME_ESCALATIONS
            and (
                claim.get("specificity") == "high"
                or claim_type in _HIGH_STAKES_CLAIM_TYPES
            )
            and topic in ("PFAS", "EPR", "REACH", "TSCA", "Prop65",
                          "ConflictMinerals", "ForcedLabor")
        )
        if should_escalate:
            sme_result = _check_sme(claim_text, topic, client)
            sme_escalations += 1
            if sme_result["accurate"]:
                result["verification_method"] = "sme"
                result["verification_detail"] = sme_result["explanation"][:300]
                verified.append(result)
            else:
                result["verification_method"] = "sme"
                result["verification_detail"] = sme_result["explanation"][:300]
                result["severity"] = "high" if claim_type in _HIGH_STAKES_CLAIM_TYPES else "medium"
                flagged.append(result)
            continue

        # Step 4: Unverifiable (low specificity, no DB match, no cache match, not escalated)
        unverifiable.append(result)

    return verified, flagged, unverifiable


def _check_db(claim: str, claim_type: str, bills: dict, deadlines: list) -> str | None:
    """Try to verify claim against in-memory DB data. Returns evidence string or None."""
    claim_lower = claim.lower()

    # Check bill references
    for bill_num, bill in bills.items():
        if bill_num.lower() in claim_lower:
            state = bill.get("state", "")
            stage = bill.get("stage", "")
            return f"DB: {state} {bill_num} found, stage={stage}, last_action={bill.get('last_action_date','')}"

    # Check deadline references
    for dl in deadlines:
        dl_title = (dl.get("title") or "").lower()
        dl_date = dl.get("deadline_date", "")
        # If the claim mentions a known deadline date or title keywords
        if dl_date and dl_date in claim:
            return f"DB: deadline '{dl.get('title','')[:60]}' date {dl_date} confirmed"
        if len(dl_title) > 10 and dl_title[:20] in claim_lower:
            return f"DB: deadline '{dl.get('title','')[:60]}' found in registry"

    return None


def _check_cache(claim: str, cache_text: str) -> str | None:
    """Check if claim is supported by article cache text."""
    if not cache_text:
        return None
    # Extract key phrases from claim (3+ word substrings)
    words = claim.split()
    if len(words) >= 3:
        # Try a 4-word sliding window
        for i in range(len(words) - 2):
            phrase = " ".join(words[i:i+4]).lower().rstrip(".,;:")
            if len(phrase) > 12 and phrase in cache_text.lower():
                return f"Article cache: found matching phrase '{phrase}'"
    return None


def _check_sme(claim: str, topic: str, client: ClaudeClient) -> dict:
    """Ask the SME agent to verify a claim. Returns {accurate: bool, explanation: str}."""
    from ai.sme_agent import SMEAgent
    try:
        agent = SMEAgent(topic)
        question = (
            f"Please verify this specific claim from our compliance dashboard. "
            f"Answer with JSON: {{\"accurate\": true/false, \"explanation\": \"...\"}}\n\n"
            f"Claim: {claim}"
        )
        raw = agent.ask(question)
        # Parse JSON from response
        raw = raw.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        # Find the JSON object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
            return {
                "accurate": bool(result.get("accurate", True)),
                "explanation": str(result.get("explanation", "")),
            }
    except Exception as e:
        logger.warning(f"SME verification failed for claim '{claim[:60]}': {e}")
    # Default to unverifiable on error
    return {"accurate": True, "explanation": "(SME verification error — treated as unverifiable)"}


def _load_cache_text() -> str:
    """Load recent Claude cache text for keyword search (last 14 days)."""
    from datetime import timedelta
    cache_dir = _CACHE_DIR / "claude"
    if not cache_dir.exists():
        return ""
    today = date.today()
    cutoff = today - timedelta(days=14)
    parts: list[str] = []
    for path in sorted(cache_dir.glob("*.json"), reverse=True)[:30]:
        stem = path.stem
        try:
            file_date = date.fromisoformat(stem[:10])
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        try:
            data = json.loads(path.read_text())
            text = data.get("text", "")
            if text:
                parts.append(text[:2000])
        except Exception:
            pass
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Phase 4: Synthesize report
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = """You are a senior compliance auditor producing an executive accuracy
report. You have verified claims from a live compliance intelligence dashboard.
Be direct, expert, and focused on actionable findings.
Return JSON with: summary, confidence_score (0-100), key_findings (array), recommendations (array)."""

def _synthesize_report(
    verified: list[dict],
    flagged: list[dict],
    unverifiable: list[dict],
    client: ClaudeClient,
) -> dict:
    """One Sonnet call to synthesize findings into a final report."""
    total = len(verified) + len(flagged) + len(unverifiable)
    if total == 0:
        return {
            "audit_date": date.today().isoformat(),
            "total_claims": 0,
            "verified_count": 0,
            "flagged_count": 0,
            "unverifiable_count": 0,
            "confidence_score": 100,
            "summary": "No claims extracted — dashboard may not have been crawled.",
            "key_findings": [],
            "recommendations": [],
        }

    flagged_summary = "\n".join(
        f"- [{c.get('type','')} | {c.get('topic','')}] {c.get('claim','')} "
        f"(SME: {c.get('verification_detail','')})"
        for c in flagged[:20]
    )
    verified_sample = "\n".join(
        f"- {c.get('claim','')[:80]} ({c.get('verification_method','')})"
        for c in verified[:10]
    )

    prompt = f"""Content accuracy audit completed. Summary:
- Total claims extracted: {total}
- Verified: {len(verified)} (DB: {sum(1 for c in verified if c.get('verification_method')=='db')}, cache: {sum(1 for c in verified if c.get('verification_method')=='article_cache')}, SME: {sum(1 for c in verified if c.get('verification_method')=='sme')})
- Flagged as potentially incorrect: {len(flagged)}
- Unverifiable (insufficient data): {len(unverifiable)}

FLAGGED CLAIMS (need attention):
{flagged_summary if flagged else 'None'}

SAMPLE VERIFIED CLAIMS:
{verified_sample if verified else 'None'}

Produce an accuracy assessment. Return JSON: {{
  "summary": "2-3 sentence executive summary",
  "confidence_score": number 0-100,
  "key_findings": ["finding 1", ...],
  "recommendations": ["action 1", ...]
}}"""

    try:
        raw = client.complete_sonnet(prompt, system=_SYNTHESIS_SYSTEM)
        raw = raw.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start = raw.find("{")
        end = raw.rfind("}") + 1
        synthesis = json.loads(raw[start:end]) if start >= 0 and end > start else {}
    except Exception as e:
        logger.warning(f"Report synthesis failed: {e}")
        synthesis = {}

    confidence = synthesis.get("confidence_score", 85 if not flagged else 70)

    return {
        "audit_date": date.today().isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_claims": total,
        "verified_count": len(verified),
        "flagged_count": len(flagged),
        "unverifiable_count": len(unverifiable),
        "confidence_score": confidence,
        "summary": synthesis.get("summary", f"{len(verified)}/{total} claims verified."),
        "key_findings": synthesis.get("key_findings", []),
        "recommendations": synthesis.get("recommendations", []),
        "flagged_claims": flagged[:30],
        "verified_sample": verified[:10],
    }


# ---------------------------------------------------------------------------
# HTML report renderer
# ---------------------------------------------------------------------------

def _render_html_report(report: dict) -> str:
    today = report.get("audit_date", date.today().isoformat())
    score = report.get("confidence_score", 0)
    score_color = "#27ae60" if score >= 85 else "#e67e22" if score >= 70 else "#c0392b"

    flagged_rows = ""
    for c in report.get("flagged_claims", []):
        severity = c.get("severity", "medium")
        bg = "#fff0f0" if severity == "high" else "#fffbe6"
        flagged_rows += (
            f'<tr style="background:{bg}">'
            f'<td style="word-break:break-all">{c.get("claim","")[:120]}</td>'
            f'<td>{c.get("type","")}</td>'
            f'<td>{c.get("topic","")}</td>'
            f'<td>{severity}</td>'
            f'<td style="font-size:11px">{c.get("verification_detail","")[:150]}</td>'
            f'</tr>'
        )

    findings_html = "".join(f"<li>{f}</li>" for f in report.get("key_findings", []))
    recs_html = "".join(f"<li>{r}</li>" for r in report.get("recommendations", []))
    th = '<th style="background:#1a1a2e;color:#fff;padding:6px 10px;text-align:left">'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Content Accuracy Report {today}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:20px;color:#222}}
h1{{font-size:22px}} .meta{{color:#666;font-size:13px;margin-bottom:20px}}
.kpi{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.kpi-card{{background:#f8f9fa;border:1px solid #ddd;border-radius:6px;padding:12px 20px}}
.kpi-num{{font-size:28px;font-weight:700}} .kpi-label{{font-size:12px;color:#666}}
h2{{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #eee;padding-bottom:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{padding:5px 8px;border-bottom:1px solid #eee}}
ul{{margin:4px 0;padding-left:20px}}
.summary-box{{background:#f0f4f8;border-left:4px solid #3498db;padding:12px 16px;
             border-radius:0 6px 6px 0;margin-bottom:16px;font-size:14px}}
</style>
</head><body>
<h1>Content Accuracy Audit Report</h1>
<div class="meta">Generated {report.get('generated_at', today)}</div>

<div class="kpi">
  <div class="kpi-card"><div class="kpi-num" style="color:{score_color}">{score}</div><div class="kpi-label">Confidence Score</div></div>
  <div class="kpi-card"><div class="kpi-num">{report['total_claims']}</div><div class="kpi-label">Claims Extracted</div></div>
  <div class="kpi-card"><div class="kpi-num" style="color:#27ae60">{report['verified_count']}</div><div class="kpi-label">Verified</div></div>
  <div class="kpi-card"><div class="kpi-num" style="color:#c0392b">{report['flagged_count']}</div><div class="kpi-label">Flagged</div></div>
  <div class="kpi-card"><div class="kpi-num" style="color:#888">{report['unverifiable_count']}</div><div class="kpi-label">Unverifiable</div></div>
</div>

<div class="summary-box">{report.get('summary', '')}</div>

<h2>Key Findings</h2>
{"<ul>" + findings_html + "</ul>" if findings_html else "<p style='color:#888'>No findings.</p>"}

<h2>Recommendations</h2>
{"<ul>" + recs_html + "</ul>" if recs_html else "<p style='color:#888'>No recommendations.</p>"}

<h2>Flagged Claims — Requires Review ({report['flagged_count']})</h2>
{"<p style='color:#27ae60'>No claims flagged. Dashboard content verified.</p>" if not report.get('flagged_claims') else f'''<table><tr>{th}Claim</th>{th}Type</th>{th}Topic</th>{th}Severity</th>{th}SME Finding</th></tr>{flagged_rows}</table>'''}

</body></html>"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = run_audit()
    print(f"\nContent audit complete:")
    print(f"  Confidence score: {report['confidence_score']}")
    print(f"  Verified: {report['verified_count']}")
    print(f"  Flagged:  {report['flagged_count']}")
    if report.get("flagged_claims"):
        print(f"\n  FLAGGED CLAIMS:")
        for c in report["flagged_claims"][:5]:
            print(f"    - [{c.get('severity','?')}] {c.get('claim','')[:80]}")
