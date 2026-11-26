"""Sync a provider into the store, triage what has no answer yet, and decide every verdict."""

from dataclasses import dataclass

from app.domain.verdict import PENDING_REASON, decide
from app.llm.triage_llm import PROMPT_VERSION, ResponseCache, RunSummary, Transport, triage
from app.providers import MailProvider
from app.store import Store

# Answers worth keeping even though they are failures: asking again would most likely fail the same way.
FINAL_FAILURES = {"refused", "truncated", "invalid"}


@dataclass(frozen=True)
class RunResult:
    synced: int
    asked: int
    summary: RunSummary


def sync(store: Store, provider: MailProvider) -> int:
    messages = provider.fetch()
    store.upsert_messages(messages, update_labels=provider.authoritative)
    if provider.authoritative:
        fetched = {m.id for m in messages}
        for m in store.messages():
            if "INBOX" in m.labels and m.id not in fetched:
                store.set_labels(m.id, [x for x in m.labels if x != "INBOX"])  # archived elsewhere, or aged out
    return len(messages)


def run_triage(
    store: Store,
    transport: Transport | None,
    cache: ResponseCache,
    *,
    model: str,
    effort: str,
    max_tokens: int,
    max_calls: int,
    force: bool = False,
) -> RunResult:
    """Triage inbox messages that have no answer for the current prompt version (all of them with ``force``)."""
    answered = store.answer_versions()
    todo = [m for m in store.messages() if "INBOX" in m.labels and (force or answered.get(m.id) != PROMPT_VERSION)]
    summary = triage(
        todo,
        transport,
        cache,
        corrections=store.recent_corrections(),
        model=model,
        effort=effort,
        max_tokens=max_tokens,
        max_calls=max_calls,
    )
    for attempt in summary.attempts:
        if attempt.status == "ok" or attempt.status in FINAL_FAILURES:
            store.save_answer(attempt.message_id, summary.answers.get(attempt.message_id), PROMPT_VERSION)
    decide_all(store)
    return RunResult(synced=len(store.messages()), asked=len(todo), summary=summary)


def decide_all(store: Store) -> None:
    """Every message gets a verdict: from its stored answer, or a visible 'not triaged yet' placeholder."""
    answers = store.answers()
    verdicts = store.verdicts()
    rules = store.rules()
    for m in store.messages():
        current = verdicts.get(m.id)
        if current is not None and current.source == "correction":
            continue
        if m.id in answers:
            store.save_verdict(m.id, decide(m, answers[m.id], rules))
        else:
            store.save_verdict(m.id, decide(m, None, rules, fallback_reason=PENDING_REASON))
