"""CRUD operations for subscribers."""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from .db import get_connection
from .models import Subscriber, TopicPreference, SendLog

_DEFAULT_TOPICS = ["PFAS", "EPR", "REACH", "TSCA"]


class SubscriberRepository:
    # --- Subscribers ---

    def add(self, email: str, first_name: str) -> Subscriber:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO subscribers (email, first_name) VALUES (?, ?)",
                (email.lower().strip(), first_name.strip()),
            )
            sub_id = cur.lastrowid
            # Add default topic preferences
            for topic in _DEFAULT_TOPICS:
                conn.execute(
                    "INSERT INTO topic_preferences (subscriber_id, topic_name) VALUES (?, ?)",
                    (sub_id, topic),
                )
            conn.commit()
            return self.get_by_id(sub_id)
        finally:
            conn.close()

    def remove(self, email: str) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE subscribers SET is_active = 0 WHERE email = ?",
                (email.lower().strip(),),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_by_id(self, sub_id: int) -> Optional[Subscriber]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM subscribers WHERE id = ?", (sub_id,)
            ).fetchone()
            return self._row_to_subscriber(row) if row else None
        finally:
            conn.close()

    def get_by_email(self, email: str) -> Optional[Subscriber]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM subscribers WHERE email = ?",
                (email.lower().strip(),),
            ).fetchone()
            return self._row_to_subscriber(row) if row else None
        finally:
            conn.close()

    def list_active(self, include_scheduled_only: bool = True) -> List[Subscriber]:
        conn = get_connection()
        try:
            if include_scheduled_only:
                rows = conn.execute(
                    "SELECT * FROM subscribers WHERE is_active = 1 ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM subscribers WHERE is_active = 1 AND scheduled_only = 0 ORDER BY created_at"
                ).fetchall()
            return [self._row_to_subscriber(r) for r in rows]
        finally:
            conn.close()

    # --- Topic preferences ---

    def get_enabled_topics(self, subscriber_id: int) -> List[str]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT topic_name FROM topic_preferences "
                "WHERE subscriber_id = ? AND is_enabled = 1",
                (subscriber_id,),
            ).fetchall()
            return [r["topic_name"] for r in rows]
        finally:
            conn.close()

    def set_topic(self, subscriber_id: int, topic: str, enabled: bool) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO topic_preferences (subscriber_id, topic_name, is_enabled)
                   VALUES (?, ?, ?)
                   ON CONFLICT(subscriber_id, topic_name) DO UPDATE SET is_enabled = excluded.is_enabled""",
                (subscriber_id, topic, int(enabled)),
            )
            conn.commit()
        finally:
            conn.close()

    # --- Send log ---

    def log_send(self, subscriber_id: int, status: str, error: str | None = None) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO send_log (subscriber_id, status, error_message) VALUES (?, ?, ?)",
                (subscriber_id, status, error),
            )
            conn.commit()
        finally:
            conn.close()

    def already_sent_today(self, subscriber_id: int) -> bool:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT 1 FROM send_log
                   WHERE subscriber_id = ?
                     AND status = 'success'
                     AND date(sent_at, 'localtime') = date('now', 'localtime')
                   LIMIT 1""",
                (subscriber_id,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def _row_to_subscriber(row) -> Subscriber:
        return Subscriber(
            id=row["id"],
            email=row["email"],
            first_name=row["first_name"],
            is_active=bool(row["is_active"]),
            scheduled_only=bool(row["scheduled_only"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )
