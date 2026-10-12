// The Branch_Graph (Req 6): the Tree's derived Branches as a node-link diagram, depth running left to right, the
// current Branch's neighbourhood in full and everything else collapsed. It pans and zooms, and `M` enlarges it (Req 6.9).
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import { currentPoint, expandedByTree, goTo, graphEnlarged, path, shape, toggleExpanded } from "../state";
import { clip, countLine } from "./text";
import { NODE_H, NODE_W, layoutGraph } from "./layout";
import { branchOf, isStub, visibleGraph, type GNode, type GraphNodes } from "./visible";

interface Cam {
  k: number;
  x: number;
  y: number;
}
const K_MIN = 0.06;
const K_MAX = 2;
const clampK = (k: number): number => Math.min(K_MAX, Math.max(K_MIN, k));

function edgePath(ax: number, ay: number, bx: number, by: number): string {
  const mx = (ax + bx) / 2;
  return `M${ax},${ay} C${mx},${ay} ${mx},${by} ${bx},${by}`;
}

/** Sibling, parent and child moves for the keyboard (Req 6.10). */
export function neighbour(g: GraphNodes, id: string, key: "ArrowUp" | "ArrowDown" | "ArrowLeft" | "ArrowRight"): string | null {
  const n = g.nodes.get(id);
  if (!n) return null;
  if (key === "ArrowLeft") return n.parentId;
  if (key === "ArrowRight") return n.childIds[0] ?? null;
  if (!n.parentId) return null;
  const sibs = g.nodes.get(n.parentId)!.childIds;
  const i = sibs.indexOf(id) + (key === "ArrowDown" ? 1 : -1);
  return sibs[i] ?? null;
}

