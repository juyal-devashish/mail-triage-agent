"""
What the dashboard can do: archive, mark read, undo, and correct a verdict.

Every mailbox write goes through here, is triggered by a user's click, and only ever removes or
re-adds the INBOX and UNREAD labels. Each write is logged by batch so one undo reverses it.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Literal

from app.domain.types import Bucket
from app.domain.verdict import LABELS, decide
from app.providers import MailProvider
from app.store import Store

Action = Literal["archive", "mark_read"]
ACTION_LABEL: dict[Action, str] = {"archive": "INBOX", "mark_read": "UNREAD"}
RuleScope = Literal["sender", "domain", "none"]


@dataclass(frozen=True)
class ActionResult:
    batch_id: str | None  # None when nothing needed changing
    changed: list[str]


def apply_action(store: Store, provider: MailProvider, action: Action, ids: list[str]) -> ActionResult:
    label = ACTION_LABEL[action]
    targets = [m for m in store.messages(ids) if label in m.labels]
    if not targets:
        return ActionResult(None, [])
    changed = [m.id for m in targets]
    provider.modify(changed, add=[], remove=[label])  # remote first: if it fails, nothing local changes
    batch_id = uuid.uuid4().hex[:12]
    for m in targets:
        store.set_labels(m.id, [x for x in m.labels if x != label])
    store.log_removed(batch_id, [(mid, label) for mid in changed])
    return ActionResult(batch_id, changed)


def undo(store: Store, provider: MailProvider, batch_id: str | None = None) -> ActionResult:
    batch_id = batch_id or store.last_batch()
    if batch_id is None:
        return ActionResult(None, [])
    pending = store.pending_undo(batch_id)
    by_label: dict[str, list[str]] = defaultdict(list)
    for mid, label in pending:
        by_label[label].append(mid)
    for label, ids in by_label.items():
        provider.modify(ids, add=[label], remove=[])
        for m in store.messages(ids):
            store.set_labels(m.id, [*m.labels, label])
    store.mark_undone(batch_id)
    return ActionResult(batch_id, [mid for mid, _ in pending])


def redecide(store: Store, ids: list[str] | None = None) -> int:
    """Re-run the code-side decision from stored model answers (no model calls). Corrections stay put."""
    answers = store.answers()
    verdicts = store.verdicts()
    rules = store.rules()
    n = 0
    for m in store.messages(ids):
        current = verdicts.get(m.id)
        if m.id not in answers or (current is not None and current.source == "correction"):
            continue
        store.save_verdict(m.id, decide(m, answers[m.id], rules))
        n += 1
    return n


def correct(store: Store, message_id: str, to_bucket: Bucket, scope: RuleScope = "sender") -> list[str]:
    """Move one email to another bucket and, by default, make a rule for its sender. Returns the ids re-decided."""
    message = store.message(message_id)
    current = store.verdicts().get(message_id)
    if message is None or current is None:
        raise KeyError(message_id)
    if current.bucket != to_bucket:
        store.add_correction(message_id, current.bucket, to_bucket)
    store.save_verdict(
        message_id,
        replace(current, bucket=to_bucket, source="correction", reason=f"You moved this to {LABELS[to_bucket]}."),
    )
    if scope == "none":
        return [message_id]
    pattern = message.from_email if scope == "sender" else message.sender_domain
    store.add_rule(pattern, to_bucket, from_message_id=message_id)
    same_sender = [
        m.id
        for m in store.messages()
        if m.id != message_id and (m.from_email.lower() == pattern.lower() or m.sender_domain == pattern.lower())
    ]
    redecide(store, same_sender)
    return [message_id, *same_sender]
