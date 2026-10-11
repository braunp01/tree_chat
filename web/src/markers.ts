// Anchor_Marker logic (Req 5): one marker per distinct passage, with a count where passages coincide.
import type { Marker, Status } from "./api";

export interface MarkerGroup {
  start: number;
  end: number;
  /** The branches anchored on exactly this passage, oldest first. */
  markers: Marker[];
  /** The most active Status among them: open, then parked, then closed. */
  status: Status;
}

const RANK: Record<Status, number> = { open: 0, parked: 1, closed: 2 };

export function groupMarkers(markers: Marker[]): MarkerGroup[] {
  const groups = new Map<string, MarkerGroup>();
  for (const m of markers) {
    const key = `${m.start}:${m.end}`;
    const g = groups.get(key);
    if (g) g.markers.push(m);
    else groups.set(key, { start: m.start, end: m.end, markers: [m], status: m.status });
  }
  const out = [...groups.values()];
  for (const g of out) g.status = g.markers.map((m) => m.status).sort((a, b) => RANK[a] - RANK[b])[0]!;
  return out.sort((a, b) => a.start - b.start || a.end - b.end);
}

/** Does a rendered run covering source [s, e) overlap the passage [start, end)? (Req 5.2 highlight) */
export function overlaps(s: number, e: number, start: number, end: number): boolean {
  return s < end && start < e;
}

/** Label for a Branch in lists: the user's Intent, else the labelled generated one, else nothing (Req 5.2, 11.4). */
export function intentLabel(m: { intent: string | null; generated_intent: string | null }): { text: string; generated: boolean } | null {
  if (m.intent) return { text: m.intent, generated: false };
  if (m.generated_intent) return { text: m.generated_intent, generated: true };
  return null;
}
