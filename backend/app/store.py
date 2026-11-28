"""
SQLite store: a local mirror of the inbox, the verdicts, the user's sender rules, and an undo log.

Messages are stored one by one, but everything the user sees or acts on is a conversation (a
thread; docs/adr/0001). Verdicts, model answers and corrections are keyed by conversation and record
the latest email they were made on, so a new reply makes them stale.

Real mail stored here stays on this machine (the database lives under `backend/data/`, which git
ignores). The clock is injected so tests are deterministic.
"""

import json
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.domain.types import Bucket, Conversation, Message, group_conversations
from app.domain.verdict import ModelVerdict, SenderRule, Verdict

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, from_name TEXT, from_email TEXT, to_addr TEXT,
    subject TEXT, date TEXT, body_text TEXT, body_html TEXT, labels TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread_id);
CREATE TABLE IF NOT EXISTS verdicts (
    conversation_id TEXT PRIMARY KEY, latest_message_id TEXT NOT NULL, bucket TEXT NOT NULL,
    category TEXT NOT NULL, summary TEXT, reason TEXT, action TEXT, deadline TEXT, confidence TEXT,
    source TEXT NOT NULL, model_bucket TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS answers (
    conversation_id TEXT PRIMARY KEY, latest_message_id TEXT NOT NULL, answer TEXT, prompt_version TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sender_rules (
    pattern TEXT PRIMARY KEY, bucket TEXT NOT NULL, from_conversation_id TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, from_bucket TEXT, to_bucket TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS undo_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, message_id TEXT NOT NULL,
    label TEXT NOT NULL, created_at TEXT, undone_at TEXT
);
CREATE INDEX IF NOT EXISTS undo_batch ON undo_log(batch_id);
"""


class StaleDatabase(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class StoredVerdict:
    verdict: Verdict
    latest_message_id: str  # the email the verdict was made on


@dataclass(frozen=True)
class StoredAnswer:
    answer: ModelVerdict | None  # None: the attempt failed for good (refused, truncated, invalid)
    latest_message_id: str
    prompt_version: str


class Store:
    def __init__(self, path: str | Path = ":memory:", now: Callable[[], str] = utc_now) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self.db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if has_tables and version != SCHEMA_VERSION:
            raise StaleDatabase(
                f"{path} was made by an older version of the app (schema {version}, now {SCHEMA_VERSION}). "
                "Delete it and sync again; Gmail still has all your mail."
            )
        self.db.executescript(SCHEMA)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.now = now

    # --- owner ------------------------------------------------------------------------------------------

    @property
    def me(self) -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key='me'").fetchone()
        return row["value"] if row else ""

    def set_me(self, address: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('me', ?)", (address.lower(),))

    # --- messages ---------------------------------------------------------------------------------------

    def upsert_messages(self, messages: Iterable[Message], update_labels: bool = True) -> None:
        conflict = "DO UPDATE SET labels=excluded.labels" if update_labels else "DO NOTHING"
        with self.db:
            self.db.executemany(
                f"INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) {conflict}",
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
        return [_message(r) for r in self._select("messages", "id", ids, order="date DESC")]

    def message(self, message_id: str) -> Message | None:
        found = self.messages([message_id])
        return found[0] if found else None

    def set_labels(self, message_id: str, labels: Iterable[str]) -> None:
        with self.db:
            self.db.execute("UPDATE messages SET labels=? WHERE id=?", (json.dumps(sorted(set(labels))), message_id))

    # --- conversations ----------------------------------------------------------------------------------

    def conversations(self, ids: Iterable[str] | None = None) -> list[Conversation]:
        """Conversations, newest first. With `ids`, only those (missing ids are skipped)."""
        rows = self._select("messages", "thread_id", ids)
        return group_conversations([_message(r) for r in rows], self.me)

    def conversation(self, conversation_id: str) -> Conversation | None:
        found = self.conversations([conversation_id])
        return found[0] if found else None

    # --- verdicts ---------------------------------------------------------------------------------------

    def save_verdict(self, conversation_id: str, latest_message_id: str, v: Verdict) -> None:
        d = asdict(v)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    conversation_id,
                    latest_message_id,
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

    def stored_verdicts(self) -> dict[str, StoredVerdict]:
        rows = self.db.execute("SELECT * FROM verdicts").fetchall()
        return {
            r["conversation_id"]: StoredVerdict(
                Verdict(
                    bucket=r["bucket"],
                    category=r["category"],
                    summary=r["summary"],
                    reason=r["reason"],
                    action=r["action"],
                    deadline=r["deadline"],
                    confidence=r["confidence"],
                    source=r["source"],
                    model_bucket=r["model_bucket"],
                ),
                r["latest_message_id"],
            )
            for r in rows
        }

    def verdicts(self) -> dict[str, Verdict]:
        return {cid: s.verdict for cid, s in self.stored_verdicts().items()}

    # --- model answers ----------------------------------------------------------------------------------

    def save_answer(
        self, conversation_id: str, latest_message_id: str, answer: ModelVerdict | None, prompt_version: str
    ) -> None:
        """The model's raw answer, kept so rules can re-decide without a new call."""
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO answers VALUES (?,?,?,?,?)",
                (
                    conversation_id,
                    latest_message_id,
                    answer.model_dump_json() if answer else None,
                    prompt_version,
                    self.now(),
                ),
            )

    def stored_answers(self) -> dict[str, StoredAnswer]:
        rows = self.db.execute("SELECT * FROM answers").fetchall()
        return {
            r["conversation_id"]: StoredAnswer(
                ModelVerdict.model_validate_json(r["answer"]) if r["answer"] else None,
                r["latest_message_id"],
                r["prompt_version"],
            )
            for r in rows
        }

    # --- rules and corrections --------------------------------------------------------------------------

    def rules(self) -> list[SenderRule]:
        return [SenderRule(r["pattern"], r["bucket"]) for r in self.db.execute("SELECT * FROM sender_rules")]

    def add_rule(self, pattern: str, bucket: Bucket, from_conversation_id: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO sender_rules VALUES (?,?,?,?)",
                (pattern.lower(), bucket, from_conversation_id, self.now()),
            )

    def remove_rule(self, pattern: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM sender_rules WHERE pattern=?", (pattern.lower(),))

    def add_correction(self, conversation_id: str, from_bucket: str, to_bucket: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO corrections (conversation_id, from_bucket, to_bucket, created_at) VALUES (?,?,?,?)",
                (conversation_id, from_bucket, to_bucket, self.now()),
            )

    def recent_corrections(self, limit: int = 8) -> list[tuple[Conversation, str, str]]:
        rows = self.db.execute(
            "SELECT conversation_id, from_bucket, to_bucket FROM corrections ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            c = self.conversation(r["conversation_id"])
            if c is not None:
                out.append((c, r["from_bucket"], r["to_bucket"]))
        return out

    # --- undo log (per message: a conversation's emails can carry different labels) ---------------------

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

    # --- helpers ----------------------------------------------------------------------------------------

    def _select(self, table: str, column: str, ids: Iterable[str] | None, order: str = "date") -> list[sqlite3.Row]:
        if ids is None:
            return self.db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        ids = list(ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return self.db.execute(f"SELECT * FROM {table} WHERE {column} IN ({marks}) ORDER BY {order}", ids).fetchall()


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
