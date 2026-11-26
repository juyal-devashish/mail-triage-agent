# mail-triage-agent

Most email needs no attention, but you still have to open it to find that out. In this app Claude reads each email and sorts it, and you review a short dashboard instead of your inbox:

- **Needs you:** the few emails that need a reply, a decision or a deadline, each with a one-line reason and a suggested next step.
- **Worth knowing:** one line per email, readable in seconds.
- **Noise:** newsletters, promotions, notifications and receipts, grouped into digests you can archive in one click, with undo.

Wrong call? Move the email and the app turns that into a rule for the sender.

It runs locally against your Gmail (archive and mark read only, never delete or send). A public demo runs on a **synthetic** inbox.

Status: under construction. See [docs/design.md](docs/design.md) for the design.

## Run it

```sh
make install   # backend venv + frontend deps
make demo      # build the synthetic inbox (no API calls)
make dev-backend   # API on :8000
make dev-frontend  # UI on :5173
```

## License

MIT
