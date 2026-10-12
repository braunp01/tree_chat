import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "preact";
import { act } from "preact/test-utils";
import { BranchGraph, neighbour } from "./BranchGraph";
import { visibleGraph } from "./visible";
import { onGlobalKey } from "../App";
import { expandedByTree, graphEnlarged, path, shape, treeId } from "../state";
import { branch, msg, pathOf, tree } from "../fixtures";
import type { BranchOut } from "../api";

function branches(): BranchOut[] {
  return [
    branch("r", { label: "How do caches work?", message_ids: ["r", "r-r", "r-u2", "r-r2"] }),
    branch("a", { parent_branch_id: "r", label: "Cache keys", forked_from: "r-r2", forked_from_preview: "Caches store…", created_at: "1" }),
    branch("b", { parent_branch_id: "r", label: "TTL question", forked_from: "r-r2", created_at: "2" }),
    branch("a1", { parent_branch_id: "a", label: "Hash collisions", created_at: "3" }),
    branch("b1", { parent_branch_id: "b", label: "hidden child", created_at: "4", message_ids: ["b1"] }),
  ];
}

let host: HTMLElement;
let calls: string[];

/** Show the graph with the Current_Point at the end of a Branch. */
function mount(currentBranch = "a"): HTMLElement {
  const bs = branches();
  shape.value = tree(bs);
  treeId.value = "tree1";
  const last = bs.find((b) => b.id === currentBranch)!.message_ids.at(-1)!;
  path.value = pathOf([msg("r", "user"), msg(last, "assistant")]);
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
    return new Response(JSON.stringify(pathOf([msg("r", "user")])), { status: 200 });
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
const click = async (el: Element) => act(async () => void el.dispatchEvent(new MouseEvent("click", { bubbles: true })));

describe("what the graph draws (Req 6.1-6.3)", () => {
  it("draws the path, siblings and the current Branch's children, and counts the rest", () => {
    mount("a");
    for (const id of ["r", "a", "b", "a1"]) expect(node(id)).not.toBeNull();
    expect(node("b1")).toBeNull();
    expect(node("stub:b")!.textContent).toContain("+ 1 more");
    expect(node("a")!.classList.contains("current")).toBe(true);
    expect(node("r")!.classList.contains("onpath")).toBe(true);
    expect(host.querySelectorAll(".edge.path").length).toBe(1); // r → a
  });

  it("labels each node with its first question and Message count (Req 6.2)", () => {
    mount("a");
    expect(node("a")!.textContent).toContain("Cache keys");
    expect(node("a")!.textContent).toContain("2 messages");
    expect(node("r")!.textContent).toContain("4 messages");
  });

  it("marks the Branch holding a pending question as current", () => {
    mount("b1");
    expect(node("b1")!.classList.contains("current")).toBe(true);
  });

  it("shows the full label and the reply it forked from on hover (Req 6.8)", async () => {
    mount("a");
    await act(async () => void node("a").dispatchEvent(new MouseEvent("mouseover", { bubbles: true })));
    await act(async () => void node("a").dispatchEvent(new FocusEvent("focus")));
    const tip = host.querySelector(".graph-tip")!;
    expect(tip.textContent).toContain("Cache keys");
    expect(tip.textContent).toContain("Caches store…");
  });

  it("tells assistive technology label, depth and place among siblings (Req 6.10)", () => {
    mount("a");
    const b = node("b")!;
    expect(b.getAttribute("role")).toBe("treeitem");
    expect(b.getAttribute("aria-level")).toBe("2");
    expect(b.getAttribute("aria-posinset")).toBe("2");
    expect(b.getAttribute("aria-setsize")).toBe("2");
    expect(b.getAttribute("aria-label")).toContain("TTL question");
    expect(host.querySelector("[role=tree]")).not.toBeNull();
    expect(node("a")!.getAttribute("aria-selected")).toBe("true");
  });
});

describe("operating it (Req 6.4-6.5, 6.10)", () => {
  it("activating a node goes to the last Message of that Branch and creates nothing (Req 6.5, 2.3)", async () => {
    mount("a");
    await click(node("b"));
    expect(location.hash).toBe("#/t/tree1/m/b-r");
    expect(calls.filter((c) => !c.startsWith("GET"))).toEqual([]);
  });

  it("a collapsed node expands its parent, and the choice is kept per Tree (Req 6.4)", async () => {
    mount("a");
    await click(node("stub:b"));
    expect(expandedByTree.value["tree1"]).toEqual(["b"]);
    expect(node("b1")).not.toBeNull();
    expect(node("stub:b")).toBeNull();
  });

  it("the toggle on an expanded node collapses it again", async () => {
    mount("a");
    await click(node("stub:b"));
    await click(node("b").querySelector(".toggle")!);
    expect(expandedByTree.value["tree1"]).toEqual([]);
    expect(node("b1")).toBeNull();
  });

  it("cannot collapse the path to the current Branch (Req 6.4)", () => {
    mount("a1");
    expect(node("a")!.querySelector(".toggle")).toBeNull();
    expect(node("r")!.querySelector(".toggle")).toBeNull();
  });

  it("arrow keys move between siblings, to the parent and to the first child (Req 6.10)", async () => {
    mount("a");
    const focused = () => (document.activeElement as Element | null)?.getAttribute("data-node-id");
    await act(async () => node("a").focus());
    expect(node("a").getAttribute("tabindex")).toBe("0"); // roving focus starts on the current Branch
    expect(node("b").getAttribute("tabindex")).toBe("-1");
    await key(node("a"), "ArrowDown");
    expect(focused()).toBe("b");
    await key(node("b"), "ArrowLeft");
    expect(focused()).toBe("r");
    await key(node("r"), "ArrowRight");
    expect(focused()).toBe("a");
    await key(node("a"), "ArrowRight");
    expect(focused()).toBe("a1");
  });

  it("Space toggles a sibling and Enter opens it", async () => {
    mount("a");
    await act(async () => node("b").focus());
    await key(node("b"), " ");
    expect(expandedByTree.value["tree1"]).toEqual(["b"]);
    await key(node("b"), "Enter");
    expect(location.hash).toBe("#/t/tree1/m/b-r");
  });
});

describe("neighbour (Req 6.10)", () => {
  const g = () => visibleGraph(branches(), "a", new Set())!;
  it("moves among siblings in order, to the parent and to the first child", () => {
    expect(neighbour(g(), "a", "ArrowDown")).toBe("b");
    expect(neighbour(g(), "b", "ArrowUp")).toBe("a");
    expect(neighbour(g(), "a", "ArrowUp")).toBeNull();
    expect(neighbour(g(), "a", "ArrowLeft")).toBe("r");
    expect(neighbour(g(), "a", "ArrowRight")).toBe("a1");
    expect(neighbour(g(), "r", "ArrowLeft")).toBeNull();
  });
});

describe("M enlarges the graph (Req 6.9)", () => {
  const press = (k: string, target: Element = document.body) => {
    const e = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
    Object.defineProperty(e, "target", { value: target });
    onGlobalKey(e);
  };
  it("toggles with M, restores with Escape, and ignores typing", () => {
    mount("a");
    press("m");
    expect(graphEnlarged.value).toBe(true);
    press("Escape");
    expect(graphEnlarged.value).toBe(false);
    press("m", document.createElement("textarea"));
    expect(graphEnlarged.value).toBe(false);
  });

  it("activating a node in the enlarged graph restores it", async () => {
    mount("a");
    graphEnlarged.value = true;
    await click(node("b"));
    expect(graphEnlarged.value).toBe(false);
  });
});
