# The conversation, not the email, is the unit of triage

On real Gmail, judging each email on its own showed a five-reply thread five times and kept an old "needs you" email flagged after you had already answered it in the same thread. So we triage conversations (Gmail threads): one verdict per conversation, judged on its latest email with the earlier ones as context, and "you sent the last reply" counts as evidence that it doesn't need you. Archive, undo, moves and sender rules all act on whole conversations, and a new reply makes Gmail return a conversation to the inbox, where it's judged again from scratch.

## Considered options

- **Per email (what the first build did).** Simpler, and it matches the synthetic demo inbox. But it duplicates threads and can't see who replied last.
- **Per conversation, judged on its latest email only.** Cheaper, but it loses the context that makes "Thanks, see you Tuesday" mean something.

## Consequences

The store, verdicts, undo log and dashboard move from message IDs to thread IDs. Each request to Claude grows with the length of the conversation, so earlier emails are trimmed first. The synthetic inbox needs some multi-email conversations so the tests and the demo exercise this.
