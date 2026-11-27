"""
Read models for the dashboard: inbox conversations grouped for review, and one conversation rendered safely.

The same functions feed the API and the static demo export, so the demo can't show anything the
app wouldn't.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import nh3

from app.domain.types import Category, Conversation
from app.domain.verdict import Verdict
from app.store import Store

CATEGORY_LABELS: dict[Category, str] = {
    "reply": "Replies",
    "deadline": "Deadlines",
    "meeting": "Meetings",
    "bill": "Bills",
    "security": "Security",
    "personal": "Personal",
    "newsletter": "Newsletters",
    "promo": "Promotions",
    "notification": "Notifications",
    "receipt": "Receipts",
    "social": "Social",
    "other": "Other",
}

# Tags an email may keep. No images (remote images are tracking pixels), no styles, no forms, no media.
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3", "h4", "hr", "i", "li", "ol", "p",
    "pre", "span", "strong", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}  # fmt: skip


def sanitize_html(html: str) -> str:
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes={"a": {"href"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )


def gmail_url(provider: str, conversation: Conversation) -> str | None:
    return f"https://mail.google.com/mail/u/0/#all/{conversation.id}" if provider == "gmail" else None


def item(provider: str, c: Conversation, v: Verdict) -> dict[str, Any]:
    who = c.counterpart
    return {
        "id": c.id,
        "from_name": who.from_name,
        "from_email": who.from_email,
        "participants": list(c.participants),
        "count": len(c.messages),
        "replied_last": c.replied_last,
        "subject": c.subject,
        "date": c.date,
        "unread": c.unread,
        "bucket": v.bucket,
        "category": v.category,
        "summary": v.summary,
        "reason": v.reason,
        "action": v.action,
        "deadline": v.deadline,
        "confidence": v.confidence,
        "source": v.source,
        "gmail_url": gmail_url(provider, c),
    }


def as_of(provider: str) -> str:
    """'Now' for relative times and due dates: the synthetic inbox has a fixed clock."""
    if provider == "synthetic":
        from app.synth.inbox import NOW

        return NOW.isoformat(timespec="seconds")
    return datetime.now(UTC).isoformat(timespec="seconds")


def inbox_view(store: Store, provider: str) -> dict[str, Any]:
    verdicts = store.verdicts()
    rows = [(c, verdicts[c.id]) for c in store.conversations() if c.in_inbox and c.id in verdicts]
    needs = [item(provider, m, v) for m, v in rows if v.bucket == "needs_you"]
    # Due soonest first; undated after, newest first (conversations() is already newest first, and sort is stable).
    needs.sort(key=lambda x: (x["deadline"] is None, x["deadline"] or ""))
    fyi = [item(provider, m, v) for m, v in rows if v.bucket == "fyi"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m, v in rows:
        if v.bucket == "noise":
            groups[v.category].append(item(provider, m, v))
    noise = [
        {"category": cat, "label": CATEGORY_LABELS.get(cat, cat.title()), "items": items}  # type: ignore[arg-type]
        for cat, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    total_noise = sum(len(g["items"]) for g in noise)
    return {
        "provider": provider,
        "synthetic": provider == "synthetic",
        "as_of": as_of(provider),
        "counts": {"needs_you": len(needs), "fyi": len(fyi), "noise": total_noise, "inbox": len(rows)},
        "needs_you": needs,
        "fyi": fyi,
        "noise": noise,
        "rules": [{"pattern": r.pattern, "bucket": r.bucket} for r in store.rules()],
    }


def conversation_view(store: Store, provider: str, conversation_id: str) -> dict[str, Any] | None:
    c = store.conversation(conversation_id)
    v = store.verdicts().get(conversation_id)
    if c is None or v is None:
        return None
    return {
        **item(provider, c, v),
        "messages": [
            {
                "id": m.id,
                "from_name": m.from_name,
                "from_email": m.from_email,
                "to": m.to,
                "date": m.date,
                "mine": c.is_mine(m),
                "unread": "UNREAD" in m.labels,
                "body_text": m.body_text,
                "body_html": sanitize_html(m.body_html) if m.body_html else None,
            }
            for m in c.messages
        ],
    }
