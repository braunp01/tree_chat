// Property 8 (design.md): the Branch_Graph draws every Branch or counts it exactly once, always draws the neighbourhood
// of the current Branch, and lays depth out left to right without overlap (Req 6.1-6.4, 6.6, 6.11).
import { describe, expect, it } from "vitest";
import fc from "fast-check";
import type { BranchOut } from "../api";
import { branch } from "../fixtures";
import { branchOf, compareSiblings, isStub, visibleGraph } from "./visible";
import { COL_W, NODE_H, NODE_W, ROW_H, layoutGraph } from "./layout";
import { clip, countLine } from "./text";

const at = (i: number) => `t${String(i).padStart(5, "0")}`;

/** Branch i+1 forks from an earlier Branch; creation times only grow, as they do in the Store. */
function build(parents: number[], sameTime = false): BranchOut[] {
  const out: BranchOut[] = [branch("b0")];
  parents.forEach((p, i) => {
    const parent = out[p % out.length]!;
    out.push(branch(`b${i + 1}`, { parent_branch_id: parent.id, created_at: sameTime ? at(1) : at(i + 1) }));
  });
  return out;
}

const scenario = fc
  .record({ parents: fc.array(fc.nat(), { maxLength: 80 }), current: fc.nat(), expanded: fc.array(fc.nat(), { maxLength: 10 }) })
  .map(({ parents, current, expanded }) => {
    const branches = build(parents);
    return {
      branches,
      current: branches[current % branches.length]!.id,
      expanded: new Set(expanded.map((e) => branches[e % branches.length]!.id)),
    };
  });

const ancestorsOf = (bs: BranchOut[], id: string): string[] => {
  const by = new Map(bs.map((b) => [b.id, b]));
  const out: string[] = [];
  for (let c = by.get(id); c; c = c.parent_branch_id ? by.get(c.parent_branch_id) : undefined) out.push(c.id);
  return out; // current first, the Root's Branch last
};

const descendants = (bs: BranchOut[], id: string): number => {
  const kids = bs.filter((b) => b.parent_branch_id === id);
  return kids.reduce((a, k) => a + 1 + descendants(bs, k.id), 0);
};

describe("Property 8a: every Branch is drawn or counted exactly once (Req 6.3-6.4)", () => {
  it("holds for any tree, current Branch and expansion", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current, expanded }) => {
        const g = visibleGraph(branches, current, expanded)!;
        const drawn = [...g.nodes.values()].filter((n) => n.branch);
        const counted = [...g.nodes.values()].reduce((a, n) => a + n.hidden, 0);
        expect(drawn.length + counted).toBe(branches.length);
        expect(new Set(drawn.map((n) => n.id)).size).toBe(drawn.length);
      }),
      { numRuns: 300 },
    );
  });

  it("gives each collapsed node exactly the number of Branches below its parent", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current, expanded }) => {
        const g = visibleGraph(branches, current, expanded)!;
        for (const n of g.nodes.values()) if (isStub(n.id)) expect(n.hidden).toBe(descendants(branches, n.parentId!));
      }),
      { numRuns: 200 },
    );
  });
});

