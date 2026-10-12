// The chat (Req 2): the Path to the Current_Point as one ordinary conversation, the Reply being written, and the
// composer. The only actions are "go back to here" and Send; the server decides every rule.
import { useEffect, useRef, useState } from "preact/hooks";
import type { JSX } from "preact";
import type { PathMessage, PathOut } from "../api";
import { MarkdownView, PlainView } from "../markdown/MarkdownView";
import { goTo, path, requestReply, send, stream, treeId, type StreamState } from "../state";
import { ManifestDialog } from "./ManifestDialog";

/** What the composer allows, and why not (Req 3.7, 3.10). The New tree page (no Path) can always send (Req 1.1). */
export function composerState(p: PathOut | null, s: StreamState | null): { disabled: boolean; reason: string | null } {
  const last = p?.messages.at(-1);
  if (!last) return { disabled: false, reason: null };
  if (last.role === "user") {
    const writing = (s?.userId === last.id && !s.error) || p!.reply_in_progress;
    return { disabled: true, reason: writing ? "A reply is being written…" : "This question has no reply yet. Request it above." };
  }
  return { disabled: false, reason: null };
}

/** Req 2.4: sending from a point that already has children starts a new branch. */
export function branchHint(p: PathOut | null): { latest: string | null } | null {
  const last = p?.messages.at(-1);
  if (!last || last.role !== "assistant" || last.child_count === 0) return null;
  return { latest: p!.latest_below };
}

function MessageView({ m, isLast, onShowSent }: { m: PathMessage; isLast: boolean; onShowSent: (id: string) => void }): JSX.Element {
  const assistant = m.role === "assistant";
  return (
    <article class={`message role-${m.role}`} data-message-id={m.id} tabIndex={-1}>
      <div class="msg-body">{assistant ? <MarkdownView source={m.content} /> : <PlainView source={m.content} />}</div>
      {m.cut_off && <p class="cutoff">Cut off: the reply reached its output limit.</p>}
      {assistant && (
        // Req 2.5: per-Message actions show on hover or focus only.
        <div class="msg-actions">
          {!isLast && (
            <button type="button" onClick={() => goTo(m.id)} title="Continue from this reply; later messages stay in their branch">
              Go back to here
            </button>
          )}
          <button type="button" onClick={() => onShowSent(m.id)}>
            See what was sent
          </button>
          {m.child_count > 1 && <span class="muted">{m.child_count} branches from here</span>}
        </div>
      )}
    </article>
  );
}

/** The pending question's Reply: the text so far, or the error and a control to ask again (Req 3.3, 3.5, 3.10). */
function Pending({ p }: { p: PathOut }): JSX.Element | null {
  const last = p.messages.at(-1)!;
  if (last.role !== "user") return null;
  const s = stream.value;
  const mine = s?.userId === last.id ? s : null;
  if (mine && !mine.error)
    return (
      <article class="message role-assistant writing" aria-live="polite" aria-busy="true">
        <div class="msg-body">{mine.text ? <MarkdownView source={mine.text} /> : <p class="muted">Writing…</p>}</div>
      </article>
    );
  if (p.reply_in_progress) return <p class="muted writing">A reply is being written…</p>;
  return (
    <div class="retry" role="status">
      {mine?.error ? <p class="error">{mine.error.message}</p> : <p class="muted">This question has no reply yet.</p>}
      <button type="button" onClick={() => void requestReply(last.id)}>
        {mine?.error ? "Try again" : "Request reply"}
      </button>
    </div>
  );
}

function Composer(): JSX.Element {
  const [text, setText] = useState("");
  const p = path.value;
  const { disabled, reason } = composerState(p, stream.value);
  const hint = branchHint(p);

  async function submit(): Promise<void> {
    const content = text;
    if (!content.trim() || disabled) return;
    if (await send(content)) setText("");
  }

  return (
    <div class="composer">
      {hint && (
        <p class="branch-hint">
          Sending here starts a new branch from this reply.
          {hint.latest && (
            <>
              {" "}
              <button type="button" class="link" onClick={() => goTo(hint.latest!)}>
                Jump to the latest message below
              </button>
            </>
          )}
        </p>
      )}
      <div class="composer-row">
        <textarea
          value={text}
          disabled={disabled}
          placeholder={reason ?? (treeId.value ? "Message" : "Start a new tree: type its first message")}
          rows={3}
          aria-label="Message"
          onInput={(e) => setText(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <button type="button" class="send" disabled={disabled || !text.trim()} onClick={() => void submit()}>
          Send
        </button>
      </div>
    </div>
  );
}

export function Chat(): JSX.Element {
  const p = path.value;
  const s = stream.value;
  const [sent, setSent] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const last = p?.messages.at(-1)?.id;

  // Req 2.2: show the latest Message; follow the Reply as it is written.
  useEffect(() => end.current?.scrollIntoView?.({ block: "end" }), [last, s?.text.length]);

  return (
    <div class="chat">
      {!treeId.value && <p class="empty">A new conversation. Its first message becomes the root of a new tree.</p>}
      {p?.messages.map((m, i) => <MessageView key={m.id} m={m} isLast={i === p.messages.length - 1} onShowSent={setSent} />)}
      {p && <Pending p={p} />}
      <div ref={end} />
      <Composer />
      {sent && <ManifestDialog messageId={sent} onClose={() => setSent(null)} />}
    </div>
  );
}
