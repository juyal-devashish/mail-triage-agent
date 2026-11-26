import { dueLabel, urgency, when } from "../format";
import type { Bucket, Item, NoiseGroup, RuleScope } from "../types";
import { MoveMenu } from "./MoveMenu";

export interface ItemHandlers {
  onOpen: (id: string) => void;
  onArchive: (ids: string[], label: string) => void;
  onMarkRead: (ids: string[], label: string) => void;
  onMove: (item: Item, bucket: Bucket, scope: RuleScope) => void;
  onFocus: (key: string) => void;
}

const SOURCE_NOTE: Record<Item["source"], string | null> = {
  model: null,
  rule: "your rule",
  correction: "you moved this",
  fallback: "not triaged",
};

function Sender({ item }: { item: Item }) {
  return (
    <span className="sender" title={item.from_email}>
      {item.unread && <span className="unread-dot" aria-label="unread" />}
      {item.from_name || item.from_email}
    </span>
  );
}

function SourceTag({ item }: { item: Item }) {
  const note = SOURCE_NOTE[item.source];
  if (note) return <span className={`tag tag-${item.source}`}>{note}</span>;
  if (item.confidence === "low") return <span className="tag tag-unsure">unsure</span>;
  return null;
}

interface CardProps extends ItemHandlers {
  item: Item;
  now: Date;
  focused: boolean;
  open: boolean;
}

/** A needs-you card: what it says, why it's here, what to do, and when. */
export function NeedsCard({ item, now, focused, open, ...h }: CardProps) {
  const u = urgency(item.deadline, now);
  const key = `msg:${item.id}`;
  return (
    <article
      className={`card urgency-${u}${focused ? " focused" : ""}${open ? " is-open" : ""}`}
      data-key={key}
      onClick={() => {
        h.onFocus(key);
        h.onOpen(item.id);
      }}
    >
      <header className="card-meta">
        <Sender item={item} />
        <span className="dot-sep">·</span>
        <time dateTime={item.date}>{when(item.date, now)}</time>
        <SourceTag item={item} />
        {item.deadline && <span className={`due due-${u}`}>{dueLabel(item.deadline, now)}</span>}
      </header>
      <p className="card-summary">{item.summary}</p>
      <p className="card-reason">{item.reason}</p>
      <footer className="card-foot">
        {item.action ? <span className="next-step">→ {item.action}</span> : <span />}
        <div className="row-actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn" onClick={() => h.onArchive([item.id], "1 email")} title="Done: archive (e)">
            Done
          </button>
          <MoveMenu item={item} onMove={(b, s) => h.onMove(item, b, s)} />
        </div>
      </footer>
    </article>
  );
}

interface RowProps extends ItemHandlers {
  item: Item;
  now: Date;
  focused: boolean;
  open: boolean;
  showReason?: boolean;
}

/** One compact line: sender, the one-line summary, time, and quick actions on hover or focus. */
export function Row({ item, now, focused, open, showReason, ...h }: RowProps) {
  const key = `msg:${item.id}`;
  return (
    <li
      className={`row${focused ? " focused" : ""}${open ? " is-open" : ""}${item.unread ? " unread" : ""}`}
      data-key={key}
      onClick={() => {
        h.onFocus(key);
        h.onOpen(item.id);
      }}
    >
      <Sender item={item} />
      <span className="row-text">
        <span className="row-summary">{item.summary}</span>
        {showReason && <span className="row-reason">{item.reason}</span>}
      </span>
      <SourceTag item={item} />
      <time className="row-time" dateTime={item.date}>
        {when(item.date, now)}
      </time>
      <span className="row-actions" onClick={(e) => e.stopPropagation()}>
        {item.unread && (
          <button className="btn ghost" onClick={() => h.onMarkRead([item.id], "1 email")} title="Mark read (m)">
            Read
          </button>
        )}
        <button className="btn ghost" onClick={() => h.onArchive([item.id], "1 email")} title="Archive (e)">
          Archive
        </button>
        <MoveMenu item={item} onMove={(b, s) => h.onMove(item, b, s)} />
      </span>
    </li>
  );
}

interface GroupProps extends ItemHandlers {
  group: NoiseGroup;
  now: Date;
  expanded: boolean;
  focusKey: string | null;
  openId: string | null;
  onToggle: () => void;
}

/** A collapsed digest: "Promotions · 35 from Gearloft, Cartwheel and 3 more", with Archive all. */
export function Digest({ group, now, expanded, focusKey, openId, onToggle, ...h }: GroupProps) {
  const key = `group:${group.category}`;
  const senders = [...new Set(group.items.map((i) => i.from_name || i.from_email))];
  const shown = senders.slice(0, 3).join(", ");
  const more = senders.length > 3 ? ` and ${senders.length - 3} more` : "";
  const unread = group.items.filter((i) => i.unread).length;
  const ids = group.items.map((i) => i.id);
  const label = `${group.items.length} ${group.label.toLowerCase()}`;
  return (
    <section className={`digest${expanded ? " expanded" : ""}`}>
      <div
        className={`digest-head${focusKey === key ? " focused" : ""}`}
        data-key={key}
        onClick={() => {
          h.onFocus(key);
          onToggle();
        }}
        role="button"
        aria-expanded={expanded}
      >
        <span className="chevron" aria-hidden>
          ›
        </span>
        <span className="digest-title">
          {group.label} <span className="count">{group.items.length}</span>
        </span>
        <span className="digest-senders">
          {shown}
          {more}
          {unread > 0 && <span className="digest-unread"> · {unread} unread</span>}
        </span>
        <span className="row-actions always" onClick={(e) => e.stopPropagation()}>
          <button className="btn" onClick={() => h.onArchive(ids, label)} title="Archive all in this digest (e)">
            Archive all
          </button>
        </span>
      </div>
      {expanded && (
        <ul className="rows">
          {group.items.map((item) => (
            <Row
              key={item.id}
              item={item}
              now={now}
              focused={focusKey === `msg:${item.id}`}
              open={openId === item.id}
              showReason
              {...h}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
