#!/usr/bin/env python3
"""
Compliance Intelligence — Main entry point.

Usage:
    python run.py                        # Full run: scrape → summarize → render → send
    python run.py --dry-run              # Scrape + summarize, print output, no email
    python run.py --preview              # Render to HTML files and open in browser
    python run.py --force                # Skip already-sent-today check
    python run.py --finalize-week        # Manually create end-of-week archive (if Friday run failed)
    python run.py --send-reminder        # Send Friday 9 AM reminder email (called by cron)
    python run.py --test-email addr@...  # Send only to test address(es)
"""
import argparse
import logging
import shutil
import subprocess
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from scrapers.federal_register import FederalRegisterScraper
from scrapers.epa import EPAScraper
from scrapers.echa import ECHAScraper
from scrapers.minnesota_mpca import MinnesotaMPCAScraper
from scrapers.state_agencies import StateAgenciesScraper
from scrapers.pfas_central import PFASCentralScraper
from scrapers.safer_states import SaferStatesScraper
from scrapers.state_agency_pfas import (
    MaineDEPScraper,
    NewYorkDECScraper,
    WashingtonEcologyScraper,
    ColoradoCDPHEScraper,
    VermontDECScraper,
)
from scrapers.state_agency_playwright import (
    OregonDEQPlaywrightScraper,
    ConnecticutDEEPPlaywrightScraper,
)
from scrapers.state_agency_all_states import AllStatesPFASScraper
from scrapers.assent import AssentScraper
from scrapers.product_stewardship import ProductStewardshipScraper
from scrapers.oehha import OEHHAScraper
from scrapers.forced_labor import ForcedLaborScraper
from scrapers.conflict_minerals import ConflictMineralsScraper
from scrapers.pfas_legislative_intel import (
    NCSLPFASScraper, EWGPFASScraper, LawFirmPFASScraper,
    AdvocacyOrgScraper, LegalNewsPFASScraper,
)
from scrapers.chemycal import ChemycalScraper
from processors.deduplicator import deduplicate
from processors.relevance_filter import keyword_filter
from processors.week_tracker import apply_weekly_window, get_week_context, last_week_is_archived
from ai.summarizer import Summarizer
from newsletter.renderer import NewsletterRenderer
from delivery.gmail_sender import GmailSender
from delivery.state_map_generator import generate_pfas_map
from subscribers.db import init_db, get_archive_weeks, save_archive_week, get_upcoming_deadlines, get_bill_calendar_events
from subscribers.repository import SubscriberRepository
from delivery.calendar_generator import generate_ics
from scrapers.legiscan_tracker import LegiScanTracker

_PAGES_BASE = "https://ryan-jenkinson.github.io/compliance-maps"
_GITHUB_REPO_DIR = Path("/tmp/compliance-maps")
_REMINDER_EMAIL = "ryan.jenkinson@andersencorp.com"


# ── Logging ────────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Config.LOGS_DIR / "run.log"),
        ],
    )


# ── CLI ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compliance Intelligence")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and summarize, print output, no email sent")
    parser.add_argument("--preview", action="store_true",
                        help="Render HTML and open in browser, no email sent")
    parser.add_argument("--force", action="store_true",
                        help="Send even if already sent today")
    parser.add_argument("--no-email", action="store_true",
                        help="Run full pipeline and push to GitHub Pages, but skip all email sends")
    parser.add_argument("--finalize-week", action="store_true",
                        help="Manually trigger end-of-week archive (if Friday run failed)")
    parser.add_argument("--send-reminder", action="store_true",
                        help="Send Friday reminder email to verify end-of-week run")
    parser.add_argument("--test-email", action="append", default=[],
                        help="Send only to these addresses (repeatable)")
    parser.add_argument("--test-subject", default="",
                        help="Override email subject for test sends")
    parser.add_argument("--week-of", metavar="YYYY-MM-DD",
                        help="Override today's date (e.g. use last Friday to archive last week)")
    parser.add_argument("--director-review", action="store_true",
                        help="Run director critique now (ignores Monday gate) and open report")
    parser.add_argument("--cross-state", action="store_true",
                        help="Run cross-state pattern analysis now (ignores weekly gate)")
    parser.add_argument("--glossary", action="store_true",
                        help="Rebuild the regulatory abbreviation glossary and open it")
    return parser.parse_args()


# ── Scraping ───────────────────────────────────────────────────────────────

