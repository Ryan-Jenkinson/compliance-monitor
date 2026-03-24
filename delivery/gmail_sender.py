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

    def send_dashboard_notification(
        self,
        to_email: str,
        subscriber_name: str,
        dashboard_url: str,
        date_display: str,
    ) -> bool:
        """Send a simple 'dashboard updated' notification email."""
        subject = f"Compliance Dashboard Updated — {date_display}"
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Georgia,serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:4px;overflow:hidden;">

        <!-- Header -->
        <tr>
          <td style="background:#1a1a2e;padding:28px 36px;">
            <p style="margin:0;color:#a0aec0;font-size:11px;letter-spacing:2px;text-transform:uppercase;font-family:Arial,sans-serif;">Compliance Intelligence</p>
            <p style="margin:6px 0 0;color:#ffffff;font-size:20px;font-weight:bold;font-family:Arial,sans-serif;">{date_display}</p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 36px 12px;">
            <p style="margin:0 0 20px;font-size:16px;color:#1a1a1a;line-height:1.6;">Hello {subscriber_name},</p>
            <p style="margin:0 0 28px;font-size:15px;color:#333333;line-height:1.7;">
              Your compliance intelligence dashboard has been updated with today's regulatory developments across PFAS, EPR, REACH, TSCA, and more.
            </p>
          </td>
        </tr>

        <!-- CTA Button -->
        <tr>
          <td align="center" style="padding:0 36px 32px;">
            <a href="{dashboard_url}"
               style="display:inline-block;background:#1a1a2e;color:#ffffff;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;letter-spacing:1px;text-decoration:none;padding:14px 36px;border-radius:3px;">
              VIEW DASHBOARD
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 36px 32px;border-top:1px solid #eeeeee;">
            <p style="margin:0;font-size:14px;color:#666666;line-height:1.6;">Thank you,<br>
            <span style="color:#1a1a1a;font-weight:bold;">Compliance Intelligence</span></p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
        return self.send(to_email, subject, html)

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
