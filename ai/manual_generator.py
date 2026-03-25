"""Dashboard User Manual Generator — screenshots every UI state, describes with vision, synthesizes into a manual."""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Capture Plan ─────────────────────────────────────────────────────────────
# Fields:
#   id             — unique slug / filename stem
#   label          — human-readable name
#   chapter        — chapter title (None = continues previous chapter)
#   chapter_intro  — 1-sentence intro shown at the start of a new chapter
#   action         — "viewport" | "full_page" | "selector" | "click_then_selector"
#   url            — override URL for this target (defaults to dashboard source_url)
#   selector       — CSS selector for element screenshot or click_then_selector result
#   click          — CSS selector to click before capturing
#   scroll_to      — CSS selector to scroll into view before capture
#   pre_js         — JS to evaluate before capture (e.g. expand a collapsed panel)
#   viewport       — (width, height) override; default (1440, 900)
#   max_height     — clip element screenshot to this many pixels tall
#   wait_ms        — extra wait after click before capture (default 600)
#   compare_with   — id of another capture to show side-by-side in the visual guide
#   optional       — True = skip gracefully if selector/click not found
#   desc_hint      — extra context for the Haiku vision description prompt

_MAPS = "file:///tmp/compliance-maps"

CAPTURE_PLAN: list[dict] = [

    # ── Chapter 1: The Dashboard ───────────────────────────────────────────────
    {
        "id": "c1-hero",
        "label": "Compliance Intelligence Dashboard",
        "chapter": "1. The Dashboard at a Glance",
        "chapter_intro": "A single-page intelligence hub that automatically aggregates, filters, and summarizes regulatory activity across seven compliance frameworks — refreshed every day.",
        "action": "viewport",
        "viewport": (1440, 900),
        "desc_hint": "This is the full compliance dashboard landing view at 1440px wide. Describe every visible section from top to bottom: the topic navigation cards, executive briefing, topic sections, deadlines panel, timeline, and any sidebars.",
    },
    {
        "id": "c1-mobile",
        "label": "Mobile Layout",
        "chapter": None,
        "action": "viewport",
        "viewport": (390, 844),
        "compare_with": "c1-hero",
        "desc_hint": "The dashboard on a 390px mobile screen. Describe how the layout collapses and what stays visible.",
    },

    # ── Chapter 2: Navigation ─────────────────────────────────────────────────
    {
        "id": "c2-nav-cards",
        "label": "Topic Navigation Cards",
        "chapter": "2. Navigation & Customization",
        "chapter_intro": "Jump instantly to any of the seven regulatory topic areas, or customize which panels are visible using the dashboard drawer.",
        "action": "selector",
        "selector": ".cmd-strip",
        "layout": "inline",
        "desc_hint": "The topic navigation card strip at the top of the dashboard. Cards for PFAS, EPR, REACH, TSCA, Prop65, Conflict Minerals, Forced Labor. Red badges show new article counts. Clicking scrolls to that topic section.",
    },
    {
        "id": "c2-drawer",
        "label": "Customize Dashboard Drawer",
        "chapter": None,
        "action": "click_then_selector",
        "click": ".customize-btn",
        "selector": "#customize-drawer",
        "wait_ms": 400,
        "optional": True,
        "layout": "inline",
        "desc_hint": "The widget customization drawer, opened by clicking the gear/settings button. Shows a list of panels that can be toggled on or off. Changes persist via localStorage.",
    },

    # ── Chapter 3: Executive Briefing ─────────────────────────────────────────
    {
        "id": "c3-exec",
        "label": "AI Executive Briefing",
        "chapter": "3. Executive Briefing",
        "chapter_intro": "Every pipeline run generates a fresh AI-authored summary of the week's most significant regulatory developments — ready to share in a leadership meeting.",
        "action": "selector",
        "selector": "#exec-panel",
        "desc_hint": "The Executive Briefing panel. An AI-generated summary covering all seven regulatory topics. Shows key developments, company-specific implications, and strategic notes. Updated every run.",
    },

    # ── Chapter 4: Topic Sections ─────────────────────────────────────────────
    {
        "id": "c4-pfas",
        "label": "PFAS — Regulatory Updates",
        "chapter": "4. Topic Intelligence Sections",
        "chapter_intro": "Each topic section surfaces curated regulatory articles with per-article AI company-impact analysis — filtered from hundreds of sources down to what matters for this company.",
        "action": "selector",
        "selector": "#section-pfas",
        "scroll_to": "#section-pfas",
        "max_height": 750,
        "desc_hint": "The PFAS topic section showing recent regulatory articles. Each article has an impact label (DIRECT / SUPPLY CHAIN / MONITORING). Green/amber/red color coding shows urgency. Source links go to the original agency publications.",
    },
    # ── Chapter 5: Compliance Deadlines ───────────────────────────────────────
    {
        "id": "c5-collapsed",
        "label": "Compliance Dates — Collapsed",
        "chapter": "5. Upcoming Compliance Dates & Deadlines",
        "chapter_intro": "A merged list of regulatory deadlines and key milestones, sorted by urgency and date — with AI-generated briefings for each deadline available on click.",
        "action": "selector",
        "selector": "#section-deadlines",
        "scroll_to": "#section-deadlines",
        "desc_hint": "The Upcoming Compliance Dates panel in its default collapsed state, showing 10 items. Red=HIGH urgency, amber=MEDIUM, green=LOW. 'New' and 'Updated' badges flag recently added or changed deadlines.",
    },
    {
        "id": "c5-expanded",
        "label": "Compliance Dates — Expanded",
        "chapter": None,
        "action": "selector",
        "selector": "#section-deadlines",
        "scroll_to": "#section-deadlines",
        "pre_js": "document.getElementById('section-deadlines').classList.remove('deadlines-collapsed');",
        "max_height": 800,
        "compare_with": "c5-collapsed",
        "desc_hint": "The same panel after clicking to expand — showing all compliance dates. The expand icon in the corner opens a full-screen modal with the complete list.",
    },
    {
        "id": "c5-modal",
        "label": "Deadline AI Analysis Modal",
        "chapter": None,
        "action": "click_then_selector",
        "scroll_to": "#section-deadlines",
        "pre_js": "document.getElementById('section-deadlines').classList.remove('deadlines-collapsed');",
        "click": ".dl-item-clickable",
        "selector": ".dd-modal",
        "wait_ms": 1000,
        "optional": True,
        "desc_hint": "The deadline detail modal with AI-generated analysis. Shows: what is required, who must comply, what the company must do, penalties, direct + supply chain impact severity, a 90/60/30/0 day preparation timeline, and recommended actions. Calendar export button at the bottom.",
    },
    {
        "id": "c5-timeline",
        "label": "Deadline Timeline — Swimlane View",
        "chapter": None,
        "action": "selector",
        "selector": ".tl-panel",
        "scroll_to": ".tl-panel",
        "layout": "inline",
        "desc_hint": "The deadline timeline swimlane widget. One row per regulatory topic, color-coded by topic. Dots represent individual deadlines — red=HIGH urgency, amber=MEDIUM, topic color=LOW. Pulsing ring indicates a newly tracked deadline. Hover any dot for details.",
    },

    # ── Chapter 6: Legislative Activity ───────────────────────────────────────
    {
        "id": "c6-bill-modal",
        "label": "Bill AI Analysis Modal",
        "chapter": "6. Legislative Activity",
        "chapter_intro": "729 tracked bills across 51 jurisdictions, filtered to what matters. Click any bill row for an AI analysis covering company impact, passage probability, and recommended next steps.",
        "action": "click_then_selector",
        "scroll_to": "#section-leg-activity",
        "click": ".la-item",
        "selector": ".bd-modal",
        "wait_ms": 800,
        "optional": True,
        "desc_hint": "The bill detail modal with AI analysis. Shows bill summary, what it requires, who must comply, company impact assessment, estimated passage probability, and recommended preparation steps.",
    },
    {
        "id": "c6-expand",
        "label": "Full-Screen Expand Mode",
        "chapter": None,
        "action": "click_then_selector",
        "click": "#section-leg-activity .expand-btn",
        "selector": "#expand-modal-overlay",
        "wait_ms": 500,
        "max_height": 820,
        "desc_hint": "The full-screen expand modal, opened by clicking the four-corner expand icon on any panel. Shows all items without the 10-item limit. Available on every major panel. Press Escape or click outside to close.",
    },

    # ── Chapter 7: Intelligence Maps ──────────────────────────────────────────
    {
        "id": "c7-pfas-map",
        "label": "PFAS Legislative Watch — State Map",
        "chapter": "7. Intelligence Maps",
        "chapter_intro": "Interactive state-by-state maps show the geographic spread of regulatory activity — built automatically from the same legislative data that feeds the dashboard.",
        "action": "viewport",
        "url": f"{_MAPS}/pfas-legislative-intel.html",
        "viewport": (1440, 900),
        "desc_hint": "The PFAS Legislative Intelligence map showing US states with PFAS-related legislation. States are color-coded by activity level. Hovering/clicking a state shows its active bills and most recent action.",
    },
    {
        "id": "c7-epr-map",
        "label": "EPR Packaging Law — State Coverage",
        "chapter": None,
        "action": "viewport",
        "url": f"{_MAPS}/epr-map.html",
        "viewport": (1440, 900),
        "compare_with": "c7-pfas-map",
        "desc_hint": "The EPR state map showing which states have active Extended Producer Responsibility packaging legislation — CA, ME, OR, CO, and others with pending bills.",
    },
    {
        "id": "c7-reach-map",
        "label": "REACH SVHC — EU Coverage",
        "chapter": None,
        "action": "viewport",
        "url": f"{_MAPS}/reach-map.html",
        "viewport": (1440, 900),
        "desc_hint": "The REACH map showing EU member state regulatory activity for SVHC substances. Relevant for any company selling or sourcing materials in EU markets.",
    },

    # ── Chapter 8: Timeline Pages ─────────────────────────────────────────────
    {
        "id": "c8-pfas-timeline",
        "label": "PFAS Deadlines — Full Timeline",
        "chapter": "8. Full Timeline Views",
        "chapter_intro": "Each topic has a dedicated full-page timeline showing every tracked deadline plotted chronologically — shareable standalone pages linked from the dashboard.",
        "action": "viewport",
        "url": f"{_MAPS}/pfas-timeline.html",
        "viewport": (1440, 900),
        "desc_hint": "The PFAS standalone timeline page showing all PFAS-related regulatory deadlines plotted chronologically. Each point is labeled with title, date, and urgency.",
    },
    {
        "id": "c8-all-deadlines",
        "label": "All Deadlines — Master Timeline",
        "chapter": None,
        "action": "viewport",
        "url": f"{_MAPS}/deadline-timeline.html",
        "viewport": (1440, 900),
        "desc_hint": "The master deadline timeline aggregating all topics — a single page showing every upcoming compliance date across PFAS, EPR, REACH, TSCA, Prop65, and more.",
    },

    # ── Chapter 9: Director's AI Review ───────────────────────────────────────
    {
        "id": "c9-director",
        "label": "Director's AI Analysis",
        "chapter": "9. Director's AI Review",
        "chapter_intro": "A separate AI-generated strategic assessment page — scored on usefulness, actionability, and signal-to-noise — with specific improvement recommendations for the compliance team.",
        "action": "viewport",
        "url": f"{_MAPS}/director_review.html",
        "viewport": (1440, 900),
        "desc_hint": "The Director Review page — a standalone AI strategic assessment of the dashboard's weekly output. Scored on usefulness (1-10), actionability, and signal-to-noise ratio. Includes specific recommended improvements for the compliance team.",
    },
    {
        "id": "c9-cross-state",
        "label": "Cross-State Pattern Analysis",
        "chapter": None,
        "action": "viewport",
        "url": f"{_MAPS}/cross_state_report.html",
        "viewport": (1440, 900),
        "desc_hint": "The cross-state pattern analysis report — identifies coordinated legislative patterns across multiple states, which often predict upcoming federal action.",
    },

    # ── Chapter 10: Analytics Panels ──────────────────────────────────────────
    {
        "id": "c10-trends",
        "label": "28-Day Article Trend Chart",
        "chapter": "10. Analytics & Resources",
        "chapter_intro": "Built-in analytics panels track coverage trends over time and show how the legislative pipeline is progressing across topics.",
        "action": "selector",
        "selector": "[data-widget-id='trends']",
        "scroll_to": "[data-widget-id='trends']",
        "desc_hint": "The 28-day article trend panel showing article volume by topic over the past month. Bars are color-coded by topic. Useful for spotting spikes in regulatory activity.",
    },
    {
        "id": "c10-funnel",
        "label": "Bill Pipeline Funnel",
        "chapter": None,
        "action": "selector",
        "selector": "[data-widget-id='bill-funnel']",
        "scroll_to": "[data-widget-id='bill-funnel']",
        "compare_with": "c10-trends",
        "desc_hint": "The bill pipeline funnel showing how many tracked bills are at each legislative stage — introduced, committee, floor vote, passed, signed. Shows attrition from introduction to enactment.",
    },
    {
        "id": "c10-glossary",
        "label": "Regulatory Glossary",
        "chapter": None,
        "action": "viewport",
        "url": f"{_MAPS}/glossary.html",
        "viewport": (1440, 900),
        "desc_hint": "The auto-generated regulatory glossary page — definitions for all abbreviations and terms used across the dashboard, compiled by AI from the tracked regulatory sources.",
    },
]


