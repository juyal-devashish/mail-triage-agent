"""
The verdict schema and the code that has the last word over the model.

`ModelVerdict` is exactly what Claude must return. `decide` turns it (or its absence) into the
verdict the dashboard shows, applying, in order:

1. Sender rules from the user's corrections. An exact address beats a domain rule.
2. No usable model answer: the email goes to `fyi`, so nothing is hidden by a failure.
3. Low-confidence noise goes to `fyi`, so an unsure call stays visible.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.types import Bucket, Category, Confidence, Message

Source = Literal["model", "rule", "fallback", "correction"]


class ModelVerdict(BaseModel):
    """The JSON Claude returns for one email."""

    bucket: Bucket
    category: Category
    summary: str = Field(max_length=200, description="One line: what the email says.")
    reason: str = Field(max_length=200, description="One line: why it belongs in this bucket.")
    action: str | None = Field(default=None, max_length=120, description="Suggested next step, if any.")
    deadline: str | None = Field(default=None, description="ISO date (YYYY-MM-DD) if the email has a due date.")
    confidence: Confidence


@dataclass(frozen=True)
class SenderRule:
    pattern: str  # an address ("a@b.example") or a domain ("b.example")
    bucket: Bucket


@dataclass(frozen=True)
class Verdict:
    bucket: Bucket
    category: Category
    summary: str
    reason: str
    action: str | None
    deadline: str | None
    confidence: Confidence
    source: Source
    model_bucket: Bucket | None  # what the model said, kept for the eval and for auditing overrides


FALLBACK_REASON = "Couldn't triage this one automatically, so it's shown rather than hidden."


def match_rule(message: Message, rules: list[SenderRule]) -> SenderRule | None:
    by_pattern = {r.pattern.lower(): r for r in rules}
    return by_pattern.get(message.from_email.lower()) or by_pattern.get(message.sender_domain)


def decide(message: Message, answer: ModelVerdict | None, rules: list[SenderRule]) -> Verdict:
    rule = match_rule(message, rules)
    if answer is None:
        base = Verdict(
            bucket="fyi",
            category="other",
            summary=message.subject[:200],
            reason=FALLBACK_REASON,
            action=None,
            deadline=None,
            confidence="low",
            source="fallback",
            model_bucket=None,
        )
    else:
        bucket = answer.bucket
        reason = answer.reason
        if bucket == "noise" and answer.confidence == "low":
            bucket = "fyi"
            reason = f"Probably noise, but not sure: {answer.reason}"
        base = Verdict(
            bucket=bucket,
            category=answer.category,
            summary=answer.summary,
            reason=reason,
            action=answer.action,
            deadline=answer.deadline,
            confidence=answer.confidence,
            source="model",
            model_bucket=answer.bucket,
        )
    if rule is None or rule.bucket == base.bucket:
        return base
    return Verdict(
        bucket=rule.bucket,
        category=base.category,
        summary=base.summary,
        reason=f"Your rule for {rule.pattern} puts this in {LABELS[rule.bucket]}.",
        action=base.action if rule.bucket == "needs_you" else None,
        deadline=base.deadline,
        confidence="high",
        source="rule",
        model_bucket=base.model_bucket,
    )


LABELS: dict[Bucket, str] = {"needs_you": "Needs you", "fyi": "Worth knowing", "noise": "Noise"}
