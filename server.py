#!/usr/bin/env python3
"""
Local Flask server for live search and keyword subscriptions.

Usage:
    python server.py
    python server.py --port 8080

Serves the static dashboard at / and provides:
    GET  /deep-dive?q=TCE          → generate deep-dive page on the fly
    POST /subscribe                → add keyword subscription
    GET  /unsubscribe?token=...    → deactivate subscription
    GET  /subscriptions            → list active subscriptions (admin)
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logger = logging.getLogger(__name__)

# ── Lazy Flask import so the rest of the codebase doesn't need flask ──────────
try:
    from flask import Flask, request, redirect, render_template_string, send_from_directory
except ImportError:
    print("Flask is required for the server. Install it with:  pip install flask")
    sys.exit(1)

from deep_dive import run_deep_dive, search_content, generate_synthesis, render_deep_dive, get_monthly_trend
from subscribers.db import (
    get_connection,
    init_db,
)
from config.settings import Config

_PAGES_DIR = Path("/tmp/compliance-maps")
_DATA_DEEP_DIVES = Config.DATA_DIR / "deep_dives"
_CACHE: dict[str, str] = {}  # in-memory cache: query → html (same-day)

app = Flask(__name__, static_folder=None)


# ── Static file serving ───────────────────────────────────────────────────────

@app.route("/")
def index():
    return _serve_static("dashboard.html")


@app.route("/<path:filename>")
def static_files(filename):
    return _serve_static(filename)


def _serve_static(filename: str):
    # First look in GitHub Pages repo, then in data/deep_dives
    for base in (_PAGES_DIR, _DATA_DEEP_DIVES):
        target = base / filename
        if target.exists() and target.is_file():
            return send_from_directory(str(base), filename)
    return f"<h3>File not found: {filename}</h3><p><a href='/'>Dashboard</a></p>", 404


# ── Deep-dive ─────────────────────────────────────────────────────────────────

@app.route("/deep-dive")
def deep_dive():
    query = request.args.get("q", "").strip()
    if not query:
        return redirect("/")

    # Check in-memory cache (cleared on server restart)
    from datetime import date
    cache_key = f"{date.today().isoformat()}::{query.lower()}"
    if cache_key in _CACHE:
        logger.debug(f"Deep-dive cache hit: {query}")
        return _CACHE[cache_key]

    articles, deadlines, bills = search_content(query)
    monthly_trend = get_monthly_trend(query)
    synthesis = generate_synthesis(query, articles, deadlines, bills)
    html = render_deep_dive(
        query=query,
        articles=articles,
        deadlines=deadlines,
        bills=bills,
        synthesis=synthesis,
        monthly_trend=monthly_trend,
        dashboard_url="/",
        server_mode=True,
    )

    _CACHE[cache_key] = html
    return html


# ── Subscription ──────────────────────────────────────────────────────────────

@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = (request.form.get("email") or "").strip().lower()
    keyword = (request.form.get("keyword") or "").strip()

    if not email or not keyword:
        return _subscribe_response("error", "Email and keyword are required.", keyword)

    import secrets
    token = secrets.token_urlsafe(24)
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO keyword_subscriptions (email, keyword, unsubscribe_token)
               VALUES (?, ?, ?)
               ON CONFLICT(email, keyword) DO UPDATE SET
                 is_active = 1,
                 unsubscribe_token = excluded.unsubscribe_token""",
            (email, keyword, token),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        logger.error(f"Subscribe error: {e}")
        return _subscribe_response("error", f"Database error: {e}", keyword)
    conn.close()

    _send_subscription_confirmation(email, keyword, token)
    return _subscribe_response("success", f'You\'re now subscribed to alerts for "{keyword}".', keyword)


@app.route("/unsubscribe")
def unsubscribe():
    token = request.args.get("token", "").strip()
    if not token:
        return _unsubscribe_response("error", "Invalid unsubscribe link.")

    conn = get_connection()
    row = conn.execute(
        "SELECT email, keyword FROM keyword_subscriptions WHERE unsubscribe_token = ?",
        (token,),
    ).fetchone()

    if not row:
        conn.close()
        return _unsubscribe_response("error", "This unsubscribe link is invalid or has already been used.")

    conn.execute(
        "UPDATE keyword_subscriptions SET is_active = 0 WHERE unsubscribe_token = ?",
        (token,),
    )
    conn.commit()
    conn.close()

    return _unsubscribe_response("success", f'Unsubscribed "{row["email"]}" from alerts for "{row["keyword"]}".')


