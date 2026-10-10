// Turns a DOM selection inside one rendered Message into an Anchor the server will accept (Req 4.1, 4.5, 4.6).
import { align, toCodePoints, type MappedKind } from "../markdown/align";

export interface AnchorSpan {
  /** Code-point offsets into the Message source. */
  start: number;
  end: number;
  quoted_text: string;
}

interface Run {
  node: Text;
  span: HTMLElement;
}

function mappedRuns(root: Element): Run[] {
  const runs: Run[] = [];
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const span = n.parentElement;
    if (span?.dataset.k !== undefined) runs.push({ node: n as Text, span });
  }
  return runs;
}

/** Source span (UTF-16) of rendered unit k of a run; falls back to the whole node if alignment fails. */
function sourceOf(run: Run, k: number, source: string): [number, number] {
  const s = Number(run.span.dataset.s);
  const e = Number(run.span.dataset.e);
  const a = align(run.node.data, source, s, e, run.span.dataset.k as MappedKind);
  if (!a) return [s, e];
  return [a.starts[k]!, a.ends[k]!];
}

function isLowSurrogate(text: string, i: number): boolean {
  const c = text.charCodeAt(i);
  return c >= 0xdc00 && c <= 0xdfff;
}

/**
 * Map `range` to an Anchor over `source`, or null if the range is empty or leaves `root`
 * (a selection spanning more than one Message is not offered a popover, Req 4.6).
 */
export function anchorFromRange(range: Range, root: Element, source: string): AnchorSpan | null {
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  let first: { run: Run; k: number } | null = null;
  let last: { run: Run; k: number } | null = null;
  for (const run of mappedRuns(root)) {
    if (!range.intersectsNode(run.node)) continue;
    let a = run.node === range.startContainer ? range.startOffset : 0;
    let b = run.node === range.endContainer ? range.endOffset : run.node.data.length;
    if (a >= b) continue;
    // Never split a surrogate pair.
    if (a > 0 && isLowSurrogate(run.node.data, a)) a--;
    if (b < run.node.data.length && isLowSurrogate(run.node.data, b)) b++;
    first ??= { run, k: a };
    last = { run, k: b - 1 };
  }
  if (!first || !last) return null;
  const startU16 = sourceOf(first.run, first.k, source)[0];
  const endU16 = sourceOf(last.run, last.k, source)[1];
  if (endU16 <= startU16) return null;
  const start = toCodePoints(source, startU16);
  const end = toCodePoints(source, endU16);
  return { start, end, quoted_text: source.slice(startU16, endU16) };
}
