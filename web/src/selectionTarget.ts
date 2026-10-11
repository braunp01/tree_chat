// From a DOM selection to "spawn a Tangent from this passage" (Req 4.1, 4.6).
import { anchorFromRange, type AnchorSpan } from "./anchor/selection";
import type { ViewMessage } from "./api";

export interface SpawnTarget {
  message: ViewMessage;
  anchor: AnchorSpan;
  /** Where to put the popover: just under the end of the selection. */
  x: number;
  y: number;
}

/**
 * The single Message a selection lies in, with its Anchor, or null when the selection is empty, leaves one Message
 * (Req 4.6) or cannot be mapped to the Message source.
 */
export function targetFromSelection(sel: Selection | null, byId: ReadonlyMap<string, ViewMessage>): SpawnTarget | null {
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  const node = range.commonAncestorContainer;
  const el = node instanceof Element ? node : node.parentElement;
  const content = el?.closest<HTMLElement>("[data-content-for]");
  if (!content) return null;
  const message = byId.get(content.dataset.contentFor ?? "");
  if (!message) return null;
  const anchor = anchorFromRange(range, content, message.content);
  if (!anchor) return null;
  const r = range.getBoundingClientRect();
  return { message, anchor, x: r.left, y: r.bottom };
}
