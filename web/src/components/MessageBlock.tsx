// One Message with its Anchor_Markers in the margin (Req 5), Alternatives switcher (Req 3.4) and actions.
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import type { BranchView, Marker, ViewMessage } from "../api";
import { rangesForPassage } from "../anchor/selection";
import { clearOwner, highlightsSupported, setHighlight } from "../highlights";
import { MarkdownView, PlainView } from "../markdown/MarkdownView";
import { groupMarkers, intentLabel, overlaps, type MarkerGroup } from "../markers";
import { highlight, makeAlternative, navigate } from "../state";
import { ManifestDialog } from "./ManifestDialog";

const GLYPH = { parked: "○", open: "●", closed: "✓" } as const;
const MIN_GAP = 26;

function closeMenu(e: Event): void {
  (e.currentTarget as HTMLElement).closest("details")?.removeAttribute("open");
}

function MarkerTip({ markers }: { markers: Marker[] }): JSX.Element {
  return (
    <ul class="tip">
      {markers.map((m) => {
        const l = intentLabel(m);
        return (
          <li key={m.branch_id}>
            <span class={`st st-${m.status}`}>{GLYPH[m.status]}</span> {l ? l.text : <em>no intent</em>}
            {l?.generated && <span class="muted"> (generated)</span>}
          </li>
        );
      })}
    </ul>
  );
}

