"""
Read models for the dashboard: the inbox grouped for review, and one message rendered safely.

The same functions feed the API and the static demo export, so the demo can't show anything the
app wouldn't.
"""

from collections import defaultdict
from typing import Any

import nh3

from app.domain.types import Category, Message
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


def gmail_url(provider: str, message: Message) -> str | None:
    return f"https://mail.google.com/mail/u/0/#all/{message.id}" if provider == "gmail" else None


def item(provider: str, m: Message, v: Verdict) -> dict[str, Any]:
    return {
        "id": m.id,
        "from_name": m.from_name,
        "from_email": m.from_email,
        "subject": m.subject,
        "date": m.date,
        "unread": "UNREAD" in m.labels,
        "bucket": v.bucket,
        "category": v.category,
        "summary": v.summary,
        "reason": v.reason,
        "action": v.action,
        "deadline": v.deadline,
        "confidence": v.confidence,
        "source": v.source,
        "gmail_url": gmail_url(provider, m),
    }


def inbox_view(store: Store, provider: str) -> dict[str, Any]:
    verdicts = store.verdicts()
    rows = [(m, verdicts[m.id]) for m in store.messages() if "INBOX" in m.labels and m.id in verdicts]
    needs = [item(provider, m, v) for m, v in rows if v.bucket == "needs_you"]
    # Due soonest first; undated after, newest first (messages() is already newest first, and sort is stable).
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
        "counts": {"needs_you": len(needs), "fyi": len(fyi), "noise": total_noise, "inbox": len(rows)},
        "needs_you": needs,
        "fyi": fyi,
        "noise": noise,
        "rules": [{"pattern": r.pattern, "bucket": r.bucket} for r in store.rules()],
    }


def message_view(store: Store, provider: str, message_id: str) -> dict[str, Any] | None:
    m = store.message(message_id)
    v = store.verdicts().get(message_id)
    if m is None or v is None:
        return None
    return {
        **item(provider, m, v),
        "to": m.to,
        "body_text": m.body_text,
        "body_html": sanitize_html(m.body_html) if m.body_html else None,
    }
