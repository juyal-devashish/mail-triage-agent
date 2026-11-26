// Shapes returned by the backend (app/views.py). Keep in step with that file.

export type Bucket = "needs_you" | "fyi" | "noise";
export type Source = "model" | "rule" | "fallback" | "correction";
export type Action = "archive" | "mark_read";
export type RuleScope = "sender" | "domain" | "none";

export interface Item {
  id: string;
  from_name: string;
  from_email: string;
  subject: string;
  date: string;
  unread: boolean;
  bucket: Bucket;
  category: string;
  summary: string;
  reason: string;
  action: string | null;
  deadline: string | null;
  confidence: "high" | "medium" | "low";
  source: Source;
  gmail_url: string | null;
}

export interface NoiseGroup {
  category: string;
  label: string;
  items: Item[];
}

export interface Rule {
  pattern: string;
  bucket: Bucket;
}

export interface Inbox {
  provider: string;
  synthetic: boolean;
  as_of: string;
  counts: { needs_you: number; fyi: number; noise: number; inbox: number };
  needs_you: Item[];
  fyi: Item[];
  noise: NoiseGroup[];
  rules: Rule[];
}

export interface MessageDetail extends Item {
  to: string;
  body_text: string;
  body_html: string | null;
}

export interface ActionResult {
  batch_id: string | null;
  changed: string[];
}

export const BUCKET_LABEL: Record<Bucket, string> = {
  needs_you: "Needs you",
  fyi: "Worth knowing",
  noise: "Noise",
};
