#!/usr/bin/env python3
"""
Andersen Compliance Intelligence — Main entry point.

Usage:
    python run.py               # Full run: scrape → filter → summarize → render → send
    python run.py --dry-run     # Scrape + summarize, print output, no email
    python run.py --preview     # Render to HTML file and open in browser
    python run.py --force       # Skip already-sent-today check
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path when run as script
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import Config
from scrapers.federal_register import FederalRegisterScraper
from scrapers.epa import EPAScraper
from scrapers.echa import ECHAScraper
from scrapers.minnesota_mpca import MinnesotaMPCAScraper
from scrapers.state_agencies import StateAgenciesScraper
from processors.deduplicator import deduplicate
from processors.relevance_filter import keyword_filter
from ai.summarizer import Summarizer
from newsletter.renderer import NewsletterRenderer
from delivery.sendgrid_sender import SendGridSender
from delivery.preview import open_preview
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
    parser = argparse.ArgumentParser(description="Andersen Compliance Intelligence")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and summarize, print output, no email sent")
    parser.add_argument("--preview", action="store_true",
                        help="Render HTML and open in browser, no email sent")
    parser.add_argument("--force", action="store_true",
                        help="Send even if already sent today")
    return parser.parse_args()


def scrape_all() -> list:
    """Run all scrapers and return deduplicated, keyword-filtered articles."""
    logger = logging.getLogger("scraper")
    scrapers = [
        FederalRegisterScraper(),
        EPAScraper(),
        ECHAScraper(),
        MinnesotaMPCAScraper(),
        StateAgenciesScraper(),
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
    logger.info("Andersen Compliance Intelligence — starting run")
    logger.info(f"Mode: {'dry-run' if args.dry_run else 'preview' if args.preview else 'full'}")

    # Initialize DB
    init_db()

    # Step 1: Scrape
    logger.info("Step 1: Scraping sources…")
    articles = scrape_all()
    logger.info(f"Scraping complete: {len(articles)} relevant articles")

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
        # Render with default subscriber name and open in browser
        html = renderer.render(pipeline_output, subscriber_name="Ryan")
        preview_path = open_preview(html)
        logger.info(f"Preview saved to: {preview_path}")
        print(f"Preview opened: {preview_path}")
        return

    # Step 4: Send to all active subscribers
    logger.info("Step 4: Sending emails…")
    repo = SubscriberRepository()
    sender = SendGridSender()
    subscribers = repo.list_active()

    if not subscribers:
        logger.warning("No active subscribers. Add one with: python subscribers/cli.py add")
        return

    subject = SendGridSender.subject_for_date()
    sent_count = 0
    skip_count = 0

    for sub in subscribers:
        if not args.force and repo.already_sent_today(sub.id):
            logger.info(f"Skipping {sub.email} — already sent today")
            skip_count += 1
            continue

        html = renderer.render(pipeline_output, subscriber_name=sub.first_name)
        success = sender.send(sub.email, subject, html)

        if success:
            repo.log_send(sub.id, "success")
            sent_count += 1
            logger.info(f"Sent to {sub.email}")
        else:
            repo.log_send(sub.id, "failure", "SendGrid send failed")
            logger.error(f"Failed to send to {sub.email}")

    logger.info(f"Done. Sent: {sent_count}, Skipped (already sent): {skip_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    # Catch-up logic: if this is the morning run and already sent today, exit cleanly
    main()
