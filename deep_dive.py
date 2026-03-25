#!/usr/bin/env python3
"""
Ad-hoc topic deep-dive generator.

Usage:
    python deep_dive.py "TCE"
    python deep_dive.py "PFOA Minnesota" --no-browser
    python run.py --deep-dive "TCE"
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from subscribers.db import get_connection
from ai.claude_client import ClaudeClient
from ai.prompts import SYSTEM_COMPLIANCE_EXPERT

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent / "dashboard" / "templates" / "deep_dive.html"
_OUTPUT_DIR = Path(__file__).parent / "data" / "deep_dives"


def get_monthly_trend(query: str, months: int = 6) -> list[dict]:
    """Return monthly article counts matching query over the last `months` months."""
    from datetime import date, timedelta
    conn = get_connection()
    like = f"%{query}%"
    today = date.today()
    result = []
    for i in range(months - 1, -1, -1):
        # First day of each month going back
        month_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1) if i == 0 else today
        # Simpler: just use SQLite date arithmetic
        start = f"date('now', 'start of month', '-{i} months')"
        end = f"date('now', 'start of month', '-{i-1} months')" if i > 0 else "date('now', '+1 day')"
        n = conn.execute(
            f"""SELECT COUNT(*) FROM articles
                WHERE (title LIKE ? OR snippet LIKE ?)
                  AND date(COALESCE(pub_date, first_seen)) >= {start}
                  AND date(COALESCE(pub_date, first_seen)) < {end}""",
            (like, like),
        ).fetchone()[0]
        label = conn.execute(f"SELECT strftime('%b %Y', {start})").fetchone()[0]
        result.append({"label": label, "count": n})
    conn.close()
    return result


def search_content(query: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Search articles, deadlines, and bills for the given query."""
    like = f"%{query}%"
    conn = get_connection()

    rows = conn.execute(
        """SELECT id, topic, title, url, source, pub_date, snippet, first_seen,
                  is_new, relevance, relevance_reason
           FROM articles
           WHERE title LIKE ? OR snippet LIKE ?
           ORDER BY COALESCE(pub_date, first_seen) DESC
           LIMIT 100""",
        (like, like),
    ).fetchall()
    articles = [dict(r) for r in rows]

    rows = conn.execute(
        """SELECT id, topic, title, deadline_date, description, jurisdiction,
                  source_url, urgency
           FROM regulatory_deadlines
           WHERE title LIKE ? OR description LIKE ?
           ORDER BY deadline_date ASC""",
        (like, like),
    ).fetchall()
    deadlines = [dict(r) for r in rows]

    # legiscan_bills may not exist in all DB versions
    try:
        rows = conn.execute(
            """SELECT id, topic, state, bill_number, title, status, stage,
                      is_active, last_action_date
               FROM legiscan_bills
               WHERE title LIKE ? OR bill_number LIKE ?
               ORDER BY last_action_date DESC""",
            (like, like),
        ).fetchall()
        bills = [dict(r) for r in rows]
    except Exception:
        bills = []

    conn.close()
    return articles, deadlines, bills


def _build_synthesis_prompt(
    query: str,
    articles: list[dict],
    deadlines: list[dict],
    bills: list[dict],
) -> str:
    lines = [f'The compliance team searched for: "{query}"\n']

    if articles:
        lines.append(f"ARTICLES ({len(articles)} found):")
        for a in articles[:20]:  # cap to keep tokens low
            lines.append(f"  - [{a.get('topic','')}] {a.get('title','')} ({a.get('pub_date','')[:10]})")
            if a.get("snippet"):
                lines.append(f"    {a['snippet'][:200]}")
        lines.append("")

    if deadlines:
        lines.append(f"DEADLINES ({len(deadlines)} found):")
        for d in deadlines[:10]:
            lines.append(f"  - {d.get('deadline_date','')[:10]} [{d.get('urgency','')}] {d.get('title','')} ({d.get('jurisdiction','')})")
        lines.append("")

    if bills:
        lines.append(f"LEGISLATION ({len(bills)} found):")
        for b in bills[:10]:
            lines.append(f"  - {b.get('state','')} {b.get('bill_number','')} ({b.get('stage','')}) {b.get('title','')}")
        lines.append("")

    lines.append(
        "Based on the above, provide a JSON object with exactly these keys:\n"
        '  "overview": 2-3 sentence summary of what is happening around this topic in the regulatory landscape.\n'
        '  "company_impact": 2-4 sentences on direct and indirect impacts for a US fluoropolymer manufacturer with PFAS coating products and supply chain exposure.\n'
        '  "key_risks": 2-4 sentences identifying the top risks to watch.\n'
        '  "next_steps": 2-4 sentences of concrete, actionable next steps for the compliance team.\n\n'
        "Return ONLY valid JSON. No markdown, no preamble."
    )
    return "\n".join(lines)


