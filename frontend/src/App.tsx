import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Backend } from "./api";
import { Digest, NeedsCard, Row, type ItemHandlers } from "./components/Items";
import { Reader } from "./components/Reader";
import { plural } from "./format";
import { BUCKET_LABEL, type Bucket, type Inbox, type Item, type RuleScope } from "./types";

interface Toast {
  text: string;
  batchId: string | null; // set when the change can be undone
}

type Target = { key: string; kind: "msg"; item: Item } | { key: string; kind: "group"; category: string; items: Item[] };

const KEYS: [string, string][] = [
  ["j / k", "next / previous"],
  ["o or Enter", "open, or expand a digest"],
  ["e", "archive (a whole digest on its header)"],
  ["m", "mark read"],
  ["1 2 3", "move to Needs you / Worth knowing / Noise"],
  ["z", "undo"],
  ["Esc", "close"],
  ["?", "this help"],
];

export function App({ backend }: { backend: Backend }) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<Toast | null>(null);
  const [help, setHelp] = useState(false);
  const [version, setVersion] = useState(0);
  const toastTimer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setInbox(await backend.inbox());
      setVersion((v) => v + 1);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [backend]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const now = useMemo(() => (inbox ? new Date(inbox.as_of) : new Date()), [inbox]);

  const show = useCallback((t: Toast) => {
    setToast(t);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 8000);
  }, []);

  // Everything j/k can land on, in reading order.
  const targets = useMemo<Target[]>(() => {
    if (!inbox) return [];
    const out: Target[] = [];
    for (const item of [...inbox.needs_you, ...inbox.fyi]) out.push({ key: `msg:${item.id}`, kind: "msg", item });
    for (const g of inbox.noise) {
      out.push({ key: `group:${g.category}`, kind: "group", category: g.category, items: g.items });
      if (expanded.has(g.category)) for (const item of g.items) out.push({ key: `msg:${item.id}`, kind: "msg", item });
    }
    return out;
  }, [inbox, expanded]);

  const run = useCallback(
    async (work: () => Promise<Toast | null>) => {
      try {
        const t = await work();
        await refresh();
        if (t) show(t);
      } catch (e) {
        show({ text: `Something went wrong: ${String(e)}`, batchId: null });
      }
    },
    [refresh, show],
  );

  // After an item leaves the view, keep focus near where it was.
  const advanceFrom = useCallback(
    (ids: string[]) => {
      const gone = new Set(ids.map((id) => `msg:${id}`));
      const idx = targets.findIndex((t) => t.key === focusKey);
      const next = targets.slice(idx + 1).find((t) => !gone.has(t.key) && !(t.kind === "group" && t.items.every((i) => ids.includes(i.id))));
      setFocusKey(next?.key ?? null);
      if (openId && ids.includes(openId)) setOpenId(next?.kind === "msg" ? next.item.id : null);
    },
    [targets, focusKey, openId],
  );

  const handlers: ItemHandlers = {
    onOpen: (id) => setOpenId(id),
    onFocus: (key) => setFocusKey(key),
    onArchive: (ids, label) => {
      advanceFrom(ids);
      void run(async () => {
        const r = await backend.act("archive", ids);
        return r.batch_id ? { text: `Archived ${label}`, batchId: r.batch_id } : null;
      });
    },
    onMarkRead: (ids, label) =>
      void run(async () => {
        const r = await backend.act("mark_read", ids);
        return r.batch_id ? { text: `Marked ${label} read`, batchId: r.batch_id } : null;
      }),
    onMove: (item: Item, bucket: Bucket, scope: RuleScope) =>
      void run(async () => {
        const r = await backend.correct(item.id, bucket, scope);
        const others = r.touched.length - 1;
        const extra =
          scope === "sender"
            ? others > 0
              ? ` along with ${plural(others, "other email")} from ${item.from_email}, and future ones will follow`
              : `; future mail from ${item.from_email} will follow`
            : "";
        return { text: `Moved to ${BUCKET_LABEL[bucket]}${extra}.`, batchId: null };
      }),
  };

  const undo = useCallback(() => {
    void run(async () => {
      const r = await backend.undo(toast?.batchId ?? null);
      return r.batch_id ? { text: `Undone: ${plural(r.changed.length, "email")} restored`, batchId: null } : { text: "Nothing to undo", batchId: null };
    });
  }, [backend, run, toast]);

  // Keyboard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [role=menu]") || e.metaKey || e.ctrlKey || e.altKey) return;
      const idx = targets.findIndex((t) => t.key === focusKey);
      const cur = idx >= 0 ? targets[idx] : undefined;
      const move = (d: number) => {
        if (!targets.length) return;
        const n = idx < 0 ? 0 : Math.min(targets.length - 1, Math.max(0, idx + d));
        const t = targets[n];
        setFocusKey(t.key);
        if (openId && t.kind === "msg") setOpenId(t.item.id);
      };
      switch (e.key) {
        case "j":
        case "ArrowDown":
          move(1);
          break;
        case "k":
        case "ArrowUp":
          move(-1);
          break;
        case "o":
        case "Enter":
          if (cur?.kind === "msg") setOpenId(cur.item.id);
          else if (cur?.kind === "group")
            setExpanded((s) => {
              const n = new Set(s);
              if (n.has(cur.category)) n.delete(cur.category);
              else n.add(cur.category);
              return n;
            });
          break;
        case "e":
          if (cur?.kind === "msg") handlers.onArchive([cur.item.id], "1 email");
          else if (cur?.kind === "group") handlers.onArchive(cur.items.map((i) => i.id), plural(cur.items.length, "email"));
          break;
        case "m":
          if (cur?.kind === "msg") handlers.onMarkRead([cur.item.id], "1 email");
          else if (cur?.kind === "group") handlers.onMarkRead(cur.items.map((i) => i.id), plural(cur.items.length, "email"));
          break;
        case "1":
        case "2":
        case "3": {
          const b = (["needs_you", "fyi", "noise"] as const)[Number(e.key) - 1];
          if (cur?.kind === "msg" && cur.item.bucket !== b) handlers.onMove(cur.item, b, "sender");
          break;
        }
        case "z":
          undo();
          break;
        case "Escape":
          if (help) setHelp(false);
          else setOpenId(null);
          break;
        case "?":
          setHelp((h) => !h);
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    if (!focusKey) return;
    document.querySelector(`[data-key="${CSS.escape(focusKey)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focusKey]);

  if (error && !inbox) {
    return (
      <main className="empty-state">
        <h1>Can't reach the triage server</h1>
        <p className="muted">{error}</p>
        <p className="muted">
          Start it with <code>make dev-backend</code>, then reload.
        </p>
      </main>
    );
  }
  if (!inbox) return <main className="empty-state muted">Loading your inbox…</main>;

  const c = inbox.counts;
  const total = Math.max(1, c.inbox);
  const today = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  const allNoise = inbox.noise.flatMap((g) => g.items.map((i) => i.id));
  const unreadFyi = inbox.fyi.filter((i) => i.unread).map((i) => i.id);

  return (
    <div className={`app${openId ? " reading" : ""}`}>
      {inbox.synthetic && (
        <div className="banner">
          <strong>Demo</strong> · a SYNTHETIC inbox for a fictional person. Every sender and email here is made up.
        </div>
      )}
      <div className="layout">
        <main className="review">
          <header className="hero">
            <p className="eyebrow">{today}</p>
            <h1>
              {c.needs_you === 0 ? (
                "Nothing needs you right now."
              ) : (
                <>
                  <span className="hl">{plural(c.needs_you, "email")}</span> {c.needs_you === 1 ? "needs" : "need"} you.
                </>
              )}
            </h1>
            <p className="lede">
              {c.fyi} {c.fyi === 1 ? "is" : "are"} worth a glance, and {c.noise} {c.noise === 1 ? "is" : "are"} noise, folded into{" "}
              {plural(inbox.noise.length, "digest")}. {c.inbox > 0 && `That's ${Math.round((c.noise / total) * 100)}% of your inbox you can skip.`}
            </p>
            <div className="mix" aria-hidden>
              <span className="mix-needs_you" style={{ flexGrow: c.needs_you }} />
              <span className="mix-fyi" style={{ flexGrow: c.fyi }} />
              <span className="mix-noise" style={{ flexGrow: c.noise }} />
            </div>
          </header>

          <section className="section" aria-labelledby="h-needs">
            <div className="section-head">
              <h2 id="h-needs">
                <span className="swatch swatch-needs_you" /> Needs you <span className="count">{c.needs_you}</span>
              </h2>
            </div>
            {inbox.needs_you.length === 0 ? (
              <p className="muted pad">You're clear. Nothing is waiting on you.</p>
            ) : (
              <div className="cards">
                {inbox.needs_you.map((item) => (
                  <NeedsCard key={item.id} item={item} now={now} focused={focusKey === `msg:${item.id}`} open={openId === item.id} {...handlers} />
                ))}
              </div>
            )}
          </section>

          <section className="section" aria-labelledby="h-fyi">
            <div className="section-head">
              <h2 id="h-fyi">
                <span className="swatch swatch-fyi" /> Worth knowing <span className="count">{c.fyi}</span>
              </h2>
              {unreadFyi.length > 0 && (
                <button className="btn ghost" onClick={() => handlers.onMarkRead(unreadFyi, plural(unreadFyi.length, "email"))}>
                  Mark all read
                </button>
              )}
            </div>
            {inbox.fyi.length === 0 ? (
              <p className="muted pad">Nothing here.</p>
            ) : (
              <ul className="rows panel">
                {inbox.fyi.map((item) => (
                  <Row key={item.id} item={item} now={now} focused={focusKey === `msg:${item.id}`} open={openId === item.id} {...handlers} />
                ))}
              </ul>
            )}
          </section>

          <section className="section" aria-labelledby="h-noise">
            <div className="section-head">
              <h2 id="h-noise">
                <span className="swatch swatch-noise" /> Noise <span className="count">{c.noise}</span>
              </h2>
              {allNoise.length > 0 && (
                <button className="btn" onClick={() => handlers.onArchive(allNoise, `all ${plural(allNoise.length, "noise email")}`)}>
                  Archive all noise
                </button>
              )}
            </div>
            {inbox.noise.length === 0 ? (
              <p className="muted pad">No noise. Enjoy it.</p>
            ) : (
              <div className="panel">
                {inbox.noise.map((g) => (
                  <Digest
                    key={g.category}
                    group={g}
                    now={now}
                    expanded={expanded.has(g.category)}
                    focusKey={focusKey}
                    openId={openId}
                    onToggle={() =>
                      setExpanded((s) => {
                        const n = new Set(s);
                        if (n.has(g.category)) n.delete(g.category);
                        else n.add(g.category);
                        return n;
                      })
                    }
                    {...handlers}
                  />
                ))}
              </div>
            )}
          </section>

          {inbox.rules.length > 0 && (
            <section className="section rules" aria-labelledby="h-rules">
              <h2 id="h-rules" className="small-head">
                Your sender rules
              </h2>
              <ul>
                {inbox.rules.map((r) => (
                  <li key={r.pattern}>
                    <code>{r.pattern}</code> → {BUCKET_LABEL[r.bucket]}
                    <button
                      className="btn ghost tiny"
                      onClick={() => void run(async () => (await backend.deleteRule(r.pattern), { text: `Rule for ${r.pattern} removed`, batchId: null }))}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <footer className="foot muted small">
            Press <kbd>?</kbd> for keyboard shortcuts. Claude sorts each email; nothing is archived until you click.
          </footer>
        </main>

        {openId && (
          <Reader
            id={openId}
            backend={backend}
            now={now}
            version={version}
            onClose={() => setOpenId(null)}
            onArchive={handlers.onArchive}
            onMove={handlers.onMove}
          />
        )}
      </div>

      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          {toast.batchId && (
            <button className="btn ghost" onClick={undo}>
              Undo <kbd>z</kbd>
            </button>
          )}
          <button className="btn ghost tiny" aria-label="Dismiss" onClick={() => setToast(null)}>
            ✕
          </button>
        </div>
      )}

      {help && (
        <div className="overlay" onClick={() => setHelp(false)}>
          <div className="help" onClick={(e) => e.stopPropagation()}>
            <h2>Keyboard</h2>
            <dl>
              {KEYS.map(([k, d]) => (
                <div key={k}>
                  <dt>
                    <kbd>{k}</kbd>
                  </dt>
                  <dd>{d}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </div>
  );
}
