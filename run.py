#!/usr/bin/env python3
"""
Compliance Intelligence — Main entry point.

Usage:
    python run.py               # Full run: scrape → filter → summarize → render → send
    python run.py --dry-run     # Scrape + summarize, print output, no email
    python run.py --preview     # Render to HTML file and open in browser
    python run.py --force       # Skip already-sent-today check
"""
import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path when run as script
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
from processors.deduplicator import deduplicate
from processors.relevance_filter import keyword_filter
from ai.summarizer import Summarizer
from newsletter.renderer import NewsletterRenderer
from delivery.gmail_sender import GmailSender
from delivery.preview import open_preview
from delivery.state_map_generator import generate_pfas_map
from subscribers.db import init_db
from subscribers.repository import SubscriberRepository


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compliance Intelligence")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and summarize, print output, no email sent")
    parser.add_argument("--preview", action="store_true",
                        help="Render HTML and open in browser, no email sent")
    parser.add_argument("--force", action="store_true",
                        help="Send even if already sent today")
    parser.add_argument("--test-email", action="append", default=[],
                        help="Send only to these addresses (repeatable, skips subscriber list)")
    return parser.parse_args()


_SENT_ARTICLES_PATH = Path(__file__).parent / "data" / "sent_articles.json"
_ROLLING_WINDOW_DAYS = 5


def _load_sent_history() -> dict:
    """Returns {article_id: first_sent_iso} dict. Migrates old list format automatically."""
    if not _SENT_ARTICLES_PATH.exists():
        return {}
    data = json.loads(_SENT_ARTICLES_PATH.read_text())
    if isinstance(data, list):
        # Migrate: old format was a plain list of IDs — treat all as sent today
        now = datetime.now(timezone.utc).isoformat()
        return {id_: now for id_ in data}
    return data


def _save_sent_history(history: dict) -> None:
    _SENT_ARTICLES_PATH.write_text(json.dumps(history, indent=2, sort_keys=True))


