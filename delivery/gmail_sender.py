"""Gmail SMTP email delivery."""
from __future__ import annotations
import logging
import smtplib
from datetime import date, datetime
from typing import Optional, List
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.settings import Config

logger = logging.getLogger(__name__)

_REMINDER_TO = "ryan.jenkinson@andersencorp.com"


class GmailSender:
    def __init__(self):
        self.gmail_address = Config.gmail_address()
        self.app_password = Config.gmail_app_password()
        self.from_name = Config.GMAIL_FROM_NAME

    def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
    ) -> bool:
        """Send an HTML email via Gmail SMTP. Returns True on success."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.gmail_address}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.gmail_address, self.app_password)
                server.sendmail(self.gmail_address, to_email, msg.as_string())
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_friday_reminder(self, week_label: str) -> bool:
        """Send a Friday 9 AM reminder to verify the end-of-week run completed."""
        subject = f"[Reminder] Verify end-of-week compliance briefing — {week_label}"
        html = f"""
        <html><body style="font-family: sans-serif; color: #1A1A1A; padding: 24px;">
          <p style="font-size: 15px;">
            This is your automated reminder to verify that the
            <strong>end-of-week compliance briefing</strong> ran successfully for
            the week of <strong>{week_label}</strong>.
          </p>
          <p style="font-size: 15px;">Check that:</p>
          <ul style="font-size: 15px;">
            <li>The briefing email was sent to all subscribers</li>
            <li>The weekly archive was published to GitHub Pages</li>
            <li>The PFAS and EPR state maps were updated</li>
          </ul>
          <p style="font-size: 15px;">
            If the Friday run failed, you can trigger it manually:<br>
            <code style="background:#f0f0f0; padding:2px 6px;">python run.py --finalize-week</code>
          </p>
          <p style="font-size: 13px; color: #888;">Compliance Intelligence — automated reminder</p>
        </body></html>
        """
        return self.send(_REMINDER_TO, subject, html)

    def send_missing_archive_warning(self, week_label: str) -> bool:
        """Warn on Monday morning if last week's archive was never created."""
        subject = f"[Action Required] Last week's compliance archive missing — {week_label}"
        html = f"""
        <html><body style="font-family: sans-serif; color: #1A1A1A; padding: 24px;">
          <p style="font-size: 15px;">
            <strong>The end-of-week archive for {week_label} was not found.</strong>
            The Friday run may have failed or been skipped.
          </p>
          <p style="font-size: 15px;">
            Run this to create the archive manually:<br>
            <code style="background:#f0f0f0; padding:2px 6px;">python run.py --finalize-week</code>
          </p>
          <p style="font-size: 13px; color: #888;">Compliance Intelligence — automated warning</p>
        </body></html>
        """
        return self.send(_REMINDER_TO, subject, html)

    @staticmethod
    def subject_for_date(d: Optional[date] = None, week_label: str = "") -> str:
        """Return a day-aware email subject line.

        Mon–Thu: "Compliance Update — Monday, Week of Mar 22"
        Friday:  "End of Week Summary — Week of Mar 22–28"
        """
        d = d or date.today()
        day_name = d.strftime("%A")
        if d.weekday() == 4:  # Friday
            return f"End of Week Summary — Week of {week_label}" if week_label else f"End of Week Summary — {d.strftime('%B %-d, %Y')}"
        short_date = d.strftime("%b %-d")
        return f"Compliance Update — {day_name}, Week of {week_label}" if week_label else f"Compliance Update — {day_name}, {d.strftime('%B %-d, %Y')}"
