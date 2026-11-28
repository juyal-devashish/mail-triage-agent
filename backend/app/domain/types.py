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
    "job",
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
    "job",
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
    """The answer key's entry for one synthetic conversation. Never loaded by the app."""

    bucket: Bucket
    category: Category
    note: str = ""


@dataclass(frozen=True)
class Conversation:
    """A Gmail thread: the unit the app triages, archives and moves (docs/adr/0001).

    `messages` are oldest first. `me` is the inbox owner's address, so the app can tell their own
    replies from everyone else's.
    """

    id: str
    messages: tuple[Message, ...]
    me: str

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError(f"conversation {self.id} has no messages")

    @property
    def latest(self) -> Message:
        return self.messages[-1]

    def is_mine(self, message: Message) -> bool:
        return message.from_email.lower() == self.me.lower()

    @property
    def counterpart(self) -> Message:
        """The latest email from someone else: whose conversation this is, for sender rules and display."""
        others = [m for m in self.messages if not self.is_mine(m)]
        return others[-1] if others else self.messages[0]

    @property
    def replied_last(self) -> bool:
        return self.is_mine(self.latest)

    @property
    def participants(self) -> tuple[str, ...]:
        """Everyone but the owner, by name, in order of first appearance."""
        seen: dict[str, str] = {}
        for m in self.messages:
            if not self.is_mine(m):
                seen.setdefault(m.from_email.lower(), m.from_name or m.from_email)
        return tuple(seen.values())

    @property
    def subject(self) -> str:
        return self.messages[0].subject

    @property
    def date(self) -> str:
        return self.latest.date

    @property
    def in_inbox(self) -> bool:
        return any("INBOX" in m.labels for m in self.messages)

    @property
    def unread(self) -> bool:
        return any("UNREAD" in m.labels for m in self.messages)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(sorted({label for m in self.messages for label in m.labels}))


def group_conversations(messages: list[Message], me: str) -> list[Conversation]:
    """Group messages by thread, oldest first within each, newest conversation first."""
    threads: dict[str, list[Message]] = {}
    for m in messages:
        threads.setdefault(m.thread_id, []).append(m)
    convs = [Conversation(tid, tuple(sorted(ms, key=lambda m: (m.date, m.id))), me) for tid, ms in threads.items()]
    return sorted(convs, key=lambda c: (c.date, c.id), reverse=True)
