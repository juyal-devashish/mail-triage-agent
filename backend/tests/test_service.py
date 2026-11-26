from app.domain.verdict import ModelVerdict, decide
from app.service import apply_action, correct, redecide, undo


def seed_verdicts(store, bucket="noise"):
    for m in store.messages():
        a = ModelVerdict(bucket=bucket, category="promo", summary=m.subject[:50], reason="r", confidence="high")
        store.save_answer(m.id, a, "test")
        store.save_verdict(m.id, decide(m, a, []))


def test_archive_and_undo_round_trip(store, provider):
    ids = [m.id for m in store.messages()[:3]]
    res = apply_action(store, provider, "archive", ids)
    assert res.changed == ids and res.batch_id
    assert provider.calls[-1] == (ids, [], ["INBOX"])
    assert all("INBOX" not in m.labels for m in store.messages(ids))
    back = undo(store, provider)
    assert sorted(back.changed) == sorted(ids)
    assert all("INBOX" in m.labels for m in store.messages(ids))
    # a second undo has nothing left to do
    assert undo(store, provider).batch_id is None


def test_mark_read_only_touches_unread_and_undo_restores_exactly(store, provider):
    msgs = store.messages()
    unread = [m.id for m in msgs if "UNREAD" in m.labels][:2]
    read = [m.id for m in msgs if "UNREAD" not in m.labels][:1]
    res = apply_action(store, provider, "mark_read", unread + read)
    assert res.changed == [m.id for m in store.messages(unread)]  # already-read mail is not logged
    undo(store, provider, res.batch_id)
    assert all("UNREAD" in m.labels for m in store.messages(unread))
    assert all("UNREAD" not in m.labels for m in store.messages(read))


def test_nothing_to_do_makes_no_provider_call(store, provider):
    mid = store.messages()[0].id
    apply_action(store, provider, "archive", [mid])
    n = len(provider.calls)
    assert apply_action(store, provider, "archive", [mid]).batch_id is None
    assert len(provider.calls) == n


def test_correct_makes_sender_rule_and_redecides_same_sender(store):
    seed_verdicts(store, "noise")
    msgs = store.messages()
    target = next(m for m in msgs if m.from_email == "deals@gearloft.example")
    others = [m.id for m in msgs if m.from_email == target.from_email and m.id != target.id]
    touched = correct(store, target.id, "fyi")
    v = store.verdicts()
    assert v[target.id].bucket == "fyi" and v[target.id].source == "correction"
    assert set(touched) == {target.id, *others}
    assert all(v[i].bucket == "fyi" and v[i].source == "rule" for i in others)
    # unrelated senders are untouched
    assert all(v[m.id].bucket == "noise" for m in msgs if m.sender_domain != target.sender_domain)
    # corrections feed the prompt
    (m, frm, to), *_ = store.recent_corrections()
    assert (m.id, frm, to) == (target.id, "noise", "fyi")


def test_correct_without_rule_only_moves_one(store):
    seed_verdicts(store, "noise")
    target = next(m for m in store.messages() if m.from_email == "deals@gearloft.example")
    assert correct(store, target.id, "needs_you", scope="none") == [target.id]
    assert store.rules() == []


def test_redecide_keeps_corrections(store):
    seed_verdicts(store, "noise")
    mid = store.messages()[0].id
    correct(store, mid, "needs_you", scope="none")
    redecide(store)
    assert store.verdicts()[mid].source == "correction"


def test_empty_id_list_is_a_no_op(store, provider):
    assert store.messages([]) == []
    assert apply_action(store, provider, "archive", []).batch_id is None


def test_correct_reports_only_emails_that_moved(store):
    seed_verdicts(store, "fyi")
    target = next(m for m in store.messages() if m.from_email == "deals@gearloft.example")
    assert correct(store, target.id, "fyi") == [target.id]  # the others were already fyi
