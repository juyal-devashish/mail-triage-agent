"""
SQLite store: a local mirror of the inbox, the verdicts, the user's sender rules, and an undo log.

Real mail stored here stays on this machine (the database lives under `backend/data/`, which git
ignores). The clock is injected so tests are deterministic.
"""

import json
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.domain.types import Bucket, Message
from app.domain.verdict import ModelVerdict, SenderRule, Verdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, thread_id TEXT, from_name TEXT, from_email TEXT, to_addr TEXT,
    subject TEXT, date TEXT, body_text TEXT, body_html TEXT, labels TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdicts (
    message_id TEXT PRIMARY KEY REFERENCES messages(id), bucket TEXT NOT NULL, category TEXT NOT NULL,
    summary TEXT, reason TEXT, action TEXT, deadline TEXT, confidence TEXT, source TEXT NOT NULL,
    model_bucket TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS answers (
    message_id TEXT PRIMARY KEY REFERENCES messages(id), answer TEXT, prompt_version TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sender_rules (
    pattern TEXT PRIMARY KEY, bucket TEXT NOT NULL, from_message_id TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, from_bucket TEXT, to_bucket TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS undo_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, message_id TEXT NOT NULL,
    label TEXT NOT NULL, created_at TEXT, undone_at TEXT
);
CREATE INDEX IF NOT EXISTS undo_batch ON undo_log(batch_id);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = ":memory:", now: Callable[[], str] = utc_now) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.now = now

    # --- messages ---------------------------------------------------------------------------------------

    def upsert_messages(self, messages: Iterable[Message]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET labels=excluded.labels",
                [
                    (
                        m.id,
                        m.thread_id,
                        m.from_name,
                        m.from_email,
                        m.to,
                        m.subject,
                        m.date,
                        m.body_text,
                        m.body_html,
                        json.dumps(list(m.labels)),
                    )
                    for m in messages
                ],
            )

    def messages(self, ids: Iterable[str] | None = None) -> list[Message]:
        if ids is None:
            rows = self.db.execute("SELECT * FROM messages ORDER BY date DESC").fetchall()
        else:
            ids = list(ids)
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            rows = self.db.execute(f"SELECT * FROM messages WHERE id IN ({marks}) ORDER BY date DESC", ids).fetchall()
        return [_message(r) for r in rows]

    def message(self, message_id: str) -> Message | None:
        found = self.messages([message_id])
        return found[0] if found else None

    def set_labels(self, message_id: str, labels: Iterable[str]) -> None:
        with self.db:
            self.db.execute("UPDATE messages SET labels=? WHERE id=?", (json.dumps(sorted(set(labels))), message_id))

    # --- verdicts ---------------------------------------------------------------------------------------

    def save_verdict(self, message_id: str, v: Verdict) -> None:
        d = asdict(v)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    d["bucket"],
                    d["category"],
                    d["summary"],
                    d["reason"],
                    d["action"],
                    d["deadline"],
                    d["confidence"],
                    d["source"],
                    d["model_bucket"],
                    self.now(),
                ),
            )

    def verdicts(self) -> dict[str, Verdict]:
        rows = self.db.execute("SELECT * FROM verdicts").fetchall()
        return {
            r["message_id"]: Verdict(
                bucket=r["bucket"],
                category=r["category"],
                summary=r["summary"],
                reason=r["reason"],
                action=r["action"],
                deadline=r["deadline"],
                confidence=r["confidence"],
                source=r["source"],
                model_bucket=r["model_bucket"],
            )
            for r in rows
        }

    def save_answer(self, message_id: str, answer: ModelVerdict | None, prompt_version: str) -> None:
        """The model's raw answer (None if the attempt failed), kept so rules can re-decide without a new call."""
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO answers VALUES (?,?,?,?)",
                (message_id, answer.model_dump_json() if answer else None, prompt_version, self.now()),
            )

    def answer_versions(self) -> dict[str, str]:
        rows = self.db.execute("SELECT message_id, prompt_version FROM answers").fetchall()
        return {r["message_id"]: r["prompt_version"] for r in rows}

    def answers(self) -> dict[str, ModelVerdict | None]:
        rows = self.db.execute("SELECT message_id, answer FROM answers").fetchall()
        return {r["message_id"]: ModelVerdict.model_validate_json(r["answer"]) if r["answer"] else None for r in rows}

    # --- rules and corrections --------------------------------------------------------------------------

    def rules(self) -> list[SenderRule]:
        return [SenderRule(r["pattern"], r["bucket"]) for r in self.db.execute("SELECT * FROM sender_rules")]

    def add_rule(self, pattern: str, bucket: Bucket, from_message_id: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO sender_rules VALUES (?,?,?,?)",
                (pattern.lower(), bucket, from_message_id, self.now()),
            )

    def remove_rule(self, pattern: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM sender_rules WHERE pattern=?", (pattern.lower(),))

    def add_correction(self, message_id: str, from_bucket: str, to_bucket: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO corrections (message_id, from_bucket, to_bucket, created_at) VALUES (?,?,?,?)",
                (message_id, from_bucket, to_bucket, self.now()),
            )

    def recent_corrections(self, limit: int = 8) -> list[tuple[Message, str, str]]:
        rows = self.db.execute(
            "SELECT message_id, from_bucket, to_bucket FROM corrections ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            m = self.message(r["message_id"])
            if m is not None:
                out.append((m, r["from_bucket"], r["to_bucket"]))
        return out

    # --- undo log ---------------------------------------------------------------------------------------

    def log_removed(self, batch_id: str, removed: list[tuple[str, str]]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT INTO undo_log (batch_id, message_id, label, created_at) VALUES (?,?,?,?)",
                [(batch_id, mid, label, self.now()) for mid, label in removed],
            )

    def pending_undo(self, batch_id: str) -> list[tuple[str, str]]:
        rows = self.db.execute(
            "SELECT message_id, label FROM undo_log WHERE batch_id=? AND undone_at IS NULL", (batch_id,)
        ).fetchall()
        return [(r["message_id"], r["label"]) for r in rows]

    def mark_undone(self, batch_id: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE undo_log SET undone_at=? WHERE batch_id=? AND undone_at IS NULL", (self.now(), batch_id)
            )

    def last_batch(self) -> str | None:
        row = self.db.execute(
            "SELECT batch_id FROM undo_log WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["batch_id"] if row else None


def _message(r: sqlite3.Row) -> Message:
    return Message(
        id=r["id"],
        thread_id=r["thread_id"],
        from_name=r["from_name"],
        from_email=r["from_email"],
        to=r["to_addr"],
        subject=r["subject"],
        date=r["date"],
        body_text=r["body_text"],
        body_html=r["body_html"],
        labels=tuple(json.loads(r["labels"])),
    )
