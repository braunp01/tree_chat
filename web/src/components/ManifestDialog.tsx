// Context inspector (Req 7.8): the Messages and Framing_Blocks that were sent for one reply, in order.
import { useEffect, useState } from "preact/hooks";
import type { JSX } from "preact";
import { api, type Manifest } from "../api";
import { describe } from "../state";

export function ManifestDialog({ messageId, onClose }: { messageId: string; onClose: () => void }): JSX.Element {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const m = await api.manifest(messageId);
        if (!live) return;
        setManifest(m);
        const ids = m.entries.flatMap((e) => (e.kind === "message" ? [e.id] : []));
        const got = await Promise.all(ids.map((id) => api.preview(id).then((p) => [id, p.preview] as const)));
        if (live) setPreviews(Object.fromEntries(got));
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
        aria-label="Context sent for this reply"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <header>
          <h2>Context sent for this reply</h2>
          <button type="button" onClick={onClose} autofocus>
            Close
          </button>
        </header>
        {error && <p class="error">{error}</p>}
        {!manifest && !error && <p>Loading…</p>}
        {manifest && (
          <>
            <p class="muted">
              {manifest.model} · effort {manifest.settings.effort} · {manifest.entries.length} entries
            </p>
            <ol class="manifest">
              {manifest.entries.map((e, i) =>
                e.kind === "framing" ? (
                  <li key={i} class="framing-entry">
                    <strong>Framing</strong>
                    <pre>{e.text}</pre>
                  </li>
                ) : (
                  <li key={i} class={`role-${e.role}`}>
                    <strong>{e.role}</strong> <span>{previews[e.id] ?? "…"}</span>
                  </li>
                ),
              )}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
