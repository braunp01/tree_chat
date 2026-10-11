// Writing in a Branch (Req 2.1, 2.5, 2.8-2.9, 12.8). The server decides every rule; this only explains why it is off.
import { useState } from "preact/hooks";
import type { JSX } from "preact";
import type { BranchView } from "../api";
import { requestReply, sendMessage, stream } from "../state";

export function composerState(v: BranchView, streaming: boolean): { disabled: boolean; reason: string | null } {
  if (v.branch.status === "closed") return { disabled: true, reason: "This branch is closed." };
  if (streaming || v.reply_in_progress) return { disabled: true, reason: "A reply is being written…" };
  if (v.awaiting_reply) return { disabled: true, reason: "Your last message has no reply yet. Request it, or edit that message." };
  return { disabled: false, reason: null };
}

export function Composer({ view }: { view: BranchView }): JSX.Element {
  const [text, setText] = useState("");
  const s = stream.value;
  const streaming = s !== null && s.branchId === view.branch.id && s.error === null;
  const { disabled, reason } = composerState(view, streaming);

  async function send(): Promise<void> {
    const content = text;
    if (!content.trim() || disabled) return;
    if (await sendMessage(view.branch.id, content)) setText("");
  }

  const canRetry = view.awaiting_reply && !streaming && !view.reply_in_progress && view.branch.status !== "closed";
  return (
    <div class="composer">
      {canRetry && (
        <p class="retry">
          {s?.branchId === view.branch.id && s.error ? `${s.error.message} ` : ""}
          <button type="button" onClick={() => void requestReply(view.branch.id)}>
            Request reply
          </button>
        </p>
      )}
      <textarea
        value={text}
        disabled={disabled}
        placeholder={reason ?? (view.branch.status === "parked" ? "Sending here will resume this tangent" : "Message")}
        rows={3}
        aria-label="Message"
        onInput={(e) => setText(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            void send();
          }
        }}
      />
      <button type="button" disabled={disabled || !text.trim()} onClick={() => void send()}>
        Send
      </button>
    </div>
  );
}
