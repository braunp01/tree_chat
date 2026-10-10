// Spike for design.md "Anchor offsets": for any markdown and any selection within one Message, the mapped
// Anchor covers exactly the source of the selected characters (Req 4.1, 4.5).
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { render } from "preact";
import { MarkdownView, PlainView } from "../markdown/MarkdownView";
import { toCodePoints } from "../markdown/align";
import { anchorFromRange } from "./selection";

/** A visible UTF-16 unit and the source span (UTF-16) that produces it: the independent oracle. */
interface Vis {
  ch: string;
  s: number;
  e: number;
}

interface Piece {
  src: string;
  vis: Vis[]; // offsets relative to piece start
}

const lit = (src: string): Piece => ({
  src,
  vis: [...src].flatMap((c, i, arr) => {
    const off = arr.slice(0, i).join("").length;
    return c.length === 2
      ? [{ ch: c[0]!, s: off, e: off + 2 }, { ch: c[1]!, s: off, e: off + 2 }]
      : [{ ch: c, s: off, e: off + 1 }];
  }),
});
// Surrogate pairs map as one source unit per UTF-16 unit in the aligner; make the oracle agree.
const litUnits = (src: string): Piece => ({
  src,
  vis: [...src].flatMap((c, i, arr) => {
    const off = arr.slice(0, i).join("").length;
    return c.length === 2
      ? [{ ch: c[0]!, s: off, e: off + 1 }, { ch: c[1]!, s: off + 1, e: off + 2 }]
      : [{ ch: c, s: off, e: off + 1 }];
  }),
});
void lit;

const syntax = (src: string): Piece => ({ src, vis: [] });
const decoded = (src: string, ch: string): Piece => ({ src, vis: [{ ch, s: 0, e: src.length }] });

function join(pieces: Piece[]): Piece {
  let src = "";
  const vis: Vis[] = [];
  for (const p of pieces) {
    for (const v of p.vis) vis.push({ ch: v.ch, s: v.s + src.length, e: v.e + src.length });
    src += p.src;
  }
  return { src, vis };
}

const word = fc
  .array(fc.constantFrom("a", "b", "x", "z", "0", "9", "é", "é", "😀", "日"), { minLength: 1, maxLength: 6 })
  .map((cs) => cs.join(""));

const inlineToken: fc.Arbitrary<Piece> = fc.oneof(
  word.map(litUnits),
  word.map((w) => join([syntax("*"), litUnits(w), syntax("*")])),
  word.map((w) => join([syntax("**"), litUnits(w), syntax("**")])),
  word.map((w) => join([syntax("~~"), litUnits(w), syntax("~~")])),
  word.map((w) => join([syntax("`"), litUnits(w), syntax("`")])),
  fc.constantFrom("*", "_", "[", "#", "|").map((c) => decoded(`\\${c}`, c)),
  fc.constant(decoded("&amp;", "&")),
  fc.constant(decoded("&#x263A;", "☺")),
);

const inline = fc
  .array(inlineToken, { minLength: 1, maxLength: 6 })
  .map((ts) => join(ts.flatMap((t, i) => (i === 0 ? [t] : [litUnits(" "), t]))));

const codeLine = fc
  .array(fc.constantFrom("a", " ", "*", "_", "x", "😀", "~"), { minLength: 1, maxLength: 8 })
  .map((cs) => cs.join(""))
  .filter((l) => l.trim().length > 0);

const block: fc.Arbitrary<Piece> = fc.oneof(
  // Paragraph with a soft line break.
  fc.tuple(inline, inline).map(([a, b]) => join([a, litUnits("\n"), b])),
  // Multi-line block quote: the second line's "> " renders nothing.
  fc.tuple(inline, inline).map(([a, b]) => join([syntax("> "), a, litUnits("\n"), syntax("> "), b])),
  // List item with an indented continuation line.
  fc.tuple(inline, inline).map(([a, b]) => join([syntax("- "), a, litUnits("\n"), syntax("  "), b])),
  // Fenced code inside a list item: the item indentation renders nothing.
  fc.tuple(inline, fc.array(codeLine, { minLength: 1, maxLength: 3 })).map(([a, lines]) => {
    const parts: Piece[] = [syntax("- "), a, syntax("\n\n  ```\n")];
    lines.forEach((l, i) => {
      if (i > 0) parts.push(litUnits("\n"), syntax("  "));
      else parts.push(syntax("  "));
      parts.push(litUnits(l));
    });
    parts.push(syntax("\n  ```"));
    return join(parts);
  }),
  // Link: the URL renders nothing.
  fc.tuple(word, word).map(([t, w]) => join([litUnits(w), litUnits(" "), syntax("["), litUnits(t), syntax("](http://example.test/x)")])),
  inline,
  inline.map((p) => join([syntax("## "), p])),
  inline.map((p) => join([syntax("> "), p])),
  fc
    .array(inline, { minLength: 1, maxLength: 3 })
    .map((items) => join(items.flatMap((p, i) => [syntax(i === 0 ? "- " : "\n- "), p]))),
  fc
    .array(fc.array(fc.constantFrom("a", " ", "*", "_", "x", "😀", "~"), { minLength: 1, maxLength: 8 }), {
      minLength: 1,
      maxLength: 3,
    })
    .map((lines) => {
      const body = lines.map((l) => l.join(""));
      const parts: Piece[] = [syntax("```\n")];
      body.forEach((l, i) => {
        if (i > 0) parts.push(litUnits("\n"));
        parts.push(litUnits(l));
      });
      parts.push(syntax("\n```"));
      return join(parts);
    }),
  fc.tuple(word, word, word, word).map(([a, b, c, d]) =>
    join([syntax("| "), litUnits(a), syntax(" | "), litUnits(b), syntax(" |\n| --- | --- |\n| "), litUnits(c), syntax(" | "), litUnits(d), syntax(" |")]),
  ),
);

