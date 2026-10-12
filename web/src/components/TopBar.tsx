// The top bar: the Trees menu (the Forest) and the open Tree's title, which can be renamed (Req 1.2-1.4).
import { useEffect, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import { api } from "../api";
import { describe, loadTrees, newTree, notice, openTree, refreshShape, shape, treeId, trees } from "../state";

export function TreesMenu(): JSX.Element {
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
  const choose = (f: () => void) => () => {
    setOpen(false);
    f();
  };
  return (
    <div class="trees-menu" ref={root}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Trees ▾
      </button>
      {open && (
        <div class="menu-pop" role="menu">
          <button type="button" role="menuitem" class="new" onClick={choose(newTree)}>
            + New tree
          </button>
          {trees.value.map((t) => (
            <button
              key={t.id}
              type="button"
              role="menuitem"
              aria-current={t.id === treeId.value ? "true" : undefined}
              onClick={choose(() => openTree(t.id))}
            >
              <span class="title">{t.title}</span>
            </button>
          ))}
          {trees.value.length === 0 && <p class="muted">No trees yet.</p>}
        </div>
      )}
    </div>
  );
}

/** Req 1.3-1.4: rename at any time; the server says why a title is refused. */
export function TreeTitle(): JSX.Element | null {
  const s = shape.value;
  const [editing, setEditing] = useState<string | null>(null);
  if (!s) return null;
  const id = s.id;
  async function save(): Promise<void> {
    const t = editing;
    setEditing(null);
    if (t === null || t.trim() === s!.title) return;
    try {
      await api.renameTree(id, t);
      await refreshShape();
      void loadTrees();
    } catch (e) {
      notice.value = describe(e);
    }
  }
  return editing === null ? (
    <button type="button" class="tree-title" title="Rename this tree" onClick={() => setEditing(s.title)}>
      {s.title}
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

export function TopBar(): JSX.Element {
  return (
    <header class="topbar">
      <TreesMenu />
      {treeId.value ? <TreeTitle /> : <strong class="muted">New tree</strong>}
      <span class="spacer" />
      <button type="button" onClick={newTree} title="Start a new conversation">
        New tree
      </button>
    </header>
  );
}
