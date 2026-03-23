"""Jinja2 rendering + premailer CSS inlining."""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import premailer
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_topic_colors() -> dict[str, str]:
    import yaml
    path = Path(__file__).parent.parent / "config" / "topics.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return {t["name"]: t["color"] for t in data["topics"]}


def _load_topic_labels() -> dict[str, str]:
    import yaml
    path = Path(__file__).parent.parent / "config" / "topics.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return {t["name"]: t["label"] for t in data["topics"]}


def _parse_fun_fact(exec_summary_text: str) -> tuple[str, str]:
    """Split exec_summary text into (main_content, fun_fact).

    Returns (text_without_fun_fact, fun_fact_text).
    """
    if "[FUN FACT]" not in exec_summary_text:
        return exec_summary_text, ""
    parts = exec_summary_text.split("[FUN FACT]", 1)
    return parts[0].strip(), parts[1].strip()


class NewsletterRenderer:
    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        self._colors = _load_topic_colors()
        self._labels = _load_topic_labels()

    def _enrich_topics(self, pipeline_output: dict) -> list[dict]:
        enriched_topics = []
        for ts in pipeline_output["topics"]:
            enriched = dict(ts)
            enriched["color"] = self._colors.get(ts["topic"], "#718096")
            enriched["label"] = self._labels.get(ts["topic"], ts["topic"])
            enriched_topics.append(enriched)
        return enriched_topics

    def render(
        self,
        pipeline_output: dict,
        subscriber_name: str = "Ryan",
        inline_css: bool = True,
        map_url: Optional[str] = None,
        epr_map_url: Optional[str] = None,
        reach_map_url: Optional[str] = None,
        is_web_version: bool = False,
        exec_summary_url: Optional[str] = None,
        week_context: Optional[dict] = None,
        archive_weeks: Optional[List[dict]] = None,
        archive_url: Optional[str] = None,
        calendar_url: Optional[str] = None,
    ) -> str:
        now = datetime.now()
        ctx = week_context or {}
        date_display = now.strftime("%B %-d, %Y")
        week_label = ctx.get("week_label", "")
        today_name = ctx.get("today_name", now.strftime("%A"))
        enriched_topics = self._enrich_topics(pipeline_output)

        exec_text, fun_fact = _parse_fun_fact(pipeline_output.get("exec_summary", ""))

        template = self.env.get_template("base.html")
        html = template.render(
            date_display=date_display,
            date_long=date_display,
            today_name=today_name,
            week_label=week_label,
            subscriber_name=subscriber_name,
            exec_summary=exec_text,
            fun_fact=fun_fact,
            exec_summary_url=exec_summary_url,
            topics=enriched_topics,
            run_timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            total_sources=pipeline_output.get("total_sources", 0),
            total_articles=pipeline_output.get("total_articles", 0),
            pfas_map_url=map_url,
            epr_map_url=epr_map_url,
            reach_map_url=reach_map_url,
            archive_weeks=archive_weeks or [],
            archive_url=archive_url,
            is_web_version=is_web_version,
            calendar_url=calendar_url,
        )

        if inline_css:
            try:
                html = premailer.transform(html, strip_important=False)
            except Exception as e:
                logger.warning(f"premailer CSS inlining failed (sending without): {e}")

        return html

    def render_weekly_briefing(
        self,
        pipeline_output: dict,
        newsletter_url: Optional[str] = None,
        week_context: Optional[dict] = None,
    ) -> str:
        """Render the standalone weekly briefing page."""
        now = datetime.now()
        ctx = week_context or {}
        exec_text, fun_fact = _parse_fun_fact(pipeline_output.get("exec_summary", ""))
        template = self.env.get_template("exec_summary.html")
        return template.render(
            date_display=now.strftime("%B %-d, %Y"),
            today_name=ctx.get("today_name", now.strftime("%A")),
            week_label=ctx.get("week_label", ""),
            week_start_long=ctx.get("week_start_long", ""),
            week_end_long=ctx.get("week_end_long", ""),
            is_friday=ctx.get("is_friday", False),
            exec_summary=exec_text,
            fun_fact=fun_fact,
            newsletter_url=newsletter_url,
        )

    def render_archive_index(self, archive_weeks: list[dict]) -> str:
        """Render the full archive index page."""
        now = datetime.now()
        template = self.env.get_template("archive.html")
        return template.render(
            date_display=now.strftime("%B %-d, %Y"),
            archive_weeks=archive_weeks,
        )

    def render_deadline_calendar(self, deadlines: List[dict], ics_url: Optional[str] = None) -> str:
        """Render the standalone deadline calendar page."""
        now = datetime.now()
        template = self.env.get_template("deadline_calendar.html")
        return template.render(
            date_display=now.strftime("%B %-d, %Y"),
            deadlines=deadlines,
            ics_url=ics_url,
        )

    # Keep old name as alias for any callers
    def render_exec_summary(self, pipeline_output: dict, newsletter_url: Optional[str] = None,
                             week_context: Optional[dict] = None) -> str:
        return self.render_weekly_briefing(pipeline_output, newsletter_url=newsletter_url,
                                           week_context=week_context)