const doc = fc
  .array(block, { minLength: 1, maxLength: 4 })
  .map((bs) => join(bs.flatMap((b, i) => (i === 0 ? [b] : [syntax("\n\n"), b]))));

function runs(root: Element): Text[] {
  const out: Text[] = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) if (n.parentElement?.dataset.k) out.push(n as Text);
  return out;
}

function positionOf(texts: Text[], index: number): [Text, number] {
  let i = index;
  for (const t of texts) {
    if (i <= t.data.length) return [t, i];
    i -= t.data.length;
  }
  throw new Error("index out of range");
}

function selectAndMap(root: Element, source: string, i: number, j: number) {
  const texts = runs(root);
  // Positions are indices into the concatenated rendered text; prefer the start of the next run at boundaries.
  const startPos = (() => {
    let k = i;
    for (const t of texts) {
      if (k < t.data.length) return [t, k] as const;
      k -= t.data.length;
    }
    throw new Error("start out of range");
  })();
  const endPos = positionOf(texts, j);
  const range = document.createRange();
  range.setStart(startPos[0], startPos[1]);
  range.setEnd(endPos[0], endPos[1]);
  return anchorFromRange(range, root, source);
}

function isLow(s: string, i: number) {
  const c = s.charCodeAt(i);
  return c >= 0xdc00 && c <= 0xdfff;
}

describe("anchor mapping (Req 4.5)", () => {
  it("rendered text equals the oracle's visible text", () => {
    fc.assert(
      fc.property(doc, (d) => {
        const host = document.createElement("div");
        render(<MarkdownView source={d.src} />, host);
        expect(runs(host).map((t) => t.data).join("")).toBe(d.vis.map((v) => v.ch).join(""));
      }),
      { numRuns: 500 },
    );
  });

  it("any selection maps to exactly the source of the selected characters", () => {
    fc.assert(
      fc.property(doc, fc.nat(), fc.nat(), (d, x, y) => {
        const n = d.vis.length;
        let i = x % n;
        let j = i + 1 + (y % (n - i)); // exclusive end, i < j <= n
        const text = d.vis.map((v) => v.ch).join("");
        if (isLow(text, i)) i--;
        if (j < n && isLow(text, j)) j++;
        const host = document.createElement("div");
        render(<MarkdownView source={d.src} />, host);
        const got = selectAndMap(host, d.src, i, j);
        const s16 = d.vis[i]!.s;
        const e16 = d.vis[j - 1]!.e;
        expect(got).toEqual({
          start: toCodePoints(d.src, s16),
          end: toCodePoints(d.src, e16),
          quoted_text: d.src.slice(s16, e16),
        });
      }),
      { numRuns: 1000 },
    );
  });

  it("plain user messages map one to one, including emoji", () => {
    const src = "hi 😀 there";
    const host = document.createElement("div");
    render(<PlainView source={src} />, host);
    // select "😀 t" : UTF-16 [3, 7)
    const t = runs(host)[0]!;
    const r = document.createRange();
    r.setStart(t, 3);
    r.setEnd(t, 7);
    expect(anchorFromRange(r, host, src)).toEqual({ start: 3, end: 6, quoted_text: "😀 t" });
  });

  it("rejects a selection that leaves the message (Req 4.6)", () => {
    const outer = document.createElement("div");
    const a = document.createElement("div");
    const b = document.createElement("div");
    outer.append(a, b);
    render(<PlainView source="one" />, a);
    render(<PlainView source="two" />, b);
    const r = document.createRange();
    r.setStart(runs(a)[0]!, 1);
    r.setEnd(runs(b)[0]!, 1);
    expect(anchorFromRange(r, a, "one")).toBeNull();
  });
});