# ── Screenshot capture ────────────────────────────────────────────────────────

def _find_latest_preview() -> Path | None:
    data_dir = Path(__file__).parent.parent / "data"
    candidates = sorted(data_dir.glob("preview_dashboard_*.html"), reverse=True)
    if candidates:
        return candidates[0]
    stable = data_dir / "preview_dashboard.html"
    return stable if stable.exists() else None


def _screenshot_target(page: Any, target: dict, output_path: Path) -> bool:
    from playwright.sync_api import Error as PWError
    action = target.get("action", "selector")
    wait_ms = target.get("wait_ms", 600)
    try:
        if target.get("scroll_to"):
            el = page.query_selector(target["scroll_to"])
            if el:
                el.scroll_into_view_if_needed()
                page.wait_for_timeout(300)

        if target.get("pre_js"):
            page.evaluate(target["pre_js"])
            page.wait_for_timeout(250)

        if action == "click_then_selector" and target.get("click"):
            el = page.query_selector(target["click"])
            if not el:
                logger.warning(f"  Click target not found: {target['click']} — skipping {target['id']}")
                return False
            el.click()
            page.wait_for_timeout(wait_ms)

        if action == "full_page":
            page.screenshot(path=str(output_path), full_page=True)

        elif action == "viewport":
            page.screenshot(path=str(output_path), full_page=False)

        elif action in ("selector", "click_then_selector"):
            sel = target.get("selector")
            if not sel:
                return False
            el = page.query_selector(sel)
            if not el:
                logger.warning(f"  Selector not found: {sel} — skipping {target['id']}")
                return False
            max_h = target.get("max_height")
            if max_h:
                box = el.bounding_box()
                if box:
                    page.screenshot(path=str(output_path), clip={
                        "x": box["x"], "y": box["y"],
                        "width": box["width"], "height": min(box["height"], max_h),
                    })
                else:
                    el.screenshot(path=str(output_path))
            else:
                el.screenshot(path=str(output_path))
        else:
            logger.warning(f"Unknown action '{action}' for {target['id']}")
            return False

        if action == "click_then_selector":
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        return True

    except PWError as e:
        logger.warning(f"  Playwright error for {target['id']}: {e}")
        return False
    except Exception as e:
        logger.warning(f"  Screenshot failed for {target['id']}: {e}")
        return False


