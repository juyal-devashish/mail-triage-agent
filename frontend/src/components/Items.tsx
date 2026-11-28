import { dueLabel, urgency, when } from "../format";
import type { Bucket, Item, NoiseGroup, RuleScope } from "../types";
import { MoveMenu } from "./MoveMenu";
import { Chevron } from "./Pixels";

export interface ItemHandlers {
  onOpen: (id: string) => void;
  onArchive: (ids: string[], label: string) => void;
  onMarkRead: (ids: string[], label: string) => void;
  onMove: (item: Item, bucket: Bucket, scope: RuleScope) => void;
  onFocus: (key: string) => void;
}

const SOURCE_NOTE: Record<Item["source"], string | null> = {
  model: null,
  rule: "Your rule",
  correction: "Moved by you",
  fallback: "Not triaged",
};

function SourceTag({ item }: { item: Item }) {
  const note = SOURCE_NOTE[item.source];
  if (note) return <span className={`tag tag-${item.source}`}>{note}</span>;
  if (item.confidence === "low") return <span className="tag tag-unsure">Unsure</span>;
  return null;
}

function Unread({ item }: { item: Item }) {
  return item.unread ? <span className="unread-px" aria-label="Unread" /> : null;
}

interface NeedsProps extends ItemHandlers {
  item: Item;
  now: Date;
  focused: boolean;
  open: boolean;
}

/** One needs-you row: a heat block with the due date, then what it says, why, and the next step. */
export function NeedsRow({ item, now, focused, open, ...h }: NeedsProps) {
  const u = urgency(item.deadline, now);
  const key = `msg:${item.id}`;
  return (
    <article
      className={`need${focused ? " focused" : ""}${open ? " is-open" : ""}`}
      data-key={key}
      onClick={() => {
        h.onFocus(key);
        h.onOpen(item.id);
      }}
    >
      <div className={`heat heat-${u}`}>{item.deadline ? dueLabel(item.deadline, now) : "No date"}</div>
      <div className="need-body">
        <div className="need-meta">
          <Unread item={item} />
          <span className="sender" title={item.from_email}>
            {item.from_name || item.from_email}
          </span>
          <SourceTag item={item} />
          <time className="when" dateTime={item.date}>
            {when(item.date, now)}
          </time>
        </div>
        <p className="need-summary">{item.summary}</p>
        <p className="need-reason">{item.reason}</p>
        {item.action && (
          <p className="next-step">
            <Chevron size={9} />
            {item.action}
          </p>
        )}
      </div>
      <div className="need-actions" onClick={(e) => e.stopPropagation()}>
        <button className="btn" onClick={() => h.onArchive([item.id], "1 conversation")} title="Done: archive it (e)">
          Done
        </button>
        <MoveMenu item={item} onMove={(b, s) => h.onMove(item, b, s)} />
      </div>
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
      <span className="row-sender" title={item.from_email}>
        <Unread item={item} />
        <span className="sender">{item.from_name || item.from_email}</span>
      </span>
      <span className="row-text">
        <span className="row-summary">{item.summary}</span>
        {showReason && <span className="row-reason">{item.reason}</span>}
      </span>
      <SourceTag item={item} />
      <time className="when" dateTime={item.date}>
        {when(item.date, now)}
      </time>
      <span className="row-actions" onClick={(e) => e.stopPropagation()}>
        {item.unread && (
          <button className="btn ghost" onClick={() => h.onMarkRead([item.id], "1 conversation")} title="Mark read (m)">
            Mark read
          </button>
        )}
        <button className="btn ghost" onClick={() => h.onArchive([item.id], "1 conversation")} title="Archive (e)">
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

/** A folded digest: "Promotions 35, from Gearloft, Cartwheel and 3 more", with Archive all. */
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
        <span className="digest-toggle" aria-hidden>
          <Chevron size={9} />
        </span>
        <span className="digest-title">{group.label}</span>
        <span className="digest-count">{group.items.length}</span>
        <span className="digest-senders">
          From {shown}
          {more}
          {unread > 0 && <span className="digest-unread">, {unread} unread</span>}
        </span>
        <span className="digest-actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn" onClick={() => h.onArchive(ids, label)} title="Archive every email in this digest (e)">
            Archive all
          </button>
        </span>
      </div>
      {expanded && (
        <ul className="rows digest-rows">
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
