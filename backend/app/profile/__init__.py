"""
The owner's profile: their standing context for triage, written by them and kept on their machine.

`template()` is the blank starting point. `draft()` fills in suggestions from Gmail metadata only
(who they write to, which senders they leave unread), never from email bodies, and makes no model
calls. The owner edits the result before the first triage.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

TEMPLATE = """# My triage profile

Claude reads this before every verdict. Write it the way you'd brief an assistant. Keep it short:
everything here is sent with each conversation. It stays on this machine.

## People who always matter
<!-- One per line: name or address, and why. Mail from them is never noise. -->

## What I'm working on
<!-- Current priorities, so related mail is recognised. -->
- Job search: recruiters, applications, interviews and offers matter.

## Always noise for me
<!-- Senders or kinds of mail you never need to see. -->

## Anything else
<!-- e.g. "Bills are on autopay unless they say past due." -->
"""


@dataclass(frozen=True)
class SentTo:
    address: str
    name: str
    count: int


@dataclass(frozen=True)
class Ignored:
    address: str
    name: str
    received: int
    unread: int


def template() -> str:
    return TEMPLATE


def draft(sent_to: Iterable[SentTo], ignored: Iterable[Ignored], days: int) -> str:
    """The template with suggestions filled in. Suggestions are marked so the owner reviews each one."""
    people = "\n".join(f"- {p.name} <{p.address}> (you wrote to them {p.count} times)" for p in sent_to)
    noise = "\n".join(f"- {i.name} <{i.address}> ({i.unread} of {i.received} left unread)" for i in ignored)
    note = f"<!-- Suggested from the last {days} days of Gmail headers. Delete anyone who doesn't belong. -->"
    out = TEMPLATE.replace(
        "<!-- One per line: name or address, and why. Mail from them is never noise. -->",
        "<!-- One per line: name or address, and why. Mail from them is never noise. -->\n" + note + "\n" + people,
    )
    return out.replace(
        "<!-- Senders or kinds of mail you never need to see. -->",
        "<!-- Senders or kinds of mail you never need to see. -->\n" + note + "\n" + noise,
    )


def top_recipients(recipients: Iterable[tuple[str, str]], me: str, limit: int = 15) -> list[SentTo]:
    """(name, address) pairs from the To/Cc of sent mail, most written-to first. Excludes the owner."""
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for name, addr in recipients:
        a = addr.lower()
        if not a or a == me.lower() or "noreply" in a or "no-reply" in a:
            continue
        counts[a] += 1
        names.setdefault(a, name or a)
    return [SentTo(a, names[a], n) for a, n in counts.most_common(limit) if n >= 2]


def mostly_unread(received: Iterable[tuple[str, str, bool]], min_count: int = 5, limit: int = 20) -> list[Ignored]:
    """(name, address, unread) for received mail: senders with at least `min_count` emails, 90% or more unread."""
    total: Counter[str] = Counter()
    unread: Counter[str] = Counter()
    names: dict[str, str] = {}
    for name, addr, is_unread in received:
        a = addr.lower()
        total[a] += 1
        unread[a] += int(is_unread)
        names.setdefault(a, name or a)
    out = [
        Ignored(a, names[a], total[a], unread[a])
        for a in total
        if total[a] >= min_count and unread[a] >= 0.9 * total[a]
    ]
    return sorted(out, key=lambda i: (-i.received, i.address))[:limit]


def load(path: Path) -> str | None:
    """The profile text, or None if there isn't one yet or it's still the untouched template."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return None if text.strip() == TEMPLATE.strip() else text


def write_new(path: Path, text: str) -> None:
    """Write a profile that doesn't exist yet, readable only by the owner. Never overwrites."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
