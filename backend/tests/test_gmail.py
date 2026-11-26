import base64

import pytest

from app.domain.types import Message
from app.pipeline import sync
from app.providers.gmail import GmailProvider, parse_message
from app.service import apply_action
from app.store import Store


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


RAW = {
    "id": "18c1a",
    "threadId": "18c19",
    "labelIds": ["INBOX", "UNREAD", "CATEGORY_UPDATES"],
    "internalDate": "1795420800000",
    "payload": {
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "Brightside Energy <Billing@Brightside-Energy.example>"},
            {"name": "To", "value": "Alex <alex@example.com>"},
            {"name": "Subject", "value": "Past due"},
        ],
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": b64("Pay by Thursday. ü")}},
                    {"mimeType": "text/html", "body": {"data": b64("<p>Pay by <b>Thursday</b></p>")}},
                ],
            },
            {"mimeType": "application/pdf", "filename": "bill.pdf", "body": {"attachmentId": "a1"}},
        ],
    },
}


def test_parse_message():
    m = parse_message(RAW)
    assert (m.id, m.thread_id, m.from_name, m.from_email) == (
        "18c1a",
        "18c19",
        "Brightside Energy",
        "billing@brightside-energy.example",
    )
    assert m.subject == "Past due" and m.body_text == "Pay by Thursday. ü"
    assert m.body_html == "<p>Pay by <b>Thursday</b></p>"
    assert m.labels == ("INBOX", "UNREAD", "CATEGORY_UPDATES")
    assert m.date.startswith("2026-")


class Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeGmail:
    """Just enough of the Gmail API client for fetch() and modify()."""

    def __init__(self, raws):
        self.raws = {r["id"]: r for r in raws}
        self.modified = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kw):
        assert "in:inbox" in kw["q"]
        return Exec({"messages": [{"id": i} for i in self.raws]})

    def get(self, userId, id, format):  # noqa: A002 - mirrors the API's argument name
        return ("get", id)

    def batchModify(self, userId, body):  # noqa: N802 - mirrors the API
        self.modified.append(body)
        return Exec({})

    def new_batch_http_request(self, callback):
        raws = self.raws

        class Batch:
            def __init__(self):
                self.items = []

            def add(self, req, request_id):
                self.items.append(request_id)

            def execute(self):
                for rid in self.items:
                    callback(rid, raws[rid], None)

        return Batch()


def gmail_provider(raws):
    fake = FakeGmail(raws)
    return GmailProvider(config_dir=None, service=fake), fake  # type: ignore[arg-type]


def test_fetch_and_modify():
    p, fake = gmail_provider([RAW])
    msgs = p.fetch()
    assert [m.id for m in msgs] == ["18c1a"]
    p.modify(["18c1a"], add=[], remove=["INBOX"])
    assert fake.modified == [{"ids": ["18c1a"], "addLabelIds": [], "removeLabelIds": ["INBOX"]}]


def test_modify_refuses_anything_but_inbox_and_unread():
    p, fake = gmail_provider([RAW])
    for labels in (["TRASH"], ["SPAM"], ["CATEGORY_PROMOTIONS"]):
        with pytest.raises(ValueError):
            p.modify(["18c1a"], add=labels, remove=[])
    assert fake.modified == []


def test_gmail_sync_is_authoritative():
    p, fake = gmail_provider([RAW])
    store = Store(":memory:")
    old = Message("old1", "t", "X", "x@x.example", "me", "s", "2026-11-01T00:00:00+00:00", "b", labels=("INBOX",))
    store.upsert_messages([old])
    sync(store, p)
    assert "INBOX" not in store.message("old1").labels  # left the inbox (or the window) remotely
    # labels changed in Gmail flow back on the next sync
    fake.raws["18c1a"] = {**RAW, "labelIds": ["INBOX"]}
    sync(store, p)
    assert store.message("18c1a").labels == ("INBOX",)


def test_synthetic_resync_keeps_local_archive(store, provider):
    mid = store.messages()[0].id
    apply_action(store, provider, "archive", [mid])
    sync(store, provider)
    assert "INBOX" not in store.message(mid).labels
