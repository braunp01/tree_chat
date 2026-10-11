// The popover beside a selection (Req 4.1-4.2, 4.10, 9.1): a focused one-line Intent field.
// Enter parks the new Tangent and leaves the view alone; Ctrl/Cmd+Enter opens it and goes there; Escape cancels.
import { useEffect, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import type { SpawnRequest } from "../api";
import type { SpawnTarget } from "../selectionTarget";

export const INTENT_MAX = 200;

interface Props {
  target: SpawnTarget;
  /** Resolves true when the Tangent was created (the popover then closes). */
  onSpawn: (req: SpawnRequest) => Promise<boolean>;
  onDismiss: () => void;
}

export function SpawnPopover({ target, onSpawn, onDismiss }: Props): JSX.Element {
  const input = useRef<HTMLInputElement>(null);
  const [intent, setIntent] = useState("");
  const [forkAt, setForkAt] = useState<"anchor" | "tip">("anchor");
  const [busy, setBusy] = useState(false);
  const notes = target.message.notes_after;

  useEffect(() => input.current?.focus(), []);

  async function submit(status: "parked" | "open"): Promise<void> {
    if (busy) return;
    setBusy(true);
    const ok = await onSpawn({
      anchor: { message_id: target.message.id, ...target.anchor },
      intent: intent.trim() || undefined,
      fork_at: forkAt,
      status,
    });
    setBusy(false);
    if (ok) onDismiss();
  }

  function onKey(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      e.preventDefault();
      onDismiss();
    } else if (e.key === "Enter") {
      e.preventDefault();
      void submit(e.ctrlKey || e.metaKey ? "open" : "parked");
    }
  }

  return (
    <div
      class="popover"
      role="dialog"
      aria-label="New tangent"
      style={{ left: `${Math.max(8, target.x)}px`, top: `${target.y + 8}px` }}
      onKeyDown={onKey}
    >
      <div class="quote">“{target.anchor.quoted_text.slice(0, 120)}”</div>
      <input
        ref={input}
        type="text"
        placeholder="What is this tangent for? (optional)"
        value={intent}
        maxLength={INTENT_MAX}
        onInput={(e) => setIntent(e.currentTarget.value)}
        aria-label="Intent"
      />
      <div class="fork">
        <label>
          <input type="radio" name="fork" checked={forkAt === "anchor"} onChange={() => setForkAt("anchor")} /> at the passage
        </label>
        <label>
          <input type="radio" name="fork" checked={forkAt === "tip"} onChange={() => setForkAt("tip")} /> at the latest message
        </label>
      </div>
      {notes > 0 && forkAt === "anchor" && (
        <p class="hint">
          {notes === 1 ? "1 note comes" : `${notes} notes come`} after this passage and a tangent forked here will not see{" "}
          {notes === 1 ? "it" : "them"}. <button type="button" onClick={() => setForkAt("tip")}>Fork at the latest message instead</button>
        </p>
      )}
      <p class="keys">
        <kbd>Enter</kbd> park · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> open · <kbd>Esc</kbd> cancel
      </p>
    </div>
  );
}
