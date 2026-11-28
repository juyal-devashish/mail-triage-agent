from collections import Counter

from app.domain.types import BUCKETS, CATEGORIES, group_conversations
from app.synth.inbox import NOW, USER_EMAIL, generate


def convs():
    msgs, key = generate()
    return group_conversations(msgs, USER_EMAIL), key


def test_same_seed_same_inbox():
    a, ka = generate(seed=7)
    b, kb = generate(seed=7)
    assert a == b and ka == kb
    c, _ = generate(seed=8)
    assert a != c


def test_shape_and_ids():
    msgs, key = generate()
    ids = [m.id for m in msgs]
    assert len(set(ids)) == len(ids)
    conversations = group_conversations(msgs, USER_EMAIL)
    assert len(conversations) == 150 and set(key) == {c.id for c in conversations}
    assert len(msgs) > 150  # some conversations have several emails
    # newest first, all in the past week
    dates = [m.date for m in msgs]
    assert dates == sorted(dates, reverse=True)
    assert all(m.date < NOW.isoformat() for m in msgs)


def test_conversations_include_your_own_replies():
    conversations, key = convs()
    threads = [c for c in conversations if len(c.messages) > 1]
    assert len(threads) >= 3
    for c in threads:
        mine = [m for m in c.messages if c.is_mine(m)]
        assert mine and all(m.labels == ("SENT",) for m in mine)  # as in Gmail: sent, not in the inbox
        assert c.in_inbox
    replied_last = {key[c.id].bucket for c in threads if c.replied_last}
    assert replied_last == {"needs_you", "fyi"}  # one with a close due date, one with nothing pending


def test_realistic_mix():
    _, key = generate()
    buckets = Counter(t.bucket for t in key.values())
    assert set(buckets) == set(BUCKETS)
    # most mail is noise; a short list needs you
    assert buckets["noise"] > buckets["fyi"] > buckets["needs_you"] >= 10
    assert buckets["needs_you"] <= 20
    cats = {t.category for t in key.values()}
    assert cats <= set(CATEGORIES)
    assert len(cats) >= 10


def test_tricky_cases_present():
    conversations, key = convs()
    by_note = {key[c.id].note: (c, key[c.id]) for c in conversations if key[c.id].note}
    phish, truth = by_note["phishing lookalike of Northwind Bank"]
    assert truth.bucket == "noise"
    bulletin, truth = by_note["real deadline buried in a newsletter-looking bulletin"]
    assert truth.bucket == "needs_you" and "CATEGORY_UPDATES" in bulletin.labels
    inj, truth = by_note["prompt injection inside a promo"]
    assert truth.bucket == "noise" and "needs_you" in inj.latest.body_text
    chase, truth = by_note["a follow-up after you promised something"]
    assert truth.bucket == "needs_you" and len(chase.messages) == 3 and not chase.replied_last


def test_everything_is_fictional():
    msgs, _ = generate()
    for m in msgs:
        assert m.sender_domain.endswith(("example", "example.com", "example.net", "example.org"))


def test_needs_you_conversations_are_unread_unless_you_replied():
    conversations, key = convs()
    for c in conversations:
        if key[c.id].bucket == "needs_you" and not c.replied_last:
            assert c.unread