def _describe_screenshot(client: Any, image_path: Path, target: dict) -> str:
    hint = target.get("desc_hint", "")
    chapter = target.get("chapter") or ""
    prompt = f"""You are writing a caption for a compliance intelligence dashboard user guide.

Screenshot: {target['label']}
{f'Chapter: {chapter}' if chapter else ''}
{f'Context: {hint}' if hint else ''}

Describe what is visible in 3-5 sentences. Focus on:
1. What information is displayed and how it's organized
2. What interactive elements exist and what they do
3. How to read the color coding, badges, or indicators shown

Be specific and practical. Write in second person. No generic filler."""

    image_data = image_path.read_bytes()
    cache_key = f"manual_desc_v2_{target['id']}_{date.today().isoformat()}"
    try:
        return client.complete_haiku_vision(prompt, image_data, cache_key=cache_key)
    except Exception as e:
        logger.warning(f"Vision description failed for {target['id']}: {e}")
        return f"[{target['label']}]"


# ── Full manual (prose) ───────────────────────────────────────────────────────

_SYNTHESIS_SYSTEM = """\
You are a technical writer producing a user manual for an internal enterprise compliance dashboard.
Audience: small expert compliance team at a US windows/doors manufacturer.
Tone: expert-to-expert, direct, no marketing fluff. Focus on what things do and how to use them."""


def _synthesize_manual(client: Any, sections: list[dict], dashboard_url: str) -> str:
    sections_text = "".join(
        f"\n\n### {s['label']} ({s.get('section','')}) — file: {s['filename']}\n{s['description']}\n"
        for s in sections
    )
    prompt = f"""Write a complete user manual for the Compliance Intelligence Dashboard.

Dashboard: {dashboard_url}
Screenshots covered ({len(sections)} total):{sections_text}

Structure:
1. Overview — what it is, who it's for
2. Navigation — topic cards, drawer customization
3. Executive Briefing — what the AI summary contains
4. Topic Sections — article cards, impact labels, filtering
5. Compliance Dates — urgency colors, New/Updated badges, AI analysis modal, timeline widget
6. Legislative Activity — bill feed, filters, bill detail modal, expand mode
7. Intelligence Maps — PFAS map, EPR map, REACH map
8. Timeline Pages — per-topic and master deadline timelines
9. Director's AI Review — strategic assessment page
10. Analytics — trends chart, bill funnel
11. Resources — glossary, calendar

For each section: H2 header, what it is, how to use it, reference screenshots as (see: filename.png).
Expert audience — skip explaining what PFAS is. Return plain markdown."""

    try:
        return client.complete_sonnet(prompt, system=_SYNTHESIS_SYSTEM,
                                      cache_key=f"manual_v2_synthesis_{date.today().isoformat()}_{len(sections)}")
    except Exception as e:
        logger.warning(f"Synthesis failed: {e}")
        return "# Compliance Dashboard User Manual\n\n[Synthesis failed]\n"


