// The top bar: Trees menu, tree title (rename), breadcrumb, depth and the Status controls (Req 1.2-1.3, 14.3, 15.1, 18.12).
import { useEffect, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import { api, type BranchView } from "../api";
import { GLYPH } from "../graph/text";
import { changeStatus, createTree, loadTrees, notice, openTree, describe, refreshView, treeDetail, trees } from "../state";
import { Breadcrumb } from "./PathView";

function TreesMenu(): JSX.Element {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => !root.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div class="trees-menu" ref={root}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Trees ▾
      </button>
      {open && (
        <div class="menu-pop" role="menu">
          <button
            type="button"
            role="menuitem"
            class="new"
            onClick={() => {
              setOpen(false);
              void createTree();
            }}
          >
            + New tree
          </button>
          {trees.value.map((t) => (
            <button
              key={t.id}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                openTree(t);
              }}
            >
              <span class="title">{t.title ?? "Untitled"}</span>
              <span class="counts">
                <span class="st-open">●</span> {t.open_count} <span class="st-parked">○</span> {t.parked_count}
              </span>
            </button>
          ))}
          {trees.value.length === 0 && <p class="muted">No trees yet.</p>}
        </div>
      )}
    </div>
  );
}

/** Req 1.3: rename at any time. */
function TreeTitle({ treeId }: { treeId: string }): JSX.Element {
  const title = treeDetail.value?.title ?? "Untitled";
  const [editing, setEditing] = useState<string | null>(null);
  async function save(): Promise<void> {
    const t = editing;
    setEditing(null);
    if (t === null || t.trim() === title) return;
    try {
      await api.renameTree(treeId, t);
      await refreshView();
      void loadTrees();
    } catch (e) {
      notice.value = describe(e);
    }
  }
  return editing === null ? (
    <button type="button" class="tree-title" title="Rename this tree" onClick={() => setEditing(title)}>
      {title}
    </button>
  ) : (
    <input
      class="tree-title-edit"
      value={editing}
      maxLength={200}
      aria-label="Tree title"
      autofocus
      onInput={(e) => setEditing(e.currentTarget.value)}
      onBlur={() => void save()}
      onKeyDown={(e) => {
        if (e.key === "Enter") void save();
        if (e.key === "Escape") setEditing(null);
      }}
    />
  );
}

export function StatusControls({ view }: { view: BranchView }): JSX.Element | null {
  const b = view.branch;
  if (b.kind === "trunk") return null;
  const action = b.status === "open" ? "park" : b.status === "parked" ? "resume" : "reopen";
  const text = { park: "Park", resume: "Resume", reopen: "Reopen" }[action];
  const hint = {
    park: "Put this branch in the queue to come back to",
    resume: "Mark this branch as in progress again",
    reopen: "Make this closed branch open again",
  }[action];
  return (
    <span class="status-controls">
      <span class={`status st-${b.status}`}>
        {GLYPH[b.status]} {b.status}
      </span>
      <button type="button" title={hint} onClick={() => void changeStatus(action)}>
        {text}
      </button>
    </span>
  );
}

/** Req 15.1: the Tree's open and parked counts are always on screen (the Trunk is not counted). */
export function TreeCounts(): JSX.Element | null {
  const bs = treeDetail.value?.branches;
  if (!bs) return null;
  const open = bs.filter((b) => b.kind !== "trunk" && b.status === "open").length;
  const parked = bs.filter((b) => b.status === "parked").length;
  return (
    <span class="counts" title="Open and parked branches in this tree">
      <span class="st-open">●</span> {open} open · <span class="st-parked">○</span> {parked} parked
    </span>
  );
}

export function TopBar({ view }: { view: BranchView | null }): JSX.Element {
  return (
    <header class="topbar">
      <TreesMenu />
      {view && (
        <>
          <TreeTitle treeId={view.branch.tree_id} />
          <Breadcrumb view={view} />
          <span class="depth" title="Depth below the trunk (the trunk is 0)">
            depth {view.branch.depth}
          </span>
          <TreeCounts />
          <StatusControls view={view} />
        </>
      )}
    </header>
  );
}
