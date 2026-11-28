from app.domain.verdict import ModelVerdict
from app.pipeline import decide_all
from app.service import apply_action, correct, undo


def seed_answers(store, bucket="noise"):
    """Give every conversation a current model answer in `bucket`, then decide."""
    from app.llm.triage_llm import PROMPT_VERSION

    for c in store.conversations():
        a = ModelVerdict(bucket=bucket, category="promo", summary=c.subject[:50], reason="r", confidence="high")
        store.save_answer(c.id, c.latest.id, a, PROMPT_VERSION)
    decide_all(store)


def thread(store, n_inbox):
    """A conversation with at least `n_inbox` emails in the inbox."""
    return next(c for c in store.conversations() if sum("INBOX" in m.labels for m in c.messages) >= n_inbox)


def test_archive_acts_on_every_email_of_a_conversation_and_undo_restores_it(store, provider):
    elena = thread(store, 2)  # her question and her follow-up are both in the inbox
    plain = [c.id for c in store.conversations() if len(c.messages) == 1][:2]
    ids = [elena.id, *plain]
    res = apply_action(store, provider, "archive", ids)
    assert res.changed == ids and res.batch_id
    inbox_mids = [m.id for m in elena.messages if "INBOX" in m.labels]
    assert set(inbox_mids) <= set(provider.calls[-1][0]) and provider.calls[-1][1:] == ([], ["INBOX"])
    assert not any(c.in_inbox for c in store.conversations(ids))
    back = undo(store, provider)
    assert sorted(back.changed) == sorted(ids)
    assert all(c.in_inbox for c in store.conversations(ids))
    # your own sent email never had INBOX and doesn't get it back
    assert all("INBOX" not in m.labels for m in store.conversation(elena.id).messages if m.from_email == store.me)
    assert undo(store, provider).batch_id is None


def test_mark_read_only_touches_unread_and_undo_restores_exactly(store, provider):
    convs = store.conversations()
    unread = [c.id for c in convs if c.unread][:2]
    read = [c.id for c in convs if not c.unread][:1]
    res = apply_action(store, provider, "mark_read", unread + read)
    assert res.changed == unread  # already-read conversations are not logged
    undo(store, provider, res.batch_id)
    assert all(c.unread for c in store.conversations(unread))
    assert not any(c.unread for c in store.conversations(read))


def test_nothing_to_do_makes_no_provider_call(store, provider):
    cid = store.conversations()[0].id
    apply_action(store, provider, "archive", [cid])
    n = len(provider.calls)
    assert apply_action(store, provider, "archive", [cid]).batch_id is None
    assert len(provider.calls) == n


def test_move_makes_a_rule_for_the_counterpart_and_redecides_their_conversations(store):
    seed_answers(store, "noise")
    convs = store.conversations()
    target = next(c for c in convs if c.counterpart.from_email == "deals@gearloft.example")
    others = [c.id for c in convs if c.counterpart.from_email == "deals@gearloft.example" and c.id != target.id]
    touched = correct(store, target.id, "fyi")
    v = store.verdicts()
    assert v[target.id].bucket == "fyi" and v[target.id].source == "correction"
    assert set(touched) == {target.id, *others}
    assert all(v[i].bucket == "fyi" and v[i].source == "rule" for i in others)
    assert all(v[c.id].bucket == "noise" for c in convs if c.counterpart.sender_domain != "gearloft.example")
    (c, frm, to), *_ = store.recent_corrections()
    assert (c.id, frm, to) == (target.id, "noise", "fyi")


def test_rule_follows_the_other_person_not_your_reply(store):
    seed_answers(store, "noise")
    sam = next(c for c in store.conversations() if c.replied_last and c.counterpart.from_name == "Sam Okafor")
    correct(store, sam.id, "needs_you")
    assert {"sam.okafor@example.net"} == {r.pattern for r in store.rules()}


def test_move_without_rule_only_moves_one(store):
    seed_answers(store, "noise")
    target = next(c for c in store.conversations() if c.counterpart.from_email == "deals@gearloft.example")
    assert correct(store, target.id, "needs_you", scope="none") == [target.id]
    assert store.rules() == []


def test_a_moved_conversation_keeps_its_section_until_a_new_email_arrives(store):
    from dataclasses import replace

    seed_answers(store, "noise")
    c = store.conversations()[0]
    correct(store, c.id, "needs_you", scope="none")
    decide_all(store)
    assert store.verdicts()[c.id].source == "correction"
    reply = replace(c.latest, id="new-1", date="2026-11-23T07:59:59+00:00", labels=("INBOX", "UNREAD"))
    store.upsert_messages([reply])
    decide_all(store)
    v = store.verdicts()[c.id]
    assert v.source == "fallback" and v.bucket == "fyi"  # stale answer: shown as not triaged yet, not hidden


def test_empty_id_list_is_a_no_op(store, provider):
    assert store.conversations([]) == []
    assert apply_action(store, provider, "archive", []).batch_id is None


def test_move_reports_only_conversations_that_moved(store):
    seed_answers(store, "fyi")
    target = next(c for c in store.conversations() if c.counterpart.from_email == "deals@gearloft.example")
    assert correct(store, target.id, "fyi") == [target.id]
