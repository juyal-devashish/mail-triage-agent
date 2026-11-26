// The public demo's backend: the exported SYNTHETIC inbox (static-demo/demo/), with archive, mark
// read, undo and corrections applied in the browser only. It mirrors app/service.py so the demo
// behaves like the real app, and resets on reload. No server, no model calls, no real mail.

import type { Backend } from "./api";
import { BUCKET_LABEL, type Action, type ActionResult, type Bucket, type Inbox, type Item, type MessageDetail, type NoiseGroup } from "./types";

interface State {
  base: Inbox; // as exported: the model's verdicts
  items: Map<string, Item>; // current verdicts
  original: Map<string, Item>; // exported verdicts, for when a rule is removed
  inInbox: Set<string>;
  rules: Map<string, Bucket>;
  batches: Map<string, { id: string; field: "inbox" | "unread" }[]>;
  order: string[]; // batch ids, newest last
}

let statePromise: Promise<State> | null = null;

function load(): Promise<State> {
  statePromise ??= fetch("./demo/inbox.json")
    .then((r) => {
      if (!r.ok) throw new Error(`demo data missing (${r.status})`);
      return r.json() as Promise<Inbox>;
    })
    .then((base) => {
      const all = [...base.needs_you, ...base.fyi, ...base.noise.flatMap((g) => g.items)];
      return {
        base,
        items: new Map(all.map((i) => [i.id, { ...i }])),
        original: new Map(all.map((i) => [i.id, { ...i }])),
        inInbox: new Set(all.map((i) => i.id)),
        rules: new Map(),
        batches: new Map(),
        order: [],
      };
    });
  return statePromise;
}

function view(s: State): Inbox {
  const live = [...s.items.values()].filter((i) => s.inInbox.has(i.id)).sort((a, b) => b.date.localeCompare(a.date));
  const needs = live.filter((i) => i.bucket === "needs_you");
  needs.sort((a, b) => (a.deadline === null ? 1 : 0) - (b.deadline === null ? 1 : 0) || (a.deadline ?? "").localeCompare(b.deadline ?? ""));
  const fyi = live.filter((i) => i.bucket === "fyi");
  const labels = new Map(s.base.noise.map((g) => [g.category, g.label]));
  const groups = new Map<string, Item[]>();
  for (const i of live.filter((x) => x.bucket === "noise")) groups.set(i.category, [...(groups.get(i.category) ?? []), i]);
  const noise: NoiseGroup[] = [...groups.entries()]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
    .map(([category, items]) => ({ category, label: labels.get(category) ?? category[0].toUpperCase() + category.slice(1), items }));
  const n = noise.reduce((t, g) => t + g.items.length, 0);
  return {
    ...s.base,
    counts: { needs_you: needs.length, fyi: fyi.length, noise: n, inbox: live.length },
    needs_you: needs,
    fyi,
    noise,
    rules: [...s.rules.entries()].map(([pattern, bucket]) => ({ pattern, bucket })),
  };
}

function ruleFor(s: State, item: Item): Bucket | undefined {
  return s.rules.get(item.from_email.toLowerCase()) ?? s.rules.get(item.from_email.split("@")[1]?.toLowerCase() ?? "");
}

// Same order as app/domain/verdict.py: a rule overrides the model unless they agree.
function redecide(s: State, item: Item): Item {
  const orig = s.original.get(item.id)!;
  const rule = ruleFor(s, item);
  if (!rule || rule === orig.bucket) return { ...orig, unread: item.unread };
  return {
    ...orig,
    unread: item.unread,
    bucket: rule,
    source: "rule",
    confidence: "high",
    reason: `Your rule for ${item.from_email} puts this in ${BUCKET_LABEL[rule]}.`,
    action: rule === "needs_you" ? orig.action : null,
  };
}

export const staticBackend: Backend = {
  inbox: async () => view(await load()),

  message: async (id) => {
    const s = await load();
    const r = await fetch(`./demo/messages/${encodeURIComponent(id)}.json`);
    if (!r.ok) throw new Error(`no such message (${r.status})`);
    const detail = (await r.json()) as MessageDetail;
    return { ...detail, ...s.items.get(id) };
  },

  act: async (action: Action, ids: string[]): Promise<ActionResult> => {
    const s = await load();
    const field = action === "archive" ? "inbox" : "unread";
    const changed = ids.filter((id) => (field === "inbox" ? s.inInbox.has(id) : s.items.get(id)?.unread));
    if (!changed.length) return { batch_id: null, changed: [] };
    for (const id of changed) {
      if (field === "inbox") s.inInbox.delete(id);
      else s.items.set(id, { ...s.items.get(id)!, unread: false });
    }
    const batchId = Math.random().toString(36).slice(2, 14);
    s.batches.set(batchId, changed.map((id) => ({ id, field })));
    s.order.push(batchId);
    return { batch_id: batchId, changed };
  },

  undo: async (batchId) => {
    const s = await load();
    const id = batchId ?? s.order[s.order.length - 1];
    const batch = id ? s.batches.get(id) : undefined;
    if (!id || !batch) return { batch_id: null, changed: [] };
    for (const { id: mid, field } of batch) {
      if (field === "inbox") s.inInbox.add(mid);
      else s.items.set(mid, { ...s.items.get(mid)!, unread: true });
    }
    s.batches.delete(id);
    s.order = s.order.filter((b) => b !== id);
    return { batch_id: id, changed: batch.map((b) => b.id) };
  },

  correct: async (id, bucket, scope) => {
    const s = await load();
    const item = s.items.get(id);
    if (!item) throw new Error("no such message");
    s.items.set(id, { ...item, bucket, source: "correction", reason: `You moved this to ${BUCKET_LABEL[bucket]}.` });
    if (scope === "none") return { touched: [id] };
    const pattern = scope === "sender" ? item.from_email.toLowerCase() : item.from_email.split("@")[1].toLowerCase();
    s.rules.set(pattern, bucket);
    const moved: string[] = [];
    for (const other of s.items.values()) {
      if (other.id === id || other.source === "correction") continue;
      const sameSender = other.from_email.toLowerCase() === pattern || other.from_email.split("@")[1]?.toLowerCase() === pattern;
      if (!sameSender) continue;
      const next = redecide(s, other);
      if (next.bucket !== other.bucket) moved.push(other.id);
      s.items.set(other.id, next);
    }
    return { touched: [id, ...moved] };
  },

  deleteRule: async (pattern) => {
    const s = await load();
    s.rules.delete(pattern);
    for (const item of s.items.values()) if (item.source !== "correction") s.items.set(item.id, redecide(s, item));
  },
};