describe("Property 8b: the neighbourhood is always drawn (Req 6.3)", () => {
  it("shows the path, every sibling on it, and the current Branch's children, with nothing expanded", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current }) => {
        const g = visibleGraph(branches, current, new Set())!;
        const path = ancestorsOf(branches, current);
        const must = new Set<string>(path);
        for (const b of branches) if (b.parent_branch_id && path.includes(b.parent_branch_id)) must.add(b.id); // siblings and children
        for (const id of must) expect(g.nodes.get(id)?.branch).toBeTruthy();
        for (const b of branches) if (!must.has(b.id)) expect(g.nodes.has(b.id)).toBe(false); // and nothing else
        expect(g.nodes.get(current)?.current).toBe(true);
        for (const id of path) expect(g.nodes.get(id)?.onPath).toBe(true);
      }),
      { numRuns: 300 },
    );
  });

  it("cannot be collapsed: Branches on the path have no toggle (Req 6.4)", () => {
    fc.assert(
      fc.property(scenario, ({ branches, current }) => {
        const g = visibleGraph(branches, current, new Set())!;
        for (const id of ancestorsOf(branches, current)) expect(g.nodes.get(id)!.toggleable).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});

describe("Property 8c: depth runs left to right without overlap (Req 6.1, 6.6)", () => {
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

  it("orders siblings by creation time and never reorders them when a Branch is added (Req 6.6)", () => {
    fc.assert(
      fc.property(scenario, fc.nat(), ({ branches, current }, extra) => {
        const order = (bs: BranchOut[]) => {
          const g = visibleGraph(bs, current, new Set(bs.map((b) => b.id)))!; // everything expanded
          const out = new Map<string, string[]>();
          for (const n of g.nodes.values()) if (n.childIds.length) out.set(n.id, n.childIds);
          return out;
        };
        const before = order(branches);
        for (const ids of before.values()) {
          const times = ids.map((id) => branches.find((b) => b.id === id)!.created_at);
          expect(times).toEqual([...times].sort());
        }
        const parent = branches[extra % branches.length]!;
        const after = order([...branches, branch("bNEW", { parent_branch_id: parent.id, created_at: at(99999) })]);
        for (const [pid, ids] of before) expect(after.get(pid)!.filter((i) => i !== "bNEW")).toEqual(ids);
        expect(after.get(parent.id)!.at(-1)).toBe("bNEW");
      }),
      { numRuns: 100 },
    );
  });

  it("breaks ties in creation time by id, so the order is total", () => {
    const bs = build([0, 0, 0], true);
    const shuffled = [bs[0]!, bs[3]!, bs[1]!, bs[2]!];
    expect(visibleGraph(shuffled, "b0", new Set())!.nodes.get("b0")!.childIds).toEqual(["b1", "b2", "b3"]);
    expect(compareSiblings(bs[1]!, bs[1]!)).toBe(0);
  });

  it("lays out 500 Branches well inside a second (Req 6.11)", () => {
    const bs = build(Array.from({ length: 499 }, (_, i) => i * 7919));
    const t0 = performance.now();
    const g = visibleGraph(bs, bs[250]!.id, new Set(bs.map((b) => b.id)))!; // worst case: all expanded
    layoutGraph(g);
    expect(performance.now() - t0).toBeLessThan(500);
    expect(ROW_H).toBeGreaterThan(NODE_H);
  });
});

describe("visibleGraph on a known tree (Req 6.3-6.4)", () => {
  const bs = [
    branch("r"),
    branch("a", { parent_branch_id: "r", created_at: at(1) }),
    branch("b", { parent_branch_id: "r", created_at: at(2) }),
    branch("a1", { parent_branch_id: "a", created_at: at(3) }),
    branch("b1", { parent_branch_id: "b", created_at: at(4) }),
    branch("b2", { parent_branch_id: "b", created_at: at(5) }),
    branch("b1x", { parent_branch_id: "b1", created_at: at(6) }),
  ];

  it("shows siblings of the path and collapses their subtrees into counted nodes", () => {
    const g = visibleGraph(bs, "a", new Set())!;
    expect(g.rootId).toBe("r");
    expect(g.nodes.get("r")!.childIds).toEqual(["a", "b"]);
    expect(g.nodes.get("a")!.childIds).toEqual(["a1"]);
    expect(g.nodes.get("b")!.childIds).toEqual(["stub:b"]);
    expect(g.nodes.get("stub:b")!.hidden).toBe(3);
  });

  it("expanding a sibling shows its children and collapses the next level", () => {
    const g = visibleGraph(bs, "a", new Set(["b"]))!;
    expect(g.nodes.get("b")!.childIds).toEqual(["b1", "b2"]);
    expect(g.nodes.get("b1")!.childIds).toEqual(["stub:b1"]);
    expect(g.nodes.get("b")!.expanded).toBe(true);
    expect(g.nodes.get("b")!.toggleable).toBe(true);
  });

  it("finds the Branch holding a Message", () => {
    expect(branchOf(bs, "b1-r")).toBe("b1");
    expect(branchOf(bs, "nowhere")).toBeNull();
    expect(branchOf(bs, null)).toBeNull();
  });

  it("returns nothing for a Tree with no Branches", () => {
    expect(visibleGraph([], null, new Set())).toBeNull();
  });
});

describe("text helpers", () => {
  it("clips and counts", () => {
    expect(clip("a  b\nc", 10)).toBe("a b c");
    expect(clip("abcdefghij", 5)).toBe("abcd…");
    expect(countLine(branch("x", { message_ids: ["x"] }))).toBe("1 message");
    expect(countLine(branch("x"))).toBe("2 messages");
  });
});
