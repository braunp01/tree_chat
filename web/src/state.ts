// Application state (signals) and the two user actions: navigate to a point, and send from it (Req 2, 3).
// Rules live in the Backend_API; this only orchestrates calls and keeps what is on screen current.
import { signal } from "@preact/signals";
import { api, ApiError, type PathOut, type ReplyEvent, type TreeRow, type TreeShape } from "./api";

export const trees = signal<TreeRow[]>([]);
/** The open Tree, or null on the "New tree" page. */
export const treeId = signal<string | null>(null);
export const shape = signal<TreeShape | null>(null);
/** The Path to the Current_Point (Req 2.1). Its last Message is the Current_Point. */
export const path = signal<PathOut | null>(null);
/** A Reply arriving now (Req 3.3) or the error that ended one (Req 3.5). */
export interface StreamState {
  userId: string;
  text: string;
  error: { category: string; message: string } | null;
}
export const stream = signal<StreamState | null>(null);
export const notice = signal<string | null>(null);
/** The Branch_Graph enlarged to the whole window (Req 6.9). */
export const graphEnlarged = signal(false);
/** Branches the user expanded in the graph, per Tree (Req 6.4: kept while the user stays in the Tree). */
export const expandedByTree = signal<Record<string, string[]>>({});

export function describe(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}

export function currentPoint(): string | null {
  return path.value?.messages.at(-1)?.id ?? null;
}

// --- Routing: the address bar is the source of truth, so back and forward work ---------------------

export interface Route {
  tree: string | null;
  point: string | null;
}

export function hashFor(r: Route): string {
  if (!r.tree) return "#/new";
  return r.point ? `#/t/${r.tree}/m/${r.point}` : `#/t/${r.tree}`;
}

export function parseHash(hash: string): Route {
  const m = /^#\/t\/([^/]+)(?:\/m\/([^/]+))?$/.exec(hash);
  return m ? { tree: decodeURIComponent(m[1]!), point: m[2] ? decodeURIComponent(m[2]) : null } : { tree: null, point: null };
}

let applied = "";
/** Applied at once, not on the later `hashchange`, so nothing can be sent from the point being left. */
export function navigate(r: Route): void {
  const h = hashFor(r);
  void show(r);
  if (location.hash !== h) location.hash = h;
}

export function startRouting(): void {
  // Back and forward, a typed address, or the first load; a hash this app just set is already shown.
  const sync = () => {
    const r = parseHash(location.hash);
    if (hashFor(r) !== applied) void show(r);
  };
  window.addEventListener("hashchange", sync);
  sync();
}

// --- Loading ----------------------------------------------------------------------------------------

export async function loadTrees(): Promise<void> {
  try {
    trees.value = await api.trees();
  } catch (e) {
    notice.value = describe(e);
  }
}

export async function refreshShape(): Promise<void> {
  const id = treeId.value;
  if (!id) return;
  try {
    const s = await api.tree(id);
    if (treeId.value === id) shape.value = s;
  } catch {
    /* the graph keeps what it had */
  }
}

async function show(r: Route): Promise<void> {
  const key = hashFor(r);
  applied = key;
  notice.value = null;
  if (!r.tree) {
    treeId.value = null;
    shape.value = null;
    path.value = null;
    return;
  }
  try {
    if (treeId.value !== r.tree || !shape.value) {
      treeId.value = r.tree;
      shape.value = null;
      path.value = null; // another Tree's Path must not stay on screen, or be sent from
      shape.value = await api.tree(r.tree);
    }
    const point = r.point ?? shape.value?.default_point ?? null; // Req 2.2
    const p = point ? await api.path(point) : null;
    if (applied !== key) return; // the user has moved on
    path.value = p;
    // Req 3.8: a Reply still being written is picked up again, with the text so far.
    const last = p?.messages.at(-1);
    if (p?.reply_in_progress && last && stream.value?.userId !== last.id) void follow(last.id, (on) => api.live(last.id, on));
  } catch (e) {
    notice.value = describe(e);
  }
}

export async function refreshPath(): Promise<void> {
  const r = parseHash(location.hash);
  await show(r);
}

// --- Sending and replies ----------------------------------------------------------------------------

type Attach = (onEvent: (e: ReplyEvent) => void) => Promise<void>;

async function follow(userId: string, attach: Attach): Promise<void> {
  stream.value = { userId, text: "", error: null };
  let reply: string | null = null;
  try {
    await attach((e) => {
      const s = stream.value;
      if (!s || s.userId !== userId) return;
      if (e.type === "delta") stream.value = { ...s, text: s.text + e.text };
      else if (e.type === "error") stream.value = { ...s, text: "", error: { category: e.error, message: e.message } };
      else if (e.type === "done") reply = e.message.id;
    });
  } catch (e) {
    stream.value = { userId, text: "", error: { category: "error", message: describe(e) } };
    return;
  }
  void loadTrees();
  await refreshShape();
  if (reply && stream.value?.userId === userId) {
    stream.value = null;
    // Req 3.4: the new Reply becomes the Current_Point, if the user is still looking at its question.
    const here = parseHash(location.hash);
    if (here.tree === treeId.value && (here.point === userId || currentPoint() === userId)) navigate({ tree: treeId.value, point: reply });
    else await refreshPath();
  }
}

/** Req 3.3, 3.10: ask for the Reply to a question (again, after a failure). */
export function requestReply(userId: string): Promise<void> {
  return follow(userId, (on) => api.reply(userId, on));
}

/** Req 1.1, 3.1: the one Send action. On the "New tree" page it creates a Tree with this Message as its Root;
 * otherwise the Message becomes a new child of the Current_Point. Returns false if the send was refused. */
export async function send(content: string): Promise<boolean> {
  try {
    if (!treeId.value) {
      const made = await api.createTree(content);
      void loadTrees();
      navigate({ tree: made.tree.id, point: made.message.id });
      void requestReply(made.message.id);
      return true;
    }
    const point = currentPoint();
    if (!point) return false;
    const m = await api.send(treeId.value, point, content);
    navigate({ tree: treeId.value, point: m.id });
    void refreshShape(); // the new question shows in the graph at once
    void requestReply(m.id);
    return true;
  } catch (e) {
    notice.value = describe(e);
    return false;
  }
}

/** Req 2.3, 6.5: go to a point. Creates nothing. */
export function goTo(messageId: string): void {
  if (treeId.value) navigate({ tree: treeId.value, point: messageId });
}

export function newTree(): void {
  navigate({ tree: null, point: null });
}

export function openTree(id: string): void {
  navigate({ tree: id, point: null });
}

export function toggleExpanded(branchId: string): void {
  const tree = treeId.value;
  if (!tree) return;
  const cur = new Set(expandedByTree.value[tree] ?? []);
  if (cur.has(branchId)) cur.delete(branchId);
  else cur.add(branchId);
  expandedByTree.value = { ...expandedByTree.value, [tree]: [...cur] };
}
