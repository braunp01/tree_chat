// Synthetic API data for tests (no real conversations).
import type { BranchSummary, BranchView, Marker, ViewMessage } from "./api";

export function msg(id: string, role: ViewMessage["role"], content: string, extra: Partial<ViewMessage> = {}): ViewMessage {
  return {
    id, branch_id: "b1", parent_message_id: null, seq: 0, role, content, model: null, stop_reason: null,
    cut_off: false, source_branch_id: null, created_at: "t", markers: [], alternatives: [], notes_after: 0, ...extra,
  };
}

export function marker(branch_id: string, start: number, end: number, status: Marker["status"] = "parked", intent: string | null = null): Marker {
  return { branch_id, start, end, status, intent, generated_intent: null };
}

export function summary(id: string, extra: Partial<BranchSummary> = {}): BranchSummary {
  return {
    id, tree_id: "t1", parent_branch_id: null, parent_label: null, kind: "trunk", anchor: null, fork_point_message_id: null,
    intent: null, generated_intent: null, standing: null, status: "open", depth: 0, message_count: 0, parked_at: null,
    parent_messages_since_fork: 0, closings: [], ...extra,
  };
}

export function trunkView(messages: ViewMessage[], extra: Partial<BranchView> = {}): BranchView {
  return {
    branch: summary("b1"), breadcrumb: [], inherited: { message_count: 0, entries: [], anchor_message_id: null, anchor_message: null },
    framing: null, messages, tip_message_id: messages.at(-1)?.id ?? null, awaiting_reply: false, reply_in_progress: false,
    assistant_reply_count: 0, ...extra,
  };
}
