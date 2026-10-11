import { afterEach, describe, expect, it } from "vitest";
import { render } from "preact";
import { act } from "preact/test-utils";
import { PathView } from "./PathView";
import { composerState } from "./Composer";
import { targetFromSelection } from "../selectionTarget";
import { marker, msg, summary, trunkView } from "../fixtures";
import type { BranchView } from "../api";

let host: HTMLElement;
function mount(v: BranchView): HTMLElement {
  host = document.createElement("div");
  document.body.append(host);
  act(() => render(<PathView view={v} />, host));
  return host;
}
afterEach(() => {
  render(null, host);
  host.remove();
});

function tangentView(): BranchView {
  const anchor = msg("m2", "assistant", "Prefix caching only helps if prefixes are shared.", {
    markers: [marker("t1", 0, 6, "open", "this one")],
  });
  return {
    ...trunkView([msg("m5", "user", "my question in the tangent", { branch_id: "t1" })]),
    branch: summary("t1", { kind: "tangent", parent_branch_id: "b1", parent_label: "Trunk", depth: 1, intent: "this one", anchor: { message_id: "m2", start: 0, end: 6, quoted_text: "Prefix" } }),
    breadcrumb: [{ id: "b1", label: "Trunk", kind: "trunk" }],
    inherited: {
      message_count: 2,
      anchor_message_id: "m2",
      anchor_message: anchor,
      entries: [
        { kind: "message", message: msg("m1", "user", "first question") },
        { kind: "message", message: anchor },
      ],
    },
    framing: { anchor_quote: "Prefix", intent: "this one", generated_intent: null, fork_point_message_id: "m2", text: "x", frozen: true },
  };
}

describe("Path_View for a Tangent (Req 14.4)", () => {
  it("collapses the inherited part to one line with the anchor message always visible", () => {
    const el = mount(tangentView());
    expect(el.querySelector(".collapse")!.textContent).toContain("2 earlier messages from Trunk");
    expect(el.textContent).not.toContain("first question");
    expect(el.textContent).toContain("Prefix caching only helps");
    expect(el.querySelector(".framing-card")!.textContent).toContain("at the passage");
    expect(el.textContent).toContain("my question in the tangent");
  });

  it("expands to show everything it inherited", async () => {
    const el = mount(tangentView());
    await act(async () => void el.querySelector<HTMLButtonElement>(".collapse")!.click());
    expect(el.textContent).toContain("first question");
    expect(el.querySelectorAll('[data-message-id="m2"]').length).toBe(1); // not shown twice
  });

  it("shows an Anchor_Marker for the passage, in the inherited part too (Req 5.1)", () => {
    const el = mount(tangentView());
    expect(el.querySelectorAll(".marker").length).toBe(1);
    expect(el.querySelector(".marker-wrap .tip")!.textContent).toContain("this one");
  });
});

describe("Path_View for the Trunk", () => {
  it("has no inherited part and no framing card", () => {
    const el = mount(trunkView([msg("m1", "user", "hello")]));
    expect(el.querySelector(".inherited")).toBeNull();
    expect(el.querySelector(".framing-card")).toBeNull();
  });

  it("shows a Note as a distinct block that links to its source (Req 13.7)", () => {
    const el = mount(trunkView([msg("n1", "note", "<tree_chat_note>x</tree_chat_note>", { source: { branch_id: "t9", label: "the tangent" } })]));
    expect(el.querySelector(".role-note .note-title")!.textContent).toContain("Conclusion from the tangent");
    expect(el.querySelector<HTMLAnchorElement>(".note-title a")!.getAttribute("href")).toBe("#/b/t9");
  });

  it("marks a cut-off reply (Req 2.4)", () => {
    const el = mount(trunkView([msg("a1", "assistant", "half a sent", { cut_off: true, stop_reason: "max_tokens" })]));
    expect(el.querySelector(".cutoff")).not.toBeNull();
  });

  it("shows how many Alternatives exist and lets you move between them (Req 3.4)", () => {
    const el = mount(trunkView([msg("a1", "assistant", "reply", { alternatives: [{ branch_id: "x", status: "open" }, { branch_id: "y", status: "open" }] })]));
    const alts = el.querySelector(".alts")!;
    expect(alts.textContent).toContain("Alternatives (2)");
    expect([...alts.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["original", "1", "2"]);
  });

  it("groups coinciding passages under one marker with a count (Req 5.3)", () => {
    const el = mount(trunkView([msg("a1", "assistant", "some passage here", { markers: [marker("x", 0, 4), marker("y", 0, 4, "open"), marker("z", 5, 12)] })]));
    const markers = [...el.querySelectorAll(".marker")];
    expect(markers.length).toBe(2);
    expect(markers[0]!.querySelector(".count")!.textContent).toBe("2");
  });
});

describe("composerState (Req 2.5, 2.9, 12.8)", () => {
  it("explains why writing is off", () => {
    expect(composerState(trunkView([]), false)).toEqual({ disabled: false, reason: null });
    expect(composerState({ ...trunkView([]), branch: summary("b", { status: "closed" }) }, false).reason).toMatch(/closed/);
    expect(composerState(trunkView([]), true).disabled).toBe(true);
    expect(composerState({ ...trunkView([]), awaiting_reply: true }, false).reason).toMatch(/no reply/);
  });
});

describe("selection to popover target (Req 4.1, 4.6)", () => {
  function select(el: HTMLElement, from: Node, a: number, to: Node, b: number): Selection {
    const range = document.createRange();
    range.setStart(from, a);
    range.setEnd(to, b);
    if (!range.getBoundingClientRect) range.getBoundingClientRect = () => new DOMRect(1, 2, 3, 4);
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(range);
    (Range.prototype as { getBoundingClientRect: unknown }).getBoundingClientRect ??= () => new DOMRect(1, 2, 3, 4);
    return sel;
  }

  it("targets one Message, and nothing when the selection spans two", () => {
    const v = trunkView([msg("u1", "user", "alpha beta"), msg("u2", "user", "gamma delta")]);
    const el = mount(v);
    const byId = new Map(v.messages.map((m) => [m.id, m]));
    const t1 = el.querySelector('[data-content-for="u1"] span')!.firstChild!;
    const t2 = el.querySelector('[data-content-for="u2"] span')!.firstChild!;
    const one = targetFromSelection(select(el, t1, 0, t1, 5), byId);
    expect(one?.message.id).toBe("u1");
    expect(one?.anchor).toEqual({ start: 0, end: 5, quoted_text: "alpha" });
    expect(targetFromSelection(select(el, t1, 2, t2, 3), byId)).toBeNull(); // Req 4.6
    window.getSelection()!.removeAllRanges();
    expect(targetFromSelection(window.getSelection(), byId)).toBeNull();
  });
});
