# Using your own Gmail

Everything runs on your machine. Your mail goes to two places only: Gmail (where it already is) and
the Claude API, which reads each email to sort it. Messages, verdicts and cached model responses stay
in `backend/data/` (git-ignored). The OAuth client and token stay in `~/.config/mail-triage-agent/`.

The app asks for the `gmail.modify` scope. It reads mail and changes labels, and the code only ever
removes or re-adds `INBOX` (archive) and `UNREAD` (mark read). It never deletes, trashes or sends.
`GmailProvider.modify` refuses any other label.

## 1. Create an OAuth client (once, about 5 minutes)

You do this step in the Google Cloud console, signed in as yourself.

1. Go to <https://console.cloud.google.com/>, create a project (for example `mail-triage`).
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform): user type **External**, app name
   of your choice, your email as support and developer contact. Under **Audience → Test users**, add
   your own Gmail address.
4. **Data access**: add the scope `https://www.googleapis.com/auth/gmail.modify`.
5. **Clients → Create client**: type **Desktop app**. Download the JSON.
6. Save it as `~/.config/mail-triage-agent/client_secret.json` and run
   `chmod 600 ~/.config/mail-triage-agent/client_secret.json`.

### Testing vs. In production

Google issues refresh tokens that **expire after 7 days** to apps whose consent screen is External
and in **Testing** status. You then see "Gmail sign-in expired" and run `gmail-login` again.

To avoid the weekly sign-in, set the publishing status to **In production**. Without verification,
Google shows an "unverified app" warning on the consent screen (you click through it as the
developer), and the app is limited to 100 users. That's fine for personal use. Either way, only
accounts you sign in with can be read.

## 2. Sign in

```sh
cd backend
.venv/bin/python -m app.cli gmail-login
```

A browser window opens for consent. The token is written to `~/.config/mail-triage-agent/token.json`,
readable only by you.

## 3. Triage and review

```sh
export MTA_PROVIDER=gmail
.venv/bin/python -m app.cli estimate                 # what a run would cost, no calls
.venv/bin/python -m app.cli triage --live --max-calls 10
make dev-backend   # in one terminal (with MTA_PROVIDER=gmail)
make dev-frontend  # in another, then open http://localhost:5173
```

`triage` syncs the last `MTA_GMAIL_DAYS` days of your inbox (default 7, at most
`MTA_GMAIL_MAX_MESSAGES`), then asks Claude about messages that have no verdict yet. Live calls stop
at `--max-calls`; the rest show as "Not triaged yet" until the next run. Each email is asked about
once; re-runs use the cache.

Archiving or marking read in the dashboard changes Gmail straight away. Undo puts the labels back.
