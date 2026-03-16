"""RawArticle dataclass — shared across all scrapers and processors."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawArticle:
    """Represents a single scraped article before AI processing."""
    id: str                        # Unique ID (URL hash or source-provided)
    title: str
    url: str
    source: str                    # e.g. "Federal Register", "EPA", "ECHA"
    topic: str                     # Matched topic name (PFAS, EPR, REACH, TSCA)
    published_at: Optional[datetime] = None
    snippet: str = ""              # Short excerpt / description
    full_text: str = ""            # Full body text (if fetched)
    extra: dict = field(default_factory=dict)  # Source-specific metadata

    def __post_init__(self):
        if not self.id:
            import hashlib
            self.id = hashlib.sha256(self.url.encode()).hexdigest()[:16]
