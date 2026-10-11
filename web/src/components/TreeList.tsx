// The list of Trees, most recently active first, with open and parked counts (Req 1.2).
import type { JSX } from "preact";
import { createTree, openTree, trees, view } from "../state";

export function TreeList(): JSX.Element {
  const current = view.value?.branch.tree_id;
  return (
    <aside class="tree-list" aria-label="Trees">
      <button type="button" class="new" onClick={() => void createTree()}>
        New tree
      </button>
      <ul>
        {trees.value.map((t) => (
          <li key={t.id}>
            <button type="button" aria-current={t.id === current} onClick={() => openTree(t)}>
              <span class="title">{t.title ?? "Untitled"}</span>
              <span class="counts">
                <span class="st st-open">●</span> {t.open_count} <span class="st st-parked">○</span> {t.parked_count}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
