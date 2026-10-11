import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "preact";
import { act } from "preact/test-utils";
import { BranchGraph, neighbour } from "./BranchGraph";
import { visibleGraph } from "./visible";
import { ago, clip, kindLine, nodeLabel } from "./text";
import { onGlobalKey } from "../App";
import { StatusControls, TreeCounts } from "../components/TopBar";
import { expandedByTree, graphEnlarged, treeDetail, view } from "../state";
import { summary, trunkView } from "../fixtures";
import type { BranchSummary } from "../api";

const T = (id: string, extra: Partial<BranchSummary>): BranchSummary =>
  summary(id, { kind: "tangent", parent_branch_id: "t", tree_id: "tree1", ...extra });

function tree(): BranchSummary[] {
  return [
    summary("t", { tree_id: "tree1", message_count: 4 }),
    T("a", { intent: "Cache keys", anchor_position: 1, created_at: "1", status: "open", message_count: 2 }),
    T("b", { intent: "TTL question", anchor_position: 3, created_at: "2", status: "parked" }),
    T("c", { generated_intent: "a generated one", anchor_position: 3, anchor: { message_id: "m", start: 9, end: 12, quoted_text: "qq" }, created_at: "3", status: "closed" }),
    T("a1", { parent_branch_id: "a", intent: "Hash collisions", anchor_position: 1, created_at: "4" }),
    T("b1", { parent_branch_id: "b", intent: "hidden child", anchor_position: 1, created_at: "5", status: "parked" }),
  ];
}

let host: HTMLElement;
let calls: string[];

function mount(currentId = "a"): HTMLElement {
  const bs = tree();
  treeDetail.value = { id: "tree1", title: "My tree", trunk_branch_id: "t", branches: bs } as never;
  view.value = trunkView([], { branch: bs.find((b) => b.id === currentId)! });
  host = document.createElement("div");
  document.body.append(host);
  act(() => render(<BranchGraph />, host));
  return host;
}

beforeEach(() => {
  calls = [];
  expandedByTree.value = {};
  graphEnlarged.value = false;
  location.hash = "";
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    return new Response(JSON.stringify(trunkView([])), { status: 200 });
  });
});
afterEach(() => {
  render(null, host);
  host.remove();
  vi.unstubAllGlobals();
});

const node = (id: string) => host.querySelector<SVGGElement>(`[data-node-id="${id}"]`)!;
const key = async (el: Element, k: string, init: KeyboardEventInit = {}) =>
  act(async () => void el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init })));

describe("what the graph draws (Req 18.1-18.3)", () => {
  it("draws the path, siblings and the current Branch's children, and counts the rest in a stub", () => {
    mount("a");
    for (const id of ["t", "a", "b", "c", "a1"]) expect(node(id)).not.toBeNull();
    expect(node("b1")).toBeNull();
    expect(node("stub:b")!.textContent).toContain("+ 1 more");
    expect(node("stub:b")!.textContent).toContain("1 parked");
    expect(node("a")!.classList.contains("current")).toBe(true);
    expect(node("t")!.classList.contains("onpath")).toBe(true);
  });

  it("shows status, label, kind and message count on each node; generated labels say so (Req 18.2, 11.4)", () => {
    mount("a");
    expect(node("a")!.textContent).toContain("Cache keys");
    expect(node("a")!.textContent).toContain("tangent · 2 msgs");
    expect(node("b")!.querySelector(".glyph")!.textContent).toBe("○");
    expect(node("c")!.textContent).toContain("a generated one");
    expect(node("c")!.textContent).toContain("·g");
    expect(node("c")!.getAttribute("aria-label")).toContain("(generated)");
    expect(node("t")!.textContent).toContain("My tree");
  });

  it("tells assistive technology label, depth and place among siblings (Req 18.8)", () => {
    mount("a");
    const b = node("b")!;
    expect(b.getAttribute("role")).toBe("treeitem");
    expect(b.getAttribute("aria-level")).toBe("2");
    expect(b.getAttribute("aria-posinset")).toBe("2");
    expect(b.getAttribute("aria-setsize")).toBe("3");
    expect(b.getAttribute("aria-label")).toContain("parked");
    expect(host.querySelector("[role=tree]")).not.toBeNull();
    expect(node("a")!.getAttribute("aria-selected")).toBe("true");
  });

  it("draws an Alternative's edge dashed (Req 18.6)", () => {
    const bs = tree();
    bs.push(T("alt", { kind: "alternative", anchor_position: 2, created_at: "6" }));
    treeDetail.value = { id: "tree1", title: "x", trunk_branch_id: "t", branches: bs } as never;
    view.value = trunkView([], { branch: bs[1]! });
    host = document.createElement("div");
    document.body.append(host);
    act(() => render(<BranchGraph />, host));
    expect(host.querySelectorAll(".edge.alt").length).toBe(1);
  });
});

