// Maps each UTF-16 unit of a rendered text node back to the source span it came from.
// This is what lets an Anchor be stored as offsets into the Message's source (design.md, Anchor offsets).
import { decodeNamedCharacterReference } from "decode-named-character-reference";

export type MappedKind = "text" | "inlineCode" | "code" | "raw";

export interface Alignment {
  /** starts[k] is the source offset (UTF-16) where rendered unit k begins. */
  starts: Int32Array;
  /** ends[k] is the source offset (UTF-16) just past the source text that rendered unit k. */
  ends: Int32Array;
}

const ASCII_PUNCT = /[!-/:-@[-`{-~]/;
const ENTITY = /^&(?:#[xX]([0-9a-fA-F]{1,6})|#([0-9]{1,7})|([A-Za-z][A-Za-z0-9]{1,31}));/;

interface Unit {
  len: number;
  yields: string;
}

function decodeNumeric(cp: number): string {
  if (cp === 0 || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return "�";
  return String.fromCodePoint(cp);
}

/** One source unit: an escape, an entity reference, or a single UTF-16 unit. */
function readUnit(src: string, p: number, kind: MappedKind): Unit {
  const ch = src[p]!;
  if (kind === "text") {
    if (ch === "\\" && p + 1 < src.length && ASCII_PUNCT.test(src[p + 1]!)) {
      return { len: 2, yields: src[p + 1]! };
    }
    if (ch === "&") {
      const m = ENTITY.exec(src.slice(p, p + 40));
      if (m) {
        if (m[1] !== undefined) return { len: m[0].length, yields: decodeNumeric(parseInt(m[1], 16)) };
        if (m[2] !== undefined) return { len: m[0].length, yields: decodeNumeric(parseInt(m[2], 10)) };
        const named = decodeNamedCharacterReference(m[3]!);
        if (named !== false) return { len: m[0].length, yields: named };
      }
    }
  }
  // A line ending inside a code span renders as a space (CommonMark 6.1).
  if (kind === "inlineCode" && (ch === "\n" || ch === "\r")) {
    const len = ch === "\r" && src[p + 1] === "\n" ? 2 : 1;
    return { len, yields: " " };
  }
  return { len: 1, yields: ch };
}

/** Where the rendered content of a node begins inside its source span. */
function contentStart(src: string, from: number, to: number, kind: MappedKind): number {
  if (kind === "inlineCode") {
    let p = from;
    while (p < to && src[p] === "`") p++;
    return p;
  }
  if (kind === "code") {
    const firstLine = src.slice(from, to).trimStart();
    if (firstLine.startsWith("```") || firstLine.startsWith("~~~")) {
      const nl = src.indexOf("\n", from);
      return nl === -1 || nl >= to ? to : nl + 1;
    }
  }
  return from;
}

/**
 * Align `value` (what mdast says is rendered) against `src[from, to)` (where mdast says it came from).
 * Source units that render nothing (indentation, block-quote markers, escapes' backslashes) are skipped.
 * Returns null if the value cannot be found in order, so callers can fall back to the whole node.
 */
export function align(value: string, src: string, from: number, to: number, kind: MappedKind): Alignment | null {
  const starts = new Int32Array(value.length);
  const ends = new Int32Array(value.length);
  if (kind === "raw") {
    if (src.slice(from, to) !== value) return null;
    for (let k = 0; k < value.length; k++) {
      starts[k] = from + k;
      ends[k] = from + k + 1;
    }
    return { starts, ends };
  }
  let p = contentStart(src, from, to, kind);
  if (kind === "code") return alignCodeLines(value, src, p, to, starts, ends);
  let k = 0;
  while (k < value.length) {
    if (p >= to) return null;
    const unit = readUnit(src, p, kind);
    if (unit.yields.length > 0 && value.startsWith(unit.yields, k)) {
      for (let i = 0; i < unit.yields.length; i++) {
        starts[k + i] = p;
        ends[k + i] = p + unit.len;
      }
      k += unit.yields.length;
    }
    p += unit.len;
  }
  return { starts, ends };
}

/**
 * Code blocks remove only a prefix from each source line (container markers, indentation), so each
 * rendered line is matched against the end of its source line. Greedy matching would confuse a code
 * line's own leading spaces with the list indentation in front of it.
 */
function alignCodeLines(
  value: string,
  src: string,
  p: number,
  to: number,
  starts: Int32Array,
  ends: Int32Array,
): Alignment | null {
  let k = 0;
  const lines = value.split("\n");
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li]!;
    if (p > to) return null;
    let eol = src.indexOf("\n", p);
    if (eol === -1 || eol > to) eol = to;
    const lineEnd = eol > p && src[eol - 1] === "\r" ? eol - 1 : eol;
    const srcLine = src.slice(p, lineEnd);
    if (!srcLine.endsWith(line)) return null;
    const base = lineEnd - line.length;
    for (let i = 0; i < line.length; i++) {
      starts[k] = base + i;
      ends[k] = base + i + 1;
      k++;
    }
    if (li < lines.length - 1) {
      // The rendered "\n" comes from this line's ending.
      starts[k] = lineEnd;
      ends[k] = eol + 1;
      k++;
    }
    p = eol + 1;
  }
  return { starts, ends };
}

/** Convert a UTF-16 offset into `src` to a code-point offset, which is what the server stores (Req 4.5). */
export function toCodePoints(src: string, utf16: number): number {
  let cp = 0;
  for (let i = 0; i < utf16; i++) {
    const c = src.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < src.length) {
      const d = src.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) {
        if (i + 1 >= utf16) return cp + 1; // never split a surrogate pair: round up
        i++;
      }
    }
    cp++;
  }
  return cp;
}
