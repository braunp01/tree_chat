// "See what was sent" (Req 4.5): the Context_Manifest of a Reply as the list of Messages sent, in order.
import { useEffect, useState } from "preact/hooks";
import type { JSX } from "preact";
import { api, type Manifest } from "../api";
import { clip } from "../graph/text";
import { describe } from "../state";

export function ManifestDialog({ messageId, onClose }: { messageId: string; onClose: () => void }): JSX.Element {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        // The manifest lists the Path to the Reply's question, so the Reply's own Path holds every Message's text.
        const [m, p] = await Promise.all([api.manifest(messageId), api.path(messageId)]);
        if (!live) return;
        setManifest(m);
        setTexts(Object.fromEntries(p.messages.map((x) => [x.id, x.content])));
      } catch (e) {
        if (live) setError(describe(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [messageId]);

  return (
    <div class="backdrop" onClick={onClose}>
      <div
        class="dialog"
        role="dialog"
        aria-label="What was sent for this reply"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <header>
          <h2>What was sent for this reply</h2>
          <button type="button" onClick={onClose} autofocus>
            Close
          </button>
        </header>
        {error && <p class="error">{error}</p>}
        {!manifest && !error && <p>Loading…</p>}
        {manifest && (
          <>
            <p class="muted">
              {manifest.model} · effort {manifest.settings.effort} · system prompt v{manifest.system_prompt_version} ·{" "}
              {manifest.entries.length} message{manifest.entries.length === 1 ? "" : "s"}
            </p>
            <ol class="manifest">
              {manifest.entries.map((e) => (
                <li key={e.id} class={`role-${e.role}`}>
                  <strong>{e.role}</strong> <span>{clip(texts[e.id] ?? "…", 280)}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