def scrape_all() -> list:
    logger = logging.getLogger("scraper")
    scrapers = [
        FederalRegisterScraper(),
        EPAScraper(),
        ECHAScraper(),
        MinnesotaMPCAScraper(),
        StateAgenciesScraper(),
        PFASCentralScraper(),
        SaferStatesScraper(),
        MaineDEPScraper(),
        NewYorkDECScraper(),
        WashingtonEcologyScraper(),
        ColoradoCDPHEScraper(),
        VermontDECScraper(),
        OregonDEQPlaywrightScraper(),
        ConnecticutDEEPPlaywrightScraper(),
        AllStatesPFASScraper(),
        AssentScraper(),
        ProductStewardshipScraper(),
        OEHHAScraper(),
        ForcedLaborScraper(),
        ConflictMineralsScraper(),
        NCSLPFASScraper(),
        EWGPFASScraper(),
        LawFirmPFASScraper(),
        AdvocacyOrgScraper(),
        LegalNewsPFASScraper(),
        ChemycalScraper(),
    ]
    all_articles = []
    for scraper in scrapers:
        try:
            articles = scraper.scrape()
            logger.info(f"{scraper.name}: {len(articles)} articles")
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"{scraper.name} failed: {e}")

    logger.info(f"Total before dedup: {len(all_articles)}")
    articles = deduplicate(all_articles)
    logger.info(f"After dedup: {len(articles)}")
    articles = keyword_filter(articles)
    logger.info(f"After keyword filter: {len(articles)}")
    return articles


# ── GitHub Pages ───────────────────────────────────────────────────────────

