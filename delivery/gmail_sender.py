"""Gmail SMTP email delivery."""
from __future__ import annotations
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.settings import Config

logger = logging.getLogger(__name__)


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

    @staticmethod
    def subject_for_date(date: datetime | None = None) -> str:
        d = date or datetime.now()
        return f"Compliance Intelligence — {d.strftime('%B %-d, %Y')}"
