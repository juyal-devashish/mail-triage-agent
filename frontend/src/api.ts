// The dashboard talks to a Backend. In development and locally that is the FastAPI server; the
// public demo swaps in a browser-only backend over the exported SYNTHETIC inbox (see staticBackend.ts).

import type { Action, ActionResult, Bucket, Inbox, MessageDetail, RuleScope } from "./types";

export interface Backend {
  inbox(): Promise<Inbox>;
  message(id: string): Promise<MessageDetail>;
  act(action: Action, ids: string[]): Promise<ActionResult>;
  undo(batchId?: string | null): Promise<ActionResult>;
  correct(id: string, bucket: Bucket, scope: RuleScope): Promise<{ touched: string[] }>;
  deleteRule(pattern: string): Promise<void>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export const httpBackend: Backend = {
  inbox: () => call<Inbox>("/api/inbox"),
  message: (id) => call<MessageDetail>(`/api/messages/${encodeURIComponent(id)}`),
  act: (action, ids) => call<ActionResult>("/api/actions", { method: "POST", body: JSON.stringify({ action, ids }) }),
  undo: (batchId) => call<ActionResult>("/api/undo", { method: "POST", body: JSON.stringify({ batch_id: batchId ?? null }) }),
  correct: (id, bucket, scope) =>
    call<{ touched: string[] }>(`/api/messages/${encodeURIComponent(id)}/correct`, {
      method: "POST",
      body: JSON.stringify({ bucket, scope }),
    }),
  deleteRule: async (pattern) => {
    await call<{ ok: true }>(`/api/rules/${encodeURIComponent(pattern)}`, { method: "DELETE" });
  },
};
