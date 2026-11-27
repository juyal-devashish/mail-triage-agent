# Plan: tailor the app to Devashish's Gmail

Settled in a planning session on 2026-11-27. Terms are defined in [GLOSSARY.md](../GLOSSARY.md). General production (other people's inboxes) comes after this phase.

## Decisions

1. **Inbox:** the user's personal Gmail. Work Outlook is out of scope.
2. **Unit:** the conversation ([ADR 0001](adr/0001-conversation-is-the-unit-of-triage.md)). "You sent the last reply" is evidence against Needs you, unless a due date is near.
3. **Profile:** a local `profile.md` (git-ignored) in Claude's instructions for every verdict. The first draft comes from Gmail metadata only (people the user writes to most in 90 days; senders they leave unread or archive straight away); the user edits it before the first triage.
4. **Job category:**
   - **Needs you:** a recruiter writing personally, interview invitations and scheduling, assessments with a deadline, offers, requests for documents.
   - **Worth knowing:** "application moved forward" with no action, and rejections.
   - **Noise:** automated "application received", job-board alerts and mass recruiter blasts, in a Job leads digest.
5. **Sync:** the first sync covers 14 days. After that: a Sync now button, plus a background sync every 30 minutes.
6. **Spend cap:** $10 a month, with a warning on the dashboard at 80%.
7. **OAuth:** switch the app to In production once the first sign-in works.
8. **Re-triage:** a new reply in a conversation means a fresh verdict. Sender rules still apply; a conversation the user moved keeps that section until something new arrives.
9. **Notifications:** a macOS notification when a new conversation lands in Needs you, showing the sender and summary only, never between 22:00 and 08:00.
10. **Gmail writes:** archive, mark read, and the one triage label "Triage/Needs you". Nothing else.
11. **Retention:** a conversation's text and the cached model answer are kept while it's in the inbox plus 30 days; after that only its ID, verdict and rule data are kept.
12. **Measuring on real mail:** the user hand-sorts 50 conversations into a local test set; prompt or model changes must pass it before they're used. The dashboard also shows "misses this week" from Moves, with hidden Needs-you conversations counted on their own.
13. **Dashboard:** each conversation shows how many emails it has, a "You replied" marker when the last email was the user's, and the other participants. The side panel shows the whole conversation, Gmail-style.

## Done when

- Two weeks of daily use.
- No Needs-you conversation ever hidden in noise.
- At least 90% of Needs-you conversations found, on the hand-sorted 50.
- Fewer than 3 Moves a day by the second week.
- Monthly spend under the cap.
- The user stops opening Gmail first in the morning.

## Build order

1. Conversations as the unit (store, verdicts, the request to Claude), with multi-email conversations added to the synthetic inbox.
2. Profile template and the draft from sent mail; the job category and the Job leads digest.
3. Spend cap, retention cleanup, the Sync now button, and the conversation display.
4. The user creates the OAuth client and signs in; Claude drafts the profile and the user edits it.
5. First real sync (14 days), after showing the estimated cost and getting a go-ahead.
6. The sorting view and the user's 50 conversations; misses this week.
7. The triage label, the 30-minute background sync and notifications.
8. Switch the OAuth app to In production; the two weeks start.
