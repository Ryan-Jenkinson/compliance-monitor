"""Save rendered HTML to file and open in browser for design iteration."""
from __future__ import annotations
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

from config.settings import Config


def save_preview(html: str, date: datetime | None = None) -> Path:
    """Save HTML to data/preview_<date>.html and return the path."""
    d = date or datetime.now()
    filename = f"preview_{d.strftime('%Y-%m-%d_%H%M%S')}.html"
    path = Config.DATA_DIR / filename
    path.write_text(html, encoding="utf-8")
    return path


def open_preview(html: str, date: datetime | None = None) -> Path:
    """Save preview HTML and open it in the default browser."""
    path = save_preview(html, date)
    webbrowser.open(f"file://{path.resolve()}")
    return path
