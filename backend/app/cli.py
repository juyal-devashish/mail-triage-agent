"""
Command line. Run from backend/ with the virtualenv: `python -m app.cli <command>`.

  demo       rebuild the synthetic database from stored responses (never calls the API)
  estimate   rough cost of triaging what has no answer yet
  triage     triage what has no answer yet; live calls need --live and stop at --max-calls
  eval       score stored answers for the synthetic inbox against its answer key
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import BACKEND, Settings, settings
from app.llm.triage_llm import PROMPT_VERSION, ResponseCache, anthropic_transport, estimate_cost, write_run_log
from app.pipeline import run_triage, sync
from app.providers import MailProvider
from app.store import Store

SYNTH_RESPONSES = BACKEND / "app" / "synth" / "responses.jsonl"  # stored answers for the SYNTHETIC inbox only


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
    Path(cfg.db_path).unlink(missing_ok=True)
    store = Store(cfg.db_path)
    sync(store, provider_for(cfg))
    result = run_triage(
        store, None, cache_for(cfg), model=cfg.model, effort=cfg.effort, max_tokens=cfg.max_tokens, max_calls=0
    )
    counts = result.summary.counts()
    print(
        f"synthetic inbox: {result.synced} messages, stored answers for {counts.get('ok', 0)}, "
        f"{counts.get('budget', 0)} without one (shown as 'not triaged yet')"
    )
    print(f"database: {cfg.db_path}")
    return 0


def _todo(store: Store, force: bool) -> list:
    answered = store.answer_versions()
    return [m for m in store.messages() if "INBOX" in m.labels and (force or answered.get(m.id) != PROMPT_VERSION)]


def cmd_estimate(cfg: Settings, args: argparse.Namespace) -> int:
    store = Store(cfg.db_path)
    sync(store, provider_for(cfg))
    todo = _todo(store, args.force)
    cache = cache_for(cfg)
    from app.llm.triage_llm import build_request, request_key

    uncached = [
        m
        for m in todo
        if cache.get(request_key(build_request(m, store.recent_corrections(), cfg.model, cfg.effort, cfg.max_tokens)))
        is None
    ]
    est = estimate_cost(uncached, cfg.input_price, cfg.output_price)
    print(
        f"{len(todo)} to triage, {len(uncached)} not cached: ~{est['input_tokens']:,} input tokens, "
        f"~${est['usd']:.2f} on {cfg.model} (rough estimate)"
    )
    return 0


def cmd_triage(cfg: Settings, args: argparse.Namespace) -> int:
    store = Store(cfg.db_path)
    sync(store, provider_for(cfg))
    transport = anthropic_transport() if args.live else None
    max_calls = args.max_calls if args.max_calls is not None else cfg.max_calls
    result = run_triage(
        store,
        transport,
        cache_for(cfg),
        model=cfg.model,
        effort=cfg.effort,
        max_tokens=cfg.max_tokens,
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
        messages, key, ResponseCache(SYNTH_RESPONSES), model=cfg.model, effort=cfg.effort, max_tokens=cfg.max_tokens
    )
    text = report(result, cfg.model, cfg.effort)
    print(text)
    if args.write:
        (BACKEND.parent / "docs" / "results.md").write_text(text, encoding="utf-8")
        print("wrote docs/results.md")
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
    args = parser.parse_args(argv)
    cfg = settings()
    return {"demo": cmd_demo, "estimate": cmd_estimate, "triage": cmd_triage, "eval": cmd_eval}[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