def _git_push(repo_dir: Path, files: list[str], message: str) -> bool:
    logger = logging.getLogger("github")
    cmds = [
        ["git", "-C", str(repo_dir), "add"] + files,
        ["git", "-C", str(repo_dir), "commit", "-m", message],
        ["git", "-C", str(repo_dir), "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "nothing to commit" not in result.stdout + result.stderr:
            logger.warning(f"Git command failed: {' '.join(cmd)}: {result.stderr.strip()}")
            return False
    return True


def _push_maps_to_github(pfas_map_path: Path, epr_map_path: Optional[Path],
                          reach_map_path: Optional[Path],
                          repo_dir: Path,
                          excel_paths: Optional[dict] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Copy PFAS, EPR, and REACH maps (and Excel files) to GitHub Pages repo and push."""
    logger = logging.getLogger("github_maps")
    try:
        dest = repo_dir / "index.html"
        shutil.copy2(pfas_map_path, dest)
        files = ["index.html"]
        epr_url = None
        reach_url = None

        if epr_map_path:
            epr_dest = repo_dir / "epr-map.html"
            shutil.copy2(epr_map_path, epr_dest)
            files.append("epr-map.html")
            epr_url = f"{_PAGES_BASE}/epr-map.html"

        if reach_map_path:
            reach_dest = repo_dir / "reach-map.html"
            shutil.copy2(reach_map_path, reach_dest)
            files.append("reach-map.html")
            reach_url = f"{_PAGES_BASE}/reach-map.html"

        # Copy Excel exports with stable filenames
        if excel_paths:
            for key, src_path in excel_paths.items():
                if src_path and Path(src_path).exists():
                    dest_name = f"{key}-tracker.xlsx"
                    shutil.copy2(src_path, repo_dir / dest_name)
                    files.append(dest_name)

        # Copy all timeline files
        data_dir = Path(__file__).parent / "data"
        for tl_name in ("deadline-timeline.html", "pfas-timeline.html", "epr-timeline.html",
                         "reach-timeline.html", "tsca-timeline.html"):
            tl_src = data_dir / tl_name
            if tl_src.exists():
                shutil.copy2(tl_src, repo_dir / tl_name)
                files.append(tl_name)

        # Copy legislative intel map if it exists
        intel_src = data_dir / "state_maps" / "pfas_proposed_preview.html"
        if intel_src.exists():
            shutil.copy2(intel_src, repo_dir / "pfas-legislative-intel.html")
            files.append("pfas-legislative-intel.html")

        date_str = date.today().isoformat()
        _git_push(repo_dir, files, f"Update state maps {date_str}")
        logger.info("Maps pushed to GitHub Pages.")
        return f"{_PAGES_BASE}/", epr_url, reach_url
    except Exception as e:
        logger.warning(f"Failed to push maps to GitHub: {e}")
        return f"{_PAGES_BASE}/", None, None


def _push_daily_newsletter(web_html: str, repo_dir: Path) -> Optional[str]:
    """Push daily newsletter web version. Returns dated URL."""
    logger = logging.getLogger("github_newsletter")
    try:
        newsletter_dir = repo_dir / "newsletter"
        newsletter_dir.mkdir(exist_ok=True)
        date_str = date.today().isoformat()

        dated_path = newsletter_dir / f"{date_str}.html"
        latest_path = newsletter_dir / "latest.html"
        dated_path.write_text(web_html, encoding="utf-8")
        shutil.copy2(dated_path, latest_path)

        _git_push(repo_dir, [f"newsletter/{date_str}.html", "newsletter/latest.html"],
                  f"Daily newsletter {date_str}")
        return f"{_PAGES_BASE}/newsletter/{date_str}.html"
    except Exception as e:
        logger.warning(f"Failed to push daily newsletter: {e}")
        return None


def _push_weekly_briefing(briefing_html: str, repo_dir: Path,
                           week_context: dict, is_archive: bool = False) -> Optional[str]:
    """Push weekly briefing page. On Friday (is_archive=True), also saves dated archive copy."""
    logger = logging.getLogger("github_weekly")
    try:
        newsletter_dir = repo_dir / "newsletter"
        newsletter_dir.mkdir(exist_ok=True)
        files = []

        # Always update the "latest" weekly briefing
        latest_path = newsletter_dir / "weekly-latest.html"
        latest_path.write_text(briefing_html, encoding="utf-8")
        files.append("newsletter/weekly-latest.html")

        week_url = f"{_PAGES_BASE}/newsletter/weekly-latest.html"

        if is_archive:
            # Friday: also save a permanent dated copy
            friday_date = week_context["week_end"]  # YYYY-MM-DD
            archived_path = newsletter_dir / f"week-{friday_date}.html"
            archived_path.write_text(briefing_html, encoding="utf-8")
            files.append(f"newsletter/week-{friday_date}.html")
            week_url = f"{_PAGES_BASE}/newsletter/week-{friday_date}.html"

        _git_push(repo_dir, files, f"Weekly briefing {week_context['week_label']}")
        return week_url
    except Exception as e:
        logger.warning(f"Failed to push weekly briefing: {e}")
        return None


def _push_archive_index(archive_html: str, repo_dir: Path) -> Optional[str]:
    """Push the archive index page."""
    logger = logging.getLogger("github_archive")
    try:
        newsletter_dir = repo_dir / "newsletter"
        newsletter_dir.mkdir(exist_ok=True)
        path = newsletter_dir / "archive.html"
        path.write_text(archive_html, encoding="utf-8")
        _git_push(repo_dir, ["newsletter/archive.html"], "Update archive index")
        return f"{_PAGES_BASE}/newsletter/archive.html"
    except Exception as e:
        logger.warning(f"Failed to push archive index: {e}")
        return None


def _push_auxiliary_pages(repo_dir: Path) -> None:
    """Push glossary, director review, cross-state report, and new timelines to GitHub Pages."""
    logger = logging.getLogger("github_aux")
    data_dir = Path(__file__).parent / "data"
    files_to_push = []

    # Pages that live at the root of GitHub Pages
    for src_name, dest_name in [
        ("glossary.html", "glossary.html"),
        ("director_review.html", "director_review.html"),
        ("cross_state_report.html", "cross_state_report.html"),
        ("prop65-timeline.html", "prop65-timeline.html"),
        ("conflict-minerals-timeline.html", "conflict-minerals-timeline.html"),
        ("forced-labor-timeline.html", "forced-labor-timeline.html"),
    ]:
        src = data_dir / src_name
        if src.exists():
            import shutil
            shutil.copy2(src, repo_dir / dest_name)
            files_to_push.append(dest_name)

    if files_to_push:
        try:
            date_str = date.today().isoformat()
            _git_push(repo_dir, files_to_push, f"Update auxiliary pages {date_str}")
            logger.info(f"Pushed auxiliary pages: {files_to_push}")
        except Exception as e:
            logger.warning(f"Failed to push auxiliary pages: {e}")


def _push_calendar_to_github(calendar_html: str, ics_path: Path, repo_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """Push deadline calendar HTML and .ics to GitHub Pages. Returns (html_url, ics_url)."""
    logger = logging.getLogger("calendar")
    try:
        dest_html = repo_dir / "deadlines.html"
        dest_ics = repo_dir / "deadlines.ics"
        dest_html.write_text(calendar_html, encoding="utf-8")
        shutil.copy2(ics_path, dest_ics)
        date_str = date.today().isoformat()
        _git_push(repo_dir, ["deadlines.html", "deadlines.ics"], f"Update deadline calendar {date_str}")
        logger.info("Deadline calendar pushed to GitHub Pages.")
        html_url = f"{_PAGES_BASE}/deadlines.html"
        ics_url = f"{_PAGES_BASE}/deadlines.ics"
        return html_url, ics_url
    except Exception as e:
        logger.warning(f"Failed to push deadline calendar: {e}")
        return None, None


# ── NotebookLM ─────────────────────────────────────────────────────────────

def _sync_notebooklm_weekly(weekly_url: str, archive_weeks: List[dict]) -> None:
    """Sync weekly briefing URL + historical digest to NotebookLM (Fridays only)."""
    logger = logging.getLogger("notebooklm")
    script = Path(__file__).parent / "notebooklm" / "sync_sources.py"

    # Build historical digest text from all archive weeks
    digest_lines = ["COMPLIANCE INTELLIGENCE — HISTORICAL WEEKLY SUMMARIES", "=" * 60, ""]
    for week in archive_weeks:
        digest_lines.append(f"Week of {week['label']} ({week['week_start']} – {week['week_end']})")
        if week.get("weekly_briefing_url"):
            digest_lines.append(f"Briefing: {week['weekly_briefing_url']}")
        digest_lines.append("")
    digest_text = "\n".join(digest_lines)

    try:
        result = subprocess.run(
            ["python3.14", str(script),
             "--weekly-url", weekly_url,
             "--digest", digest_text],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            logger.info("NotebookLM weekly sync complete.")
        else:
            logger.warning(f"NotebookLM sync failed: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logger.warning("NotebookLM sync timed out.")
    except Exception as e:
        logger.warning(f"NotebookLM sync error: {e}")


# ── Maps ───────────────────────────────────────────────────────────────────

def _generate_maps(repo_dir: Path, articles: Optional[List] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Generate PFAS, EPR, and REACH maps (with activity heat) and push to GitHub Pages."""
    logger = logging.getLogger("maps")
    pfas_map_path = None
    epr_map_path = None
    reach_map_path = None

    # Compute activity counts from this week's articles
    us_activity: Optional[dict] = None
    eu_activity: Optional[dict] = None
    if articles:
        try:
            from delivery.map_activity import count_us_state_activity, count_eu_country_activity
            article_dicts = [
                {"title": getattr(a, "title", ""), "snippet": getattr(a, "snippet", "")}
                for a in articles
            ]
            us_activity = count_us_state_activity(article_dicts)
            eu_activity = count_eu_country_activity(article_dicts)
            logger.info(f"Activity counts: {sum(us_activity.values())} US mentions, {sum(eu_activity.values())} EU mentions")
        except Exception as e:
            logger.warning(f"Activity count failed: {e}")

    try:
        pfas_map_path = generate_pfas_map(activity_counts=us_activity)
        logger.info("PFAS map generated.")
    except Exception as e:
        logger.warning(f"PFAS map generation failed: {e}")

    try:
        from delivery.epr_map_generator import generate_epr_map
        epr_map_path = generate_epr_map(activity_counts=us_activity)
        logger.info("EPR map generated.")
    except Exception as e:
        logger.warning(f"EPR map generation failed: {e}")

    try:
        from delivery.reach_map_generator import generate_reach_map
        reach_map_path = generate_reach_map(activity_counts=eu_activity)
        logger.info("REACH map generated.")
    except Exception as e:
        logger.warning(f"REACH map generation failed: {e}")

    # Generate Excel exports
    excel_paths: dict = {}
    try:
        from delivery.excel_exporter import generate_pfas_excel, generate_epr_excel, generate_reach_excel
        excel_paths["pfas"] = generate_pfas_excel(activity_counts=us_activity)
        excel_paths["epr"] = generate_epr_excel(activity_counts=us_activity)
        excel_paths["reach"] = generate_reach_excel(activity_counts=eu_activity)
        logger.info("Excel exports generated.")
    except Exception as e:
        logger.warning(f"Excel generation failed: {e}")

    # Generate deadline timelines (all topics + combined)
    try:
        from delivery.timeline_generator import generate_all_timelines
        generate_all_timelines()
        logger.info("Deadline timelines generated.")
    except Exception as e:
        logger.warning(f"Timeline generation failed: {e}")

    if pfas_map_path:
        pfas_url, epr_url, reach_url = _push_maps_to_github(
            pfas_map_path, epr_map_path, reach_map_path, repo_dir,
            excel_paths=excel_paths,
        )
        return pfas_url, epr_url, reach_url
    return None, None, None


# ── LegiScan weekly gate ────────────────────────────────────────────────────

def _run_legiscan_if_due(today: date) -> None:
    """Run LegiScan full pull on Mondays, or if it hasn't run in 7+ days."""
    logger = logging.getLogger("legiscan_gate")
    import sqlite3
    try:
        conn = sqlite3.connect(str(Config.DB_PATH))
        row = conn.execute(
            "SELECT MAX(last_updated) as last_run FROM legiscan_bills"
        ).fetchone()
        conn.close()
        last_run_str = row[0] if row and row[0] else None
        last_run = date.fromisoformat(last_run_str[:10]) if last_run_str else None
    except Exception:
        last_run = None

    is_monday = today.weekday() == 0
    days_since = (today - last_run).days if last_run else 999

    if not is_monday and days_since < 7:
        logger.info(
            f"LegiScan: skipping (last run {days_since}d ago, not Monday)"
        )
        return

    reason = "Monday" if is_monday else f"{days_since}d since last run"
    logger.info(f"LegiScan: running full pull ({reason})…")
    try:
        tracker = LegiScanTracker()
        report = tracker.run()
        tracker.close()
        logger.info(
            f"LegiScan complete: {report['total_tracked']} bills, "
            f"{len(report['new_bills'])} new, {report['api_calls']} API calls"
        )
    except Exception as e:
        logger.warning(f"LegiScan pull failed (non-fatal): {e}")


# ── Dashboard ───────────────────────────────────────────────────────────────

def _push_dashboard(dashboard_html: str, repo_dir: Path) -> Optional[str]:
    """Push dashboard.html to GitHub Pages and set it as index. Returns URL."""
    logger = logging.getLogger("github_dashboard")
    try:
        dest = repo_dir / "dashboard.html"
        dest.write_text(dashboard_html, encoding="utf-8")
        # index.html = instant redirect so root URL lands on the dashboard
        index_redirect = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8">'
            '<meta http-equiv="refresh" content="0;url=dashboard.html">'
            '<title>Compliance Intelligence Dashboard</title></head>'
            '<body><a href="dashboard.html">Go to dashboard</a></body></html>'
        )
        (repo_dir / "index.html").write_text(index_redirect, encoding="utf-8")
        date_str = date.today().isoformat()
        _git_push(repo_dir, ["dashboard.html", "index.html"], f"Update dashboard {date_str}")
        url = f"{_PAGES_BASE}/dashboard.html"
        logger.info(f"Dashboard pushed: {url}")
        return url
    except Exception as e:
        logger.warning(f"Failed to push dashboard: {e}")
        return None


# ── Main pipeline ──────────────────────────────────────────────────────────

def run_pipeline(args: argparse.Namespace) -> None:
    logger = logging.getLogger("run")
    today = date.fromisoformat(args.week_of) if args.week_of else date.today()
    week_context = get_week_context(today)
    is_friday = week_context["is_friday"]
    is_finalize = args.finalize_week

    logger.info("=" * 60)
    logger.info(f"Compliance Intelligence — {week_context['today_name']}, week of {week_context['week_label']}")
    logger.info(f"Mode: {'finalize-week' if is_finalize else 'dry-run' if args.dry_run else 'preview' if args.preview else 'no-email' if args.no_email else 'full'}")

    init_db()

    # Seed regulation registry (idempotent — only adds missing rows)
    try:
        from processors.regulation_registry import seed_all
        from subscribers.db import get_regulation_count
        if get_regulation_count() < 10:
            logger.info("Regulation registry empty — seeding known regulations…")
            result = seed_all()
            logger.info(
                f"Registry seeded: {result['regulations_after']} regulations "
                f"({result['new_regulations']} new)"
            )
        else:
            logger.debug(f"Regulation registry: {get_regulation_count()} regulations already seeded")
    except Exception as e:
        logger.warning(f"Regulation registry seed failed (non-fatal): {e}")

    # Deadline watchdog (deduplicate DB + compute threshold status)
    try:
        from processors.deadline_watchdog import run_watchdog
        watchdog = run_watchdog(as_of=today)
        logger.info(
            f"Deadlines: {watchdog['total']} total, "
            f"{watchdog['critical_count']} critical/urgent/overdue"
        )
    except Exception as e:
        logger.warning(f"Deadline watchdog failed (non-fatal): {e}")
        watchdog = None

    # LegiScan weekly pull (Mondays, or if overdue)
    _run_legiscan_if_due(today)

    # Cross-state pattern analysis (weekly on Mondays, or --cross-state flag)
    if week_context["is_monday"] or args.cross_state:
        try:
            from ai.cross_state_agent import run_cross_state_analysis
            logger.info("Cross-state analysis: running weekly…")
            run_cross_state_analysis(force=args.cross_state)
        except Exception as e:
            logger.warning(f"Cross-state analysis failed (non-fatal): {e}")

    # Glossary: seed on first run, or rebuild on --glossary flag
    if args.glossary:
        try:
            from ai.glossary_agent import run_glossary_agent
            logger.info("Glossary: rebuilding…")
            run_glossary_agent()
            import subprocess, sys
            subprocess.Popen([sys.executable, "-c",
                "import webbrowser; webbrowser.open('data/glossary.html')"])
        except Exception as e:
            logger.warning(f"Glossary build failed (non-fatal): {e}")

    # Monday check: warn if last week's archive is missing
    if week_context["is_monday"] and not last_week_is_archived():
        logger.warning("Last week's archive not found. Consider running: python run.py --finalize-week")
        try:
            GmailSender().send_missing_archive_warning(week_context["week_label"])
        except Exception:
            pass

    # Step 1: Scrape
    logger.info("Step 1: Scraping sources…")
    articles = scrape_all()
    logger.info(f"Scraping complete: {len(articles)} relevant articles")

    # Apply weekly window (Sat–Fri)
    articles, new_count, carried_count = apply_weekly_window(articles)
    logger.info(f"Weekly window: {new_count} new, {carried_count} carried-over ({len(articles)} total)")

    # Step 2: AI pipeline
    logger.info("Step 2: Running AI summarization pipeline…")
    summarizer = Summarizer()
    pipeline_output = summarizer.run(articles, week_context=week_context)

    # Step 2b: Extract new regulations from this week's articles (lightweight, no Claude call)
    try:
        from processors.regulation_registry import extract_from_pipeline
        n_extracted = extract_from_pipeline(pipeline_output.get("topics", []))
        if n_extracted:
            logger.info(f"Regulation registry: {n_extracted} records updated from articles")
    except Exception as e:
        logger.warning(f"Regulation extraction failed (non-fatal): {e}")

    # Step 2c: Update abbreviation glossary from this week's articles
    try:
        from ai.glossary_agent import run_glossary_agent
        run_glossary_agent(pipeline_output=pipeline_output)
    except Exception as e:
        logger.warning(f"Glossary update failed (non-fatal): {e}")

    # Step 2d: Change detection
    daily_changes = []
    try:
        from processors.change_detector import detect_and_save
        daily_changes = detect_and_save(pipeline_output, run_date=today)
        logger.info(f"Change detection: {len(daily_changes)} change(s) recorded")
    except Exception as e:
        logger.warning(f"Change detection failed (non-fatal): {e}")

    # Step 2d: Director's critique (daily — writes to data/director_review.html)
    try:
        from ai.director_agent import run_director_critique
        run_director_critique(
            pipeline_output,
            watchdog=watchdog,
            daily_changes=daily_changes,
        )
    except Exception as e:
        logger.warning(f"Director critique failed (non-fatal): {e}")

    if args.dry_run:
        print("\n" + "=" * 60)
        print(f"DRY RUN — Weekly Briefing ({week_context['today_name']}, week of {week_context['week_label']}):")
        print(pipeline_output["exec_summary"])
        print("\nTopics:")
        for ts in pipeline_output["topics"]:
            devs = ts.get("developments", [])
            print(f"  {ts['topic']}: {len(devs)} development(s)")
            for d in devs:
                print(f"    [{d.get('urgency')}] {d.get('headline')}")
        print(f"\nTotal articles: {pipeline_output['total_articles']}")
        return

    # Step 3: Render
    logger.info("Step 3: Rendering…")
    renderer = NewsletterRenderer()
    archive_weeks = get_archive_weeks()
    archive_url = f"{_PAGES_BASE}/newsletter/archive.html"

    if args.preview:
        ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        data_dir = Config.DATA_DIR

        # Render weekly briefing page
        briefing_html = renderer.render_weekly_briefing(
            pipeline_output, newsletter_url=None, week_context=week_context,
        )
        briefing_path = data_dir / f"preview_weekly_{ts}.html"
        briefing_path.write_text(briefing_html, encoding="utf-8")

        # Render web newsletter (main page)
        web_html = renderer.render(
            pipeline_output, map_url=None, is_web_version=True,
            exec_summary_url=f"file://{briefing_path.resolve()}",
            week_context=week_context, archive_weeks=archive_weeks, archive_url=archive_url,
        )
        web_path = data_dir / f"preview_web_{ts}.html"
        web_path.write_text(web_html, encoding="utf-8")

        # Re-render weekly briefing with back-link to web version
        briefing_html = renderer.render_weekly_briefing(
            pipeline_output,
            newsletter_url=f"file://{web_path.resolve()}",
            week_context=week_context,
        )
        briefing_path.write_text(briefing_html, encoding="utf-8")

        # Render email version
        email_html = renderer.render(
            pipeline_output, subscriber_name="Ryan", map_url=None,
            exec_summary_url=f"file://{briefing_path.resolve()}",
            week_context=week_context, archive_weeks=archive_weeks, archive_url=archive_url,
        )
        email_path = data_dir / f"preview_email_{ts}.html"
        email_path.write_text(email_html, encoding="utf-8")

        # Render archive index
        archive_html = renderer.render_archive_index(archive_weeks)
        archive_path = data_dir / f"preview_archive_{ts}.html"
        archive_path.write_text(archive_html, encoding="utf-8")

        # Render dashboard
        from processors.deadline_watchdog import run_watchdog, enrich_deadlines
        try:
            wdg = run_watchdog(as_of=today)
            deadlines_preview = wdg["enriched"][:30]
        except Exception:
            deadlines_preview = get_upcoming_deadlines(days_ahead=180)
        dashboard_html = renderer.render_dashboard(
            pipeline_output, week_context=week_context,
            archive_weeks=archive_weeks, deadlines=deadlines_preview,
            daily_changes=daily_changes,
        )
        dashboard_path = data_dir / f"preview_dashboard_{ts}.html"
        dashboard_path.write_text(dashboard_html, encoding="utf-8")

        webbrowser.open(f"file://{dashboard_path.resolve()}")
        print(f"Dashboard:       {dashboard_path}")
        print(f"Web version:     {web_path}")
        print(f"Weekly briefing: {briefing_path}")
        print(f"Email version:   {email_path}")
        print(f"Archive index:   {archive_path}")

        # Director critique — runs automatically during preview, opens alongside dashboard
        try:
            from ai.director_agent import run_director_critique
            logger.info("Running director critique for preview…")
            critique = run_director_critique(
                pipeline_output,
                watchdog=watchdog,
                daily_changes=daily_changes,
                force=True,  # always refresh during preview/dev
            )
            review_path = Config.DATA_DIR / "director_review.html"
            if review_path.exists():
                print(f"Director review: {review_path}")
        except Exception as e:
            logger.warning(f"Director critique skipped in preview: {e}")

        return

    # Step 3b: Generate maps (Fridays and --finalize-week only)
    # Default to URL only if the file already exists in the GitHub Pages repo
    pfas_map_url = f"{_PAGES_BASE}/" if (_GITHUB_REPO_DIR / "index.html").exists() else None
    epr_map_url = f"{_PAGES_BASE}/epr-map.html" if (_GITHUB_REPO_DIR / "epr-map.html").exists() else None
    reach_map_url = f"{_PAGES_BASE}/reach-map.html" if (_GITHUB_REPO_DIR / "reach-map.html").exists() else None
    if is_friday or is_finalize:
        logger.info("Step 3b: Generating and pushing state maps…")
        pfas_map_url, epr_map_url, reach_map_url = _generate_maps(_GITHUB_REPO_DIR, articles=articles)

    # Step 3c: Publish to GitHub Pages
    logger.info("Step 3c: Publishing to GitHub Pages…")

    # Daily newsletter web version
    web_html = renderer.render(
        pipeline_output, map_url=pfas_map_url, epr_map_url=epr_map_url, reach_map_url=reach_map_url,
        is_web_version=True, week_context=week_context,
        archive_weeks=archive_weeks, archive_url=archive_url,
    )
    newsletter_url = _push_daily_newsletter(web_html, _GITHUB_REPO_DIR)

    # Weekly briefing page (updated daily, archived on Friday)
    briefing_html = renderer.render_weekly_briefing(
        pipeline_output,
        newsletter_url=newsletter_url,
        week_context=week_context,
    )
    weekly_briefing_url = _push_weekly_briefing(
        briefing_html, _GITHUB_REPO_DIR, week_context,
        is_archive=(is_friday or is_finalize),
    )

    # Dashboard — rendered and pushed every day
    logger.info("Step 3c-dash: Rendering and pushing dashboard…")
    try:
        deadlines_dash = (
            watchdog["enriched"][:30]
            if watchdog else get_upcoming_deadlines(days_ahead=180)
        )
        # Merge in bill action dates so the calendar shows legislative activity
        bill_events = get_bill_calendar_events(days_past=30, days_ahead=180)
        existing_keys = {(d.get("topic",""), d.get("deadline_date","")) for d in deadlines_dash}
        for be in bill_events:
            if (be["topic"], be["deadline_date"]) not in existing_keys:
                deadlines_dash = list(deadlines_dash) + [be]
        deadlines_dash.sort(key=lambda d: d.get("deadline_date", ""))
        dashboard_html = renderer.render_dashboard(
            pipeline_output, week_context=week_context,
            archive_weeks=archive_weeks, deadlines=deadlines_dash,
            calendar_url=calendar_url, daily_changes=daily_changes,
        )
        _push_dashboard(dashboard_html, _GITHUB_REPO_DIR)
        _push_auxiliary_pages(_GITHUB_REPO_DIR)
    except Exception as e:
        logger.warning(f"Dashboard render/push failed (non-fatal): {e}")

    # Friday / finalize: save archive entry and push archive index
    if is_friday or is_finalize:
        save_archive_week(
            week_start=week_context["week_start"],
            week_end=week_context["week_end"],
            label=week_context["week_label"],
            year=week_context["year"],
            newsletter_url=newsletter_url,
            weekly_briefing_url=weekly_briefing_url,
        )
        archive_weeks = get_archive_weeks()  # Reload with new entry
        archive_html = renderer.render_archive_index(archive_weeks)
        archive_url = _push_archive_index(archive_html, _GITHUB_REPO_DIR)
        logger.info(f"End-of-week archive saved: week of {week_context['week_label']}")

    # Step 3d: Generate deadline calendar (Fridays and --finalize-week only)
    calendar_url: Optional[str] = (
        f"{_PAGES_BASE}/deadlines.html"
        if (_GITHUB_REPO_DIR / "deadlines.html").exists()
        else None
    )
    if is_friday or is_finalize:
        logger.info("Step 3d: Generating deadline calendar…")
        deadlines = get_upcoming_deadlines(days_ahead=365)
        deadlines = list(deadlines) + get_bill_calendar_events(days_past=30, days_ahead=365)
        deadlines.sort(key=lambda d: d.get("deadline_date", ""))
        if deadlines:
            ics_path = generate_ics(deadlines)
            ics_url = f"{_PAGES_BASE}/deadlines.ics"
            calendar_html = renderer.render_deadline_calendar(deadlines, ics_url=ics_url)
            calendar_url, _ = _push_calendar_to_github(calendar_html, ics_path, _GITHUB_REPO_DIR)

    # Update web version with exec_summary_url and archive now that we have the URL
    web_html = renderer.render(
        pipeline_output, map_url=pfas_map_url, epr_map_url=epr_map_url, reach_map_url=reach_map_url,
        is_web_version=True, exec_summary_url=weekly_briefing_url,
        week_context=week_context, archive_weeks=archive_weeks, archive_url=archive_url,
        calendar_url=calendar_url,
    )

    # Step 4: Send emails
    if args.no_email:
        logger.info("Step 4: Skipped (--no-email)")
        logger.info(f"Done. Sent: 0, Skipped: all (--no-email)")
        logger.info("=" * 60)
        return

    sender = GmailSender()
    dash_url = f"{_PAGES_BASE}/dashboard.html"
    date_display = today.strftime("%B %-d, %Y")
    sent_count = 0
    skip_count = 0

    if args.test_email:
        logger.info(f"Step 4: Sending TEST emails to {args.test_email}…")
        for email in args.test_email:
            name = email.split("@")[0].split(".")[0].title()
            success = sender.send_dashboard_notification(email, name, dash_url, date_display)
            if success:
                sent_count += 1
    else:
        logger.info("Step 4: Sending dashboard notification emails to subscribers…")
        repo = SubscriberRepository()
        subscribers = repo.list_active(include_scheduled_only=not args.force)

        if not subscribers:
            logger.warning("No active subscribers.")
        else:
            for sub in subscribers:
                if not args.force and repo.already_sent_today(sub.id):
                    skip_count += 1
                    continue
                success = sender.send_dashboard_notification(
                    sub.email, sub.first_name, dash_url, date_display
                )
                if success:
                    repo.log_send(sub.id, "success")
                    sent_count += 1
                else:
                    repo.log_send(sub.id, "failure", "Gmail send failed")

    logger.info(f"Done. Sent: {sent_count}, Skipped: {skip_count}")

    # Step 5: NotebookLM sync (Fridays only)
    if (is_friday or is_finalize) and weekly_briefing_url:
        logger.info("Step 5: Syncing to NotebookLM…")
        _sync_notebooklm_weekly(weekly_briefing_url, get_archive_weeks())

    logger.info("=" * 60)


def main() -> None:
    args = parse_args()
    setup_logging(Config.LOG_LEVEL)

    # --send-reminder: send Friday reminder email and exit
    if args.send_reminder:
        logging.getLogger("reminder").info("Sending Friday reminder email…")
        from processors.week_tracker import get_week_context
        ctx = get_week_context()
        try:
            GmailSender().send_friday_reminder(ctx["week_label"])
            logging.getLogger("reminder").info("Reminder sent.")
        except Exception as e:
            logging.getLogger("reminder").error(f"Reminder failed: {e}")
        return

    if args.director_review:
        _run_director_review_standalone()
        return

    run_pipeline(args)


def _run_director_review_standalone() -> None:
    """Run director critique on-demand and open the HTML report."""
    logger = logging.getLogger("director")
    init_db()
    logger.info("Running director critique (forced)…")

    # Get latest pipeline output from cache if available, otherwise use minimal stub
    try:
        cache_dir = Config.DATA_DIR / "cache" / "claude"
        import glob as _glob
        cache_files = sorted(_glob.glob(str(cache_dir / "s3_*.json")), reverse=True)
        if cache_files:
            import json as _json
            with open(cache_files[0]) as f:
                pipeline_output = _json.load(f)
        else:
            pipeline_output = {"topics": [], "exec_summary": "", "total_articles": 0, "total_sources": 0}
    except Exception:
        pipeline_output = {"topics": [], "exec_summary": "", "total_articles": 0, "total_sources": 0}

    try:
        from processors.deadline_watchdog import run_watchdog
        watchdog = run_watchdog()
    except Exception:
        watchdog = None

    from ai.director_agent import run_director_critique
    critique = run_director_critique(pipeline_output, watchdog=watchdog, force=True)

    report_path = Config.DATA_DIR / "director_review.html"
    if report_path.exists():
        webbrowser.open(f"file://{report_path.resolve()}")
        print(f"Director review: {report_path}")
    else:
        print("Director critique complete — check logs for output")


if __name__ == "__main__":
    main()
