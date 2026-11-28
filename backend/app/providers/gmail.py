"""
Your Gmail inbox as a provider. Runs locally with your own OAuth client; nothing here is hosted.

Scope is `gmail.modify`: read threads and change labels. The app only ever removes or re-adds the
INBOX and UNREAD labels; it never deletes, trashes or sends. The OAuth client secret and token live
in ~/.config/mail-triage-agent/ (outside the repo), and the token file is written owner-only.

Setup: docs/gmail.md.
"""

import base64
import logging
import os
import time
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
from pathlib import Path
from typing import Any

from app.domain.types import Message

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
ALLOWED_LABEL_CHANGES = {"INBOX", "UNREAD"}
CLIENT_SECRET = "client_secret.json"
TOKEN = "token.json"


class GmailSetupError(RuntimeError):
    pass


def login(config_dir: Path) -> None:
    """Run the browser consent flow once and store the token. Needs client_secret.json from Google Cloud."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = config_dir / CLIENT_SECRET
    if not secret.is_file():
        raise GmailSetupError(f"Put your OAuth client file at {secret} first (see docs/gmail.md).")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    _save_token(config_dir, creds.to_json())


def _save_token(config_dir: Path, data: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / TOKEN
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(data)


def _credentials(config_dir: Path) -> Any:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = config_dir / TOKEN
    if not path.is_file():
        raise GmailSetupError("Not signed in to Gmail. Run: python -m app.cli gmail-login")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise GmailSetupError("Gmail token can't be refreshed. Run: python -m app.cli gmail-login")
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Apps left in "Testing" get refresh tokens that expire after 7 days (docs/gmail.md).
            raise GmailSetupError(f"Gmail sign-in expired ({exc}). Run: python -m app.cli gmail-login") from exc
        _save_token(config_dir, creds.to_json())
    return creds


# --------------------------------------------------------------------------------------- parsing
def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _bodies(part: dict[str, Any]) -> tuple[str, str]:
    """(text/plain, text/html) from a Gmail payload, walking multipart trees and skipping attachments."""
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if part.get("filename"):
        return "", ""
    if mime == "text/plain" and data:
        return _b64(data), ""
    if mime == "text/html" and data:
        return "", _b64(data)
    text, html = "", ""
    for sub in part.get("parts", []) or []:
        t, h = _bodies(sub)
        text = text or t
        html = html or h
    return text, html


def parse_message(raw: dict[str, Any]) -> Message:
    """A Gmail API message resource (format=full) as a Message."""
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    name, email = parseaddr(headers.get("from", ""))
    text, html = _bodies(payload)
    received = datetime.fromtimestamp(int(raw.get("internalDate", "0")) / 1000, tz=UTC)
    return Message(
        id=raw["id"],
        thread_id=raw.get("threadId", raw["id"]),
        from_name=name or email,
        from_email=email.lower(),
        to=headers.get("to", ""),
        subject=headers.get("subject", "(no subject)"),
        date=received.isoformat(timespec="seconds"),
        body_text=text,
        body_html=html or None,
        labels=tuple(raw.get("labelIds", [])),
    )


# --------------------------------------------------------------------------------------- provider
class GmailProvider:
    name = "gmail"
    authoritative = True  # Gmail is the source of truth for labels; a sync overwrites the local mirror

    def __init__(self, config_dir: Path, days: int = 7, max_threads: int = 300, service: Any = None) -> None:
        self.config_dir = config_dir
        self.days = days
        self.max_threads = max_threads
        self._service = service
        self._me: str | None = None

    @property
    def service(self) -> Any:
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("gmail", "v1", credentials=_credentials(self.config_dir), cache_discovery=False)
        return self._service

    @property
    def me(self) -> str:
        if self._me is None:
            self._me = self.service.users().getProfile(userId="me").execute()["emailAddress"].lower()
        return self._me

    def fetch(self) -> list[Message]:
        """Every email of the inbox conversations active in the last `days` days, at most `max_threads` of them.

        Whole threads come back, the owner's sent replies included, so the app can see who wrote last.
        """
        users = self.service.users()
        ids: list[str] = []
        page = None
        while len(ids) < self.max_threads:
            resp = (
                users.threads()
                .list(
                    userId="me",
                    q=f"in:inbox newer_than:{self.days}d",
                    pageToken=page,
                    maxResults=min(500, self.max_threads - len(ids)),
                )
                .execute()
            )
            ids += [t["id"] for t in resp.get("threads", [])]
            page = resp.get("nextPageToken")
            if not page:
                break
        raws: dict[str, dict[str, Any]] = {}

        def collect(request_id: str, response: dict[str, Any], exception: Exception | None) -> None:
            if exception is not None:
                log.warning("Gmail thread get failed for %s: %s", request_id, type(exception).__name__)
            else:
                raws[request_id] = response

        for start in range(0, len(ids), 50):
            batch = self.service.new_batch_http_request(callback=collect)
            for tid in ids[start : start + 50]:
                batch.add(users.threads().get(userId="me", id=tid, format="full"), request_id=tid)
            batch.execute()
        # Batched gets can fail one by one (rate limits). Retry those singly; if any still fail, stop the
        # sync rather than return a partial inbox, which would make the missing mail look archived.
        missing = [tid for tid in ids if tid not in raws]
        for attempt, tid in enumerate(missing):
            time.sleep(min(2.0, 0.2 * (attempt + 1)))
            try:
                raws[tid] = users.threads().get(userId="me", id=tid, format="full").execute()
            except Exception as exc:  # noqa: BLE001 - any failure means the snapshot is incomplete
                log.warning("Gmail thread get failed again for %s: %s", tid, type(exc).__name__)
        still = [tid for tid in ids if tid not in raws]
        if still:
            raise GmailSetupError(f"Couldn't fetch {len(still)} of {len(ids)} inbox conversations; try again shortly.")
        messages = [
            parse_message(raw)
            for tid in ids
            for raw in raws[tid].get("messages", [])
            if "DRAFT" not in raw.get("labelIds", [])  # unsent drafts aren't part of the conversation yet
        ]
        return sorted(messages, key=lambda m: m.date, reverse=True)

    # --- profile signals: headers only, never bodies -------------------------------------------------

    def _list_ids(self, q: str, cap: int) -> list[str]:
        users = self.service.users()
        ids: list[str] = []
        page = None
        while len(ids) < cap:
            resp = (
                users.messages().list(userId="me", q=q, pageToken=page, maxResults=min(500, cap - len(ids))).execute()
            )
            ids += [m["id"] for m in resp.get("messages", [])]
            page = resp.get("nextPageToken")
            if not page:
                break
        return ids

    def _headers(self, ids: list[str], names: list[str]) -> list[dict[str, Any]]:
        """format=metadata gets: only the named headers and the labels come back."""
        users = self.service.users()
        out: dict[str, dict[str, Any]] = {}

        def collect(request_id: str, response: dict[str, Any], exception: Exception | None) -> None:
            if exception is None:
                out[request_id] = response

        for start in range(0, len(ids), 50):
            batch = self.service.new_batch_http_request(callback=collect)
            for mid in ids[start : start + 50]:
                req = users.messages().get(userId="me", id=mid, format="metadata", metadataHeaders=names)
                batch.add(req, request_id=mid)
            batch.execute()
        return [out[i] for i in ids if i in out]  # a few misses only weaken suggestions; no retry needed

    def profile_signals(
        self, days: int = 90, cap: int = 1500
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str, bool]]]:
        """Who the owner writes to (name, address), and what they receive (name, address, unread)."""
        sent = self._headers(self._list_ids(f"in:sent newer_than:{days}d", cap), ["To", "Cc"])
        recipients: list[tuple[str, str]] = []
        for raw in sent:
            for h in raw.get("payload", {}).get("headers", []):
                if h["name"].lower() in ("to", "cc"):
                    recipients += getaddresses([h["value"]])
        q = f"newer_than:{days}d -in:sent -in:chats -in:spam -in:trash"
        received: list[tuple[str, str, bool]] = []
        for raw in self._headers(self._list_ids(q, cap), ["From"]):
            frm = next(
                (h["value"] for h in raw.get("payload", {}).get("headers", []) if h["name"].lower() == "from"), ""
            )
            name, addr = parseaddr(frm)
            if addr:
                received.append((name, addr, "UNREAD" in raw.get("labelIds", [])))
        return recipients, received

    def modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        bad = (set(add) | set(remove)) - ALLOWED_LABEL_CHANGES
        if bad:
            raise ValueError(f"refusing to change labels {sorted(bad)}: only INBOX and UNREAD")
        for start in range(0, len(ids), 1000):
            self.service.users().messages().batchModify(
                userId="me",
                body={"ids": ids[start : start + 1000], "addLabelIds": add, "removeLabelIds": remove},
            ).execute()