def generate_synthesis(
    query: str,
    articles: list[dict],
    deadlines: list[dict],
    bills: list[dict],
) -> dict:
    """Run a Haiku call to synthesize findings. Returns dict with overview/impact/risks/steps."""
    if not articles and not deadlines and not bills:
        return {
            "overview": f'No content found matching "{query}" in the compliance database.',
            "company_impact": "",
            "key_risks": "",
            "next_steps": "Run the full pipeline to populate the article database, then retry.",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "cached": False,
        }

    client = ClaudeClient()
    prompt = _build_synthesis_prompt(query, articles, deadlines, bills)

    # Use a cache key so same-query same-day calls are free
    cache_key = f"deepdive_{query.lower().replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}"

    try:
        raw = client.complete_haiku(
            prompt=prompt,
            system=SYSTEM_COMPLIANCE_EXPERT,
            cache_key=cache_key,
        )
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(text)
        data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["cached"] = False
        return data
    except Exception as e:
        logger.warning(f"Synthesis generation failed: {e}")
        return {
            "overview": f'Found {len(articles)} articles, {len(deadlines)} deadlines, and {len(bills)} bills matching "{query}".',
            "company_impact": "AI synthesis unavailable — review the articles above directly.",
            "key_risks": "",
            "next_steps": "",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "cached": False,
        }


def render_deep_dive(
    query: str,
    articles: list[dict],
    deadlines: list[dict],
    bills: list[dict],
    synthesis: dict,
    monthly_trend: list[dict] | None = None,
    dashboard_url: str = "dashboard.html",
    server_mode: bool = False,
) -> str:
    """Render the deep_dive.html template and return HTML string."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("deep_dive.html")
    return template.render(
        query=query,
        articles=articles,
        deadlines=deadlines,
        bills=bills,
        synthesis=synthesis,
        monthly_trend=monthly_trend or [],
        dashboard_url=dashboard_url,
        generated_date=datetime.now().strftime("%B %d, %Y"),
        server_mode=server_mode,
    )


def run_deep_dive(
    query: str,
    open_browser: bool = True,
    push_to_pages: bool = False,
    server_mode: bool = False,
    dashboard_url: str = "dashboard.html",
) -> Path:
    """
    Full deep-dive pipeline: search DB → AI synthesis → render HTML → save → open.
    Returns the path to the generated HTML file.
    """
    logger.info(f"Generating deep-dive for: {query!r}")

    articles, deadlines, bills = search_content(query)
    logger.info(f"Found {len(articles)} articles, {len(deadlines)} deadlines, {len(bills)} bills")

    monthly_trend = get_monthly_trend(query)
    synthesis = generate_synthesis(query, articles, deadlines, bills)

    html = render_deep_dive(
        query=query,
        articles=articles,
        deadlines=deadlines,
        bills=bills,
        synthesis=synthesis,
        monthly_trend=monthly_trend,
        dashboard_url=dashboard_url,
        server_mode=server_mode,
    )

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = query.lower().replace(" ", "_").replace("/", "-")[:40]
    out_path = _OUTPUT_DIR / f"deep_dive_{slug}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info(f"Saved: {out_path}")

    if push_to_pages:
        _push_to_pages(slug, html)

    if open_browser:
        webbrowser.open(f"file://{out_path.resolve()}")

    return out_path


def _push_to_pages(slug: str, html: str) -> None:
    """Push deep-dive page to GitHub Pages repo."""
    import shutil
    import subprocess

    pages_dir = Path("/tmp/compliance-maps")
    if not pages_dir.exists():
        logger.warning("GitHub Pages repo not found at /tmp/compliance-maps — skipping push")
        return

    deep_dir = pages_dir / "deep-dives"
    deep_dir.mkdir(exist_ok=True)
    dest = deep_dir / f"{slug}.html"
    dest.write_text(html, encoding="utf-8")

    fname = f"deep-dives/{slug}.html"
    cmds = [
        ["git", "-C", str(pages_dir), "add", fname],
        ["git", "-C", str(pages_dir), "commit", "-m", f"Add deep-dive: {slug}"],
        ["git", "-C", str(pages_dir), "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Git command failed: {result.stderr.strip()}")
            break


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Generate a topic deep-dive page")
    parser.add_argument("query", help="Search term (e.g. 'TCE', 'PFOA Minnesota')")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--push", action="store_true", help="Push to GitHub Pages")
    args = parser.parse_args()

    path = run_deep_dive(
        query=args.query,
        open_browser=not args.no_browser,
        push_to_pages=args.push,
    )
    print(f"Generated: {path}")
