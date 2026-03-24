"""Site link checker — pure Python BFS crawler, zero API cost.

Crawls the GitHub Pages site starting from the dashboard, checks every link
with HTTP HEAD requests, and saves a JSON + HTML report to data/site_audit/.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE_URL = "https://ryan-jenkinson.github.io/compliance-maps"
_START_URL = f"{_BASE_URL}/dashboard.html"
_AUDIT_DIR = Path(__file__).parent.parent / "data" / "site_audit"
_MAX_DEPTH = 3
_REQUEST_TIMEOUT = 15
_DELAY_BETWEEN_REQUESTS = 0.3  # seconds, be polite to GitHub Pages


def run_check(start_url: str = _START_URL) -> dict:
    """BFS crawl from start_url. Returns structured report dict.

    Records:
    - broken: 4xx/5xx responses
    - redirects: 3xx responses
    - timeouts: connection/read timeouts
    - ok: 2xx responses
    - external: links to other domains (HEAD checked but not crawled)
    """
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    base_parsed = urlparse(start_url)
    base_domain = f"{base_parsed.scheme}://{base_parsed.netloc}"
    base_path_prefix = base_parsed.path.rsplit("/", 1)[0]  # e.g. /compliance-maps

    visited_urls: set[str] = set()
    queue: deque[tuple[str, int, str]] = deque()  # (url, depth, found_on_page)
    queue.append((start_url, 0, "start"))

    results: list[dict] = []
    session = requests.Session()
    session.headers["User-Agent"] = "ComplianceMonitor-LinkChecker/1.0"

    def _check_url(url: str, depth: int, found_on: str) -> dict:
        """HEAD request a URL and return a result dict."""
        try:
            resp = session.head(url, timeout=_REQUEST_TIMEOUT, allow_redirects=False)
            status = resp.status_code
            if status in (405, 501):
                # Some servers don't support HEAD — fallback to GET with stream
                resp = session.get(url, timeout=_REQUEST_TIMEOUT,
                                   allow_redirects=False, stream=True)
                resp.close()
                status = resp.status_code

            category = "ok"
            if 200 <= status < 300:
                category = "ok"
            elif 300 <= status < 400:
                category = "redirect"
                location = resp.headers.get("Location", "")
                return {
                    "url": url, "status": status, "category": category,
                    "depth": depth, "found_on": found_on,
                    "redirect_to": location,
                }
            elif 400 <= status < 500:
                category = "broken"
            elif status >= 500:
                category = "server_error"

            return {"url": url, "status": status, "category": category,
                    "depth": depth, "found_on": found_on}

        except requests.exceptions.Timeout:
            return {"url": url, "status": None, "category": "timeout",
                    "depth": depth, "found_on": found_on}
        except requests.exceptions.ConnectionError as e:
            return {"url": url, "status": None, "category": "connection_error",
                    "depth": depth, "found_on": found_on, "error": str(e)[:120]}
        except Exception as e:
            return {"url": url, "status": None, "category": "error",
                    "depth": depth, "found_on": found_on, "error": str(e)[:120]}

    def _is_same_domain(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == base_parsed.netloc

    def _normalize(url: str, page_url: str) -> str | None:
        """Resolve relative URLs, strip fragments, return None for non-http."""
        try:
            absolute = urljoin(page_url, url)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                return None
            # Strip fragment
            return absolute.split("#")[0]
        except Exception:
            return None

    pages_crawled = 0

    while queue:
        url, depth, found_on = queue.popleft()
        if url in visited_urls:
            continue
        visited_urls.add(url)

        is_same_domain = _is_same_domain(url)
        result = _check_url(url, depth, found_on)

        # Mark external links
        if not is_same_domain:
            result["category"] = "external_" + result.get("category", "ok")

        results.append(result)
        time.sleep(_DELAY_BETWEEN_REQUESTS)

        # Only crawl internal HTML pages within depth limit
        if not is_same_domain or depth >= _MAX_DEPTH:
            continue
        if result.get("status") not in (200, None):
            continue
        if url.endswith((".pdf", ".xlsx", ".csv", ".ics", ".json", ".xml",
                          ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                          ".zip", ".gz", ".woff", ".woff2", ".ttf", ".css", ".js")):
            continue

        # Fetch the page and extract links
        try:
            resp = session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            pages_crawled += 1
            soup = BeautifulSoup(resp.text, "html.parser")

            for tag in soup.find_all(["a", "link", "script", "img", "iframe"]):
                href = (tag.get("href") or tag.get("src") or "").strip()
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                normalized = _normalize(href, url)
                if normalized and normalized not in visited_urls:
                    queue.append((normalized, depth + 1, url))

            time.sleep(_DELAY_BETWEEN_REQUESTS)
        except Exception as e:
            logger.warning(f"Failed to parse {url}: {e}")

    # Build summary
    broken = [r for r in results if r["category"] == "broken"]
    redirects = [r for r in results if r["category"] == "redirect"]
    timeouts = [r for r in results if r["category"] in ("timeout", "connection_error", "error")]
    server_errors = [r for r in results if r["category"] == "server_error"]
    ok = [r for r in results if r["category"] == "ok"]
    external_broken = [r for r in results if r["category"] == "external_broken"]

    issues_count = len(broken) + len(timeouts) + len(server_errors) + len(external_broken)
    critical_count = len(broken) + len(server_errors)

    summary = {
        "audit_date": date.today().isoformat(),
        "start_url": start_url,
        "pages_crawled": pages_crawled,
        "total_urls_checked": len(results),
        "ok_count": len(ok),
        "broken_count": len(broken),
        "redirect_count": len(redirects),
        "timeout_count": len(timeouts),
        "server_error_count": len(server_errors),
        "external_broken_count": len(external_broken),
        "issues_count": issues_count,
        "critical_count": critical_count,
        "broken_urls": [r["url"] for r in broken],
        "redirect_urls": [(r["url"], r.get("redirect_to", "")) for r in redirects],
        "timeout_urls": [r["url"] for r in timeouts],
        "external_broken_urls": [r["url"] for r in external_broken],
    }

    # Save JSON report
    today_str = date.today().isoformat()
    json_path = _AUDIT_DIR / f"link_report_{today_str}.json"
    json_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    logger.info(f"Link report saved: {json_path}")

    # Save HTML report
    html_path = _AUDIT_DIR / f"link_report_{today_str}.html"
    html_path.write_text(_render_html_report(summary, results))
    logger.info(f"Link HTML report saved: {html_path}")

    # Persist to DB
    try:
        from subscribers.db import get_connection
        conn = get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO site_audit_reports
               (audit_date, audit_type, summary_json, issues_count, critical_count, report_path)
               VALUES (?, 'links', ?, ?, ?, ?)""",
            (today_str, json.dumps(summary), issues_count, critical_count, str(html_path)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to save link audit to DB: {e}")

    return summary


def _render_html_report(summary: dict, results: list[dict]) -> str:
    today = summary["audit_date"]
    broken = [r for r in results if r["category"] in ("broken", "server_error")]
    redirects = [r for r in results if r["category"] == "redirect"]
    timeouts = [r for r in results if r["category"] in ("timeout", "connection_error", "error")]
    ext_broken = [r for r in results if r["category"] == "external_broken"]

    def _row(r: dict, bg: str = "#fff") -> str:
        status = r.get("status", "—") or "—"
        extra = r.get("redirect_to") or r.get("error") or ""
        return (f'<tr style="background:{bg}">'
                f'<td style="word-break:break-all;max-width:400px">'
                f'<a href="{r["url"]}" target="_blank">{r["url"]}</a></td>'
                f'<td style="text-align:center">{status}</td>'
                f'<td>{r["category"]}</td>'
                f'<td style="font-size:11px;color:#555;word-break:break-all">{r.get("found_on","")}</td>'
                f'<td style="font-size:11px;color:#888">{extra[:100]}</td>'
                f'</tr>')

    rows_broken = "\n".join(_row(r, "#fff0f0") for r in broken)
    rows_redirect = "\n".join(_row(r, "#fffbe6") for r in redirects)
    rows_timeout = "\n".join(_row(r, "#f5f5f5") for r in timeouts)
    rows_ext = "\n".join(_row(r, "#fff0f0") for r in ext_broken)

    th = '<th style="background:#1a1a2e;color:#fff;padding:6px 10px;text-align:left">'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Link Report {today}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:20px;color:#222}}
h1{{font-size:22px;margin-bottom:4px}}
.meta{{color:#666;font-size:13px;margin-bottom:20px}}
.kpi{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.kpi-card{{background:#f8f9fa;border:1px solid #ddd;border-radius:6px;padding:12px 20px;min-width:120px}}
.kpi-num{{font-size:28px;font-weight:700}}
.kpi-num.red{{color:#c0392b}} .kpi-num.green{{color:#27ae60}} .kpi-num.orange{{color:#e67e22}}
.kpi-label{{font-size:12px;color:#666;margin-top:2px}}
h2{{font-size:16px;margin:24px 0 8px;border-bottom:2px solid #eee;padding-bottom:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{padding:5px 8px;border-bottom:1px solid #eee}}
a{{color:#0066cc}}
</style>
</head><body>
<h1>Site Link Check Report</h1>
<div class="meta">Generated {today} &bull; Start: <a href="{summary['start_url']}">{summary['start_url']}</a>
&bull; Pages crawled: {summary['pages_crawled']} &bull; Total URLs: {summary['total_urls_checked']}</div>

<div class="kpi">
  <div class="kpi-card"><div class="kpi-num {'red' if summary['broken_count'] else 'green'}">{summary['broken_count']}</div><div class="kpi-label">Broken (4xx)</div></div>
  <div class="kpi-card"><div class="kpi-num {'red' if summary['server_error_count'] else 'green'}">{summary['server_error_count']}</div><div class="kpi-label">Server Errors (5xx)</div></div>
  <div class="kpi-card"><div class="kpi-num {'orange' if summary['redirect_count'] else 'green'}">{summary['redirect_count']}</div><div class="kpi-label">Redirects (3xx)</div></div>
  <div class="kpi-card"><div class="kpi-num {'orange' if summary['timeout_count'] else 'green'}">{summary['timeout_count']}</div><div class="kpi-label">Timeouts/Errors</div></div>
  <div class="kpi-card"><div class="kpi-num">{summary['ok_count']}</div><div class="kpi-label">OK (2xx)</div></div>
  <div class="kpi-card"><div class="kpi-num">{summary['external_broken_count']}</div><div class="kpi-label">External Broken</div></div>
</div>

<h2>Broken Links ({len(broken)})</h2>
{"<p style='color:#27ae60'>None found.</p>" if not broken else f'''<table><tr>{th}URL</th>{th}Status</th>{th}Category</th>{th}Found On</th>{th}Details</th></tr>{rows_broken}</table>'''}

<h2>Redirects ({len(redirects)})</h2>
{"<p style='color:#888'>None.</p>" if not redirects else f'''<table><tr>{th}URL</th>{th}Status</th>{th}Category</th>{th}Found On</th>{th}Redirect To</th></tr>{rows_redirect}</table>'''}

<h2>Timeouts / Connection Errors ({len(timeouts)})</h2>
{"<p style='color:#888'>None.</p>" if not timeouts else f'''<table><tr>{th}URL</th>{th}Status</th>{th}Category</th>{th}Found On</th>{th}Error</th></tr>{rows_timeout}</table>'''}

<h2>External Broken Links ({len(ext_broken)})</h2>
{"<p style='color:#888'>None.</p>" if not ext_broken else f'''<table><tr>{th}URL</th>{th}Status</th>{th}Category</th>{th}Found On</th>{th}Details</th></tr>{rows_ext}</table>'''}

</body></html>"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run_check()
    print(f"\nLink check complete:")
    print(f"  Pages crawled:  {summary['pages_crawled']}")
    print(f"  URLs checked:   {summary['total_urls_checked']}")
    print(f"  OK:             {summary['ok_count']}")
    print(f"  Broken:         {summary['broken_count']}")
    print(f"  Redirects:      {summary['redirect_count']}")
    print(f"  Timeouts:       {summary['timeout_count']}")
    print(f"  Issues total:   {summary['issues_count']}")
    if summary['broken_urls']:
        print(f"\n  BROKEN URLs:")
        for u in summary['broken_urls']:
            print(f"    - {u}")
