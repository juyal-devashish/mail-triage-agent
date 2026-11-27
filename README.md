# mail-triage-agent

Most email needs no attention, but you still have to open it to find that out. In this app Claude reads each email and sorts it, and you review a short dashboard instead of your inbox:

- **Needs you:** the few emails that need a reply, a decision or a deadline, each with a one-line reason and a suggested next step.
- **Worth knowing:** one line per email, readable in seconds.
- **Noise:** newsletters, promotions, notifications and receipts, grouped into digests you can archive in one click, with undo.

Wrong call? Move the email and the app turns that into a rule for the sender.

It runs locally against your Gmail (archive and mark read only, never delete or send).

**Live demo:** <https://juyal-devashish.github.io/mail-triage-agent/>, on a **synthetic** inbox for a fictional person. Archive, undo and corrections work in your browser and reset on reload.

See [docs/design.md](docs/design.md) for the design, [docs/gmail.md](docs/gmail.md) to connect your own inbox, and `docs/results.md` (written by `eval --write` once the synthetic inbox has stored model answers) for how the triage scores against the synthetic answer key.

## Run it

```sh
make install   # backend venv + frontend deps
make demo      # build the synthetic inbox (no API calls)
make dev-backend   # API on :8000
make dev-frontend  # UI on :5173
```

## Commands

Run from `backend/` with `.venv/bin/python -m app.cli <command>`:

| Command | What it does |
|---|---|
| `demo` | Rebuild the synthetic database from stored responses. No API calls. |
| `estimate` | Rough cost of triaging whatever has no verdict yet. No API calls. |
| `triage --live --max-calls N` | Ask Claude about up to N emails that have no verdict yet. Without `--live`, cache only. |
| `gmail-login` | Sign in to Gmail once (see docs/gmail.md). |
| `eval --write` | Score the synthetic inbox against its answer key and rewrite docs/results.md. |
| `export-static` | Write the synthetic demo snapshot for the hosted page. |

## How it stays safe

- Claude gets one email at a time, with no tools, and returns a fixed JSON verdict. Text in an email can't make the app do anything.
- Code has the last word: your sender rules win, failed answers and unsure noise stay visible, and nothing is archived until you click.
- The only mailbox changes are archive and mark read, each with undo. The Gmail adapter refuses any other label change.
- Real mail stays on your machine (`backend/data/`, git-ignored), apart from the model call itself.

## License

MIT
