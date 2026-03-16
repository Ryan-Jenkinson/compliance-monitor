"""SendGrid email delivery."""
from __future__ import annotations
import logging
from datetime import datetime

import sendgrid
from sendgrid.helpers.mail import Mail, To, Content

from config.settings import Config

logger = logging.getLogger(__name__)


class SendGridSender:
    def __init__(self):
        self.client = sendgrid.SendGridAPIClient(api_key=Config.sendgrid_api_key())
        self.from_email = Config.SENDGRID_FROM_EMAIL
        self.from_name = Config.SENDGRID_FROM_NAME

    def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
    ) -> bool:
        """
        Send an HTML email via SendGrid.

        Returns True on success, False on failure.
        """
        message = Mail(
            from_email=(self.from_email, self.from_name),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", html_body),
        )

        try:
            response = self.client.send(message)
            status = response.status_code
            if 200 <= status < 300:
                logger.info(f"Email sent to {to_email} (status {status})")
                return True
            else:
                logger.error(f"SendGrid returned status {status} for {to_email}")
                return False
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    @staticmethod
    def subject_for_date(date: datetime | None = None) -> str:
        d = date or datetime.now()
        return f"Compliance Intelligence — {d.strftime('%B %-d, %Y')}"
