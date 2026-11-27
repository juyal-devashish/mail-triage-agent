"""Sync a provider into the store, triage conversations that need a fresh answer, and decide every verdict."""

from dataclasses import dataclass

from app.domain.types import Conversation
from app.domain.verdict import PENDING_REASON, decide
from app.llm.triage_llm import PROMPT_VERSION, ResponseCache, RunSummary, Transport, triage
from app.providers import MailProvider
from app.store import Store, StoredAnswer

# Answers worth keeping even though they are failures: asking again would most likely fail the same way.
FINAL_FAILURES = {"refused", "truncated", "invalid"}


@dataclass(frozen=True)
class RunResult:
    synced: int  # conversations in the store
    asked: int  # conversations that needed an answer this run
    summary: RunSummary


def sync(store: Store, provider: MailProvider) -> int:
    """Mirror the provider's inbox conversations into the store. Returns how many messages came back."""
    messages = provider.fetch()
    store.set_me(provider.me)
    store.upsert_messages(messages, update_labels=provider.authoritative)
    if provider.authoritative:
        fetched = {m.id for m in messages}
        for m in store.messages():
            if "INBOX" in m.labels and m.id not in fetched:
                store.set_labels(m.id, [x for x in m.labels if x != "INBOX"])  # archived elsewhere, or aged out
    return len(messages)


def is_current(answer: StoredAnswer | None, conv: Conversation) -> bool:
    """An answer counts only if it was made on the conversation's latest email with today's prompt."""
    return answer is not None and answer.latest_message_id == conv.latest.id and answer.prompt_version == PROMPT_VERSION


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
    """Triage inbox conversations without a current answer (all inbox conversations with ``force``)."""
    answers = store.stored_answers()
    convs = store.conversations()
    todo = [c for c in convs if c.in_inbox and (force or not is_current(answers.get(c.id), c))]
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
            store.save_answer(
                attempt.conversation_id,
                attempt.latest_message_id,
                summary.answers.get(attempt.conversation_id),
                PROMPT_VERSION,
            )
    decide_all(store)
    return RunResult(synced=len(convs), asked=len(todo), summary=summary)


def decide_all(store: Store, ids: list[str] | None = None) -> None:
    """Every conversation gets a verdict, from code, without model calls.

    A conversation the user moved keeps its section until a new email arrives. Otherwise the verdict
    comes from a current model answer, or is a visible 'not triaged yet' placeholder.
    """
    answers = store.stored_answers()
    verdicts = store.stored_verdicts()
    rules = store.rules()
    for c in store.conversations(ids):
        current = verdicts.get(c.id)
        if current and current.verdict.source == "correction" and current.latest_message_id == c.latest.id:
            continue
        answer = answers.get(c.id)
        if is_current(answer, c):
            verdict = decide(c, answer.answer, rules)  # type: ignore[union-attr]  # is_current checked it
        else:
            verdict = decide(c, None, rules, fallback_reason=PENDING_REASON)
        store.save_verdict(c.id, c.latest.id, verdict)
