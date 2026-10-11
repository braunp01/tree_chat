// Small pure helpers for drawing the Branch_Graph.
import type { BranchSummary } from "../api";
import { intentLabel } from "../markers";

export const GLYPH = { parked: "○", open: "●", closed: "✓" } as const;

export function clip(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

/** What to call a Branch in the graph (Req 18.2): Intent, else the labelled generated one, else the Anchor quote. */
export function nodeLabel(b: BranchSummary, treeTitle: string | null): { text: string; generated: boolean } {
  if (b.kind === "trunk") return { text: treeTitle ?? "Trunk", generated: false };
  const l = intentLabel(b);
  if (l) return l;
  return { text: b.anchor?.quoted_text ?? "(no label)", generated: false };
}

export function kindLine(b: BranchSummary): string {
  const n = `${b.message_count} msg${b.message_count === 1 ? "" : "s"}`;
  return `${b.kind === "alternative" ? "alternative" : b.kind} · ${n}`;
}

/** "3 min ago" style age for the tooltip (Req 18.9). `now` is passed in so tests need no clock. */
export function ago(iso: string, now: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
