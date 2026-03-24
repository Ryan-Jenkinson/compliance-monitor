"""Site Visual Auditor — Playwright screenshots + Haiku vision analysis.

Takes desktop (1440px) and mobile (375px) screenshots of each site page, then
sends each to Haiku vision to identify layout issues, text readability problems,
and design inconsistencies.

Cost: ~$0.04/run (20 pages × 2 screenshots × ~$0.001 Haiku vision call).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

from ai.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_AUDIT_DIR = Path(__file__).parent.parent / "data" / "site_audit"
_SCREENSHOT_DIR = _AUDIT_DIR / "screenshots"
_BASE_URL = "https://ryan-jenkinson.github.io/compliance-maps"
_START_URL = f"{_BASE_URL}/dashboard.html"

_DESKTOP_WIDTH = 1440
_MOBILE_WIDTH = 375

_VISION_SYSTEM = """You are a professional UI/UX design reviewer and accessibility auditor.
Analyze dashboard screenshots with an expert eye for:
1. Text readability — contrast, font size, overflow, truncation
2. Layout issues — broken grids, overflow, empty sections, misaligned elements
3. Missing content — broken images, empty charts, placeholder text
4. Professional consistency — visual coherence, color usage, spacing
5. Mobile usability (for mobile screenshots) — tap target size, zoom needed

Be concise and specific. Only flag real issues — not stylistic preferences.
Return JSON: {"issues": [{"severity": "high/medium/low", "category": "readability/layout/content/consistency", "description": "..."}], "overall": "pass/warning/fail", "notes": "one sentence"}"""

_VISION_PROMPT = """Analyze this {viewport} ({width}px) screenshot of a compliance intelligence dashboard.
Identify any issues with text readability, layout, broken elements, or design consistency.
Return JSON with issues array."""


def run_audit(
    pages: list[str] | None = None,
    start_url: str = _START_URL,
) -> dict:
    """Screenshot each page at desktop and mobile, analyze with Haiku vision.

    Args:
        pages: explicit list of URLs to audit (if None, discovers via link checker)
        start_url: fallback start URL for discovery
    """
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Check Playwright is available
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return {"error": "playwright_not_installed", "pages_audited": 0}

    # Discover pages if not provided
    if pages is None:
        pages = _discover_pages(start_url)
    logger.info(f"Visual audit: {len(pages)} pages to screenshot")

    client = ClaudeClient()
    today_str = date.today().isoformat()
    page_results: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for url in pages:
            logger.info(f"  Screenshotting: {url}")
            page_result = {"url": url, "desktop": None, "mobile": None}

            for viewport_name, width, height in [
                ("desktop", _DESKTOP_WIDTH, 900),
                ("mobile", _MOBILE_WIDTH, 812),
            ]:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                pw_page = context.new_page()
                try:
                    pw_page.goto(url, wait_until="networkidle", timeout=20000)
                    pw_page.wait_for_timeout(1000)  # let JS render
                    screenshot_path = (
                        _SCREENSHOT_DIR
                        / f"{today_str}_{_url_slug(url)}_{viewport_name}.png"
                    )
                    pw_page.screenshot(path=str(screenshot_path), full_page=False)

                    # Send to Haiku vision
                    image_data = screenshot_path.read_bytes()
                    prompt = _VISION_PROMPT.format(
                        viewport=viewport_name, width=width
                    )
                    raw = client.complete_haiku_vision(
                        prompt=prompt,
                        image_data=image_data,
                        system=_VISION_SYSTEM,
                    )
                    analysis = _parse_vision_response(raw)
                    analysis["screenshot"] = str(screenshot_path)
                    page_result[viewport_name] = analysis

                except Exception as e:
                    logger.warning(f"Screenshot/vision failed for {url} ({viewport_name}): {e}")
                    page_result[viewport_name] = {"error": str(e)[:120]}
                finally:
                    pw_page.close()
                    context.close()

            page_results.append(page_result)
        browser.close()

    # Build summary
    all_issues: list[dict] = []
    for pr in page_results:
        for viewport in ("desktop", "mobile"):
            vp = pr.get(viewport) or {}
            if "issues" in vp:
                for issue in vp["issues"]:
                    all_issues.append({
                        "url": pr["url"],
                        "viewport": viewport,
                        **issue,
                    })

    high = [i for i in all_issues if i.get("severity") == "high"]
    medium = [i for i in all_issues if i.get("severity") == "medium"]
    low = [i for i in all_issues if i.get("severity") == "low"]

    summary = {
        "audit_date": today_str,
        "pages_audited": len(page_results),
        "total_issues": len(all_issues),
        "high_count": len(high),
        "medium_count": len(medium),
        "low_count": len(low),
        "overall": "fail" if high else "warning" if medium else "pass",
        "all_issues": all_issues[:50],
    }

    # Save reports
    json_path = _AUDIT_DIR / f"visual_report_{today_str}.json"
    json_path.write_text(json.dumps({"summary": summary, "pages": page_results}, indent=2))

    html_path = _AUDIT_DIR / f"visual_report_{today_str}.html"
    html_path.write_text(_render_html_report(summary, page_results))

    # Persist to DB
    try:
        from subscribers.db import get_connection
        conn = get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO site_audit_reports
               (audit_date, audit_type, summary_json, issues_count, critical_count, report_path)
               VALUES (?, 'visual', ?, ?, ?, ?)""",
            (today_str, json.dumps(summary), len(all_issues), len(high), str(html_path)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to save visual audit to DB: {e}")

    logger.info(f"Visual audit saved: {html_path} — {len(all_issues)} issues found")
    return summary


def _discover_pages(start_url: str) -> list[str]:
    """Discover pages via link checker (reuse existing crawl logic)."""
    from ai.site_link_checker import _AUDIT_DIR as _LC_AUDIT_DIR
    from datetime import date as _date
    import glob

    # Try today's link report first
    today_str = _date.today().isoformat()
    pattern = str(_LC_AUDIT_DIR / f"link_report_{today_str}.json")
    files = glob.glob(pattern)
    if not files:
        # Fall back to any recent link report
        files = sorted(glob.glob(str(_LC_AUDIT_DIR / "link_report_*.json")), reverse=True)

    if files:
        try:
            data = json.loads(Path(files[0]).read_text())
            results = data.get("results", [])
            # Only pages on the same domain that were OK
            pages = [
                r["url"] for r in results
                if r.get("category") == "ok"
                and not r["url"].endswith((".pdf", ".xlsx", ".ics", ".csv", ".json"))
                and "ryan-jenkinson.github.io" in r["url"]
            ]
            if pages:
                return pages[:20]  # cap
        except Exception:
            pass

    # Fallback: just audit key pages
    base = "https://ryan-jenkinson.github.io/compliance-maps"
    return [
        f"{base}/dashboard.html",
        f"{base}/exec-summary.html",
        f"{base}/deadline-calendar.html",
        f"{base}/archive.html",
    ]


def _url_slug(url: str) -> str:
    """Convert URL to filesystem-safe slug."""
    import re
    slug = url.replace("https://", "").replace("http://", "")
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)
    return slug[:60]


