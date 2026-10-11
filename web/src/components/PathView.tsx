// The Path_View for one Branch (Req 14.4): what it inherited (collapsed), the framing card, then its own Messages.
import { useEffect, useMemo, useState } from "preact/hooks";
import type { JSX } from "preact";
import type { BranchView, ViewMessage } from "../api";
import { intentLabel } from "../markers";
import { navigate, spawnTangent, stream } from "../state";
import { targetFromSelection, type SpawnTarget } from "../selectionTarget";
import { Composer } from "./Composer";
import { MessageBlock } from "./MessageBlock";
import { SpawnPopover } from "./SpawnPopover";

export function forkDescription(v: BranchView): string {
  const f = v.framing;
  if (!f || !v.branch.anchor) return "";
  if (v.branch.kind === "alternative") return "after the message before the replaced one";
  return f.fork_point_message_id === v.branch.anchor.message_id ? "at the passage" : "at the latest message";
}

function FramingCard({ view }: { view: BranchView }): JSX.Element | null {
  const f = view.framing;
  if (!f) return null;
  const label = intentLabel(f);
  return (
    <section class="framing-card" aria-label="Framing">
      {view.branch.kind === "alternative" ? (
        <p>
          <strong>Alternative</strong> to the message below.
        </p>
      ) : (
        <>
          <blockquote>{f.anchor_quote}</blockquote>
          <p>
            <strong>Intent:</strong>{" "}
            {label ? (
              <>
                {label.text}
                {label.generated && <span class="muted"> (generated)</span>}
              </>
            ) : (
              <em>none</em>
            )}
          </p>
        </>
      )}
      <p class="muted">Forked {forkDescription(view)}</p>
    </section>
  );
}

function Inherited({ view, all }: { view: BranchView; all: Map<string, ViewMessage> }): JSX.Element | null {
  const [open, setOpen] = useState(false);
  const inh = view.inherited;
  useEffect(() => setOpen(false), [view.branch.id]);
  if (!view.branch.parent_branch_id) return null;
  const anchor = inh.anchor_message;
  const anchorInEntries = inh.entries.some((e) => e.kind === "message" && e.message.id === inh.anchor_message_id);
  return (
    <section class="inherited" aria-label="Inherited conversation">
      <button type="button" class="collapse" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {inh.message_count} earlier message{inh.message_count === 1 ? "" : "s"} from{" "}
        {view.branch.parent_label ?? "the parent"}
      </button>
      {open &&
        inh.entries.map((e, i) =>
          e.kind === "framing" ? (
            <p key={`f${i}`} class="framing-note">
              Tangent “{e.label}” begins here
            </p>
          ) : (
            <MessageBlock key={e.message.id} message={all.get(e.message.id) ?? e.message} view={view} inherited />
          ),
        )}
      {anchor && (!open || !anchorInEntries) && (
        <MessageBlock message={anchor} view={view} inherited label={view.branch.kind === "alternative" ? "Replaced message" : "Anchor message"} />
      )}
    </section>
  );
}

export function PathView({ view }: { view: BranchView }): JSX.Element {
  const [target, setTarget] = useState<SpawnTarget | null>(null);
  const byId = useMemo(() => {
    const m = new Map<string, ViewMessage>();
    for (const e of view.inherited.entries) if (e.kind === "message") m.set(e.message.id, e.message);
    if (view.inherited.anchor_message) m.set(view.inherited.anchor_message.id, view.inherited.anchor_message);
    for (const x of view.messages) m.set(x.id, x);
    return m;
  }, [view]);

  useEffect(() => setTarget(null), [view.branch.id]);

  // The popover follows the selection when the pointer or keyboard finishes selecting (Req 4.1).
  function onSelectionEnd(e: Event): void {
    if ((e.target as Element | null)?.closest(".popover")) return;
    setTarget(targetFromSelection(window.getSelection(), byId));
  }

  const s = stream.value;
  const mine = s && s.branchId === view.branch.id ? s : null;
  return (
    <div class="path-view" onMouseUp={onSelectionEnd} onKeyUp={onSelectionEnd}>
      <Inherited view={view} all={byId} />
      <FramingCard view={view} />
      {view.messages.map((m) => (
        <MessageBlock key={m.id} message={m} view={view} />
      ))}
      {mine && mine.error === null && (
        <article class="message role-assistant streaming" aria-live="polite">
          <header>
            <span class="who">Assistant</span>
          </header>
          <div class="plain">{mine.text || "…"}</div>
        </article>
      )}
      {mine?.error && (
        <p class="error" role="alert">
          The reply failed: {mine.error.message}
        </p>
      )}
      <Composer view={view} />
      {target && <SpawnPopover target={target} onSpawn={spawnTangent} onDismiss={() => setTarget(null)} />}
    </div>
  );
}

export function Breadcrumb({ view }: { view: BranchView }): JSX.Element {
  return (
    <nav class="breadcrumb" aria-label="Ancestry">
      {view.breadcrumb.map((b) => (
        <span key={b.id}>
          <a href={`#/b/${b.id}`} onClick={() => navigate(b.id)}>
            {b.label}
          </a>
          {" › "}
        </span>
      ))}
      <strong>{view.branch.kind === "trunk" ? "Trunk" : (intentLabel(view.branch)?.text ?? view.branch.anchor?.quoted_text.slice(0, 60))}</strong>
    </nav>
  );
}
