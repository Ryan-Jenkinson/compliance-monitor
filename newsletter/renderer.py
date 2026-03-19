"""Jinja2 rendering + premailer CSS inlining."""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path

import premailer
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_topic_colors() -> dict[str, str]:
    """Load topic colors from topics.yaml for template context."""
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


class NewsletterRenderer:
    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        self._colors = _load_topic_colors()
        self._labels = _load_topic_labels()

    def render(
        self,
        pipeline_output: dict,
        subscriber_name: str = "Ryan",
        inline_css: bool = True,
        map_url: str | None = None,
    ) -> str:
        """
        Render the newsletter to HTML.

        Args:
            pipeline_output: Result from Summarizer.run()
            subscriber_name: Recipient's first name for greeting
            inline_css: Run premailer to inline CSS (required for email clients)

        Returns:
            HTML string
        """
        now = datetime.now()
        date_display = now.strftime("%B %-d, %Y")
        date_long = now.strftime("%B %-d, %Y")

        # Enrich topic summaries with color/label from config
        enriched_topics = []
        for ts in pipeline_output["topics"]:
            enriched = dict(ts)
            enriched["color"] = self._colors.get(ts["topic"], "#718096")
            enriched["label"] = self._labels.get(ts["topic"], ts["topic"])
            enriched_topics.append(enriched)

        template = self.env.get_template("base.html")
        html = template.render(
            date_display=date_display,
            date_long=date_long,
            subscriber_name=subscriber_name,
            exec_summary=pipeline_output["exec_summary"],
            topics=enriched_topics,
            run_timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            total_sources=pipeline_output.get("total_sources", 0),
            total_articles=pipeline_output.get("total_articles", 0),
            pfas_map_url=map_url,
        )

        if inline_css:
            try:
                html = premailer.transform(html)
            except Exception as e:
                logger.warning(f"premailer CSS inlining failed (sending without): {e}")

        return html
