// Placement of the Branch_Graph (Req 18.1, 18.6): x is the depth column, y comes from a tidy-tree layout.
import type { GraphNodes } from "./visible";

export const COL_W = 184;
export const ROW_H = 62;
export const NODE_W = 164;
export const NODE_H = 46;
export const PAD = 16;

export interface Placed {
  x: number;
  y: number;
}

export interface GraphLayout {
  pos: Map<string, Placed>;
  width: number;
  height: number;
}

/** Leaves take consecutive rows; a parent sits centred on its first and last child. Iterative: depth is unbounded. */
export function layoutGraph(g: GraphNodes): GraphLayout {
  const row = new Map<string, number>();
  let next = 0;
  // Explicit DFS (leaves in sibling order), then centre each parent on its children on the way back up.
  const visit: { id: string; done: boolean }[] = [{ id: g.rootId, done: false }];
  while (visit.length) {
    const top = visit[visit.length - 1]!;
    const n = g.nodes.get(top.id)!;
    if (!top.done) {
      top.done = true;
      if (n.childIds.length === 0) {
        row.set(top.id, next++);
        visit.pop();
      } else {
        for (const c of [...n.childIds].reverse()) visit.push({ id: c, done: false });
      }
    } else {
      const first = row.get(n.childIds[0]!)!;
      const last = row.get(n.childIds[n.childIds.length - 1]!)!;
      row.set(top.id, (first + last) / 2);
      visit.pop();
    }
  }
  const pos = new Map<string, Placed>();
  let maxDepth = 0;
  for (const [id, n] of g.nodes) {
    pos.set(id, { x: PAD + n.depth * COL_W, y: PAD + row.get(id)! * ROW_H });
    maxDepth = Math.max(maxDepth, n.depth);
  }
  return { pos, width: PAD * 2 + maxDepth * COL_W + NODE_W, height: PAD * 2 + Math.max(0, next - 1) * ROW_H + NODE_H };
}