describe("operating it (Req 18.4-18.5, 14.6)", () => {
  it("activating a node navigates and changes no Status (Req 18.5, 10.8)", async () => {
    mount("a");
    await act(async () => void node("b").dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(location.hash).toBe("#/b/b");
    expect(calls.filter((c) => c.startsWith("POST") || c.startsWith("PATCH"))).toEqual([]);
  });

  it("a stub expands its parent, and the expansion is kept per Tree (Req 18.4)", async () => {
    mount("a");
    await act(async () => void node("stub:b").dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(expandedByTree.value["tree1"]).toEqual(["b"]);
    expect(node("b1")).not.toBeNull();
    expect(node("stub:b")).toBeNull();
  });

  it("the toggle on an expanded node collapses it again", async () => {
    mount("a");
    await act(async () => void node("stub:b").dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => void node("b").querySelector(".toggle")!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(expandedByTree.value["tree1"]).toEqual([]);
    expect(node("b1")).toBeNull();
  });

  it("cannot collapse the path to the current Branch (Req 18.4)", () => {
    mount("a1");
    expect(node("a")!.querySelector(".toggle")).toBeNull();
    expect(node("t")!.querySelector(".toggle")).toBeNull();
  });

  it("arrow keys move between siblings, to the parent and to the first child; Enter opens (Req 14.6)", async () => {
    mount("a");
    const focused = () => (document.activeElement as Element | null)?.getAttribute("data-node-id");
    await act(async () => node("a").focus());
    expect(node("a").getAttribute("tabindex")).toBe("0"); // roving focus starts on the current Branch
    expect(node("b").getAttribute("tabindex")).toBe("-1");
    await key(node("a"), "ArrowDown");
    expect(focused()).toBe("b");
    await key(node("b"), "ArrowDown");
    expect(focused()).toBe("c");
    await key(node("c"), "ArrowLeft");
    expect(focused()).toBe("t");
    await key(node("t"), "ArrowRight");
    expect(focused()).toBe("a");
    await key(node("a"), "ArrowRight");
    expect(focused()).toBe("a1");
  });

  it("Enter on a focused node opens it; Space toggles a sibling", async () => {
    mount("a");
    await act(async () => node("b").focus()); // let the focus state settle, as it does between real key presses
    await key(node("b"), " ");
    expect(expandedByTree.value["tree1"]).toEqual(["b"]);
    await key(node("b"), "Enter");
    expect(location.hash).toBe("#/b/b");
  });
});

describe("neighbour (Req 14.6)", () => {
  const g = () => visibleGraph(tree(), "a", new Set())!;
  it("moves among siblings in order, to the parent and to the first child", () => {
    expect(neighbour(g(), "a", "ArrowDown")).toBe("b");
    expect(neighbour(g(), "b", "ArrowUp")).toBe("a");
    expect(neighbour(g(), "a", "ArrowUp")).toBeNull();
    expect(neighbour(g(), "a", "ArrowLeft")).toBe("t");
    expect(neighbour(g(), "a", "ArrowRight")).toBe("a1");
    expect(neighbour(g(), "t", "ArrowLeft")).toBeNull();
  });
});

describe("M enlarges the graph (Req 14.8, 18.11)", () => {
  const press = (k: string, target: Element = document.body) => {
    const e = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
    Object.defineProperty(e, "target", { value: target });
    onGlobalKey(e);
  };
  it("toggles with M, restores with Escape, and ignores typing", () => {
    mount("a");
    press("m");
    expect(graphEnlarged.value).toBe(true);
    expect(host.querySelector(".graph-panel")!.classList.contains("enlarged")).toBe(false); // re-render not flushed here
    press("Escape");
    expect(graphEnlarged.value).toBe(false);
    const ta = document.createElement("textarea");
    press("m", ta);
    expect(graphEnlarged.value).toBe(false);
  });
});

describe("Park, Resume, Reopen (Req 18.12, 10.1)", () => {
  const show = (status: BranchSummary["status"], kind: BranchSummary["kind"] = "tangent") => {
    host = document.createElement("div");
    document.body.append(host);
    act(() => render(<StatusControls view={trunkView([], { branch: summary("x", { status, kind }) })} />, host));
    return host;
  };
  it("offers the one move the Status allows", () => {
    expect(show("open").querySelector("button")!.textContent).toBe("Park");
    render(null, host);
    expect(show("parked").querySelector("button")!.textContent).toBe("Resume");
    render(null, host);
    expect(show("closed").querySelector("button")!.textContent).toBe("Reopen");
    render(null, host);
    expect(show("open", "trunk").querySelector("button")).toBeNull(); // the Trunk never moves
  });
});

describe("text helpers", () => {
  it("clips, labels and ages", () => {
    expect(clip("a  b\nc", 10)).toBe("a b c");
    expect(clip("abcdefghij", 5)).toBe("abcd…");
    expect(kindLine(summary("x", { kind: "tangent", message_count: 1 }))).toBe("tangent · 1 msg");
    expect(nodeLabel(summary("x"), null)).toEqual({ text: "Trunk", generated: false });
    const now = Date.parse("2026-10-11T10:00:00Z");
    expect(ago("2026-10-11T09:59:30Z", now)).toBe("just now");
    expect(ago("2026-10-11T09:30:00Z", now)).toBe("30 min ago");
    expect(ago("2026-10-09T10:00:00Z", now)).toBe("2 days ago");
  });
});

describe("counts in the top bar (Req 15.1)", () => {
  it("shows open and parked counts without the Trunk", () => {
    mount("a");
    act(() => render(<TreeCounts />, host));
    // tree(): a open, a1 open, b parked, b1 parked, c closed; the Trunk is open but not counted
    expect(host.textContent).toContain("2 open");
    expect(host.textContent).toContain("2 parked");
  });
});
