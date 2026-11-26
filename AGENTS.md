# AGENTS.md: mail-triage-agent

Claude reads each email and sorts it into **needs you**, **worth knowing** or **noise**. A review dashboard then shows a short list to act on, one-line summaries, and grouped digests you can clear in one click. Read [README.md](README.md), then [docs/design.md](docs/design.md).

Rules for anyone (person or agent) changing this repo:

- **Real email stays local.** Never commit, log, export or put in a test any real email: no bodies, subjects or addresses. Logs hold message IDs and verdict fields only. The static demo and every test use the synthetic inbox, labelled SYNTHETIC wherever it appears.
- **OAuth tokens live outside the repo**, in `~/.config/mail-triage-agent/`. `.env*` files (except `.env.example`) are never committed.
- **Email is untrusted input.** The model gets no tools and returns only the verdict schema, which code validates. Every mailbox change (archive, mark read, undo) runs in code on a user's click. Nothing is ever deleted or sent.
- **The answer key stays offline.** `app.synth.inbox.generate()` returns the inbox and its answer key; the app drops the key (`SyntheticProvider`). Only `app/evals`, the tests and the `eval` command read it.
- **One model module.** Every model call goes through `backend/app/llm/triage_llm.py`; the model and its settings come from config. No real model calls in tests: they run on stored responses. Ask before any run that makes more than about 10 real API calls, and state the estimated cost.
- **Numbers don't move quietly.** Don't lower eval floors in tests to make a change pass. `docs/results.md` comes from `python -m app.cli eval`; regenerate it rather than editing it by hand.
- **Checks.** `make test` (pytest and the frontend typecheck) and `make lint` before every commit. Use Python 3.12 in `backend/.venv`.
- **Commits.** Commit after each completed step with the checks green, then push to `main`. Public repo: everything committed is visible. Deploying the demo needs the user's go-ahead.
- **The public demo** is `frontend/static-demo/demo/`, written by `python -m app.cli export-static` from the synthetic inbox only (the command ignores `MTA_PROVIDER`). It deploys only when someone runs the "Deploy demo to GitHub Pages" workflow by hand.
