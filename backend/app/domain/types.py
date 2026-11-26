"""Core types shared by providers, the store, the model module and the API."""

from dataclasses import dataclass, field
from typing import Literal

Bucket = Literal["needs_you", "fyi", "noise"]
Category = Literal[
    "reply",
    "deadline",
    "meeting",
    "bill",
    "security",
    "personal",
    "newsletter",
    "promo",
    "notification",
    "receipt",
    "social",
    "other",
]
Confidence = Literal["high", "medium", "low"]

BUCKETS: tuple[Bucket, ...] = ("needs_you", "fyi", "noise")
CATEGORIES: tuple[Category, ...] = (
    "reply",
    "deadline",
    "meeting",
    "bill",
    "security",
    "personal",
    "newsletter",
    "promo",
    "notification",
    "receipt",
    "social",
    "other",
)


@dataclass(frozen=True)
class Message:
    """One email as a provider hands it over. `labels` uses Gmail's label IDs (INBOX, UNREAD, CATEGORY_*)."""

    id: str
    thread_id: str
    from_name: str
    from_email: str
    to: str
    subject: str
    date: str  # ISO 8601, UTC
    body_text: str
    body_html: str | None = None
    labels: tuple[str, ...] = field(default=("INBOX", "UNREAD"))

    @property
    def sender_domain(self) -> str:
        return self.from_email.rsplit("@", 1)[-1].lower()


@dataclass(frozen=True)
class Truth:
    """The answer key's entry for one synthetic message. Never loaded by the app."""

    bucket: Bucket
    category: Category
    note: str = ""
