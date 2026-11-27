import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.domain.verdict import PENDING_REASON
from app.llm.triage_llm import ResponseCache
from app.pipeline import run_triage, sync
from app.service import apply_action, correct
from app.store import StaleDatabase, Store


def noise_transport(requests):
    def send(kwargs):
        requests.append(kwargs)
        text = json.dumps(
            {
                "bucket": "noise",
                "category": "promo",
                "summary": "A sale.",
                "reason": "Marketing.",
                "action": None,
                "deadline": None,
                "confidence": "high",
            }
        )
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    return send


def go(store, transport, max_calls=1000, **kw):
    return run_triage(
        store, transport, ResponseCache(None), model="m", effort="low", max_tokens=100, max_calls=max_calls, **kw
    )


def test_every_conversation_gets_a_verdict_even_without_calls(store):
    go(store, None)
    v = store.verdicts()
    assert len(v) == len(store.conversations()) == 150
    assert all(x.bucket == "fyi" and x.reason == PENDING_REASON for x in v.values())


def test_answered_conversations_are_not_asked_again(store):
    reqs = []
    go(store, noise_transport(reqs), max_calls=5)
    assert len(reqs) == 5
    r = go(store, noise_transport(reqs), max_calls=5)
    assert len(reqs) == 10 and r.asked == 150 - 5


def test_a_new_reply_means_a_fresh_answer(store):
    reqs = []
    go(store, noise_transport(reqs))
    assert go(store, noise_transport(reqs)).asked == 0
    c = store.conversations()[3]
    store.upsert_messages(
        [replace(c.latest, id="reply-1", date="2026-11-23T07:59:00+00:00", body_text="One more thing...")]
    )
    r = go(store, noise_transport(reqs))
    assert r.asked == 1 and r.summary.attempts[0].conversation_id == c.id
    assert "One more thing" in reqs[-1]["messages"][0]["content"]


def test_archived_conversations_are_not_triaged(store, provider):
    ids = [c.id for c in store.conversations()]
    apply_action(store, provider, "archive", ids[:10])
    r = go(store, noise_transport([]))
    assert r.asked == len(ids) - 10


def test_corrections_survive_a_new_run(store):
    go(store, noise_transport([]))
    cid = store.conversations()[0].id
    correct(store, cid, "needs_you", scope="none")
    go(store, noise_transport([]), force=True)
    assert store.verdicts()[cid].bucket == "needs_you"


def test_sync_is_idempotent_and_records_the_owner(store, provider):
    n = len(store.messages())
    assert sync(store, provider) == n and len(store.messages()) == n
    assert store.me == provider.me


def test_old_databases_are_refused_with_a_clear_message(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE messages (id TEXT)")
    db.commit()
    db.close()
    with pytest.raises(StaleDatabase, match="Delete it and sync again"):
        Store(path)
