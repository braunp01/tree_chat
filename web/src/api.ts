// Typed access to the Backend_API (design.md, API Contract and Read models). No state lives here.

export type Status = "parked" | "open" | "closed";
export type Kind = "trunk" | "tangent" | "alternative";
export type Role = "user" | "assistant" | "note";

export interface TreeListItem {
  id: string;
  title: string | null;
  trunk_branch_id: string;
  last_activity_at: string;
  open_count: number;
  parked_count: number;
}

export interface Closing {
  outcome: "merged" | "kept" | "abandoned";
  conclusion: string | null;
  merge_target: string | null;
  note_message_id: string | null;
  closed_at: string;
}

export interface AnchorRef {
  message_id: string;
  start: number;
  end: number;
  quoted_text: string;
}

export interface BranchSummary {
  id: string;
  tree_id: string;
  parent_branch_id: string | null;
  parent_label: string | null;
  kind: Kind;
  anchor: AnchorRef | null;
  /** Conversation_Position of the Anchor Message (null for the Trunk); orders siblings (Req 18.6). */
  anchor_position: number | null;
  created_at: string;
  status_since: string;
  fork_point_message_id: string | null;
  intent: string | null;
  generated_intent: string | null;
  standing: string | null;
  status: Status;
  depth: number;
  message_count: number;
  parked_at: string | null;
  parent_messages_since_fork: number;
  closings: Closing[];
}

export interface TreeDetail {
  id: string;
  title: string | null;
  trunk_branch_id: string;
  branches: BranchSummary[];
}

export interface Marker {
  branch_id: string;
  start: number;
  end: number;
  status: Status;
  intent: string | null;
  generated_intent: string | null;
}

export interface AltRef {
  branch_id: string;
  status: Status;
}

export interface MessageOut {
  id: string;
  branch_id: string;
  parent_message_id: string | null;
  seq: number;
  role: Role;
  content: string;
  model: string | null;
  stop_reason: string | null;
  cut_off: boolean;
  source_branch_id: string | null;
  created_at: string;
}

export interface ViewMessage extends MessageOut {
  markers: Marker[];
  alternatives: AltRef[];
  notes_after: number;
  source?: { branch_id: string; label: string };
}

export type InheritedEntry =
  | { kind: "message"; message: ViewMessage }
  | { kind: "framing"; branch_id: string; text: string; label: string };

export interface BranchView {
  branch: BranchSummary;
  breadcrumb: { id: string; label: string; kind: Kind }[];
  inherited: {
    message_count: number;
    entries: InheritedEntry[];
    anchor_message_id: string | null;
    anchor_message: ViewMessage | null;
  };
  framing: {
    anchor_quote: string;
    intent: string | null;
    generated_intent: string | null;
    fork_point_message_id: string | null;
    text: string | null;
    frozen: boolean;
  } | null;
  messages: ViewMessage[];
  tip_message_id: string | null;
  awaiting_reply: boolean;
  reply_in_progress: boolean;
  assistant_reply_count: number;
}

export interface Manifest {
  model: string;
  settings: { effort: string; max_tokens: number };
  entries: ({ kind: "message"; id: string; role: Role } | { kind: "framing"; branch_id: string; text: string })[];
}

export type ReplyEvent =
  | { type: "started"; job_id: string }
  | { type: "delta"; text: string }
  | { type: "done"; message: MessageOut }
  | { type: "error"; error: string; message: string };

export interface SpawnRequest {
  anchor: AnchorRef;
  intent?: string;
  fork_at: "anchor" | "tip";
  status: "parked" | "open";
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly category: string,
    readonly fields: string[],
    message: string,
  ) {
    super(message);
  }
}

async function failure(r: Response): Promise<ApiError> {
  try {
    const b = await r.json();
    return new ApiError(r.status, b.error ?? "error", b.fields ?? [], b.message ?? r.statusText);
  } catch {
    return new ApiError(r.status, "error", [], r.statusText || "Request failed");
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw await failure(r);
  return (await r.json()) as T;
}

// --- Server-sent events -----------------------------------------------------------------------

/** Split a text buffer into complete `data:` events and the unfinished rest (one JSON object per event). */
export function parseSse(buffer: string): { events: ReplyEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: ReplyEvent[] = [];
  for (const frame of frames) {
    const data = frame
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).replace(/^ /, ""))
      .join("\n");
    if (data) events.push(JSON.parse(data) as ReplyEvent);
  }
  return { events, rest };
}

/** Follow a reply stream (`POST …/reply` or `GET …/live`) to its end, reporting each event. */
async function follow(method: "POST" | "GET", path: string, onEvent: (e: ReplyEvent) => void): Promise<void> {
  const r = await fetch(`/api${path}`, { method });
  if (!r.ok) throw await failure(r);
  if (r.status === 204 || !r.body) return;
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += value;
    const { events, rest } = parseSse(buf);
    buf = rest;
    events.forEach(onEvent);
  }
}

export const api = {
  trees: () => call<TreeListItem[]>("GET", "/trees"),
  createTree: () => call<TreeDetail>("POST", "/trees"),
  renameTree: (id: string, title: string) => call<TreeDetail>("PATCH", `/trees/${id}`, { title }),
  tree: (id: string) => call<TreeDetail>("GET", `/trees/${id}`),
  park: (branchId: string) => call<BranchSummary>("POST", `/branches/${branchId}/park`),
  resume: (branchId: string) => call<BranchSummary>("POST", `/branches/${branchId}/resume`),
  reopen: (branchId: string) => call<BranchSummary>("POST", `/branches/${branchId}/reopen`),
  view: (branchId: string) => call<BranchView>("GET", `/branches/${branchId}/view`),
  send: (branchId: string, content: string) => call<MessageOut>("POST", `/branches/${branchId}/messages`, { content }),
  reply: (branchId: string, onEvent: (e: ReplyEvent) => void) => follow("POST", `/branches/${branchId}/reply`, onEvent),
  live: (branchId: string, onEvent: (e: ReplyEvent) => void) => follow("GET", `/branches/${branchId}/live`, onEvent),
  spawn: (req: SpawnRequest) =>
    call<BranchSummary>("POST", "/branches", {
      anchor: req.anchor,
      intent: req.intent || undefined,
      fork_at: req.fork_at,
      status: req.status,
    }),
  edit: (messageId: string, content: string) =>
    call<BranchSummary>("POST", `/messages/${messageId}/alternatives`, { content }),
  regenerate: (messageId: string) => call<BranchSummary>("POST", `/messages/${messageId}/alternatives`),
  manifest: (messageId: string) => call<Manifest>("GET", `/messages/${messageId}/manifest`),
  preview: (messageId: string) => call<{ id: string; preview: string }>("GET", `/messages/${messageId}/preview`),
};
