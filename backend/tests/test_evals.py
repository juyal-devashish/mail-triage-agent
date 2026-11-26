import json

from app.evals import evaluate, report
from app.llm.triage_llm import ResponseCache, build_request, request_key
from app.synth.inbox import generate


def cache_from(answers_for):
    """A cache holding a stored response for every synthetic email, built from a function of the truth."""
    msgs, key = generate()
    cache = ResponseCache(None)
    for m in msgs:
        bucket, confidence = answers_for(m, key[m.id])
        text = json.dumps(
            {
                "bucket": bucket,
                "category": key[m.id].category,
                "summary": "s",
                "reason": "r",
                "action": None,
                "deadline": None,
                "confidence": confidence,
            }
        )
        kw = build_request(m, [], "m", "low", 100)
        cache.put(
            request_key(kw),
            {
                "stop_reason": "end_turn",
                "text": text,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        )
    return msgs, key, cache


def run(answers_for):
    msgs, key, cache = cache_from(answers_for)
    return evaluate(msgs, key, cache, model="m", effort="low", max_tokens=100)


def test_perfect_answers_score_perfectly():
    r = run(lambda m, t: (t.bucket, "high"))
    assert r.answered == 150 and r.accuracy == 1.0 and r.needs_recall == 1.0 and r.hidden == []
    assert all(ok for *_, ok in r.tricky)
    assert "| Needs-you recall | 100% (13 of 13) |" in report(r, "m", "low")


def test_hidden_counts_needs_you_shown_as_noise():
    r = run(lambda m, t: ("noise", "high") if t.bucket == "needs_you" else (t.bucket, "high"))
    assert len(r.hidden) == 13 and r.needs_recall == 0.0


def test_low_confidence_noise_is_scored_as_shown():
    # the model says noise for everything needing you, but unsure: the dashboard shows them in fyi
    r = run(lambda m, t: ("noise", "low") if t.bucket == "needs_you" else (t.bucket, "high"))
    assert r.hidden == [] and r.count(truth="needs_you", pred="fyi") == 13


def test_no_stored_answers_means_nothing_hidden():
    msgs, key = generate()
    r = evaluate(msgs, key, ResponseCache(None), model="m", effort="low", max_tokens=100)
    assert r.answered == 0 and r.statuses == {"budget": 150} and r.hidden == []
