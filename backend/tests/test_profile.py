import os
import stat

import pytest

from app import profile
from app.domain.types import Conversation, Message
from app.llm.triage_llm import POLICY, build_request, estimate_cost, request_key

ME = "alex@example.com"
CONV = Conversation(
    "t1",
    (Message("m1", "t1", "Sam", "sam@example.net", ME, "Hi", "2026-11-22T10:00:00+00:00", "Dinner?"),),
    ME,
)


def test_profile_rides_in_the_system_prompt_and_is_cached():
    plain = build_request(CONV, [], "m", "low", 100)
    assert [b["text"] for b in plain["system"]] == [POLICY] and plain["system"][0]["cache_control"]
    with_profile = build_request(CONV, [], "m", "low", 100, "- Sam: my best friend")
    first, second = with_profile["system"]
    assert first["text"] == POLICY and "cache_control" not in first
    assert "<profile>" in second["text"] and "Sam: my best friend" in second["text"] and second["cache_control"]
    assert request_key(plain) != request_key(with_profile)
    # a blank profile changes nothing, so the synthetic answers stay cached
    assert request_key(build_request(CONV, [], "m", "low", 100, "  \n")) == request_key(plain)


def test_long_profiles_are_capped_and_counted_in_estimates():
    long = "x" * 20_000
    text = build_request(CONV, [], "m", "low", 100, long)["system"][1]["text"]
    assert text.count("x") == 6000 and "[...profile truncated]" in text
    assert estimate_cost([CONV], 2.0, 10.0, long)["input_tokens"] > estimate_cost([CONV], 2.0, 10.0)["input_tokens"]


def test_untouched_template_counts_as_no_profile(tmp_path):
    path = tmp_path / "profile.md"
    assert profile.load(path) is None
    profile.write_new(path, profile.template())
    assert profile.load(path) is None
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    path.write_text(profile.template() + "\n- Mom: always matters\n")
    assert "Mom" in profile.load(path)


def test_write_new_never_overwrites(tmp_path):
    path = tmp_path / "profile.md"
    profile.write_new(path, "mine")
    with pytest.raises(FileExistsError):
        profile.write_new(path, "other")
    assert path.read_text() == "mine"


def test_draft_suggests_people_and_noise_from_headers():
    recipients = [("Mom", "linda@example.org")] * 6 + [("Priya", "Priya@Work.example")] * 3
    recipients += [("Once", "once@example.com"), ("Me", ME), ("", "noreply@x.example"), ("", "noreply@x.example")]
    people = profile.top_recipients(recipients, ME)
    assert [(p.address, p.count) for p in people] == [("linda@example.org", 6), ("priya@work.example", 3)]
    received = [("Deals", "deals@shop.example", True)] * 9 + [("Deals", "deals@shop.example", False)]
    received += [("News", "news@paper.example", True)] * 3 + [("Boss", "boss@work.example", False)] * 8
    noise = profile.mostly_unread(received)
    assert [(i.address, i.unread, i.received) for i in noise] == [("deals@shop.example", 9, 10)]
    text = profile.draft(people, noise, days=90)
    assert "Mom <linda@example.org> (you wrote to them 6 times)" in text
    assert "Deals <deals@shop.example> (9 of 10 left unread)" in text
    assert "last 90 days of Gmail headers" in text
