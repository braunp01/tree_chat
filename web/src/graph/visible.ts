// Which Branches the Branch_Graph draws as nodes, and which hide inside a counted stub (Req 18.3-18.4, 18.6).
// Pure: no DOM, no clock.
import type { BranchSummary } from "../api";

export interface StubInfo {
  /** Hidden Branches under this parent (all descendants), and how many of them are open and parked. */
  total: number;
  open: number;
  parked: number;
}

export interface GNode {
  /** The Branch id, or `stub:<parent id>` for a collapsed node. */
  id: string;
  parentId: string | null;
  depth: number;
  branch: BranchSummary | null;
  stub: StubInfo | null;
  /** Shown children, in sibling order. */
  childIds: string[];
  onPath: boolean;
  current: boolean;
  /** Has children (shown or hidden) the user can toggle. False for the path, which cannot collapse (Req 18.4). */
  toggleable: boolean;
  expanded: boolean;
}

export interface GraphNodes {
  rootId: string;
  nodes: Map<string, GNode>;
  /** Pre-order list of node ids, siblings in sibling order. */
  order: string[];
}

export const stubId = (parentId: string): string => `stub:${parentId}`;
export const isStub = (id: string): boolean => id.startsWith("stub:");

/** Req 18.6: Anchor position (Conversation_Position, then offset), then creation time. */
export function siblingKey(b: BranchSummary): [number, number, string, string] {
  return [b.anchor_position ?? -1, b.anchor?.start ?? 0, b.created_at, b.id];
}

export function compareSiblings(a: BranchSummary, b: BranchSummary): number {
  const x = siblingKey(a);
  const y = siblingKey(b);
  return x[0] - y[0] || x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0) || (x[3] < y[3] ? -1 : x[3] > y[3] ? 1 : 0);
}

export function visibleGraph(
  branches: readonly BranchSummary[],
  currentId: string | null,
  expanded: ReadonlySet<string>,
): GraphNodes | null {
  const byId = new Map(branches.map((b) => [b.id, b]));
  const kids = new Map<string, BranchSummary[]>();
  let root: BranchSummary | undefined;
  for (const b of branches) {
    if (b.parent_branch_id === null) root = b;
    else kids.set(b.parent_branch_id, [...(kids.get(b.parent_branch_id) ?? []), b]);
  }
  if (!root) return null;
  for (const list of kids.values()) list.sort(compareSiblings);

  const path = new Set<string>();
  for (let cur = currentId ? byId.get(currentId) : undefined; cur; cur = cur.parent_branch_id ? byId.get(cur.parent_branch_id) : undefined)
    path.add(cur.id);

  const nodes = new Map<string, GNode>();
  const order: string[] = [];
  const stack: { b: BranchSummary; depth: number }[] = [{ b: root, depth: 0 }];
  while (stack.length) {
    const { b, depth } = stack.pop()!;
    const children = kids.get(b.id) ?? [];
    const open = path.has(b.id) || expanded.has(b.id);
    const node: GNode = {
      id: b.id,
      parentId: b.parent_branch_id,
      depth,
      branch: b,
      stub: null,
      childIds: [],
      onPath: path.has(b.id),
      current: b.id === currentId,
      toggleable: children.length > 0 && !path.has(b.id),
      expanded: open && children.length > 0,
    };
    nodes.set(b.id, node);
    order.push(b.id);
    if (children.length === 0) continue;
    if (open) {
      node.childIds = children.map((c) => c.id);
      for (const c of [...children].reverse()) stack.push({ b: c, depth: depth + 1 });
    } else {
      // Everything below a collapsed Branch is counted once, in one stub (Req 18.3).
      const hidden: BranchSummary[] = [];
      const walk = [...children];
      while (walk.length) {
        const h = walk.pop()!;
        hidden.push(h);
        walk.push(...(kids.get(h.id) ?? []));
      }
      const sid = stubId(b.id);
      node.childIds = [sid];
      nodes.set(sid, {
        id: sid,
        parentId: b.id,
        depth: depth + 1,
        branch: null,
        stub: {
          total: hidden.length,
          open: hidden.filter((h) => h.status === "open").length,
          parked: hidden.filter((h) => h.status === "parked").length,
        },
        childIds: [],
        onPath: false,
        current: false,
        toggleable: false,
        expanded: false,
      });
      order.push(sid);
    }
  }
  return { rootId: root.id, nodes, order };
}
