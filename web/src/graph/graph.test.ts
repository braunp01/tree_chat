// Properties 17-19 (design.md): the Branch_Graph draws the neighbourhood, counts the rest once, and lays depth out left to right.
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import type { BranchSummary, Status } from "../api";
import { summary } from "../fixtures";
import { isStub, visibleGraph } from "./visible";
import { COL_W, NODE_H, NODE_W, ROW_H, layoutGraph } from "./layout";

interface Spec {
  parent: number; // index among earlier Branches
  status: Status;
  pos: number;
  start: number;
  alt: boolean;
}

const specArb = fc.record({
  parent: fc.nat(),
  status: fc.constantFrom<Status>("open", "parked", "closed"),
  pos: fc.nat({ max: 6 }),
  start: fc.nat({ max: 5 }),
  alt: fc.boolean(),
});

function build(specs: Spec[]): BranchSummary[] {
  const out: BranchSummary[] = [summary("b0")];
  specs.forEach((s, i) => {
    const parent = out[s.parent % out.length]!;
    out.push(
      summary(`b${i + 1}`, {
        kind: s.alt ? "alternative" : "tangent",
        parent_branch_id: parent.id,
        status: s.status,
        anchor_position: s.pos,
        anchor: { message_id: "m", start: s.start, end: s.start + 1, quoted_text: "x" },
        created_at: `t${String(i + 1).padStart(5, "0")}`,
      }),
    );
  });
  return out;
}

const scenario = fc
  .record({ specs: fc.array(specArb, { maxLength: 80 }), current: fc.nat(), expanded: fc.array(fc.nat(), { maxLength: 10 }) })
  .map(({ specs, current, expanded }) => {
    const branches = build(specs);
    return {
      branches,
      current: branches[current % branches.length]!.id,
      expanded: new Set(expanded.map((e) => branches[e % branches.length]!.id)),
    };
  });

const ancestorsOf = (bs: BranchSummary[], id: string): string[] => {
  const by = new Map(bs.map((b) => [b.id, b]));
  const out: string[] = [];
  for (let c = by.get(id); c; c = c.parent_branch_id ? by.get(c.parent_branch_id) : undefined) out.push(c.id);
  return out; // current first, Trunk last
};

describe("Property 17: every Branch is drawn or counted exactly once (Req 18.3, 18.4)", () => {
  it("holds for any tree, current Branch and expansion", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current, expanded }) => {
        const g = visibleGraph(branches, current, expanded)!;
        const drawn = [...g.nodes.values()].filter((n) => n.branch).length;
        const counted = [...g.nodes.values()].reduce((a, n) => a + (n.stub?.total ?? 0), 0);
        expect(drawn + counted).toBe(branches.length);
      }),
      { numRuns: 300 },
    );
  });

  it("gives each stub exactly the status counts of what it hides", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current, expanded }) => {
        const g = visibleGraph(branches, current, expanded)!;
        const shown = new Set([...g.nodes.keys()]);
        const hidden = branches.filter((b) => !shown.has(b.id));
        const sum = (f: (s: NonNullable<ReturnType<typeof stubOf>>) => number) =>
          [...g.nodes.values()].reduce((a, n) => a + (n.stub ? f(n.stub) : 0), 0);
        const stubOf = (n: { stub: { total: number; open: number; parked: number } | null }) => n.stub;
        expect(sum((s) => s.total)).toBe(hidden.length);
        expect(sum((s) => s.open)).toBe(hidden.filter((b) => b.status === "open").length);
        expect(sum((s) => s.parked)).toBe(hidden.filter((b) => b.status === "parked").length);
      }),
      { numRuns: 300 },
    );
  });
});

describe("Property 18: the neighbourhood is always drawn (Req 18.3)", () => {
  it("shows the path, every sibling on it, and the current Branch's children, even with nothing expanded", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current }) => {
        const g = visibleGraph(branches, current, new Set())!;
        const path = ancestorsOf(branches, current);
        const must = new Set<string>(path);
        for (const b of branches) if (b.parent_branch_id && path.includes(b.parent_branch_id)) must.add(b.id); // siblings and children
        for (const id of must) expect(g.nodes.get(id)?.branch).not.toBeNull();
        expect(g.nodes.get(current)?.current).toBe(true);
        for (const id of path) expect(g.nodes.get(id)?.onPath).toBe(true);
      }),
      { numRuns: 300 },
    );
  });

  it("cannot be collapsed away by the expansion set", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current }) => {
        const g = visibleGraph(branches, current, new Set())!;
        for (const id of ancestorsOf(branches, current)) expect(g.nodes.get(id)!.toggleable).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});

