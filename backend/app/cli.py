"""
Command line. Run from backend/ with the virtualenv: `python -m app.cli <command>`.

  demo       rebuild the synthetic database from stored responses (never calls the API)
  estimate   rough cost of triaging what has no answer yet
  triage     triage what has no answer yet; live calls need --live and stop at --max-calls
  gmail-login  sign in to Gmail once (browser consent); see docs/gmail.md
  export-static  write the SYNTHETIC demo snapshot the hosted page reads
  eval       score stored answers for the synthetic inbox against its answer key
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import BACKEND, Settings, settings
from app.llm.triage_llm import PROMPT_VERSION, ResponseCache, anthropic_transport, estimate_cost, write_run_log
from app.pipeline import run_triage, sync
from app.providers import MailProvider
from app.store import Store

SYNTH_RESPONSES = BACKEND / "app" / "synth" / "responses.jsonl"  # stored answers for the SYNTHETIC inbox only
# The stored synthetic answers were made with these settings. The cache key includes them, so they are
# pinned here: changing MTA_MODEL for your own Gmail must not make the demo and eval find nothing.


@dataclass(frozen=True)
class ModelParams:
    model: str
    effort: str
    max_tokens: int


SYNTH = ModelParams("claude-sonnet-5-5", "low", 4000)


def params_for(cfg: Settings) -> ModelParams:
    return SYNTH if cfg.provider == "synthetic" else ModelParams(cfg.model, cfg.effort, cfg.max_tokens)


def provider_for(cfg: Settings) -> MailProvider:
    if cfg.provider == "gmail":
        from app.providers.gmail import GmailProvider

        return GmailProvider(cfg.gmail_dir, days=cfg.gmail_days, max_messages=cfg.gmail_max_messages)
    from app.providers.synthetic import SyntheticProvider

    return SyntheticProvider()


def cache_for(cfg: Settings) -> ResponseCache:
    return ResponseCache(SYNTH_RESPONSES if cfg.provider == "synthetic" else cfg.cache_path)


def cmd_demo(cfg: Settings, _: argparse.Namespace) -> int:
    if cfg.provider != "synthetic":
        print("demo only runs on the synthetic inbox (unset MTA_PROVIDER)", file=sys.stderr)
        return 2
    Path(cfg.database).unlink(missing_ok=True)
    store = Store(cfg.database)
    sync(store, provider_for(cfg))
    result = run_triage(
        store, None, cache_for(cfg), model=SYNTH.model, effort=SYNTH.effort, max_tokens=SYNTH.max_tokens, max_calls=0
    )
    counts = result.summary.counts()
    print(
        f"synthetic inbox: {result.synced} messages, stored answers for {counts.get('ok', 0)}, "
        f"{counts.get('budget', 0)} without one (shown as 'not triaged yet')"
    )
    print(f"database: {cfg.database}")
    return 0


def _todo(store: Store, force: bool) -> list:
    answered = store.answer_versions()
    return [m for m in store.messages() if "INBOX" in m.labels and (force or answered.get(m.id) != PROMPT_VERSION)]


def cmd_estimate(cfg: Settings, args: argparse.Namespace) -> int:
    store = Store(cfg.database)
    sync(store, provider_for(cfg))
    todo = _todo(store, args.force)
    cache = cache_for(cfg)
    p = params_for(cfg)
    from app.llm.triage_llm import build_request, request_key

    uncached = [
        m
        for m in todo
        if cache.get(request_key(build_request(m, store.recent_corrections(), p.model, p.effort, p.max_tokens))) is None
    ]
    est = estimate_cost(uncached, cfg.input_price, cfg.output_price)
    print(
        f"{len(todo)} to triage, {len(uncached)} not cached: ~{est['input_tokens']:,} input tokens, "
        f"~${est['usd']:.2f} on {p.model} (rough estimate; thinking tokens can add more)"
    )
    return 0


def cmd_triage(cfg: Settings, args: argparse.Namespace) -> int:
    store = Store(cfg.database)
    sync(store, provider_for(cfg))
    transport = anthropic_transport() if args.live else None
    max_calls = args.max_calls if args.max_calls is not None else cfg.max_calls
    p = params_for(cfg)
    result = run_triage(
        store,
        transport,
        cache_for(cfg),
        model=p.model,
        effort=p.effort,
        max_tokens=p.max_tokens,
        max_calls=max_calls if args.live else 0,
        force=args.force,
    )
    s = result.summary
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    write_run_log(BACKEND / "runs" / f"triage-{stamp}.jsonl", s)
    print(
        f"asked {result.asked}: {s.counts()} | live {s.live_calls}, cached {s.cached_calls} | "
        f"~${s.cost_usd(cfg.input_price, cfg.output_price):.4f} at list prices"
    )
    if s.stopped:
        print(f"stopped early: {s.stopped}", file=sys.stderr)
        return 1
    return 0


def cmd_eval(cfg: Settings, args: argparse.Namespace) -> int:
    from app.evals import evaluate, report
    from app.synth.inbox import generate

    messages, key = generate()
    result = evaluate(
        messages,
        key,
        ResponseCache(SYNTH_RESPONSES),
        model=SYNTH.model,
        effort=SYNTH.effort,
        max_tokens=SYNTH.max_tokens,
    )
    text = report(result, SYNTH.model, SYNTH.effort)
    print(text)
    if args.write:
        (BACKEND.parent / "docs" / "results.md").write_text(text, encoding="utf-8")
        print("wrote docs/results.md")
    return 0


def cmd_gmail_login(cfg: Settings, _: argparse.Namespace) -> int:
    from app.providers.gmail import GmailSetupError, login

    try:
        login(cfg.gmail_dir)
    except GmailSetupError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"Signed in. Token saved to {cfg.gmail_dir / 'token.json'} (owner-only).")
    return 0


def cmd_export_static(cfg: Settings, _: argparse.Namespace) -> int:
    """Real API responses for the synthetic inbox, fetched the way the dashboard does. Refuses real mail."""
    import json
    import shutil

    from app.providers.synthetic import SyntheticProvider
    from app.views import inbox_view, message_view

    store = Store(":memory:")
    provider = SyntheticProvider()  # always synthetic, whatever MTA_PROVIDER says
    sync(store, provider)
    result = run_triage(
        store,
        None,
        ResponseCache(SYNTH_RESPONSES),
        model=SYNTH.model,
        effort=SYNTH.effort,
        max_tokens=SYNTH.max_tokens,
        max_calls=0,
    )
    missing = result.summary.counts().get("budget", 0)
    if missing:
        print(
            f"{missing} synthetic emails have no stored answer, so the demo would show them as 'not triaged yet'. "
            "Run `triage --live` on the synthetic inbox first.",
            file=sys.stderr,
        )
        return 1
    out = BACKEND.parent / "frontend" / "static-demo" / "demo"
    shutil.rmtree(out, ignore_errors=True)
    (out / "messages").mkdir(parents=True)
    inbox = inbox_view(store, provider.name)
    assert inbox["synthetic"] is True
    (out / "inbox.json").write_text(json.dumps(inbox, indent=1), encoding="utf-8")
    for m in store.messages():
        view = message_view(store, provider.name, m.id)
        (out / "messages" / f"{m.id}.json").write_text(json.dumps(view), encoding="utf-8")
    print(f"wrote {out} ({inbox['counts']['inbox']} synthetic messages)")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="rebuild the synthetic database from stored responses (no API calls)")
    p = sub.add_parser("estimate", help="rough cost of triaging what has no answer yet")
    p.add_argument("--force", action="store_true", help="count every inbox message, answered or not")
    p = sub.add_parser("triage", help="triage what has no answer yet")
    p.add_argument("--live", action="store_true", help="allow real API calls (otherwise cache only)")
    p.add_argument("--max-calls", type=int, help="cap on live calls this run (default MTA_MAX_CALLS)")
    p.add_argument("--force", action="store_true", help="re-ask messages that already have an answer")
    p = sub.add_parser("eval", help="score stored answers for the synthetic inbox against its answer key")
    p.add_argument("--write", action="store_true", help="also write docs/results.md")
    sub.add_parser("gmail-login", help="sign in to Gmail once (browser consent)")
    sub.add_parser("export-static", help="write the SYNTHETIC demo snapshot for the hosted page")
    args = parser.parse_args(argv)
    cfg = settings()
    try:
        return {
            "demo": cmd_demo,
            "estimate": cmd_estimate,
            "triage": cmd_triage,
            "eval": cmd_eval,
            "gmail-login": cmd_gmail_login,
            "export-static": cmd_export_static,
        }[args.command](cfg, args)
    except Exception as exc:
        if type(exc).__name__ == "GmailSetupError":
            print(exc, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