@app.route("/subscriptions")
def list_subscriptions():
    """Simple admin view of active subscriptions."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT email, keyword, created_at FROM keyword_subscriptions
           WHERE is_active = 1 ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()

    items = "".join(
        f"<tr><td>{r['email']}</td><td>{r['keyword']}</td><td>{r['created_at'][:16]}</td></tr>"
        for r in rows
    )
    return f"""<!DOCTYPE html><html><head><title>Subscriptions</title>
    <style>body{{font-family:monospace;padding:24px;}} table{{border-collapse:collapse;width:100%;}}
    th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left;}}
    th{{background:#f0f0f0;}}</style></head><body>
    <h2>Active Keyword Subscriptions</h2>
    <table><thead><tr><th>Email</th><th>Keyword</th><th>Created</th></tr></thead>
    <tbody>{items}</tbody></table>
    <p><a href="/">← Dashboard</a></p>
    </body></html>"""


# ── Response helpers ──────────────────────────────────────────────────────────

def _subscribe_response(status: str, message: str, keyword: str) -> str:
    color = "#0F7B3F" if status == "success" else "#D63031"
    return f"""<!DOCTYPE html><html><head><title>Subscription</title>
    <meta charset="UTF-8">
    <style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100vh;
      background:#F4F5F7;margin:0;}}
    .card{{background:#fff;border:1px solid #D8DBE0;border-radius:8px;
      padding:32px 40px;max-width:440px;text-align:center;}}
    .icon{{font-size:32px;margin-bottom:12px;}}
    h2{{color:{color};margin:0 0 8px;font-size:18px;}}
    p{{color:#4A4F5C;font-size:14px;margin:0 0 20px;}}
    a{{color:#1565C0;font-size:14px;text-decoration:none;}}
    a:hover{{text-decoration:underline;}}
    </style></head><body>
    <div class="card">
      <div class="icon">{"✓" if status == "success" else "✕"}</div>
      <h2>{"Subscribed!" if status == "success" else "Error"}</h2>
      <p>{message}</p>
      <a href="/deep-dive?q={keyword}">← Back to {keyword} deep-dive</a>
    </div></body></html>"""


def _unsubscribe_response(status: str, message: str) -> str:
    color = "#0F7B3F" if status == "success" else "#D63031"
    return f"""<!DOCTYPE html><html><head><title>Unsubscribed</title>
    <meta charset="UTF-8">
    <style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100vh;
      background:#F4F5F7;margin:0;}}
    .card{{background:#fff;border:1px solid #D8DBE0;border-radius:8px;
      padding:32px 40px;max-width:440px;text-align:center;}}
    h2{{color:{color};margin:0 0 8px;font-size:18px;}}
    p{{color:#4A4F5C;font-size:14px;margin:0 0 20px;}}
    a{{color:#1565C0;font-size:14px;text-decoration:none;}}
    </style></head><body>
    <div class="card">
      <h2>{"Unsubscribed" if status == "success" else "Error"}</h2>
      <p>{message}</p>
      <a href="/">← Dashboard</a>
    </div></body></html>"""


def _send_subscription_confirmation(email: str, keyword: str, token: str) -> None:
    """Send a confirmation email with unsubscribe link."""
    try:
        from delivery.gmail_sender import GmailSender
        from config.settings import Config

        unsubscribe_url = f"http://localhost:{_port}/unsubscribe?token={token}"
        body = f"""You've subscribed to compliance alerts for: "{keyword}"

You'll receive an email whenever a new article, deadline, or bill matching this term
is found during the weekly compliance pipeline run.

To unsubscribe at any time, click: {unsubscribe_url}

— Compliance Intelligence
"""
        sender = GmailSender(Config.gmail_address(), Config.gmail_app_password())
        sender.send(
            to_addresses=[email],
            subject=f'Compliance alerts: "{keyword}"',
            html_body=f"<pre style='font-family:sans-serif;'>{body}</pre>",
            text_body=body,
        )
        logger.info(f"Confirmation sent to {email} for keyword: {keyword}")
    except Exception as e:
        logger.warning(f"Could not send confirmation email: {e}")


# ── Startup ───────────────────────────────────────────────────────────────────

_port = 5000


def _ensure_subscriptions_table() -> None:
    """Create keyword_subscriptions table if it doesn't exist (migration-safe)."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_subscriptions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            email               TEXT NOT NULL,
            keyword             TEXT NOT NULL,
            is_active           INTEGER NOT NULL DEFAULT 1,
            unsubscribe_token   TEXT NOT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(email, keyword)
        )
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Compliance Intelligence local server")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    args = parser.parse_args()
    _port = args.port

    init_db()
    _ensure_subscriptions_table()

    _DATA_DEEP_DIVES.mkdir(parents=True, exist_ok=True)

    print(f"\n  Compliance Intelligence server running at http://{args.host}:{args.port}/")
    print(f"  Dashboard:     http://{args.host}:{args.port}/")
    print(f"  Deep-dive:     http://{args.host}:{args.port}/deep-dive?q=TCE")
    print(f"  Subscriptions: http://{args.host}:{args.port}/subscriptions\n")

    app.run(host=args.host, port=args.port, debug=False)
