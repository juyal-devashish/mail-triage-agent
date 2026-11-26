"""
Your Gmail inbox as a provider. Runs locally with your own OAuth client; nothing here is hosted.

Scope is `gmail.modify`: read messages and change labels. The app only ever removes or re-adds the
INBOX and UNREAD labels; it never deletes, trashes or sends. The OAuth client secret and token live
in ~/.config/mail-triage-agent/ (outside the repo), and the token file is written owner-only.

Setup: docs/gmail.md.
"""

import base64
import logging
import os
from datetime import UTC, datetime
from email.utils import parseaddr
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

    def __init__(self, config_dir: Path, days: int = 7, max_messages: int = 300, service: Any = None) -> None:
        self.config_dir = config_dir
        self.days = days
        self.max_messages = max_messages
        self._service = service

    @property
    def service(self) -> Any:
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("gmail", "v1", credentials=_credentials(self.config_dir), cache_discovery=False)
        return self._service

    def fetch(self) -> list[Message]:
        """Inbox messages from the last `days` days, newest first, at most `max_messages`."""
        users = self.service.users()
        ids: list[str] = []
        page = None
        while len(ids) < self.max_messages:
            resp = (
                users.messages()
                .list(
                    userId="me",
                    q=f"in:inbox newer_than:{self.days}d",
                    pageToken=page,
                    maxResults=min(500, self.max_messages - len(ids)),
                )
                .execute()
            )
            ids += [m["id"] for m in resp.get("messages", [])]
            page = resp.get("nextPageToken")
            if not page:
                break
        raws: dict[str, dict[str, Any]] = {}

        def collect(request_id: str, response: dict[str, Any], exception: Exception | None) -> None:
            if exception is not None:
                log.warning("Gmail get failed for %s: %s", request_id, type(exception).__name__)
            else:
                raws[request_id] = response

        for start in range(0, len(ids), 50):
            batch = self.service.new_batch_http_request(callback=collect)
            for mid in ids[start : start + 50]:
                batch.add(users.messages().get(userId="me", id=mid, format="full"), request_id=mid)
            batch.execute()
        messages = [parse_message(raws[mid]) for mid in ids if mid in raws]
        return sorted(messages, key=lambda m: m.date, reverse=True)

    def modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        bad = (set(add) | set(remove)) - ALLOWED_LABEL_CHANGES
        if bad:
            raise ValueError(f"refusing to change labels {sorted(bad)}: only INBOX and UNREAD")
        for start in range(0, len(ids), 1000):
            self.service.users().messages().batchModify(
                userId="me",
                body={"ids": ids[start : start + 1000], "addLabelIds": add, "removeLabelIds": remove},
            ).execute()