def _apply_rolling_window(articles: list, history: dict) -> tuple:
    """
    Filter articles to the rolling window and mark each as new or carried-over.

    - New articles (not in history): marked is_new=True, added to history.
    - Carried-over articles (in history, within window): marked is_new=False with age.
    - Expired articles (older than ROLLING_WINDOW_DAYS): dropped.

    Returns (filtered_articles, updated_history).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_ROLLING_WINDOW_DAYS)
    result = []

    for article in articles:
        if article.id in history:
            first_sent = datetime.fromisoformat(history[article.id])
            if first_sent.tzinfo is None:
                first_sent = first_sent.replace(tzinfo=timezone.utc)
            if first_sent < cutoff:
                continue  # Expired — drop it
            days_ago = (now - first_sent).days
            article.extra["is_new"] = False
            article.extra["days_in_newsletter"] = days_ago
        else:
            history[article.id] = now.isoformat()
            article.extra["is_new"] = True
            article.extra["days_in_newsletter"] = 0

        result.append(article)

    return result, history


def _push_map_to_github(map_path: Path, repo_dir: Path) -> None:
    """Copy the map to the local GitHub Pages repo clone and push."""
    logger = logging.getLogger("github_map")
    try:
        import shutil
        dest = repo_dir / "index.html"
        shutil.copy2(map_path, dest)
        cmds = [
            ["git", "-C", str(repo_dir), "add", "index.html"],
            ["git", "-C", str(repo_dir), "commit", "-m", f"Update PFAS map {datetime.now().strftime('%Y-%m-%d')}"],
            ["git", "-C", str(repo_dir), "push"],
        ]
        for cmd in cmds:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "nothing to commit" not in result.stdout:
                logger.warning(f"Git command failed: {' '.join(cmd)}: {result.stderr.strip()}")
                return
        logger.info("PFAS map pushed to GitHub Pages.")
    except Exception as e:
        logger.warning(f"Failed to push map to GitHub: {e}")


def _push_newsletter_to_github(html: str, repo_dir: Path):
    """Save the web version HTML to the GitHub Pages repo and push. Returns the URL."""
    logger = logging.getLogger("github_newsletter")
    try:
        import shutil

        # Create newsletter directory if needed
        newsletter_dir = repo_dir / "newsletter"
        newsletter_dir.mkdir(exist_ok=True)

        # Save date-based version and latest copy
        date_str = datetime.now().strftime("%Y-%m-%d")
        dated_path = newsletter_dir / f"{date_str}.html"
        latest_path = newsletter_dir / "latest.html"

        dated_path.write_text(html, encoding="utf-8")
        shutil.copy2(dated_path, latest_path)

        cmds = [
            ["git", "-C", str(repo_dir), "add", f"newsletter/{date_str}.html", "newsletter/latest.html"],
            ["git", "-C", str(repo_dir), "commit", "-m", f"Update newsletter {date_str}"],
            ["git", "-C", str(repo_dir), "push"],
        ]
        for cmd in cmds:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 and "nothing to commit" not in result.stdout:
                logger.warning(f"Git command failed: {' '.join(cmd)}: {result.stderr.strip()}")
                # Still return URL even if push fails — the file exists locally
                return f"https://ryan-jenkinson.github.io/compliance-maps/newsletter/{date_str}.html"
        logger.info("Newsletter web version pushed to GitHub Pages.")
        return f"https://ryan-jenkinson.github.io/compliance-maps/newsletter/{date_str}.html"
    except Exception as e:
        logger.warning(f"Failed to push newsletter to GitHub: {e}")
        return None


def _sync_notebooklm(urls: list) -> None:
    """Fire-and-forget: sync article URLs into NotebookLM in a subprocess."""
    logger = logging.getLogger("notebooklm")
    script = Path(__file__).parent / "notebooklm" / "sync_sources.py"
    try:
        result = subprocess.run(
            ["python3.14", str(script)] + urls,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("NotebookLM sync complete.")
        else:
            logger.warning(f"NotebookLM sync exited with code {result.returncode}: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logger.warning("NotebookLM sync timed out (sources may still process in background).")
    except Exception as e:
        logger.warning(f"NotebookLM sync failed: {e}")


def scrape_all() -> list:
    """Run all scrapers and return deduplicated, keyword-filtered articles."""
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
    logger.info(f"Total after dedup: {len(articles)}")
    articles = keyword_filter(articles)
    logger.info(f"Total after keyword filter: {len(articles)}")
    return articles


def main() -> None:
    args = parse_args()
    setup_logging(Config.LOG_LEVEL)
    logger = logging.getLogger("run")

    logger.info("=" * 60)
    logger.info("Compliance Intelligence — starting run")
    logger.info(f"Mode: {'dry-run' if args.dry_run else 'preview' if args.preview else 'full'}")

    # Initialize DB
    init_db()

    # Generate PFAS state map and push to GitHub Pages
    _GITHUB_PAGES_URL = "https://ryan-jenkinson.github.io/compliance-maps/"
    _GITHUB_REPO_DIR = Path("/tmp/compliance-maps")
    logger.info("Generating PFAS state map…")
    try:
        pfas_map_path = generate_pfas_map()
        pfas_map_url = _GITHUB_PAGES_URL
        # Push updated map to GitHub Pages
        _push_map_to_github(pfas_map_path, _GITHUB_REPO_DIR)
    except Exception as e:
        logger.warning(f"PFAS map generation failed: {e}")
        pfas_map_url = None

    # Step 1: Scrape
    logger.info("Step 1: Scraping sources…")
    articles = scrape_all()
    logger.info(f"Scraping complete: {len(articles)} relevant articles")

    # Rolling window: keep articles from last 5 days, mark new vs carried-over
    sent_history = _load_sent_history()
    articles, sent_history = _apply_rolling_window(articles, sent_history)
    new_count = sum(1 for a in articles if a.extra.get("is_new"))
    carried_count = len(articles) - new_count
    logger.info(f"Rolling window: {new_count} new, {carried_count} carried-over ({len(articles)} total)")

    # Step 2: AI pipeline
    logger.info("Step 2: Running AI summarization pipeline…")
    summarizer = Summarizer()
    pipeline_output = summarizer.run(articles)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — Executive Summary:")
        print(pipeline_output["exec_summary"])
        print("\nTopics:")
        for ts in pipeline_output["topics"]:
            devs = ts.get("developments", [])
            print(f"  {ts['topic']}: {len(devs)} development(s)")
            for d in devs:
                print(f"    [{d.get('urgency')}] {d.get('headline')}")
        print(f"\nTotal articles: {pipeline_output['total_articles']}")
        print(f"Total sources: {pipeline_output['total_sources']}")
        return

    # Step 3: Render
    logger.info("Step 3: Rendering newsletter…")
    renderer = NewsletterRenderer()

    if args.preview:
        from delivery.preview import save_preview
        d = datetime.now()

        # Render web preview (interactive, with JS)
        web_html = renderer.render(pipeline_output, map_url=pfas_map_url, is_web_version=True)
        web_filename = f"preview_web_{d.strftime('%Y-%m-%d_%H%M%S')}.html"
        web_preview_path = Config.DATA_DIR / web_filename
        web_preview_path.write_text(web_html, encoding="utf-8")

        # Render email preview (full content, no JS)
        email_html = renderer.render(
            pipeline_output, subscriber_name="Ryan", map_url=pfas_map_url,
        )
        email_filename = f"preview_email_{d.strftime('%Y-%m-%d_%H%M%S')}.html"
        email_preview_path = Config.DATA_DIR / email_filename
        email_preview_path.write_text(email_html, encoding="utf-8")

        import webbrowser
        webbrowser.open(f"file://{web_preview_path.resolve()}")

        logger.info(f"Web version preview: {web_preview_path}")
        logger.info(f"Email version preview: {email_preview_path}")
        print(f"Web version (interactive): {web_preview_path}")
        print(f"Email version (full content): {email_preview_path}")
        return

    # Step 3b: Render and push web version to GitHub Pages
    logger.info("Step 3b: Publishing web version to GitHub Pages…")
    web_html = renderer.render(pipeline_output, map_url=pfas_map_url, is_web_version=True)
    _push_newsletter_to_github(web_html, _GITHUB_REPO_DIR)

    # Step 4: Send emails
    sender = GmailSender()
    subject = GmailSender.subject_for_date()
    sent_count = 0
    skip_count = 0

    if args.test_email:
        # --test-email mode: send to specific addresses, skip subscriber list entirely
        logger.info(f"Step 4: Sending TEST emails to {args.test_email}…")
        for email in args.test_email:
            name = email.split("@")[0].split(".")[0].title()
            html = renderer.render(
                pipeline_output, subscriber_name=name, map_url=pfas_map_url,
            )
            success = sender.send(email, f"[TEST] {subject}", html)
            if success:
                sent_count += 1
                logger.info(f"Test sent to {email}")
            else:
                logger.error(f"Failed to send test to {email}")
    else:
        logger.info("Step 4: Sending emails to subscribers…")
        repo = SubscriberRepository()
        subscribers = repo.list_active(include_scheduled_only=not args.force)

        if not subscribers:
            logger.warning("No active subscribers. Add one with: python subscribers/cli.py add")
            return

        for sub in subscribers:
            if not args.force and repo.already_sent_today(sub.id):
                logger.info(f"Skipping {sub.email} — already sent today")
                skip_count += 1
                continue

            html = renderer.render(
                pipeline_output, subscriber_name=sub.first_name, map_url=pfas_map_url,
            )
            success = sender.send(sub.email, subject, html)

            if success:
                repo.log_send(sub.id, "success")
                sent_count += 1
                logger.info(f"Sent to {sub.email}")
            else:
                repo.log_send(sub.id, "failure", "Gmail send failed")
                logger.error(f"Failed to send to {sub.email}")

    logger.info(f"Done. Sent: {sent_count}, Skipped (already sent): {skip_count}")

    # Save updated rolling window history
    if sent_count > 0:
        _save_sent_history(sent_history)
        logger.info(f"Rolling window history updated ({len(sent_history)} total entries)")

    # Sync article URLs into persistent NotebookLM notebook (non-blocking)
    article_urls = [a.url for a in articles if a.url]
    if article_urls:
        logger.info("Step 5: Syncing sources to NotebookLM…")
        _sync_notebooklm(article_urls)

    logger.info("=" * 60)


if __name__ == "__main__":
    # Catch-up logic: if this is the morning run and already sent today, exit cleanly
    main()