function MarginMarker({ message, group, top }: { message: ViewMessage; group: MarkerGroup; top: number }): JSX.Element {
  const [choosing, setChoosing] = useState(false);
  const many = group.markers.length > 1;
  const on = () => (highlight.value = { messageId: message.id, start: group.start, end: group.end });
  const off = () => (highlight.value = null);
  return (
    <div class="marker-wrap" style={{ top: `${top}px` }}>
      <button
        type="button"
        class={`marker st-${group.status}`}
        aria-label={`${group.markers.length} branch${many ? "es" : ""} anchored here`}
        onMouseEnter={on}
        onMouseLeave={off}
        onFocus={on}
        onBlur={off}
        onClick={() => (many ? setChoosing(!choosing) : navigate(group.markers[0]!.branch_id))} // Req 5.4
      >
        {GLYPH[group.status]}
        {many && <span class="count">{group.markers.length}</span>}
      </button>
      {!choosing && <MarkerTip markers={group.markers} />}
      {choosing && (
        <ul class="menu" role="menu">
          {group.markers.map((m) => (
            <li key={m.branch_id}>
              <button type="button" role="menuitem" onClick={() => navigate(m.branch_id)}>
                <span class={`st st-${m.status}`}>{GLYPH[m.status]}</span> {intentLabel(m)?.text ?? "no intent"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Alternatives({ message, view }: { message: ViewMessage; view: BranchView }): JSX.Element | null {
  const alts = message.alternatives;
  if (alts.length === 0) return null;
  const current = view.branch.id;
  return (
    <span class="alts" aria-label="Alternatives">
      Alternatives ({alts.length}):{" "}
      <button type="button" aria-current={current === message.branch_id} onClick={() => navigate(message.branch_id)}>
        original
      </button>
      {alts.map((a, i) => (
        <button key={a.branch_id} type="button" aria-current={current === a.branch_id} onClick={() => navigate(a.branch_id)}>
          {i + 1}
        </button>
      ))}
    </span>
  );
}

interface Props {
  message: ViewMessage;
  view: BranchView;
  /** Shown as a quiet, shorter block (the inherited part). */
  inherited?: boolean;
  label?: string;
}

export function MessageBlock({ message, view, inherited, label }: Props): JSX.Element {
  const body = useRef<HTMLDivElement>(null);
  const [tops, setTops] = useState<number[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [showContext, setShowContext] = useState(false);
  const groups = groupMarkers(message.markers);
  const hl = highlight.value;
  const active = hl && hl.messageId === message.id ? hl : null;

  // Req 5.1: anchored passages are underlined in the text, character by character where the browser can
  // (CSS Custom Highlight API), else by whole rendered run. Colour and line style both say the Status.
  const owner = useRef({}).current;
  const underline = groups.map((g) => `${g.start}:${g.end}:${g.status}`).join(",");
  useEffect(() => {
    const root = body.current;
    if (!root) return;
    if (highlightsSupported()) {
      for (const st of ["open", "parked", "closed"] as const) {
        const ranges = groups.filter((g) => g.status === st).flatMap((g) => rangesForPassage(root, message.content, g.start, g.end));
        setHighlight(`anchor-${st}`, owner, ranges);
      }
      return;
    }
    root.querySelectorAll<HTMLElement>("[data-s]").forEach((el) => {
      const hit = groups.filter((g) => overlaps(Number(el.dataset.s), Number(el.dataset.e), g.start, g.end)).map((g) => g.status);
      const best = (["open", "parked", "closed"] as const).find((st) => hit.includes(st));
      if (best) el.dataset.anchored = best;
      else delete el.dataset.anchored;
    });
  }, [message.id, message.content, underline]);
  useEffect(() => () => clearOwner(owner), []);

  // Req 5.2: strengthen the passage of the hovered marker or graph node.
  useEffect(() => {
    const root = body.current;
    if (!root) return;
    if (highlightsSupported()) {
      setHighlight("anchor-hover", owner, active ? rangesForPassage(root, message.content, active.start, active.end) : []);
      return;
    }
    root.querySelectorAll<HTMLElement>("[data-s]").forEach((el) => {
      const on = active !== null && overlaps(Number(el.dataset.s), Number(el.dataset.e), active.start, active.end);
      el.classList.toggle("hl", on);
    });
  }, [active?.start, active?.end, message.id, message.content]);

  // Req 5.1: each marker sits beside its passage; markers never overlap each other.
  useLayoutEffect(() => {
    const place = () => {
      const root = body.current;
      if (!root) return;
      const base = root.getBoundingClientRect().top;
      let floor = -Infinity;
      setTops(
        groups.map((g) => {
          const span = [...root.querySelectorAll<HTMLElement>("[data-s]")].find((el) =>
            overlaps(Number(el.dataset.s), Number(el.dataset.e), g.start, g.end),
          );
          const want = span ? span.getBoundingClientRect().top - base : 0;
          floor = Math.max(want, floor + MIN_GAP);
          return floor;
        }),
      );
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [message.id, message.content, message.markers.length]);

  const isNote = message.role === "note";
  return (
    <article class={`message role-${message.role}${inherited ? " inherited" : ""}`} data-message-id={message.id}>
      <header>
        <span class="who">{label ?? (isNote ? "Note" : message.role === "user" ? "You" : "Assistant")}</span>
        {message.cut_off && <span class="cutoff">cut off at the output limit</span>}
        <Alternatives message={message} view={view} />
        <details class="more">
          <summary aria-label="More actions" title="More actions">
            ⋯
          </summary>
          <div class="more-pop">
            {message.role === "user" && (
              <button
                type="button"
                onClick={(e) => {
                  closeMenu(e);
                  setEditing(message.content);
                }}
              >
                Edit as an alternative
              </button>
            )}
            {message.role === "assistant" && (
              <>
                <button
                  type="button"
                  onClick={(e) => {
                    closeMenu(e);
                    void makeAlternative(message.id);
                  }}
                >
                  Regenerate as an alternative
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    closeMenu(e);
                    setShowContext(true);
                  }}
                >
                  See what the model was sent
                </button>
              </>
            )}
            {isNote && <span class="muted">Notes cannot be edited.</span>}
          </div>
        </details>
      </header>
      {isNote && message.source && (
        <p class="note-title">
          Conclusion from{" "}
          <a href={`#/b/${message.source.branch_id}`} onClick={() => navigate(message.source!.branch_id)}>
            {message.source.label}
          </a>
        </p>
      )}
      <div class="msg-row" style={{ minHeight: tops.length ? `${(tops[tops.length - 1] ?? 0) + MIN_GAP}px` : undefined }}>
        <div class="msg-body" ref={body} data-content-for={message.id}>
          {message.role === "assistant" ? (
            <MarkdownView source={message.content} />
          ) : (
            <PlainView source={message.content} />
          )}
        </div>
        <div class="margin">
          {groups.map((g, i) => (
            <MarginMarker key={`${g.start}:${g.end}`} message={message} group={g} top={tops[i] ?? 0} />
          ))}
        </div>
      </div>
      {editing !== null && (
        <div class="edit">
          <textarea value={editing} rows={3} aria-label="Edited message" onInput={(e) => setEditing(e.currentTarget.value)} />
          <button
            type="button"
            disabled={!editing.trim()}
            onClick={async () => {
              if (await makeAlternative(message.id, editing)) setEditing(null);
            }}
          >
            Save as alternative
          </button>
          <button type="button" onClick={() => setEditing(null)}>
            Cancel
          </button>
        </div>
      )}
      {showContext && <ManifestDialog messageId={message.id} onClose={() => setShowContext(false)} />}
    </article>
  );
}
