"""Mail providers: where messages come from and where label changes go."""

from typing import Protocol

from app.domain.types import Message


class MailProvider(Protocol):
    """A mailbox. Label changes are the only writes: archive removes INBOX, mark-read removes UNREAD."""

    name: str
    # True when the remote mailbox is the source of truth for labels (Gmail). A sync then overwrites the
    # local mirror and drops INBOX from local messages that left the inbox. False for the synthetic
    # inbox, whose label changes live only in the local store.
    authoritative: bool

    def fetch(self) -> list[Message]:
        """Messages currently in the inbox, newest first."""
        ...

    def modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        """Add and remove label IDs on the given messages. Never deletes or sends."""
        ...
