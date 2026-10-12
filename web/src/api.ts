// Typed access to the Backend_API (design.md, API Contract). No state lives here.

export type Role = "user" | "assistant";

export interface TreeRow {
  id: string;
  title: string;
  created_at: string;
  last_activity_at: string;
}

export interface MessageOut {
  id: string;
  tree_id: string;
  parent_id: string | null;
  role: Role;
  content: string;
  model: string | null;
  stop_reason: string | null;
  cut_off: boolean;
  created_at: string;
}

export interface PathMessage extends MessageOut {
  child_count: number;
}

export interface PathOut {
  tree_id: string;
  messages: PathMessage[];
  awaiting_reply: boolean;
  reply_in_progress: boolean;
  /** The most recently created Reply below the last Message, if it has children (Req 2.4). */
  latest_below: string | null;
}

export interface BranchOut {
  id: string;
  parent_branch_id: string | null;
  message_ids: string[];
  /** Req 6.2, 9.4: the Branch_Summary, or the start of its first question until that exists. */
  label: string;
  summary: string | null;
  /** Req 9.4: a summary is being written now; the Tree shape is fetched again until it arrives. */
  summary_pending: boolean;
  /** Req 6.8: the start of the Branch's first question. */
  question: string;
  forked_from: string | null;
  forked_from_preview: string | null;
  created_at: string;
}

export interface TreeShape extends TreeRow {
  default_point: string | null;
  branches: BranchOut[];
}

export interface Manifest {
  system_prompt_version: number;
  model: string;
  settings: { effort: string; max_tokens: number };
  entries: { id: string; role: Role }[];
  cache_breakpoint_after: number | null;
}

export type ReplyEvent =
  | { type: "started"; job_id: string }
  | { type: "delta"; text: string }
  | { type: "done"; message: MessageOut }
  | { type: "error"; error: string; message: string };

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
  trees: () => call<TreeRow[]>("GET", "/trees"),
  createTree: (content: string) => call<{ tree: TreeRow; message: MessageOut }>("POST", "/trees", { content }),
  renameTree: (id: string, title: string) => call<TreeRow>("PATCH", `/trees/${id}`, { title }),
  tree: (id: string) => call<TreeShape>("GET", `/trees/${id}`),
  path: (messageId: string) => call<PathOut>("GET", `/messages/${messageId}/path`),
  send: (treeId: string, parentId: string, content: string) =>
    call<MessageOut>("POST", `/trees/${treeId}/messages`, { parent_id: parentId, content }),
  reply: (userId: string, onEvent: (e: ReplyEvent) => void) => follow("POST", `/messages/${userId}/reply`, onEvent),
  live: (userId: string, onEvent: (e: ReplyEvent) => void) => follow("GET", `/messages/${userId}/live`, onEvent),
  manifest: (messageId: string) => call<Manifest>("GET", `/messages/${messageId}/manifest`),
};
