"""
Historical Trend Tracker — queries daily_snapshots for sparkline data.

Provides 4-week and 12-week trend series for the dashboard.
Sparklines are rendered as inline SVG paths — no chart library needed.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional

from config.settings import Config

logger = logging.getLogger(__name__)

_DB_PATH = Config.DB_PATH


def get_trend_data(days: int = 28) -> dict:
    """
    Return trend data for the last N days from daily_snapshots.

    {
        "dates": ["2026-03-01", ...],               # x-axis labels
        "total": [12, 15, 9, ...],                  # total articles per day
        "high":  [3, 5, 2, ...],                    # HIGH urgency per day
        "by_topic": {
            "PFAS": [8, 9, 5, ...],
            "EPR":  [2, 3, 1, ...],
            ...
        },
        "days_with_data": int,
        "latest": {snapshot dict} or None,
    }
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM daily_snapshots WHERE snapshot_date >= ? ORDER BY snapshot_date ASC",
        (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return {
            "dates": [], "total": [], "high": [],
            "by_topic": {}, "days_with_data": 0, "latest": None,
        }

    dates, totals, highs = [], [], []
    topic_series: dict[str, list[int]] = {}

    for row in rows:
        dates.append(row["snapshot_date"])
        totals.append(row["total_articles"] or 0)
        highs.append(row["high_count"] or 0)
        try:
            tc = json.loads(row["topic_counts_json"] or "{}")
        except Exception:
            tc = {}
        for topic, count in tc.items():
            topic_series.setdefault(topic, []).append(count)
        # Backfill missing topics for this date
        for topic in list(topic_series.keys()):
            if len(topic_series[topic]) < len(dates):
                topic_series[topic].append(0)

    latest = dict(rows[-1]) if rows else None
    if latest:
        try:
            latest["topic_counts"] = json.loads(latest.get("topic_counts_json") or "{}")
        except Exception:
            latest["topic_counts"] = {}

    return {
        "dates": dates,
        "total": totals,
        "high": highs,
        "by_topic": topic_series,
        "days_with_data": len(rows),
        "latest": latest,
    }


# ── SVG Sparkline generation ────────────────────────────────────────────────

def _sparkline_path(values: list[int | float], width: int = 80, height: int = 24,
                    padding: int = 2) -> str:
    """
    Generate an SVG <polyline> points string for a sparkline.
    Returns empty string if fewer than 2 data points.
    """
    if len(values) < 2:
        return ""
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v or 1
    w = width - 2 * padding
    h = height - 2 * padding

    n = len(values)
    points = []
    for i, v in enumerate(values):
        x = padding + (i / (n - 1)) * w
        y = padding + (1 - (v - min_v) / span) * h
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def build_sparklines(trend: dict) -> dict:
    """
    Build sparkline SVG snippets from trend data.

    Returns {
        "total": "<svg>...</svg>",
        "high":  "<svg>...</svg>",
        "by_topic": { "PFAS": "<svg>...", ... }
    }
    """
    def _svg(values: list, color: str = "#1565C0", width: int = 80, height: int = 24) -> str:
        if not values or len(values) < 2:
            return ""
        pts = _sparkline_path(values, width=width, height=height)
        if not pts:
            return ""
        # Last point dot
        last_x, last_y = pts.split()[-1].split(",")
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'style="display:block;overflow:visible;">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{last_x}" cy="{last_y}" r="2" fill="{color}"/>'
            f'</svg>'
        )

    topic_colors = {
        "PFAS": "#0F766E", "EPR": "#1565C0", "REACH": "#5B21B6",
        "TSCA": "#9A3412", "Prop65": "#E67E22", "ConflictMinerals": "#1A7A87",
        "ForcedLabor": "#7B241C",
    }

    result = {
        "total": _svg(trend["total"], color="#1565C0"),
        "high":  _svg(trend["high"],  color="#D63031"),
        "by_topic": {},
    }
    for topic, series in trend.get("by_topic", {}).items():
        color = topic_colors.get(topic, "#888")
        result["by_topic"][topic] = _svg(series, color=color, width=60, height=20)

    return result
