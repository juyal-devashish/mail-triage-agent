"""
What the dashboard can do: archive, mark read, undo, and move a conversation to another section.

Every action names conversations, and acts on all of their emails. Every mailbox write goes through
here, is triggered by a user's click, and only ever removes or re-adds the INBOX and UNREAD labels.
Each write is logged by batch, per email, so one undo puts back exactly what was removed.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Literal

from app.domain.types import Bucket
from app.domain.verdict import LABELS
from app.pipeline import decide_all
from app.providers import MailProvider
from app.store import Store

Action = Literal["archive", "mark_read"]
ACTION_LABEL: dict[Action, str] = {"archive": "INBOX", "mark_read": "UNREAD"}
RuleScope = Literal["sender", "domain", "none"]


@dataclass(frozen=True)
class ActionResult:
    batch_id: str | None  # None when nothing needed changing
    changed: list[str]  # conversation ids


def apply_action(store: Store, provider: MailProvider, action: Action, ids: list[str]) -> ActionResult:
    label = ACTION_LABEL[action]
    targets = [(c.id, m) for c in store.conversations(ids) for m in c.messages if label in m.labels]
    if not targets:
        return ActionResult(None, [])
    provider.modify([m.id for _, m in targets], add=[], remove=[label])  # remote first: if it fails, nothing changes
    batch_id = uuid.uuid4().hex[:12]
    for _, m in targets:
        store.set_labels(m.id, [x for x in m.labels if x != label])
    store.log_removed(batch_id, [(m.id, label) for _, m in targets])
    touched = set(cid for cid, _ in targets)
    return ActionResult(batch_id, [cid for cid in dict.fromkeys(ids) if cid in touched])  # in the caller's order


def undo(store: Store, provider: MailProvider, batch_id: str | None = None) -> ActionResult:
    batch_id = batch_id or store.last_batch()
    if batch_id is None:
        return ActionResult(None, [])
    pending = store.pending_undo(batch_id)
    by_label: dict[str, list[str]] = defaultdict(list)
    for mid, label in pending:
        by_label[label].append(mid)
    restored: list[str] = []
    for label, mids in by_label.items():
        provider.modify(mids, add=[label], remove=[])
        for m in store.messages(mids):
            store.set_labels(m.id, [*m.labels, label])
            restored.append(m.thread_id)
    store.mark_undone(batch_id)
    return ActionResult(batch_id, list(dict.fromkeys(restored)))


def correct(store: Store, conversation_id: str, to_bucket: Bucket, scope: RuleScope = "sender") -> list[str]:
    """Move one conversation to another section and, by default, make a rule for its counterpart.

    Returns the moved id followed by the ids of other conversations whose section changed because of the rule.
    """
    conv = store.conversation(conversation_id)
    current = store.verdicts().get(conversation_id)
    if conv is None or current is None:
        raise KeyError(conversation_id)
    if current.bucket != to_bucket:
        store.add_correction(conversation_id, current.bucket, to_bucket)
    store.save_verdict(
        conversation_id,
        conv.latest.id,
        replace(current, bucket=to_bucket, source="correction", reason=f"You moved this to {LABELS[to_bucket]}."),
    )
    if scope == "none":
        return [conversation_id]
    who = conv.counterpart
    pattern = (who.from_email if scope == "sender" else who.sender_domain).lower()
    store.add_rule(pattern, to_bucket, from_conversation_id=conversation_id)
    same = [
        c.id
        for c in store.conversations()
        if c.id != conversation_id
        and (c.counterpart.from_email.lower() == pattern or c.counterpart.sender_domain == pattern)
    ]
    before = store.verdicts()
    decide_all(store, same)
    after = store.verdicts()
    moved = [i for i in same if i in after and (i not in before or before[i].bucket != after[i].bucket)]
    return [conversation_id, *moved]
