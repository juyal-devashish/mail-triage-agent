import type { Inbox, Item } from "../types";

/** Mistral-style pixel chevron: five squares on a 3x5 grid. Inherits the text colour. */
export function Chevron({ size = 10 }: { size?: number }) {
  return (
    <svg className="chevron-px" width={(size * 3) / 5} height={size} viewBox="0 0 3 5" aria-hidden shapeRendering="crispEdges">
      <rect x="0" y="0" width="1" height="1" fill="currentColor" />
      <rect x="1" y="1" width="1" height="1" fill="currentColor" />
      <rect x="2" y="2" width="1" height="1" fill="currentColor" />
      <rect x="1" y="3" width="1" height="1" fill="currentColor" />
      <rect x="0" y="4" width="1" height="1" fill="currentColor" />
    </svg>
  );
}

/** The brand mark: a 3x3 block stepping down the heat scale, the same colours that mark urgency in the app. */
export function Mark() {
  const cells: [number, number, string][] = [
    [0, 0, "var(--ember)"], [1, 0, "var(--flame)"], [2, 0, "var(--tangerine)"],
    [0, 1, "var(--flame)"], [1, 1, "var(--tangerine)"], [2, 1, "var(--amber)"],
    [0, 2, "var(--tangerine)"], [1, 2, "var(--amber)"], [2, 2, "var(--ash)"],
  ]; // prettier-ignore
  return (
    <svg width="18" height="18" viewBox="0 0 3 3" aria-hidden shapeRendering="crispEdges">
      {cells.map(([x, y, c]) => (
        <rect key={`${x}${y}`} x={x} y={y} width="1" height="1" fill={c} />
      ))}
    </svg>
  );
}

interface InboxPixelsProps {
  inbox: Inbox;
  onOpen: (id: string) => void;
}

/**
 * The whole inbox at a glance: one square per conversation, needs-you first, then worth-knowing, then noise.
 * Squares disappear as mail is archived. Each square opens its conversation.
 */
export function InboxPixels({ inbox, onOpen }: InboxPixelsProps) {
  const runs: [Item["bucket"], Item[]][] = [
    ["needs_you", inbox.needs_you],
    ["fyi", inbox.fyi],
    ["noise", inbox.noise.flatMap((g) => g.items)],
  ];
  let n = 0;
  return (
    <div className="pixels" role="list" aria-label={`${inbox.counts.inbox} conversations in your inbox`}>
      {runs.map(([bucket, items]) =>
        items.map((item) => (
          <button
            key={item.id}
            role="listitem"
            className={`px px-${bucket}`}
            style={{ animationDelay: `${Math.min(n++ * 6, 900)}ms` }}
            title={`${item.from_name}: ${item.summary}`}
            aria-label={`${item.from_name}: ${item.summary}`}
            onClick={() => onOpen(item.id)}
          />
        )),
      )}
    </div>
  );
}
