from collections import Counter

from app.domain.types import BUCKETS, CATEGORIES
from app.synth.inbox import NOW, generate


def test_same_seed_same_inbox():
    a, ka = generate(seed=7)
    b, kb = generate(seed=7)
    assert a == b and ka == kb
    c, _ = generate(seed=8)
    assert a != c


def test_shape_and_ids():
    msgs, key = generate()
    assert len(msgs) == 150
    ids = [m.id for m in msgs]
    assert len(set(ids)) == len(ids)
    assert set(key) == set(ids)
    # newest first, all in the past week
    dates = [m.date for m in msgs]
    assert dates == sorted(dates, reverse=True)
    assert all(m.date < NOW.isoformat() for m in msgs)


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
    msgs, key = generate()
    by_note = {key[m.id].note: (m, key[m.id]) for m in msgs if key[m.id].note}
    phish, truth = by_note["phishing lookalike of Northwind Bank"]
    assert truth.bucket == "noise"
    bulletin, truth = by_note["real deadline buried in a newsletter-looking bulletin"]
    assert truth.bucket == "needs_you" and "CATEGORY_UPDATES" in bulletin.labels
    inj, truth = by_note["prompt injection inside a promo"]
    assert truth.bucket == "noise" and "needs_you" in inj.body_text


def test_everything_is_fictional():
    msgs, _ = generate()
    for m in msgs:
        assert m.from_email.split("@")[1].split(".")[-1] in {"example", "net", "org"}
        assert m.sender_domain.endswith((".example", "example.net", "example.org"))


def test_needs_you_mail_is_unread():
    msgs, key = generate()
    assert all("UNREAD" in m.labels for m in msgs if key[m.id].bucket == "needs_you")
