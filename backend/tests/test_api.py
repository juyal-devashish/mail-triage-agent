import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.evals import synthetic_conversations
from app.llm.triage_llm import ResponseCache
from app.main import create_app
from app.pipeline import run_triage
from app.views import sanitize_html

CONVS, KEY = synthetic_conversations()


def truth_transport(kwargs):
    """Answers with the answer key, so the API tests see a realistic mix without a model."""
    block = kwargs["messages"][0]["content"]
    subject = next(line[9:] for line in block.splitlines() if line.startswith("Subject: "))
    c = next(x for x in CONVS if x.subject == subject)
    t = KEY[c.id]
    answer = {
        "bucket": t.bucket,
        "category": t.category,
        "summary": c.subject,
        "reason": "r",
        "action": "Do it" if t.bucket == "needs_you" else None,
        "deadline": "2026-11-26" if t.category == "deadline" else None,
        "confidence": "high",
    }
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(answer))],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


@pytest.fixture
def client(store, provider):
    run_triage(store, truth_transport, ResponseCache(None), model="m", effort="low", max_tokens=1, max_calls=1000)
    return TestClient(create_app(store, provider))


def test_inbox_grouping(client):
    data = client.get("/api/inbox").json()
    assert data["synthetic"] is True
    c = data["counts"]
    assert c["needs_you"] + c["fyi"] + c["noise"] == c["inbox"] == 150
    assert c["noise"] > c["fyi"] > c["needs_you"] > 0
    # needs-you: dated first, soonest first
    dl = [x["deadline"] for x in data["needs_you"]]
    dated = [d for d in dl if d]
    assert dl[: len(dated)] == sorted(dated)
    # noise digests: biggest group first, each item in the right category
    sizes = [len(g["items"]) for g in data["noise"]]
    assert sizes == sorted(sizes, reverse=True)
    assert all(i["category"] == g["category"] for g in data["noise"] for i in g["items"])


def test_conversation_detail_is_sanitised(client):
    data = client.get("/api/inbox").json()
    promo = data["noise"][0]["items"][0]
    detail = client.get(f"/api/conversations/{promo['id']}").json()
    assert detail["messages"] and detail["messages"][0]["body_text"]
    for m in detail["messages"]:
        if m["body_html"]:
            assert "<img" not in m["body_html"] and "<script" not in m["body_html"]
    assert client.get("/api/conversations/nope").status_code == 404


def test_conversation_shows_every_email_and_who_wrote_last(client):
    data = client.get("/api/inbox").json()
    items = [i for i in data["needs_you"] + data["fyi"] if i["count"] > 1]
    sam = next(i for i in items if i["from_name"] == "Sam Okafor")
    assert sam["replied_last"] is True and sam["participants"] == ["Sam Okafor"]
    detail = client.get(f"/api/conversations/{sam['id']}").json()
    assert [m["mine"] for m in detail["messages"]] == [False, True]


def test_sanitize_strips_tracking_and_scripts():
    out = sanitize_html(
        '<p onclick="x()">Hi</p><img src="https://t.example/p.gif"><script>alert(1)</script>'
        '<a href="javascript:alert(1)">bad</a><a href="https://ok.example">ok</a><style>p{}</style>'
    )
    assert "<img" not in out and "script" not in out and "onclick" not in out and "javascript" not in out
    assert "<style" not in out
    assert 'href="https://ok.example"' in out and 'target="_blank"' in out and "noopener" in out


def test_archive_all_noise_group_then_undo(client, provider):
    group = client.get("/api/inbox").json()["noise"][0]
    ids = [i["id"] for i in group["items"]]
    res = client.post("/api/actions", json={"action": "archive", "ids": ids}).json()
    assert sorted(res["changed"]) == sorted(ids)
    after = client.get("/api/inbox").json()
    assert after["counts"]["inbox"] == 150 - len(ids)
    client.post("/api/undo", json={"batch_id": res["batch_id"]})
    assert client.get("/api/inbox").json()["counts"]["inbox"] == 150


def test_correct_moves_sender_and_rule_can_be_removed(client):
    data = client.get("/api/inbox").json()
    promo = next(i for g in data["noise"] for i in g["items"] if i["from_email"] == "deals@gearloft.example")
    touched = client.post(f"/api/conversations/{promo['id']}/correct", json={"bucket": "fyi"}).json()["touched"]
    data = client.get("/api/inbox").json()
    fyi_ids = {i["id"] for i in data["fyi"]}
    assert set(touched) <= fyi_ids
    assert {"pattern": "deals@gearloft.example", "bucket": "fyi"} in data["rules"]
    client.delete("/api/rules/deals@gearloft.example")
    data = client.get("/api/inbox").json()
    assert data["rules"] == []
    others = set(touched) - {promo["id"]}
    noise_ids = {i["id"] for g in data["noise"] for i in g["items"]}
    assert others <= noise_ids  # back to the model's call; the corrected one stays where the user put it
    assert promo["id"] in {i["id"] for i in data["fyi"]}


def test_bad_requests_are_rejected(client):
    assert client.post("/api/actions", json={"action": "delete", "ids": ["x"]}).status_code == 422
    assert client.post("/api/actions", json={"action": "archive", "ids": []}).status_code == 422
    assert client.post("/api/conversations/nope/correct", json={"bucket": "fyi"}).status_code == 404