export function BranchGraph(): JSX.Element | null {
  const s = shape.value;
  path.value; // re-render when the Current_Point moves
  const treeId = s?.id ?? "";
  const currentId = s ? branchOf(s.branches, currentPoint()) : null;
  const expandedIds = expandedByTree.value[treeId];
  const enlarged = graphEnlarged.value;

  const graph = useMemo(
    () => (s ? visibleGraph(s.branches, currentId, new Set(expandedIds ?? [])) : null),
    [s, currentId, expandedIds],
  );
  const layout = useMemo(() => (graph ? layoutGraph(graph) : null), [graph]);

  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [cam, setCam] = useState<Cam>({ k: 1, x: 16, y: 16 });
  const [focusId, setFocusId] = useState<string | null>(null);
  const [tip, setTip] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [enlarged, !!graph]);

  // First view of a Tree: show the whole graph if it fits at a readable scale, otherwise centre on the current node.
  const initialised = useRef<string | null>(null);
  useEffect(() => {
    if (!layout || size.w === 0 || initialised.current === treeId) return;
    initialised.current = treeId;
    const k = Math.max(0.8, clampK(Math.min(1, (size.w - 32) / layout.width, (size.h - 32) / layout.height)));
    const fits = layout.width * k <= size.w - 32 && layout.height * k <= size.h - 32;
    const p = currentId ? layout.pos.get(currentId) : undefined;
    if (fits || !p) setCam({ k, x: 16, y: Math.max(16, (size.h - layout.height * k) / 2) });
    else setCam({ k, x: size.w / 2 - (p.x + NODE_W / 2) * k, y: size.h / 2 - (p.y + NODE_H / 2) * k });
  }, [treeId, layout, size.w, size.h]);

  // Req 6.7: keep the current node in view. Only moves the camera when it is out of sight, so clicking a visible node
  // does not make the picture jump.
  useEffect(() => {
    if (!layout || !currentId || size.w === 0) return;
    const p = layout.pos.get(currentId);
    if (!p) return;
    setCam((c) => {
      const left = c.x + p.x * c.k;
      const top = c.y + p.y * c.k;
      const margin = 24;
      const inside = left >= margin && left + NODE_W * c.k <= size.w - margin && top >= margin && top + NODE_H * c.k <= size.h - margin;
      if (inside) return c;
      return { k: c.k, x: size.w / 2 - (p.x + NODE_W / 2) * c.k, y: size.h / 2 - (p.y + NODE_H / 2) * c.k };
    });
  }, [currentId, layout, size.w, size.h]);

  // Wheel zoom needs a non-passive listener to stop the page scrolling.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [!!graph, enlarged]);

  function zoomAt(factor: number, px: number, py: number): void {
    setCam((c) => {
      const k = clampK(c.k * factor);
      const f = k / c.k;
      return { k, x: px - (px - c.x) * f, y: py - (py - c.y) * f };
    });
  }

  function fit(): void {
    if (!layout || size.w === 0) return;
    const k = clampK(Math.min((size.w - 32) / layout.width, (size.h - 32) / layout.height, 1));
    setCam({ k, x: (size.w - layout.width * k) / 2, y: Math.max(16, (size.h - layout.height * k) / 2) });
  }

  if (!s || !graph || !layout) return <div class="graph-panel empty">{s ? "Loading…" : "The graph of a tree appears here."}</div>;
  const nodes = graph.nodes;

  function activate(n: GNode): void {
    if (isStub(n.id)) toggleExpanded(n.parentId!);
    else if (n.branch) {
      goTo(n.branch.message_ids.at(-1)!); // Req 6.5: the last Message of the Branch
      graphEnlarged.value = false; // Req 6.9: choosing a Branch in the enlarged graph restores it
    }
  }

  function focusNode(id: string): void {
    setFocusId(id);
    box.current?.querySelector<SVGGElement>(`[data-node-id="${id}"]`)?.focus();
  }

  function onKey(e: KeyboardEvent): void {
    const id = focusId ?? currentId;
    if (e.key === "+" || e.key === "=") return zoomAt(1.25, size.w / 2, size.h / 2), e.preventDefault();
    if (e.key === "-" || e.key === "_") return zoomAt(0.8, size.w / 2, size.h / 2), e.preventDefault();
    if (e.key === "0") return fit(), e.preventDefault();
    if (e.key.startsWith("Arrow")) {
      e.preventDefault();
      if (e.shiftKey) {
        const d = 80;
        setCam((c) => ({ ...c, x: c.x + (e.key === "ArrowLeft" ? d : e.key === "ArrowRight" ? -d : 0), y: c.y + (e.key === "ArrowUp" ? d : e.key === "ArrowDown" ? -d : 0) }));
        return;
      }
      const next = id ? neighbour(graph!, id, e.key as "ArrowUp") : null;
      if (next) focusNode(next);
      return;
    }
    const n = id ? nodes.get(id) : undefined;
    if (!n) return;
    if (e.key === "Enter") return activate(n), e.preventDefault();
    if (e.key === " ") {
      e.preventDefault();
      if (isStub(n.id)) toggleExpanded(n.parentId!);
      else if (n.toggleable) toggleExpanded(n.id);
    }
  }

  const tipNode = tip ? nodes.get(tip) : undefined;
  const tipPos = tip ? layout.pos.get(tip) : undefined;

  return (
    <div class={`graph-panel${enlarged ? " enlarged" : ""}`}>
      <div class="graph-toolbar">
        <strong>Branches</strong>
        <span class="muted">{s.branches.length}</span>
        <span class="spacer" />
        <button type="button" title="Zoom out (-)" aria-label="Zoom out" onClick={() => zoomAt(0.8, size.w / 2, size.h / 2)}>
          −
        </button>
        <button type="button" title="Zoom in (+)" aria-label="Zoom in" onClick={() => zoomAt(1.25, size.w / 2, size.h / 2)}>
          +
        </button>
        <button type="button" title="Fit the whole graph (0)" onClick={fit}>
          Fit
        </button>
        <button type="button" title="Enlarge or restore (M)" aria-pressed={enlarged} onClick={() => (graphEnlarged.value = !enlarged)}>
          {enlarged ? "Restore" : "Enlarge"}
        </button>
      </div>
      <div
        class="graph-viewport"
        ref={box}
        onKeyDown={onKey}
        onPointerDown={(e) => {
          if ((e.target as Element).closest(".gnode")) return;
          drag.current = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y };
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d) setCam((c) => ({ ...c, x: d.cx + e.clientX - d.x, y: d.cy + e.clientY - d.y }));
        }}
        onPointerUp={() => (drag.current = null)}
      >
        <svg width="100%" height="100%" role="tree" aria-label="Branches of this tree, depth left to right">
          <g transform={`translate(${cam.x} ${cam.y}) scale(${cam.k})`}>
            {[...nodes.values()].flatMap((n) =>
              n.childIds.map((cid) => {
                const a = layout.pos.get(n.id)!;
                const b = layout.pos.get(cid)!;
                const child = nodes.get(cid)!;
                const cls = `edge${child.onPath ? " path" : ""}${isStub(cid) ? " stubedge" : ""}`;
                return <path key={`e${cid}`} class={cls} d={edgePath(a.x + NODE_W, a.y + NODE_H / 2, b.x, b.y + NODE_H / 2)} />;
              }),
            )}
            {[...nodes.values()].map((n) => {
              const p = layout.pos.get(n.id)!;
              const b = n.branch;
              const sibs = n.parentId ? nodes.get(n.parentId)!.childIds : [n.id];
              return (
                <g
                  key={n.id}
                  class={`gnode${b ? "" : " stub"}${n.current ? " current" : ""}${n.onPath ? " onpath" : ""}`}
                  transform={`translate(${p.x} ${p.y})`}
                  data-node-id={n.id}
                  role="treeitem"
                  // lowercase: Preact sets SVG attributes verbatim and `tabIndex` would not be recognised
                  {...{ tabindex: n.id === (focusId ?? currentId ?? graph.rootId) ? 0 : -1 }}
                  aria-level={n.depth + 1}
                  aria-posinset={sibs.indexOf(n.id) + 1}
                  aria-setsize={sibs.length}
                  aria-selected={n.current}
                  aria-expanded={n.toggleable ? n.expanded : undefined}
                  aria-label={b ? `${b.label}, ${countLine(b)}` : `${n.hidden} more branches. Activate to expand.`}
                  onClick={() => activate(n)}
                  onFocus={() => {
                    setFocusId(n.id);
                    setTip(n.id);
                  }}
                  onBlur={() => setTip(null)}
                  onMouseEnter={() => setTip(n.id)}
                  onMouseLeave={() => setTip(null)}
                >
                  <rect width={NODE_W} height={NODE_H} rx={8} />
                  {b ? (
                    <>
                      <text class="label" x={12} y={19}>
                        {clip(b.label, 21)}
                      </text>
                      <text class="sub" x={12} y={36}>
                        {countLine(b)}
                      </text>
                      {n.toggleable && n.expanded && (
                        <g
                          class="toggle"
                          transform={`translate(${NODE_W - 4} ${NODE_H / 2})`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpanded(n.id);
                          }}
                        >
                          <circle r={9} />
                          <text y={4} text-anchor="middle">
                            −
                          </text>
                        </g>
                      )}
                    </>
                  ) : (
                    <>
                      <text class="label" x={12} y={19}>
                        + {n.hidden} more
                      </text>
                      <text class="sub" x={12} y={36}>
                        branch{n.hidden === 1 ? "" : "es"} hidden
                      </text>
                    </>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        {tipNode?.branch && tipPos && (
          <div class="graph-tip" role="tooltip" style={{ left: `${cam.x + (tipPos.x + NODE_W) * cam.k + 8}px`, top: `${cam.y + tipPos.y * cam.k}px` }}>
            <strong>{tipNode.branch.label}</strong>
            {/* Req 6.8: the Message it forked from */}
            {tipNode.branch.forked_from_preview ? (
              <>
                <div class="muted">Forked from the reply</div>
                <blockquote>{clip(tipNode.branch.forked_from_preview, 140)}</blockquote>
              </>
            ) : (
              <div class="muted">The start of this tree</div>
            )}
            <div class="muted">{countLine(tipNode.branch)}</div>
          </div>
        )}
        <div class="graph-legend" aria-hidden="true">
          depth →
        </div>
      </div>
    </div>
  );
}
