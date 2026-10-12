// Small pure helpers for drawing the Branch_Graph.
import type { BranchOut } from "../api";

export function clip(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : `${t.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

/** Req 6.2: Message count, counting the Branch's own Messages. */
export function countLine(b: BranchOut): string {
  const n = b.message_ids.length;
  return `${n} message${n === 1 ? "" : "s"}`;
}
