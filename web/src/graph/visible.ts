// Which Branches the Branch_Graph draws as nodes, and which hide inside a counted stub (Req 6.3-6.4, 6.6).
// Pure: no DOM, no clock.
import type { BranchOut } from "../api";

export interface GNode {
  /** The Branch id, or `stub:<parent id>` for a collapsed node. */
  id: string;
  parentId: string | null;
  depth: number;
  branch: BranchOut | null;
  /** For a stub: how many Branches it hides (all descendants of its parent). */
  hidden: number;
  /** Shown children, in sibling order. */
  childIds: string[];
  onPath: boolean;
  current: boolean;
  /** Has children the user can toggle. False on the path to the current Branch, which cannot collapse. */
  toggleable: boolean;
  expanded: boolean;
}

export interface GraphNodes {
  rootId: string;
  nodes: Map<string, GNode>;
  order: string[];
}

export const stubId = (parentId: string): string => `stub:${parentId}`;
export const isStub = (id: string): boolean => id.startsWith("stub:");

/** Req 6.6: siblings by creation time, so a new Branch never reorders existing ones. */
export function compareSiblings(a: BranchOut, b: BranchOut): number {
  return a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** The Branch holding a Message (Req 6.2). */
export function branchOf(branches: readonly BranchOut[], messageId: string | null): string | null {
  if (!messageId) return null;
  return branches.find((b) => b.message_ids.includes(messageId))?.id ?? null;
}

export function visibleGraph(
  branches: readonly BranchOut[],
  currentId: string | null,
  expanded: ReadonlySet<string>,
): GraphNodes | null {
  const byId = new Map(branches.map((b) => [b.id, b]));
  const kids = new Map<string, BranchOut[]>();
  let root: BranchOut | undefined;
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
  const stack: { b: BranchOut; depth: number }[] = [{ b: root, depth: 0 }];
  while (stack.length) {
    const { b, depth } = stack.pop()!;
    const children = kids.get(b.id) ?? [];
    const open = path.has(b.id) || expanded.has(b.id); // Req 6.3: the path, its siblings and the current children
    const node: GNode = {
      id: b.id,
      parentId: b.parent_branch_id,
      depth,
      branch: b,
      hidden: 0,
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
      let hidden = 0;
      const walk = [...children];
      while (walk.length) {
        const h = walk.pop()!;
        hidden++;
        walk.push(...(kids.get(h.id) ?? []));
      }
      const sid = stubId(b.id);
      node.childIds = [sid];
      nodes.set(sid, {
        id: sid,
        parentId: b.id,
        depth: depth + 1,
        branch: null,
        hidden,
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
