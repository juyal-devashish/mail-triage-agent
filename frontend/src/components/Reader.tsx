import { useEffect, useState } from "react";
import type { Backend } from "../api";
import { dueLabel, urgency } from "../format";
import { BUCKET_LABEL, type Bucket, type Item, type MessageDetail, type RuleScope } from "../types";
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
  const [msg, setMsg] = useState<MessageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

  useEffect(() => {
    let live = true;
    setError(null);
    backend
      .message(id)
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
          <button className="btn" onClick={() => onArchive([msg.id], "1 email")}>
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
        <p className="small">
          <strong>{msg.from_name}</strong> <span className="muted">&lt;{msg.from_email}&gt;</span>
        </p>
        <p className="small muted">
          To {msg.to}, {new Date(msg.date).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
        </p>
      </header>
      <div className="mail-body">
        {msg.body_html ? (
          <iframe
            title="Email body"
            sandbox="allow-popups allow-popups-to-escape-sandbox"
            srcDoc={frameDoc(msg.body_html, dark)}
            referrerPolicy="no-referrer"
          />
        ) : (
          <pre className="plain">{msg.body_text}</pre>
        )}
        {msg.body_html && <p className="muted small">Images and scripts are blocked in this view.</p>}
      </div>
    </aside>
  );
}
