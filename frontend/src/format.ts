const DAY = 86_400_000;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "9:14 AM", "Yesterday", "Tue", "Nov 12": how far back the email arrived, relative to `now`. */
export function when(iso: string, now: Date): string {
  const d = new Date(iso);
  const days = Math.round((startOfDay(now) - startOfDay(d)) / DAY);
  if (days <= 0) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export type Urgency = "overdue" | "today" | "soon" | "later" | "none";

/** Days from `now` to an ISO date (YYYY-MM-DD), in local calendar days. */
export function daysUntil(deadline: string, now: Date): number {
  const [y, m, d] = deadline.split("-").map(Number);
  return Math.round((new Date(y, m - 1, d).getTime() - startOfDay(now)) / DAY);
}

export function urgency(deadline: string | null, now: Date): Urgency {
  if (!deadline) return "none";
  const n = daysUntil(deadline, now);
  if (n < 0) return "overdue";
  if (n <= 1) return "today";
  if (n <= 4) return "soon";
  return "later";
}

export function dueLabel(deadline: string, now: Date): string {
  const n = daysUntil(deadline, now);
  if (n < 0) return `Overdue ${-n}d`;
  if (n === 0) return "Due today";
  if (n === 1) return "Due tomorrow";
  const [y, m, d] = deadline.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return n < 7
    ? `Due ${date.toLocaleDateString([], { weekday: "short" })}`
    : `Due ${date.toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}