def _parse_vision_response(raw: str) -> dict:
    """Parse Haiku vision JSON response, gracefully handling non-JSON."""
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception:
        pass
    # Couldn't parse — return raw text as a single note
    return {"issues": [], "overall": "pass", "notes": raw[:200]}


def _render_html_report(summary: dict, page_results: list[dict]) -> str:
    today = summary["audit_date"]
    overall = summary.get("overall", "pass")
    overall_color = "#c0392b" if overall == "fail" else "#e67e22" if overall == "warning" else "#27ae60"

    issue_rows = ""
    for issue in summary.get("all_issues", []):
        sev = issue.get("severity", "low")
        bg = "#fff0f0" if sev == "high" else "#fffbe6" if sev == "medium" else "#fff"
        issue_rows += (
            f'<tr style="background:{bg}">'
            f'<td style="word-break:break-all;max-width:250px">'
            f'<a href="{issue["url"]}" target="_blank">{issue["url"].split("/")[-1] or "/"}</a></td>'
            f'<td>{issue.get("viewport","")}</td>'
            f'<td>{sev}</td>'
            f'<td>{issue.get("category","")}</td>'
            f'<td>{issue.get("description","")[:200]}</td>'
            f'</tr>'
        )

    th = '<th style="background:#1a1a2e;color:#fff;padding:6px 10px;text-align:left">'

    screenshot_grid = ""
    for pr in page_results:
        page_name = pr["url"].split("/")[-1] or "index"
        for vp in ("desktop", "mobile"):
            vp_data = pr.get(vp) or {}
            ss = vp_data.get("screenshot", "")
            if ss and Path(ss).exists():
                rel = Path(ss).name
                screenshot_grid += (
                    f'<div style="margin:8px;display:inline-block;vertical-align:top">'
                    f'<div style="font-size:11px;color:#666;margin-bottom:4px">'
                    f'{page_name} ({vp})</div>'
                    f'<img src="screenshots/{rel}" style="width:200px;border:1px solid #ddd" '
                    f'onerror="this.style.display=\'none\'">'
                    f'</div>'
                )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Visual Audit {today}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:20px;color:#222}}
h1{{font-size:22px}} .meta{{color:#666;font-size:13px;margin-bottom:20px}}
.kpi{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.kpi-card{{background:#f8f9fa;border:1px solid #ddd;border-radius:6px;padding:12px 20px}}
.kpi-num{{font-size:28px;font-weight:700}} .kpi-label{{font-size:12px;color:#666}}
h2{{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #eee;padding-bottom:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{padding:5px 8px;border-bottom:1px solid #eee}}
.badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:700}}
</style>
</head><body>
<h1>Site Visual Audit Report</h1>
<div class="meta">Generated {today} &bull; {summary['pages_audited']} pages audited</div>

<div class="kpi">
  <div class="kpi-card">
    <div class="kpi-num" style="color:{overall_color}">{overall.upper()}</div>
    <div class="kpi-label">Overall Status</div>
  </div>
  <div class="kpi-card"><div class="kpi-num" style="color:#c0392b">{summary['high_count']}</div><div class="kpi-label">High Issues</div></div>
  <div class="kpi-card"><div class="kpi-num" style="color:#e67e22">{summary['medium_count']}</div><div class="kpi-label">Medium Issues</div></div>
  <div class="kpi-card"><div class="kpi-num" style="color:#888">{summary['low_count']}</div><div class="kpi-label">Low Issues</div></div>
</div>

<h2>All Issues ({summary['total_issues']})</h2>
{"<p style='color:#27ae60'>No issues found.</p>" if not summary.get('all_issues') else f'''<table><tr>{th}Page</th>{th}Viewport</th>{th}Severity</th>{th}Category</th>{th}Description</th></tr>{issue_rows}</table>'''}

<h2>Screenshot Gallery</h2>
<div style="margin-top:8px">{screenshot_grid if screenshot_grid else '<p style="color:#888">No screenshots available.</p>'}</div>

</body></html>"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run_audit()
    print(f"\nVisual audit complete:")
    print(f"  Pages audited: {summary.get('pages_audited', 0)}")
    print(f"  Total issues:  {summary.get('total_issues', 0)}")
    print(f"  High:          {summary.get('high_count', 0)}")
    print(f"  Overall:       {summary.get('overall', 'unknown')}")
