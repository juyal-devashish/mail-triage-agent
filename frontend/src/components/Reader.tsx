import { useEffect, useState } from "react";
import type { Backend } from "../api";
import { dueLabel, urgency } from "../format";
import { BUCKET_LABEL, type Bucket, type Item, type ConversationDetail, type Email, type RuleScope } from "../types";
import { MoveMenu } from "./MoveMenu";
import { Chevron } from "./Pixels";

interface Props {
  id: string;
  backend: Backend;
  now: Date;
  version: number; // bumps after any change, so the verdict shown stays current
  onClose: () => void;
  onArchive: (ids: string[], label: string) => void;
  onMove: (item: Item, bucket: Bucket, scope: RuleScope) => void;
}

// The sanitised HTML still goes into a sandboxed frame with a strict CSP: no scripts, no remote
// images or fonts, so opening an email can't phone home. Links open in a new tab.
const CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:";

function frameDoc(html: string, dark: boolean): string {
  const fg = dark ? "#e6e4df" : "#1d1c1a";
  const link = dark ? "#8fb0ff" : "#2f5bea";
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${CSP}">
<style>body{margin:0;padding:4px 2px;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:${fg};background:transparent;word-wrap:break-word}
a{color:${link}}table{max-width:100%}h1{font-size:20px}h2{font-size:17px}</style></head><body>${html}</body></html>`;
}

const SOURCE_TEXT: Record<Item["source"], string> = {
  model: "Claude's call",
  rule: "Your sender rule",
  correction: "You moved this",
  fallback: "Not triaged",
};

export function Reader({ id, backend, now, version, onClose, onArchive, onMove }: Props) {
  const [msg, setMsg] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

  useEffect(() => {
    let live = true;
    setError(null);
    backend
      .conversation(id)
      .then((m) => live && setMsg(m))
      .catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [id, backend, version]);

  if (error) {
    return (
      <aside className="reader">
        <div className="reader-bar">
          <button className="btn ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="error">Couldn't load this email. {error}</p>
      </aside>
    );
  }
  if (!msg || msg.id !== id) {
    return (
      <aside className="reader">
        <p className="muted pad">Loading…</p>
      </aside>
    );
  }
  const u = urgency(msg.deadline, now);
  return (
    <aside className="reader" aria-label="Email">
      <div className="reader-bar">
        <button className="btn ghost" onClick={onClose} title="Close (Esc)">
          Close
        </button>
        <div className="row-actions always">
          {msg.gmail_url && (
            <a className="btn ghost" href={msg.gmail_url} target="_blank" rel="noopener noreferrer">
              Open in Gmail
            </a>
          )}
          <MoveMenu item={msg} onMove={(b, s) => onMove(msg, b, s)} />
          <button className="btn" onClick={() => onArchive([msg.id], "1 conversation")}>
            Archive
          </button>
        </div>
      </div>
      <div className={`verdict verdict-${msg.bucket} edge-${msg.bucket === "needs_you" ? u : msg.bucket}`}>
        <div className="verdict-top">
          <span className={`pill pill-${msg.bucket}`}>{BUCKET_LABEL[msg.bucket]}</span>
          <span className="verdict-source">
            {SOURCE_TEXT[msg.source]}
            {msg.source === "model" && `, ${msg.confidence} confidence`}
          </span>
          {msg.deadline && <span className={`due due-${u}`}>{dueLabel(msg.deadline, now)}</span>}
        </div>
        <p className="verdict-summary">{msg.summary}</p>
        <p className="verdict-reason">{msg.reason}</p>
        {msg.action && (
          <p className="next-step">
            <Chevron size={9} />
            {msg.action}
          </p>
        )}
      </div>
      <header className="mail-head">
        <h2>{msg.subject}</h2>
        <p className="small muted">
          {msg.count === 1 ? "1 email" : `${msg.count} emails`} with {msg.participants.join(", ") || "you"}
        </p>
      </header>
      <ol className="thread">
        {msg.messages.map((m, i) => (
          <ThreadEmail key={m.id} email={m} dark={dark} startOpen={i === msg.messages.length - 1 || m.unread} />
        ))}
      </ol>
    </aside>
  );
}

/** One email in the conversation. Earlier read emails start folded to a one-line preview, as in Gmail. */
function ThreadEmail({ email, dark, startOpen }: { email: Email; dark: boolean; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  const when = new Date(email.date).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  const preview = email.body_text.replace(/\s+/g, " ").slice(0, 140);
  return (
    <li className={`thread-email${open ? " open" : ""}${email.mine ? " mine" : ""}`}>
      <button className="thread-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="thread-from">
          {email.mine ? "You" : email.from_name}
          {!email.mine && <span className="muted"> &lt;{email.from_email}&gt;</span>}
        </span>
        <time className="when" dateTime={email.date}>
          {when}
        </time>
        {!open && <span className="thread-preview">{preview}</span>}
      </button>
      {open && (
        <div className="mail-body">
          <p className="small muted">To {email.to}</p>
          {email.body_html ? (
            <>
              <iframe
                title={`Email from ${email.from_name}`}
                sandbox="allow-popups allow-popups-to-escape-sandbox"
                srcDoc={frameDoc(email.body_html, dark)}
                referrerPolicy="no-referrer"
              />
              <p className="muted small">Images and scripts are blocked in this view.</p>
            </>
          ) : (
            <pre className="plain">{email.body_text}</pre>
          )}
        </div>
      )}
    </li>
  );
}
