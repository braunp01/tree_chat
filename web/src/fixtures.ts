// Synthetic test data in the shapes the Backend_API returns (design.md, API Contract).
import type { BranchOut, PathMessage, PathOut, Role, TreeShape } from "./api";

export function branch(id: string, extra: Partial<BranchOut> = {}): BranchOut {
  return {
    id,
    parent_branch_id: null,
    message_ids: [id, `${id}-r`],
    label: `Label ${id}`,
    summary: null,
    summary_pending: false,
    question: `Label ${id}`,
    forked_from: null,
    forked_from_preview: null,
    created_at: "t00000",
    ...extra,
  };
}

export function tree(branches: BranchOut[], extra: Partial<TreeShape> = {}): TreeShape {
  return {
    id: "tree1",
    title: "My tree",
    created_at: "t00000",
    last_activity_at: "t00000",
    default_point: branches[0]?.message_ids.at(-1) ?? null,
    branches,
    ...extra,
  };
}

export function msg(id: string, role: Role, content = `text of ${id}`, extra: Partial<PathMessage> = {}): PathMessage {
  return {
    id,
    tree_id: "tree1",
    parent_id: null,
    role,
    content,
    model: role === "assistant" ? "claude-opus-5-5" : null,
    stop_reason: role === "assistant" ? "end_turn" : null,
    cut_off: false,
    created_at: "t00000",
    child_count: 0,
    ...extra,
  };
}

/** A Path whose Messages alternate user, assistant, … and are chained by parent. */
export function pathOf(messages: PathMessage[], extra: Partial<PathOut> = {}): PathOut {
  const chained = messages.map((m, i) => ({ ...m, parent_id: i === 0 ? null : messages[i - 1]!.id, child_count: m.child_count || (i < messages.length - 1 ? 1 : 0) }));
  const last = chained.at(-1);
  const waiting = last?.role === "user";
  return { tree_id: "tree1", messages: chained, awaiting_reply: waiting, reply_in_progress: false, latest_below: null, ...extra };
}
