// The one view (Req 2, 6): the Branch_Graph beside the chat, under a top bar with the Trees menu.
import { useEffect } from "preact/hooks";
import type { JSX } from "preact";
import { BranchGraph } from "./graph/BranchGraph";
import { Chat } from "./components/Chat";
import { TopBar } from "./components/TopBar";
import { graphEnlarged, loadTrees, notice, shape, startRouting } from "./state";

/** `M` enlarges the Branch_Graph and restores it; Escape restores it (Req 6.9). Never while typing. */
export function onGlobalKey(e: KeyboardEvent): void {
  const t = e.target as HTMLElement | null;
  const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
  if (e.key === "Escape" && graphEnlarged.value) {
    graphEnlarged.value = false;
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if ((e.key === "m" || e.key === "M") && shape.value) {
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
  return (
    <div class="app">
      <TopBar />
      <div class="body">
        <BranchGraph />
        <main>
          {notice.value && (
            <p class="error" role="alert">
              {notice.value}
            </p>
          )}
          <Chat />
        </main>
      </div>
    </div>
  );
}
