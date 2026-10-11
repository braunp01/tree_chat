import { useEffect } from "preact/hooks";
import type { JSX } from "preact";
import { BranchGraph } from "./graph/BranchGraph";
import { PathView } from "./components/PathView";
import { TopBar } from "./components/TopBar";
import { changeStatus, graphEnlarged, loadTrees, notice, startRouting, view } from "./state";

/** `M` enlarges the Branch_Graph and restores it; Escape restores it (Req 14.8, 18.11). Never while typing. */
export function onGlobalKey(e: KeyboardEvent): void {
  const t = e.target as HTMLElement | null;
  const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
  if (e.key === "Escape" && graphEnlarged.value) {
    graphEnlarged.value = false;
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if ((e.key === "m" || e.key === "M") && view.value) {
    e.preventDefault();
    graphEnlarged.value = !graphEnlarged.value;
  }
}

export function App(): JSX.Element {
  useEffect(() => {
    void loadTrees();
    startRouting();
    window.addEventListener("keydown", onGlobalKey);
    return () => window.removeEventListener("keydown", onGlobalKey);
  }, []);
  const v = view.value;
  return (
    <div class={`app${graphEnlarged.value ? " graph-enlarged" : ""}`}>
      <TopBar view={v} />
      <div class="body">
        <BranchGraph />
        <main>
          {notice.value && (
            <p class="error" role="alert">
              {notice.value}
            </p>
          )}
          {v?.branch.status === "parked" && (
            <p class="banner parked">
              This branch is parked. Sending a message resumes it.{" "}
              <button type="button" onClick={() => void changeStatus("resume")}>
                Resume
              </button>
            </p>
          )}
          {v?.branch.status === "closed" && (
            <p class="banner closed">
              This branch is closed.{" "}
              <button type="button" onClick={() => void changeStatus("reopen")}>
                Reopen
              </button>
            </p>
          )}
          {v ? <PathView key={v.branch.id} view={v} /> : <p class="empty">Choose a tree from the Trees menu, or start a new one.</p>}
        </main>
      </div>
    </div>
  );
}

