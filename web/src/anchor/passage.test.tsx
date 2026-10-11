// The inverse of the anchor mapping: an anchored passage is marked character by character (Req 5.1, 5.2).
import { afterEach, describe, expect, it } from "vitest";
import fc from "fast-check";
import { render } from "preact";
import { act } from "preact/test-utils";
import { MarkdownView, PlainView } from "../markdown/MarkdownView";
import { MessageBlock } from "../components/MessageBlock";
import { marker, msg, trunkView } from "../fixtures";
import { rangesForPassage } from "./selection";

let host: HTMLElement;
function mount(node: preact.JSX.Element): HTMLElement {
  host = document.createElement("div");
  document.body.append(host);
  act(() => render(node, host));
  return host;
}
afterEach(() => {
  render(null, host);
  host.remove();
});
const text = (rs: Range[]) => rs.map((r) => r.toString()).join("");
const cps = (s: string) => [...s];

describe("rangesForPassage", () => {
  it("covers exactly the passage in plain text, with emoji counted as one code point", () => {
    const src = "a😀b cd";
    const root = mount(<PlainView source={src} />);
    expect(text(rangesForPassage(root, src, 1, 3))).toBe("😀b");
    expect(text(rangesForPassage(root, src, 0, 1))).toBe("a");
  });

  it("holds for any text and any passage (property)", () => {
    fc.assert(
      fc.property(fc.string({ unit: "grapheme", minLength: 1, maxLength: 40 }).filter((s) => !s.includes("\n")), fc.nat(), fc.nat(), (src, a, b) => {
        const n = cps(src).length;
        const start = a % n;
        const end = start + 1 + (b % (n - start));
        const root = mount(<PlainView source={src} />);
        expect(text(rangesForPassage(root, src, start, end))).toBe(cps(src).slice(start, end).join(""));
        render(null, host);
        host.remove();
      }),
      { numRuns: 100 },
    );
  });

  it("marks only the rendered characters of a passage inside formatting", () => {
    const src = "plain **bold text** after";
    const root = mount(<MarkdownView source={src} />);
    expect(text(rangesForPassage(root, src, 8, 12))).toBe("bold");
    expect(text(rangesForPassage(root, src, 6, 14))).toBe("bold t"); // the ** markers render nothing
    expect(text(rangesForPassage(root, src, 0, src.length))).toBe("plain bold text after");
  });

  it("is empty for a passage outside the text", () => {
    const root = mount(<PlainView source="abc" />);
    expect(rangesForPassage(root, "abc", 3, 3)).toEqual([]);
  });
});

describe("underline fallback without the Custom Highlight API (Req 5.1)", () => {
  it("marks the rendered runs of an anchored passage with its Status", () => {
    const m = msg("a1", "assistant", "some **bold** words", { markers: [marker("t", 7, 11, "parked")] });
    const root = mount(<MessageBlock message={m} view={trunkView([m])} />);
    const marked = [...root.querySelectorAll<HTMLElement>("[data-anchored]")];
    expect(marked.map((e) => e.textContent)).toEqual(["bold"]);
    expect(marked[0]!.dataset.anchored).toBe("parked");
  });

  it("prefers the most active Status where passages overlap", () => {
    const m = msg("a1", "user", "overlap", { markers: [marker("x", 0, 7, "closed"), marker("y", 0, 7, "open")] });
    const root = mount(<MessageBlock message={m} view={trunkView([m])} />);
    expect(root.querySelector<HTMLElement>("[data-anchored]")!.dataset.anchored).toBe("open");
  });
});
