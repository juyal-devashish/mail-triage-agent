"""
The REST API the dashboard talks to. Model calls never happen here: triage runs from the CLI, so
a page load can't spend money. Every write is an explicit user action on given message IDs.

Handlers are `async` on purpose: they run one at a time on the event loop, so the single SQLite
connection and the undo log never see two writes interleave. Fine for one local user.
"""

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.types import Bucket
from app.pipeline import decide_all
from app.providers import MailProvider
from app.service import Action, RuleScope, apply_action, correct, undo
from app.store import Store
from app.views import inbox_view, message_view


class ActionIn(BaseModel):
    action: Action
    ids: list[str] = Field(min_length=1, max_length=500)


class UndoIn(BaseModel):
    batch_id: str | None = None


class CorrectIn(BaseModel):
    bucket: Bucket
    scope: RuleScope = "sender"


def create_app(store: Store, provider: MailProvider) -> FastAPI:
    app = FastAPI(title="mail-triage-agent")

    @app.get("/api/inbox")
    async def get_inbox() -> dict[str, Any]:
        return inbox_view(store, provider.name)

    @app.get("/api/messages/{message_id}")
    async def get_message(message_id: str) -> dict[str, Any]:
        view = message_view(store, provider.name, message_id)
        if view is None:
            raise HTTPException(404, "no such message")
        return view

    @app.post("/api/actions")
    async def post_action(body: ActionIn) -> dict[str, Any]:
        res = apply_action(store, provider, body.action, body.ids)
        return {"batch_id": res.batch_id, "changed": res.changed}

    @app.post("/api/undo")
    async def post_undo(body: UndoIn) -> dict[str, Any]:
        res = undo(store, provider, body.batch_id)
        return {"batch_id": res.batch_id, "changed": res.changed}

    @app.post("/api/messages/{message_id}/correct")
    async def post_correct(message_id: str, body: CorrectIn) -> dict[str, Any]:
        try:
            touched = correct(store, message_id, body.bucket, body.scope)
        except KeyError:
            raise HTTPException(404, "no such message") from None
        return {"touched": touched}

    @app.delete("/api/rules/{pattern}")
    async def delete_rule(pattern: str) -> dict[str, Literal[True]]:
        store.remove_rule(pattern)
        decide_all(store)  # code-side only: verdicts fall back to the model's stored answers
        return {"ok": True}

    return app


def default_app() -> FastAPI:
    """App factory for uvicorn (`--factory`), so importing this module opens no database."""
    from app.cli import provider_for

    cfg = settings()
    return create_app(Store(cfg.database), provider_for(cfg))
