import { useEffect } from "preact/hooks";
import type { JSX } from "preact";
import { Breadcrumb, PathView } from "./components/PathView";
import { TreeList } from "./components/TreeList";
import { loadTrees, notice, startRouting, view } from "./state";

export function App(): JSX.Element {
  useEffect(() => {
    void loadTrees();
    startRouting();
  }, []);
  const v = view.value;
  return (
    <div class="app">
      <TreeList />
      <main>
        {notice.value && (
          <p class="error" role="alert">
            {notice.value}
          </p>
        )}
        {v ? (
          <>
            <header class="top">
              <Breadcrumb view={v} />
              <span class="depth" title="Depth below the trunk">
                depth {v.branch.depth}
              </span>
              <span class={`status st-${v.branch.status}`}>{v.branch.status}</span>
            </header>
            <PathView key={v.branch.id} view={v} />
          </>
        ) : (
          <p class="empty">Choose a tree, or start a new one.</p>
        )}
      </main>
    </div>
  );
}
