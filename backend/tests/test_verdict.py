from app.domain.types import Message
from app.domain.verdict import FALLBACK_REASON, ModelVerdict, SenderRule, decide

MSG = Message("m1", "t1", "Gearloft", "deals@gearloft.example", "me", "Sale", "2026-11-22T00:00:00+00:00", "30% off")


def answer(bucket="noise", confidence="high", **kw) -> ModelVerdict:
    return ModelVerdict(
        bucket=bucket,
        category=kw.get("category", "promo"),
        summary="A sale.",
        reason="Marketing email.",
        action=kw.get("action"),
        deadline=None,
        confidence=confidence,
    )


def test_model_verdict_passes_through():
    v = decide(MSG, answer(), [])
    assert (v.bucket, v.source, v.model_bucket) == ("noise", "model", "noise")


def test_failed_answer_falls_back_to_fyi():
    v = decide(MSG, None, [])
    assert (v.bucket, v.source, v.reason) == ("fyi", "fallback", FALLBACK_REASON)


def test_low_confidence_noise_stays_visible():
    v = decide(MSG, answer(confidence="low"), [])
    assert v.bucket == "fyi" and v.model_bucket == "noise" and v.reason.startswith("Probably noise")
    # low confidence in the other buckets is left alone
    assert decide(MSG, answer(bucket="needs_you", confidence="low"), []).bucket == "needs_you"


def test_address_rule_beats_domain_rule_and_model():
    rules = [SenderRule("gearloft.example", "noise"), SenderRule("deals@gearloft.example", "needs_you")]
    v = decide(MSG, answer(), rules)
    assert (v.bucket, v.source, v.model_bucket) == ("needs_you", "rule", "noise")
    v = decide(MSG, answer(), [SenderRule("gearloft.example", "fyi")])
    assert (v.bucket, v.source) == ("fyi", "rule")


def test_rule_agreeing_with_model_keeps_model_reason():
    v = decide(MSG, answer(), [SenderRule("gearloft.example", "noise")])
    assert v.source == "model" and v.reason == "Marketing email."


def test_rule_to_noise_drops_action():
    v = decide(MSG, answer(bucket="needs_you", action="Reply"), [SenderRule("gearloft.example", "noise")])
    assert v.action is None
