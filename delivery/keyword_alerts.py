"""
Keyword subscription alert dispatcher.

Called at the end of each pipeline run. Checks all active keyword subscriptions
against newly-ingested articles and sends email alerts where matches are found.
Token cost: zero (string matching only — no AI calls).
"""
from __future__ import annotations
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


def dispatch_keyword_alerts(base_url: str = "http://localhost:5000") -> int:
    """
    Check all keyword subscriptions against new articles (last 25 hours).
    Sends one email per subscriber per keyword if matches exist.
    Returns the number of alerts sent.
    """
    from subscribers.db import get_active_keyword_subscriptions, get_new_articles_for_keyword

    subscriptions = get_active_keyword_subscriptions()
    if not subscriptions:
        return 0

    # Group by keyword so we only query each keyword once
    by_keyword: dict[str, list[dict]] = {}
    for sub in subscriptions:
        by_keyword.setdefault(sub["keyword"], []).append(sub)

    total_sent = 0
    for keyword, subs in by_keyword.items():
        articles = get_new_articles_for_keyword(keyword)
        if not articles:
            continue

        for sub in subs:
            try:
                _send_keyword_alert(
                    email=sub["email"],
                    keyword=keyword,
                    articles=articles,
                    unsubscribe_token=sub["unsubscribe_token"],
                    base_url=base_url,
                )
                total_sent += 1
            except Exception as e:
                logger.warning(f"Alert send failed ({sub['email']}, {keyword!r}): {e}")

    if total_sent:
        logger.info(f"Keyword alerts: {total_sent} sent")
    return total_sent


def _send_keyword_alert(
    email: str,
    keyword: str,
    articles: list[dict],
    unsubscribe_token: str,
    base_url: str,
) -> None:
    from delivery.gmail_sender import GmailSender
    from config.settings import Config

    count = len(articles)
    subject = f'[Compliance Alert] {count} new result{"s" if count != 1 else ""} for "{keyword}"'

    # Build plain text
    lines = [
        f'New compliance content matching "{keyword}":',
        "",
    ]
    for a in articles[:10]:
        lines.append(f"• {a.get('title', '(no title)')}")
        if a.get("snippet"):
            snippet = a["snippet"][:160].rstrip()
            lines.append(f"  {snippet}…" if len(a["snippet"]) > 160 else f"  {snippet}")
        if a.get("url"):
            lines.append(f"  {a['url']}")
        lines.append("")

    deep_dive_url = f"{base_url}/deep-dive?q={keyword.replace(' ', '+')}"
    unsubscribe_url = f"{base_url}/unsubscribe?token={unsubscribe_token}"
    lines += [
        f"View full analysis: {deep_dive_url}",
        "",
        f"Unsubscribe: {unsubscribe_url}",
    ]
    text_body = "\n".join(lines)

    # Build HTML
    article_html = ""
    for a in articles[:10]:
        title = a.get("title", "(no title)")
        url = a.get("url", "#")
        snippet = a.get("snippet", "")[:200]
        source = a.get("source", "")
        topic = a.get("topic", "")
        article_html += f"""
        <div style="border:1px solid #E8EAED;border-radius:6px;padding:12px 16px;margin-bottom:10px;">
          <div style="font-size:14px;font-weight:600;margin-bottom:4px;">
            <a href="{url}" style="color:#1565C0;text-decoration:none;">{title}</a>
          </div>
          {f'<div style="font-size:13px;color:#4A4F5C;margin-bottom:6px;">{snippet}{"…" if len(a.get("snippet",""))>200 else ""}</div>' if snippet else ""}
          <div style="font-size:11px;color:#7A8194;font-family:monospace;">
            {f'<span style="background:#EBF3FD;color:#1565C0;border-radius:3px;padding:1px 5px;margin-right:6px;">{topic}</span>' if topic else ""}
            {source}
          </div>
        </div>"""

    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Instrument Sans',sans-serif;
                max-width:600px;margin:0 auto;color:#111318;">
      <div style="background:#1A1D23;padding:16px 24px;border-bottom:3px solid #1565C0;">
        <span style="color:#fff;font-weight:700;font-size:15px;">Compliance Alert</span>
        <span style="color:rgba(255,255,255,0.55);font-size:12px;margin-left:12px;">
          {count} new result{"s" if count != 1 else ""} for &ldquo;{keyword}&rdquo;
        </span>
      </div>
      <div style="padding:20px 24px;background:#fff;">
        {article_html}
        <div style="margin-top:20px;padding-top:16px;border-top:1px solid #E8EAED;">
          <a href="{deep_dive_url}"
             style="display:inline-block;background:#1565C0;color:#fff;
                    text-decoration:none;border-radius:4px;padding:8px 18px;
                    font-size:14px;font-weight:600;">
            View Deep-Dive Analysis →
          </a>
        </div>
      </div>
      <div style="padding:12px 24px;background:#F4F5F7;border-top:1px solid #E8EAED;
                  font-size:11px;color:#7A8194;text-align:center;">
        You're receiving this because you subscribed to alerts for &ldquo;{keyword}&rdquo;.
        <a href="{unsubscribe_url}" style="color:#7A8194;">Unsubscribe</a>
      </div>
    </div>"""

    sender = GmailSender(Config.gmail_address(), Config.gmail_app_password())
    sender.send(
        to_addresses=[email],
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    logger.info(f"Keyword alert sent: {email} ← {keyword!r} ({count} articles)")
