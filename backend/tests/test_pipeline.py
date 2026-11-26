import json
from types import SimpleNamespace

from app.domain.verdict import PENDING_REASON
from app.llm.triage_llm import ResponseCache
from app.pipeline import decide_all, run_triage, sync
from app.service import apply_action, correct


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


def test_every_message_gets_a_verdict_even_without_calls(store):
    go(store, None)
    v = store.verdicts()
    assert len(v) == len(store.messages())
    assert all(x.bucket == "fyi" and x.reason == PENDING_REASON for x in v.values())


def test_answered_messages_are_not_asked_again(store):
    reqs = []
    go(store, noise_transport(reqs), max_calls=5)
    assert len(reqs) == 5
    r = go(store, noise_transport(reqs), max_calls=5)
    assert len(reqs) == 10 and r.asked == len(store.messages()) - 5


def test_archived_mail_is_not_triaged(store, provider):
    ids = [m.id for m in store.messages()]
    apply_action(store, provider, "archive", ids[:10])
    reqs = []
    r = go(store, noise_transport(reqs))
    assert r.asked == len(ids) - 10


def test_corrections_survive_a_new_run(store, provider):
    go(store, noise_transport([]))
    mid = store.messages()[0].id
    correct(store, mid, "needs_you", scope="none")
    go(store, noise_transport([]), force=True)
    decide_all(store)
    assert store.verdicts()[mid].bucket == "needs_you"


def test_sync_is_idempotent(store, provider):
    n = len(store.messages())
    assert sync(store, provider) == n and len(store.messages()) == n