describe("Property 19: depth runs left to right without overlap (Req 18.1, 18.6)", () => {
  it("puts x at the depth column, children right of parents, and no two nodes overlap", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current, expanded }) => {
        const g = visibleGraph(branches, current, expanded)!;
        const l = layoutGraph(g);
        const rects = [...g.nodes.values()].map((n) => ({ n, p: l.pos.get(n.id)! }));
        for (const { n, p } of rects) {
          expect(p.x).toBe(16 + n.depth * COL_W);
          if (n.parentId) expect(p.x).toBeGreaterThan(l.pos.get(n.parentId)!.x);
        }
        for (let i = 0; i < rects.length; i++)
          for (let j = i + 1; j < rects.length; j++) {
            const a = rects[i]!.p;
            const b = rects[j]!.p;
            const overlap = a.x < b.x + NODE_W && b.x < a.x + NODE_W && a.y < b.y + NODE_H && b.y < a.y + NODE_H;
            expect(overlap).toBe(false);
          }
      }),
      { numRuns: 100 },
    );
  });

  it("orders siblings by anchor position, offset, then creation, and never reorders them when a Branch is added", () => {
    fc.assert(
      fc.property(scenario, fc.record({ pos: fc.nat({ max: 6 }), start: fc.nat({ max: 5 }), parent: fc.nat() }), ({ branches, current, expanded }, extra) => {
        const order = (bs: BranchSummary[]) => {
          const g = visibleGraph(bs, current, new Set([...expanded, ...bs.map((b) => b.id)]))!; // everything expanded
          const out = new Map<string, string[]>();
          for (const n of g.nodes.values()) if (n.childIds.length && !n.childIds.some(isStub)) out.set(n.id, n.childIds);
          return out;
        };
        const before = order(branches);
        for (const [parent, ids] of before) {
          const bs = ids.map((id) => branches.find((b) => b.id === id)!);
          // An independent statement of Req 18.6: anchor position, then offset, then creation time, then id.
          const expected = [...bs].sort((a, b) =>
            a.anchor_position! !== b.anchor_position! ? a.anchor_position! - b.anchor_position!
            : a.anchor!.start !== b.anchor!.start ? a.anchor!.start - b.anchor!.start
            : a.created_at !== b.created_at ? (a.created_at < b.created_at ? -1 : 1)
            : a.id < b.id ? -1 : 1);
          expect(ids).toEqual(expected.map((b) => b.id));
          expect(parent).toBeTruthy();
        }
        const parent = branches[extra.parent % branches.length]!;
        const added = summary("bNEW", {
          kind: "tangent",
          parent_branch_id: parent.id,
          anchor_position: extra.pos,
          anchor: { message_id: "m", start: extra.start, end: extra.start + 1, quoted_text: "x" },
          created_at: "t99999",
        });
        const after = order([...branches, added]);
        for (const [pid, ids] of before) expect(after.get(pid)!.filter((i) => i !== "bNEW")).toEqual(ids);
      }),
      { numRuns: 100 },
    );
  });

  it("lays out 500 Branches well inside a second (Req 18.10)", () => {
    const specs: Spec[] = Array.from({ length: 499 }, (_, i) => ({ parent: i * 7919, status: "open", pos: i % 7, start: i % 5, alt: false }));
    const bs = build(specs);
    const t0 = performance.now();
    const g = visibleGraph(bs, bs[250]!.id, new Set(bs.map((b) => b.id)))!; // worst case: all expanded
    layoutGraph(g);
    expect(performance.now() - t0).toBeLessThan(500);
    expect(ROW_H).toBeGreaterThan(NODE_H);
  });
});

describe("visibleGraph on a known tree (Req 18.3-18.4)", () => {
  const bs = [
    summary("t"),
    summary("a", { parent_branch_id: "t", kind: "tangent", anchor_position: 1, created_at: "2" }),
    summary("b", { parent_branch_id: "t", kind: "tangent", anchor_position: 3, created_at: "1" }),
    summary("c", { parent_branch_id: "t", kind: "tangent", anchor_position: 1, created_at: "3", status: "parked" }),
    summary("a1", { parent_branch_id: "a", kind: "tangent", anchor_position: 1 }),
    summary("b1", { parent_branch_id: "b", kind: "tangent", anchor_position: 1, status: "parked" }),
    summary("b2", { parent_branch_id: "b", kind: "tangent", anchor_position: 2 }),
    summary("b1x", { parent_branch_id: "b1", kind: "tangent", anchor_position: 1, status: "parked" }),
  ];

  it("shows siblings of the path and collapses their subtrees into counted stubs", () => {
    const g = visibleGraph(bs, "a", new Set())!;
    expect(g.nodes.get("t")!.childIds).toEqual(["a", "c", "b"]); // position, then creation
    expect(g.nodes.get("a")!.childIds).toEqual(["a1"]);
    expect(g.nodes.get("b")!.childIds).toEqual(["stub:b"]);
    expect(g.nodes.get("stub:b")!.stub).toEqual({ total: 3, open: 1, parked: 2 }); // b1 parked, b1x parked, b2 open
  });

  it("orders siblings by position first and offset second (Req 18.6)", () => {
    const sib = [
      summary("t"),
      summary("x", { parent_branch_id: "t", kind: "tangent", anchor_position: 2, anchor: { message_id: "m", start: 0, end: 1, quoted_text: "a" } }),
      summary("y", { parent_branch_id: "t", kind: "tangent", anchor_position: 1, anchor: { message_id: "m", start: 9, end: 10, quoted_text: "a" } }),
      summary("z", { parent_branch_id: "t", kind: "tangent", anchor_position: 1, anchor: { message_id: "m", start: 2, end: 3, quoted_text: "a" } }),
    ];
    expect(visibleGraph(sib, "t", new Set())!.nodes.get("t")!.childIds).toEqual(["z", "y", "x"]);
  });

  it("expanding a sibling shows its children; the Branches stay counted once", () => {
    const g = visibleGraph(bs, "a", new Set(["b"]))!;
    expect(g.nodes.get("b")!.childIds).toEqual(["b1", "b2"]);
    expect(g.nodes.get("stub:b1")!.stub!.total).toBe(1);
  });
});