def _markdown_to_html_fragment(md: str) -> str:
    h = md
    h = re.sub(r'^### (.+)$', r'<h3>\1</h3>', h, flags=re.MULTILINE)
    h = re.sub(r'^## (.+)$', r'<h2>\1</h2>', h, flags=re.MULTILINE)
    h = re.sub(r'^# (.+)$', r'<h1>\1</h1>', h, flags=re.MULTILINE)
    h = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', h)
    h = re.sub(r'`(.+?)`', r'<code>\1</code>', h)
    h = re.sub(r'(?m)^[-*] (.+)$', r'<li>\1</li>', h)
    h = re.sub(r'(?m)^\d+\. (.+)$', r'<li>\1</li>', h)
    parts = [f'<p>{p.strip().replace(chr(10),"<br>")}</p>' if not p.strip().startswith('<') else p.strip()
             for p in re.split(r'\n\n+', h) if p.strip()]
    return '\n'.join(parts)


def _build_html_manual(markdown_text: str, sections: list[dict], output_dir: Path) -> str:
    body = _markdown_to_html_fragment(markdown_text)
    today_str = date.today().strftime("%B %d, %Y")
    screenshots_html = ""
    for s in sections:
        if (output_dir / "screenshots" / s["filename"]).exists():
            screenshots_html += f"""
<div class="ss-block">
  <div class="ss-lbl">{s['label']} <span class="ss-sec">{s.get('section','')}</span></div>
  <img src="screenshots/{s['filename']}" alt="{s['label']}">
  <p class="ss-desc">{s['description']}</p>
</div>"""

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Compliance Dashboard — User Manual</title>
<style>
:root{{--bg:#f8fafc;--s:#fff;--b:#e2e8f0;--t:#0f172a;--m:#64748b;--a:#2563eb;--mono:'Fira Code',monospace}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:var(--bg);color:var(--t);line-height:1.65;font-size:15px}}
.layout{{display:flex;min-height:100vh}}
.sidebar{{width:220px;flex-shrink:0;background:var(--s);border-right:1px solid var(--b);padding:24px 0;position:sticky;top:0;height:100vh;overflow-y:auto}}
.sidebar h2{{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--m);padding:0 18px 8px}}
.sidebar a{{display:block;padding:4px 18px;font-size:12px;color:var(--m);text-decoration:none;border-left:2px solid transparent}}
.sidebar a:hover{{color:var(--a);border-left-color:var(--a)}}
.content{{flex:1;max-width:880px;padding:48px 56px}}
h1{{font-size:26px;font-weight:700;margin-bottom:6px}}
h2{{font-size:18px;font-weight:700;margin:36px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--b)}}
h3{{font-size:15px;font-weight:600;margin:20px 0 6px}}
p{{margin-bottom:10px;color:#334155}}
code{{font-family:var(--mono);font-size:12px;background:#f1f5f9;padding:2px 5px;border-radius:3px}}
strong{{font-weight:600}}
.meta{{font-size:12px;color:var(--m);margin-bottom:32px}}
.ss-block{{margin-bottom:36px;border:1px solid var(--b);border-radius:8px;overflow:hidden;background:var(--s)}}
.ss-lbl{{font-size:11px;font-weight:600;padding:8px 14px;background:#f8fafc;border-bottom:1px solid var(--b)}}
.ss-sec{{color:var(--m);font-weight:400}}
.ss-block img{{width:100%;display:block;border-bottom:1px solid var(--b)}}
.ss-desc{{font-size:12px;color:var(--m);padding:8px 14px;margin:0}}
@media print{{.sidebar{{display:none}}.content{{padding:24px}}}}
</style></head><body>
<div class="layout">
<nav class="sidebar"><h2>Contents</h2>
<a href="#overview">Overview</a><a href="#navigation">Navigation</a>
<a href="#briefing">Executive Briefing</a><a href="#topics">Topic Sections</a>
<a href="#deadlines">Compliance Dates</a><a href="#legislative">Legislative</a>
<a href="#maps">Maps</a><a href="#timelines">Timelines</a>
<a href="#director">Director Review</a><a href="#analytics">Analytics</a>
<a href="#resources">Resources</a>
<a href="#screenshots" style="margin-top:16px;border-top:1px solid var(--b);padding-top:10px">All Screenshots</a>
</nav>
<main class="content">
<h1>Compliance Dashboard</h1>
<p class="meta">User Manual &mdash; {today_str}</p>
{body}
<h2 id="screenshots">Screenshot Reference</h2>
{screenshots_html}
</main></div></body></html>"""


def generate_manual(source_url: str | None = None, output_dir: Path | None = None, force: bool = False) -> Path:
    """Generate the full prose user manual with all screenshots."""
    from ai.claude_client import ClaudeClient
    from playwright.sync_api import sync_playwright

    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "data" / "manual"
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    today = date.today().isoformat()
    manual_path = output_dir / f"user-manual-{today}.html"
    if manual_path.exists() and not force:
        logger.info(f"Manual already generated today: {manual_path}")
        return manual_path

    if source_url is None:
        preview = _find_latest_preview()
        if not preview:
            raise FileNotFoundError("No preview dashboard HTML found. Run with --preview first.")
        source_url = preview.as_uri()
        logger.info(f"Using preview: {preview.name}")

    client = ClaudeClient()
    completed_sections: list[dict] = []
    failed: list[str] = []

    logger.info(f"Taking {len(CAPTURE_PLAN)} screenshots…")
    with sync_playwright() as pw:
        for target in CAPTURE_PLAN:
            tid = target["id"]
            vp = target.get("viewport", (1440, 900))
            png_name = f"{tid}.png"
            png_path = screenshots_dir / png_name
            target_url = target.get("url", source_url)
            logger.info(f"  [{tid}] {target['label']}")

            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": vp[0], "height": vp[1]}, device_scale_factor=2)
            page = ctx.new_page()
            try:
                page.goto(target_url, wait_until="networkidle", timeout=30_000)
                page.wait_for_timeout(800)
                ok = _screenshot_target(page, target, png_path)
                if ok:
                    logger.info(f"    {png_name} ({png_path.stat().st_size // 1024}KB)")
                    completed_sections.append({
                        "id": tid, "label": target["label"],
                        "section": target.get("chapter", target.get("section", "")),
                        "filename": png_name, "description": "",
                    })
                else:
                    if not target.get("optional"):
                        failed.append(tid)
                    else:
                        logger.info(f"    Skipped (optional): {tid}")
            except Exception as e:
                logger.warning(f"    Failed {tid}: {e}")
                if not target.get("optional"):
                    failed.append(tid)
            finally:
                browser.close()

    logger.info(f"Screenshots: {len(completed_sections)} captured, {len(failed)} failed")

    target_map = {t["id"]: t for t in CAPTURE_PLAN}
    logger.info("Describing screenshots with Haiku vision…")
    for sec in completed_sections:
        sec["description"] = _describe_screenshot(client, screenshots_dir / sec["filename"], target_map[sec["id"]])

    logger.info("Synthesizing manual with Sonnet…")
    markdown = _synthesize_manual(client, completed_sections, source_url)

    html = _build_html_manual(markdown, completed_sections, output_dir)
    manual_path.write_text(html, encoding="utf-8")
    md_path = output_dir / f"user-manual-{today}.md"
    md_path.write_text(markdown, encoding="utf-8")
    shutil.copy2(manual_path, output_dir / "user-manual.html")
    shutil.copy2(md_path, output_dir / "user-manual.md")

    record = {"generated_at": datetime.now().isoformat(), "source_url": source_url,
               "screenshots": len(completed_sections), "failed": failed}
    (output_dir / "last_run.json").write_text(json.dumps(record, indent=2))
    logger.info(f"Manual: {manual_path}")
    return manual_path


# ── Visual Guide ──────────────────────────────────────────────────────────────

def _rewrite_for_visual_guide(client: Any, sections: list[dict]) -> list[dict]:
    """One Sonnet call rewrites all descriptions into punchy visual-guide captions + bullets."""
    input_text = "".join(
        f"\n---\nID: {s['id']}\nLabel: {s['label']}\nChapter: {s.get('section','')}\nDescription: {s['description']}\n"
        for s in sections
    )
    prompt = f"""Rewrite each compliance dashboard screenshot description as a visual guide entry. This is a user manual for a director-level compliance team — it must be both polished AND genuinely instructional.

For each entry produce exactly:
- "caption": one punchy sentence (≤18 words) — what this shows and why it matters
- "body": 2-4 sentences of real how-to instructions — what to do, what to click, what to watch for, step by step. This is the main instructional content. Write like a knowledgeable colleague explaining it over your shoulder.
- "bullets": 2-3 items (≤12 words each) — the most important single interaction points ("Click any deadline for AI impact analysis")

Rules:
- The audience knows regulatory compliance — no explaining what PFAS is
- Body text should be genuinely useful instructions, not a description of what's visible
- Bullets should be imperative: start with a verb ("Click", "Filter", "Hover", "Use")
- For interactive features (modals, drawers, maps), body must explain how to open and use them
- For data panels, body must say what to look for and how to act on it
- Marketing quality, but not empty marketing language

{input_text}

Return a JSON array in the same order:
[{{"id": "...", "caption": "...", "body": "...", "bullets": ["...", "...", "..."]}}, ...]

Return only valid JSON."""

    cache_key = f"vg_v3_captions_{date.today().isoformat()}_{len(sections)}"
    try:
        raw = client.complete_sonnet(prompt, cache_key=cache_key).strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
        entry_map = {e["id"]: e for e in json.loads(raw)}
        for sec in sections:
            e = entry_map.get(sec["id"], {})
            sec["vg_caption"] = e.get("caption", sec["label"])
            sec["vg_body"] = e.get("body", "")
            sec["vg_bullets"] = e.get("bullets", [])
    except Exception as ex:
        logger.warning(f"Caption rewrite failed: {ex}")
        for sec in sections:
            sec["vg_caption"] = (sec.get("description") or sec["label"]).split(".")[0].strip() + "."
            sec["vg_body"] = ""
            sec["vg_bullets"] = []
    return sections


def _build_visual_guide_html(sections: list[dict], output_dir: Path) -> str:
    today_str = date.today().strftime("%B %d, %Y")
    target_map = {t["id"]: t for t in CAPTURE_PLAN}

    # Build section lookup
    sec_map = {s["id"]: s for s in sections}

    # Identify pairs (compare_with)
    paired_ids: set[str] = set()
    for t in CAPTURE_PLAN:
        if t.get("compare_with") and t["id"] in sec_map and t["compare_with"] in sec_map:
            paired_ids.add(t["id"])
            paired_ids.add(t["compare_with"])

    # Build chapter groups
    chapters: list[dict] = []
    current_chapter: dict | None = None
    for t in CAPTURE_PLAN:
        sid = t["id"]
        if sid not in sec_map:
            continue
        sec = sec_map[sid]
        if t.get("chapter"):
            current_chapter = {
                "title": t["chapter"],
                "intro": t.get("chapter_intro", ""),
                "items": [],
            }
            chapters.append(current_chapter)
        if current_chapter is not None:
            current_chapter["items"].append(sec)

    def browser_chrome(url_hint: str = "") -> str:
        return f"""<div class="chrome-bar"><span class="chrome-dot" style="background:#ff5f57"></span><span class="chrome-dot" style="background:#febc2e"></span><span class="chrome-dot" style="background:#28c840"></span><span class="chrome-url">{url_hint or 'Compliance Intelligence Dashboard'}</span></div>"""

    def render_card(sec: dict, pair_label: str = "", full_width: bool = True) -> str:
        png = output_dir / "screenshots" / sec["filename"]
        if not png.exists():
            return ""
        t = target_map.get(sec["id"], {})
        url_hint = t.get("url", "").replace("file:///tmp/compliance-maps/", "").replace(".html", "") or ""
        bullets_html = "".join(f'<li>{b}</li>' for b in sec.get("vg_bullets", []))
        body_text = sec.get("vg_body", "")
        use_inline = t.get("layout") == "inline" and full_width and not pair_label
        pair_badge = f'<span class="pair-badge">{pair_label}</span>' if pair_label else ""

        body_content = f"""
    <div class="card-title">{sec['label']}</div>
    <p class="card-caption">{sec.get('vg_caption', '')}</p>
    {f'<p class="card-body-text">{body_text}</p>' if body_text else ''}
    {'<ul class="card-bullets">' + bullets_html + '</ul>' if bullets_html else ''}"""

        if use_inline:
            return f"""
<div class="card-inline" id="s-{sec['id']}">
  <div class="card-inline-img">
    {browser_chrome(url_hint)}
    <div class="card-img-wrap"><img src="screenshots/{sec['filename']}" alt="{sec['label']}" loading="lazy"></div>
  </div>
  <div class="card-body">{body_content}
  </div>
</div>"""
        else:
            w_cls = "card-full" if full_width else "card-half"
            return f"""
<div class="{w_cls}" id="s-{sec['id']}">
  {browser_chrome(url_hint)}
  <div class="card-img-wrap">{pair_badge}<img src="screenshots/{sec['filename']}" alt="{sec['label']}" loading="lazy"></div>
  <div class="card-body">{body_content}
  </div>
</div>"""

    # Render chapters
    chapters_html = ""
    rendered_pairs: set[frozenset] = set()

    for ch_idx, ch in enumerate(chapters):
        ch_num = ch["title"].split(".")[0] if "." in ch["title"] else str(ch_idx + 1)
        ch_name = ch["title"].split(". ", 1)[-1] if ". " in ch["title"] else ch["title"]
        chapters_html += f"""
<div class="chapter" id="ch-{ch_idx+1}">
  <div class="chapter-hdr">
    <span class="chapter-num">{ch_num}</span>
    <div>
      <div class="chapter-name">{ch_name}</div>
      {f'<p class="chapter-intro">{ch["intro"]}</p>' if ch["intro"] else ""}
    </div>
  </div>
"""
        # Group items: find pairs first, then singles
        items = ch["items"]
        i = 0
        while i < len(items):
            sec = items[i]
            t = target_map.get(sec["id"], {})
            compare_id = t.get("compare_with")
            pair_key = frozenset([sec["id"], compare_id]) if compare_id else None

            if compare_id and compare_id in sec_map and pair_key not in rendered_pairs:
                # Side-by-side pair
                other = sec_map[compare_id]
                rendered_pairs.add(pair_key)
                chapters_html += f'<div class="pair-row">'
                chapters_html += render_card(other, pair_label="Before", full_width=False)
                chapters_html += render_card(sec, pair_label="After", full_width=False)
                chapters_html += '</div>'
            elif pair_key in rendered_pairs or (sec["id"] in paired_ids and compare_id is None):
                # Skip — already rendered as part of a pair, or is a pair target
                # Check if this is the "source" of a pair (compare_with points TO it)
                is_pair_target = any(
                    t2.get("compare_with") == sec["id"] and t2["id"] in sec_map
                    for t2 in CAPTURE_PLAN
                )
                if is_pair_target:
                    pass  # will be rendered when the item that points to it is processed
                else:
                    chapters_html += render_card(sec, full_width=True)
            else:
                chapters_html += render_card(sec, full_width=True)
            i += 1

        chapters_html += '</div>'

    # TOC page + floating nav
    toc_items_html = ""
    nav_links = ""
    for ch_idx, ch in enumerate(chapters):
        name = ch["title"].split(". ", 1)[-1] if ". " in ch["title"] else ch["title"]
        num = ch["title"].split(".")[0] if "." in ch["title"] else str(ch_idx + 1)
        toc_items_html += (
            f'      <li class="toc-item"><span class="toc-num">{num}</span>'
            f'<a class="toc-name" href="#ch-{ch_idx+1}">{name}</a></li>\n'
        )
        nav_links += f'  <a class="fn-dot" href="#ch-{ch_idx+1}" title="{ch["title"]}">{num}</a>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compliance Intelligence Dashboard — Visual Guide</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,400&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --navy:   #0a0e1a;
  --accent: #2563eb;
  --text:   #0f172a;
  --text2:  #334155;
  --muted:  #64748b;
  --border: #e2e8f0;
  --bg:     #f8f9fc;
  --card:   #ffffff;
  --chrome: #f1f5f9;
  --chr-b:  #cbd5e1;
  --pair-a: #eff6ff;
  --pair-b: #f0fdf4;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; color-adjust: exact; }}
body {{ font-family: 'DM Sans', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.55; font-size: 15px; }}
a {{ color: inherit; text-decoration: none; }}

/* ── Cover ── */
.cover {{
  background: var(--navy); color: #fff;
  min-height: 100vh; padding: 80px 96px 72px;
  display: flex; flex-direction: column;
  position: relative; overflow: hidden;
}}
.cover::before {{
  content: ''; position: absolute; inset: 0;
  background-image: linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.022) 1px, transparent 1px);
  background-size: 52px 52px; pointer-events: none;
}}
.cover::after {{
  content: ''; position: absolute; top: 0; right: 0;
  width: 50%; height: 100%;
  background: linear-gradient(145deg, transparent 35%, rgba(37,99,235,.09) 100%);
  pointer-events: none;
}}
.cover-inner {{ position: relative; z-index: 1; flex: 1; display: flex; flex-direction: column; }}
.cover-rule {{ width: 52px; height: 3px; background: var(--accent); border-radius: 2px; margin-bottom: 44px; }}
.cover-eyebrow {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: .2em; text-transform: uppercase; color: rgba(255,255,255,.35); margin-bottom: 20px; }}
.cover-title {{ font-family: 'Playfair Display', Georgia, serif; font-size: clamp(38px, 5vw, 60px); font-weight: 900; line-height: 1.04; letter-spacing: -.5px; max-width: 640px; }}
.cover-title em {{ font-style: italic; color: rgba(255,255,255,.6); font-weight: 400; }}
.cover-subtitle {{ font-size: 16px; color: rgba(255,255,255,.42); max-width: 400px; line-height: 1.65; margin-top: 28px; font-weight: 300; }}
.cover-spacer {{ flex: 1; min-height: 60px; }}
.cover-footer {{ display: flex; align-items: flex-end; justify-content: space-between; padding-top: 36px; border-top: 1px solid rgba(255,255,255,.07); }}
.cover-date {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: rgba(255,255,255,.28); letter-spacing: .06em; line-height: 1.7; }}
.cover-badge {{ font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: .14em; text-transform: uppercase; color: rgba(255,255,255,.2); border: 1px solid rgba(255,255,255,.1); padding: 5px 12px; border-radius: 20px; }}

/* ── TOC ── */
.toc {{ background: var(--card); padding: 80px 96px 64px; min-height: 100vh; }}
.toc-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: .2em; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; }}
.toc-heading {{ font-family: 'Playfair Display', serif; font-size: 32px; font-weight: 700; color: var(--text); margin-bottom: 44px; line-height: 1.15; }}
.toc-list {{ list-style: none; border-top: 2px solid var(--border); }}
.toc-item {{ display: flex; align-items: center; gap: 16px; padding: 15px 0; border-bottom: 1px solid var(--border); }}
.toc-num {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--accent); width: 26px; flex-shrink: 0; }}
.toc-name {{ font-size: 15px; font-weight: 500; color: var(--text2); flex: 1; transition: color .12s; }}
.toc-name:hover {{ color: var(--accent); }}

/* ── Chapter ── */
.chapter {{ padding: 80px 96px 48px; }}
.chapter-hdr {{ display: flex; align-items: flex-start; gap: 28px; padding-bottom: 32px; margin-bottom: 40px; border-bottom: 2px solid var(--border); }}
.chapter-num {{ font-family: 'Playfair Display', serif; font-size: 72px; font-weight: 900; color: var(--border); line-height: 1; flex-shrink: 0; letter-spacing: -4px; margin-top: -8px; user-select: none; }}
.chapter-name {{ font-family: 'Playfair Display', serif; font-size: 28px; font-weight: 700; color: var(--text); line-height: 1.2; margin-bottom: 10px; }}
.chapter-intro {{ font-size: 14px; color: var(--muted); line-height: 1.7; max-width: 540px; font-weight: 300; }}

/* ── Browser chrome ── */
.chrome-bar {{ background: var(--chrome); border-bottom: 1px solid var(--chr-b); padding: 8px 12px; display: flex; align-items: center; gap: 6px; border-radius: 8px 8px 0 0; }}
.chrome-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
.chrome-url {{ flex: 1; background: #fff; border: 1px solid var(--chr-b); border-radius: 4px; padding: 3px 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-left: 8px; }}

/* ── Cards ── */
.card-full, .card-half {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.05), 0 6px 24px rgba(0,0,0,.06); margin-bottom: 32px; }}
.card-img-wrap {{ position: relative; background: #f1f5f9; }}
.card-img-wrap img {{ width: 100%; height: auto; display: block; }}
.pair-badge {{ position: absolute; top: 10px; left: 10px; font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: .1em; text-transform: uppercase; padding: 3px 8px; border-radius: 3px; backdrop-filter: blur(4px); }}
.card-half:first-child .pair-badge {{ background: var(--pair-a); color: #1d4ed8; }}
.card-half:last-child .pair-badge {{ background: var(--pair-b); color: #15803d; }}
.card-body {{ padding: 18px 22px 20px; }}
.card-title {{ font-size: 13px; font-weight: 600; margin-bottom: 6px; color: var(--text); }}
.card-caption {{ font-size: 13px; color: var(--text2); line-height: 1.6; margin-bottom: 10px; font-weight: 300; }}
.card-bullets {{ list-style: none; padding: 0; display: flex; flex-direction: column; gap: 5px; }}
.card-bullets li {{ font-size: 12px; color: var(--muted); display: flex; gap: 8px; align-items: flex-start; line-height: 1.4; }}
.card-bullets li::before {{ content: '\2014'; color: var(--accent); font-weight: 700; flex-shrink: 0; font-size: 10px; margin-top: 2px; }}

/* ── Body text (instructional paragraph) ── */
.card-body-text {{ font-size: 13px; color: var(--text2); line-height: 1.7; margin-bottom: 12px; font-weight: 300; border-left: 2px solid var(--border); padding-left: 14px; }}

/* ── Inline card (image left, text right) ── */
.card-inline {{
  display: grid; grid-template-columns: 42% 58%;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.05), 0 6px 24px rgba(0,0,0,.06);
  margin-bottom: 32px; align-items: stretch;
}}
.card-inline .card-inline-img {{ border-right: 1px solid var(--border); display: flex; flex-direction: column; }}
.card-inline .card-inline-img .chrome-bar {{ border-radius: 0; flex-shrink: 0; }}
.card-inline .card-inline-img .card-img-wrap {{ flex: 1; overflow: hidden; }}
.card-inline .card-inline-img img {{ width: 100%; height: 100%; object-fit: cover; object-position: top center; display: block; }}
.card-inline .card-body {{ padding: 24px 26px; display: flex; flex-direction: column; justify-content: center; }}

/* ── Pair row ── */
.pair-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 32px; align-items: start; }}
.pair-row .card-half {{ margin-bottom: 0; }}

/* ── Floating nav (screen only) ── */
.fnav {{ position: fixed; right: 20px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: column; gap: 7px; z-index: 200; }}
.fn-dot {{ width: 26px; height: 26px; border-radius: 50%; background: var(--navy); color: rgba(255,255,255,.45); display: flex; align-items: center; justify-content: center; font-family: 'JetBrains Mono', monospace; font-size: 9px; transition: all .15s; border: 1px solid rgba(255,255,255,.07); box-shadow: 0 2px 8px rgba(0,0,0,.25); }}
.fn-dot:hover {{ background: var(--accent); color: #fff; transform: scale(1.18); }}

/* ═══════════════════════════════════════════════════
   PRINT / PDF — Comprehensive layout rules
   ═══════════════════════════════════════════════════ */
@media print {{

  @page {{ size: A4; margin: 25mm 22mm 22mm 22mm; }}
  @page :first {{ margin: 0; }}

  html, body {{ background: #fff !important; font-size: 10.5pt; }}
  .fnav {{ display: none !important; }}

  /* Cover — exactly one A4 page, full bleed */
  .cover {{
    height: 297mm;
    min-height: 0 !important;
    padding: 50mm 28mm 36mm !important;
    overflow: hidden !important;
    page-break-after: always;
    break-after: page;
  }}
  .cover-title {{ font-size: 34pt !important; }}
  .cover-subtitle {{ font-size: 11pt !important; }}
  .cover-eyebrow {{ font-size: 8pt !important; letter-spacing: .18em !important; }}
  .cover-date {{ font-size: 9pt !important; }}
  .cover-rule {{ margin-bottom: 36mm; }}

  /* TOC — own page */
  .toc {{
    min-height: 0 !important;
    padding: 26mm 22mm !important;
    page-break-after: always;
    break-after: page;
  }}
  .toc-heading {{ font-size: 20pt !important; margin-bottom: 22pt !important; }}
  .toc-item {{ padding: 9pt 0 !important; }}
  .toc-name {{ font-size: 10.5pt !important; }}
  .toc-num {{ font-size: 9pt !important; }}

  /* Chapters — each starts on a new page */
  .chapter {{
    padding: 0 0 16mm !important;
    page-break-before: always;
    break-before: page;
  }}
  .chapter-hdr {{ padding-bottom: 13pt !important; margin-bottom: 20pt !important; }}
  .chapter-num {{ font-size: 42pt !important; }}
  .chapter-name {{ font-size: 19pt !important; }}
  .chapter-intro {{ font-size: 9.5pt !important; }}

  /* Cards — never split across pages */
  .card-full, .card-half {{
    page-break-inside: avoid !important;
    break-inside: avoid !important;
    box-shadow: none !important;
    border: 1px solid #dde3ec !important;
    margin-bottom: 13pt !important;
  }}
  .pair-row {{
    page-break-inside: avoid !important;
    break-inside: avoid !important;
    gap: 9pt !important;
    margin-bottom: 13pt !important;
    grid-template-columns: 1fr 1fr !important;
  }}
  .card-img-wrap img {{ max-width: 100% !important; width: 100% !important; height: auto !important; }}
  .card-inline {{ grid-template-columns: 40% 60% !important; }}
  .card-inline .card-inline-img img {{ height: auto !important; object-fit: contain !important; }}
  .card-body {{ padding: 9pt 11pt 11pt !important; }}
  .card-title {{ font-size: 9pt !important; font-weight: 600 !important; }}
  .card-caption {{ font-size: 8.5pt !important; line-height: 1.5 !important; }}
  .card-body-text {{ font-size: 8pt !important; line-height: 1.55 !important; padding-left: 8pt !important; margin-bottom: 7pt !important; }}
  .card-bullets li {{ font-size: 8pt !important; }}
  .chrome-bar {{ padding: 5px 9px !important; }}
  .chrome-url {{ font-size: 7.5pt !important; }}
  .chrome-dot {{ width: 7px !important; height: 7px !important; }}
  a {{ color: inherit !important; text-decoration: none !important; }}
}}
</style>
</head>
<body>

<nav class="fnav" aria-hidden="true">
{nav_links}</nav>

<div class="cover">
  <div class="cover-inner">
    <div class="cover-rule"></div>
    <div class="cover-eyebrow">Internal Reference &nbsp;&bull;&nbsp; Compliance Team</div>
    <div class="cover-title">Compliance<br><em>Intelligence</em><br>Dashboard</div>
    <div class="cover-subtitle">A visual walkthrough of every panel, map, and interactive feature of the regulatory monitoring platform.</div>
    <div class="cover-spacer"></div>
    <div class="cover-footer">
      <div class="cover-date">Generated {today_str}<br>Andersen Corporation &mdash; Confidential</div>
      <div class="cover-badge">Visual Guide</div>
    </div>
  </div>
</div>

<div class="toc">
  <div class="toc-label">Contents</div>
  <div class="toc-heading">What&rsquo;s Inside</div>
  <ul class="toc-list">
{toc_items_html}  </ul>
</div>

{chapters_html}
</body>
</html>"""


def generate_visual_guide(
    output_dir: Path | None = None,
    source_url: str | None = None,
    force: bool = False,
) -> Path:
    """Generate visual-first quick reference guide from existing or fresh screenshots."""
    from ai.claude_client import ClaudeClient

    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "data" / "manual"
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    guide_path = output_dir / f"visual-guide-{today}.html"
    if guide_path.exists() and not force:
        logger.info(f"Visual guide already exists: {guide_path}")
        return guide_path

    screenshots_dir = output_dir / "screenshots"
    existing_pngs = set(p.name for p in screenshots_dir.glob("*.png")) if screenshots_dir.exists() else set()

    if not existing_pngs:
        logger.info("No screenshots found — running generate_manual first…")
        generate_manual(source_url=source_url, output_dir=output_dir, force=True)
        existing_pngs = set(p.name for p in screenshots_dir.glob("*.png"))

    client = ClaudeClient()
    target_map = {t["id"]: t for t in CAPTURE_PLAN}
    sections: list[dict] = []

    for t in CAPTURE_PLAN:
        png_name = f"{t['id']}.png"
        if png_name not in existing_pngs:
            continue
        description = _describe_screenshot(client, screenshots_dir / png_name, t)
        sections.append({
            "id": t["id"], "label": t["label"],
            "section": t.get("chapter", ""),
            "filename": png_name, "description": description,
        })

    if not sections:
        raise RuntimeError("No screenshots found in data/manual/screenshots/")

    logger.info(f"Rewriting {len(sections)} captions (Sonnet)…")
    sections = _rewrite_for_visual_guide(client, sections)

    html = _build_visual_guide_html(sections, output_dir)
    guide_path.write_text(html, encoding="utf-8")
    shutil.copy2(guide_path, output_dir / "visual-guide.html")

    logger.info(f"Visual guide: {guide_path}")
    return guide_path
