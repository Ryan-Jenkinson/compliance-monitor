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

    @staticmethod
    def _load_pfas_intel() -> dict:
        """Load PFAS legislative intel metrics from cached pipeline result."""
        import json
        path = Path(__file__).parent.parent / "data" / "cache" / "claude" / "pfas_legislative_intel_result.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            states = data.get("states", {})
            stages = {}
            relevance = {"high": 0, "medium": 0, "low": 0}
            total_bills = 0
            high_relevance_states = []
            for code, st in states.items():
                stage = st.get("stage", "none")
                stages[stage] = stages.get(stage, 0) + 1
                rel = st.get("company_relevance", "low")
                relevance[rel] = relevance.get(rel, 0) + 1
                bills = st.get("bills", [])
                if isinstance(bills, list):
                    total_bills += len(bills)
                if rel == "high":
                    high_relevance_states.append({
                        "code": code, "stage": stage,
                        "name": st.get("name", code),
                        "bills": len(bills) if isinstance(bills, list) else 0,
                    })
            # Sort stages by pipeline order
            stage_order = ["enacted_watching", "advanced", "passed_one",
                           "committee", "introduced", "rulemaking",
                           "discussion", "pre_discussion"]
            sorted_stages = [(s, stages.get(s, 0)) for s in stage_order if stages.get(s, 0) > 0]
            return {
                "total_bills": total_bills,
                "total_states": len(states),
                "active_states": sum(1 for s in states.values() if s.get("stage", "none") != "none"),
                "stages": sorted_stages,
                "relevance": relevance,
                "high_relevance_states": sorted(high_relevance_states, key=lambda x: x["code"]),
                "generated": data.get("generated", ""),
            }
        except Exception as e:
            logger.warning(f"Failed to load PFAS intel: {e}")
            return {}

    @staticmethod
    def _load_bill_funnel() -> dict:
        """Load bill stage distribution across all topics for the pipeline funnel widget."""
        try:
            from subscribers.db import get_connection
            conn = get_connection()
            rows = conn.execute("""
                SELECT topic, stage, COUNT(*) as cnt
                FROM legiscan_bills
                WHERE is_active = 1 AND stage IS NOT NULL AND stage != 'none'
                GROUP BY topic, stage
            """).fetchall()
            conn.close()

            stage_order = ["introduced", "committee", "passed_one", "advanced",
                           "enacted_watching", "rulemaking"]
            stage_labels = {
                "introduced": "Introduced",
                "committee": "Committee",
                "passed_one": "Passed 1",
                "advanced": "Advanced",
                "enacted_watching": "Enacted",
                "rulemaking": "Rulemaking",
            }

            by_topic: dict = {}
            totals: dict = {s: 0 for s in stage_order}
            totals["total"] = 0

            for row in rows:
                topic = row["topic"]
                stage = row["stage"]
                cnt = row["cnt"]
                if topic not in by_topic:
                    by_topic[topic] = {s: 0 for s in stage_order}
                    by_topic[topic]["total"] = 0
                if stage in by_topic[topic]:
                    by_topic[topic][stage] += cnt
                    totals[stage] += cnt
                by_topic[topic]["total"] += cnt
                totals["total"] += cnt

            return {
                "by_topic": by_topic,
                "totals": totals,
                "stage_order": stage_order,
                "stage_labels": stage_labels,
            }
        except Exception as e:
            logger.warning(f"Failed to load bill funnel data: {e}")
            return {}

    @staticmethod
    def _load_source_health() -> list[dict]:
        """
        Scan dated scraper cache files to build a source health summary.
        Returns list sorted by article_count desc.
        """
        import json
        from datetime import date, timedelta
        cache_dir = Path(__file__).parent.parent / "data" / "cache"
        today = date.today()
        today_str = today.isoformat()
        yesterday_str = (today - timedelta(days=1)).isoformat()

        import re as _re
        _date_pat = _re.compile(r"^(.+)_(\d{4}-\d{2}-\d{2})$")

        # Map source_name → {last_date, article_count, status}
        health: dict = {}
        for path in sorted(cache_dir.glob("*.json")):
            name = path.stem  # e.g. "federal_register_2026-03-23"
            m = _date_pat.match(name)
            if not m:
                continue
            source_key = m.group(1)
            date_str = m.group(2)
            try:
                articles = json.loads(path.read_text())
                count = len(articles) if isinstance(articles, list) else 0
            except Exception:
                count = 0

            if source_key not in health or date_str > health[source_key]["last_date"]:
                health[source_key] = {
                    "source": source_key.replace("_", " ").title(),
                    "last_date": date_str,
                    "article_count": count,
                    "status": "ok" if date_str >= yesterday_str else "stale",
                }

        return sorted(health.values(), key=lambda x: x["article_count"], reverse=True)

    def render_dashboard(
        self,
        pipeline_output: dict,
        week_context: Optional[dict] = None,
        archive_weeks: Optional[List[dict]] = None,
        deadlines: Optional[List[dict]] = None,
        calendar_url: Optional[str] = None,
        daily_changes: Optional[List[dict]] = None,
        bill_activity: Optional[List[dict]] = None,
        bill_analyses: Optional[dict] = None,
        deadline_analyses: Optional[dict] = None,
    ) -> str:
        """Render the compliance intelligence dashboard."""
        now = datetime.now()
        ctx = week_context or {}
        exec_text, fun_fact = _parse_fun_fact(pipeline_output.get("exec_summary", ""))
        enriched_topics = self._enrich_topics(pipeline_output)
        pfas_intel = self._load_pfas_intel()
        bill_funnel = self._load_bill_funnel()

        # Source health (scraper cache scan)
        source_health = self._load_source_health()

        # Trend data for sparklines
        trend_data: dict = {}
        sparklines: dict = {}
        try:
            from processors.trend_tracker import get_trend_data, build_sparklines
            trend_data = get_trend_data(days=28)
            sparklines = build_sparklines(trend_data)
        except Exception:
            pass

        base_url = "https://ryan-jenkinson.github.io/compliance-maps"

        # Normalize deadline topics to lowercase so they match `topic.topic|lower`
        # in the template filter (topics.yaml names are uppercase e.g. "PFAS").
        # Also ensure days_until is present on every item.
        from datetime import date as _date, timedelta
        _today = _date.today()
        normalized_deadlines = []
        for dl in (deadlines or []):
            dl = dict(dl)
            dl["topic"] = (dl.get("topic") or "").lower()
            dl["_source"] = "deadline"
            if "days_until" not in dl or dl["days_until"] is None:
                try:
                    dl["days_until"] = (_date.fromisoformat(dl["deadline_date"]) - _today).days
                except Exception:
                    dl["days_until"] = None
            normalized_deadlines.append(dl)

        # Merge regulation milestones into the deadlines list.
        # Milestones carry the official regulation name and event description.
        # Deduplicate: skip a milestone if a deadline already covers the same
        # date + topic + jurisdiction combo (deadline entry has more detail + AI analysis).
        try:
            from processors.regulation_registry import get_key_regulation_milestones
            reg_milestones_raw = get_key_regulation_milestones(limit=20)
            deadline_keys = {
                (dl.get("deadline_date"), dl.get("topic", "").lower(), (dl.get("jurisdiction") or "").lower())
                for dl in normalized_deadlines
            }
            for m in reg_milestones_raw:
                m_date = m.get("next_event_date") or ""
                m_topic = (m.get("topic") or "").lower()
                m_juris = (m.get("jurisdiction") or "").lower()
                if (m_date, m_topic, m_juris) in deadline_keys:
                    continue  # already covered by a deadline entry
                try:
                    days = (_date.fromisoformat(m_date) - _today).days if m_date else None
                except Exception:
                    days = None
                # Infer urgency from days_until
                if days is None:
                    urgency = "LOW"
                elif days <= 30:
                    urgency = "HIGH"
                elif days <= 90:
                    urgency = "MEDIUM"
                else:
                    urgency = "LOW"
                normalized_deadlines.append({
                    "id": None,
                    "title": m.get("next_event_desc") or m.get("regulation_name", ""),
                    "regulation_name": m.get("regulation_name", ""),
                    "deadline_date": m_date,
                    "topic": m_topic,
                    "jurisdiction": m.get("jurisdiction", ""),
                    "urgency": urgency,
                    "description": None,
                    "source_url": m.get("source_url") or "",
                    "days_until": days,
                    "current_status": m.get("current_status", ""),
                    "_source": "milestone",
                })
        except Exception as e:
            logger.warning(f"Failed to merge regulation milestones: {e}")

        # Sort merged list by days_until (overdue first, then soonest)
        def _sort_key(dl):
            d = dl.get("days_until")
            return d if d is not None else 9999

        normalized_deadlines.sort(key=_sort_key)

        # Flag freshness:
        #   "new"     = deadline first appeared in the most recent pipeline week
        #   "updated" = existing deadline whose content changed since it was first added
        #               (updated_at is set and more recent than week_start)
        # Milestones have no week_start/updated_at so they get no flag.
        week_starts = sorted(
            {dl["week_start"] for dl in normalized_deadlines if dl.get("week_start")},
            reverse=True,
        )
        latest_week = week_starts[0] if week_starts else None
        _fourteen_days_ago = (_today - timedelta(days=14)).isoformat()
        for dl in normalized_deadlines:
            ws = dl.get("week_start")
            updated_at = dl.get("updated_at") or ""
            if ws and ws == latest_week:
                dl["_freshness"] = "new"
            elif updated_at and updated_at[:10] >= _fourteen_days_ago:
                dl["_freshness"] = "updated"
            else:
                dl["_freshness"] = ""

        template = self.env.get_template("dashboard.html")
        return template.render(
            date_display=now.strftime("%-d %b %Y"),
            date_long=now.strftime("%A, %B %-d, %Y"),
            run_timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            exec_summary=exec_text,
            fun_fact=fun_fact,
            topics=enriched_topics,
            total_sources=pipeline_output.get("total_sources", 0),
            total_articles=pipeline_output.get("total_articles", 0),
            week_label=ctx.get("week_label", ""),
            archive_weeks=archive_weeks or [],
            pfas_intel=pfas_intel,
            maps={
                "pfas_map_url": f"{base_url}/pfas-map.html",
                "epr_map_url": f"{base_url}/epr-map.html",
                "reach_map_url": f"{base_url}/reach-map.html",
                "pfas_intel_url": f"{base_url}/pfas-legislative-intel.html",
            },
            timelines={
                "pfas": f"{base_url}/pfas-timeline.html",
                "epr": f"{base_url}/epr-timeline.html",
                "reach": f"{base_url}/reach-timeline.html",
                "tsca": f"{base_url}/tsca-timeline.html",
                "all": f"{base_url}/deadline-timeline.html",
            },
            downloads={
                "pfas_xlsx": f"{base_url}/pfas-tracker.xlsx",
                "epr_xlsx": f"{base_url}/epr-tracker.xlsx",
                "reach_xlsx": f"{base_url}/reach-tracker.xlsx",
            },
            calendar_url=calendar_url or f"{base_url}/deadlines.ics",
            deadlines=normalized_deadlines,
            bill_activity=bill_activity or [],
            bill_analyses=bill_analyses or {},
            deadline_analyses=deadline_analyses or {},
            daily_changes=daily_changes or [],
            trend_data=trend_data,
            sparklines=sparklines,
            bill_funnel=bill_funnel,
            reg_milestones=[],
            source_health=source_health,
        )

    # Keep old name as alias for any callers
    def render_exec_summary(self, pipeline_output: dict, newsletter_url: Optional[str] = None,
                             week_context: Optional[dict] = None) -> str:
        return self.render_weekly_briefing(pipeline_output, newsletter_url=newsletter_url,
                                           week_context=week_context)
