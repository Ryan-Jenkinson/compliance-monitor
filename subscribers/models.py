"""Subscriber and TopicPreference dataclasses."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Subscriber:
    email: str
    first_name: str
    is_active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class TopicPreference:
    subscriber_id: int
    topic_name: str
    is_enabled: bool = True
    id: Optional[int] = None


@dataclass
class SendLog:
    subscriber_id: int
    status: str                    # 'success' | 'failure'
    error_message: Optional[str] = None
    id: Optional[int] = None
    sent_at: Optional[datetime] = None
