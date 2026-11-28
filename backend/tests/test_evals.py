import json

from app.evals import evaluate, report, synthetic_conversations
from app.llm.triage_llm import ResponseCache, build_request, request_key

NEEDS = sum(t.bucket == "needs_you" for t in synthetic_conversations()[1].values())


def cache_from(answers_for):
    """A cache holding a stored response for every synthetic conversation, built from a function of the truth."""
    convs, key = synthetic_conversations()
    cache = ResponseCache(None)
    for c in convs:
        bucket, confidence = answers_for(c, key[c.id])
        text = json.dumps(
            {
                "bucket": bucket,
                "category": key[c.id].category,
                "summary": "s",
                "reason": "r",
                "action": None,
                "deadline": None,
                "confidence": confidence,
            }
        )
        kw = build_request(c, [], "m", "low", 100)
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
    return convs, key, cache


def run(answers_for):
    convs, key, cache = cache_from(answers_for)
    return evaluate(convs, key, cache, model="m", effort="low", max_tokens=100)


def test_perfect_answers_score_perfectly():
    r = run(lambda m, t: (t.bucket, "high"))
    assert r.answered == 150 and r.accuracy == 1.0 and r.needs_recall == 1.0 and r.hidden == []
    assert all(ok for *_, ok in r.tricky)
    assert f"| Needs-you recall | 100% ({NEEDS} of {NEEDS}) |" in report(r, "m", "low")


def test_hidden_counts_needs_you_shown_as_noise():
    r = run(lambda m, t: ("noise", "high") if t.bucket == "needs_you" else (t.bucket, "high"))
    assert len(r.hidden) == NEEDS and r.needs_recall == 0.0


def test_low_confidence_noise_is_scored_as_shown():
    # the model says noise for everything needing you, but unsure: the dashboard shows them in fyi
    r = run(lambda m, t: ("noise", "low") if t.bucket == "needs_you" else (t.bucket, "high"))
    assert r.hidden == [] and r.count(truth="needs_you", pred="fyi") == NEEDS


def test_no_stored_answers_means_nothing_hidden():
    convs, key = synthetic_conversations()
    r = evaluate(convs, key, ResponseCache(None), model="m", effort="low", max_tokens=100)
    assert r.answered == 0 and r.statuses == {"budget": 150} and r.hidden == []


def test_stored_synthetic_answers_hold_their_floors():
    """Regression floors on the committed Sonnet answers (app/synth/responses.jsonl). Don't lower these."""
    from app.cli import SYNTH, SYNTH_RESPONSES

    convs, key = synthetic_conversations()
    r = evaluate(
        convs, key, ResponseCache(SYNTH_RESPONSES), model=SYNTH.model, effort=SYNTH.effort, max_tokens=SYNTH.max_tokens
    )
    assert r.answered == 150
    assert r.hidden == []
    assert r.needs_recall == 1.0
    assert r.noise_precision >= 0.95
    assert r.accuracy >= 0.95
