// Application state (signals) and the operations that change it. Rules live in the Backend_API; this only
// orchestrates calls and keeps what is on screen current.
import { signal } from "@preact/signals";
import { api, ApiError, type BranchView, type ReplyEvent, type SpawnRequest, type TreeDetail, type TreeListItem } from "./api";

export const trees = signal<TreeListItem[]>([]);
/** Every Branch of the current Tree, for the Branch_Graph (Req 14.1, 18). */
export const treeDetail = signal<TreeDetail | null>(null);
/** Branches the user expanded in the graph, per Tree (Req 18.4: kept while the user stays in the Tree). */
export const expandedByTree = signal<Record<string, string[]>>({});
/** The Branch_Graph enlarged to the whole window (Req 14.8, 18.11). */
export const graphEnlarged = signal(false);
export const branchId = signal<string | null>(null);
export const view = signal<BranchView | null>(null);
/** A reply arriving now (Req 2.2) or the error that ended one (Req 2.3). */
export interface StreamState {
  branchId: string;
  text: string;
  error: { category: string; message: string } | null;
}
export const stream = signal<StreamState | null>(null);
export const notice = signal<string | null>(null);
/** The passage whose Anchor_Marker is hovered or focused (Req 5.2). */
export const highlight = signal<{ messageId: string; start: number; end: number } | null>(null);

export function describe(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}

function fail(e: unknown): void {
  notice.value = describe(e);
}

// --- Routing: the address bar is the source of truth, so back and forward work ---------------------

export function hashFor(id: string | null): string {
  return id ? `#/b/${id}` : "#/";
}

export function parseHash(hash: string): string | null {
  const m = /^#\/b\/([^/]+)$/.exec(hash);
  return m ? decodeURIComponent(m[1]!) : null;
}

export function navigate(id: string): void {
  if (location.hash === hashFor(id)) void showBranch(id);
  else location.hash = hashFor(id);
}

export function startRouting(): void {
  const sync = () => void showBranch(parseHash(location.hash));
  window.addEventListener("hashchange", sync);
  sync();
}

// --- Loading ----------------------------------------------------------------------------------------

export async function loadTrees(): Promise<void> {
  try {
    trees.value = await api.trees();
  } catch (e) {
    fail(e);
  }
}

/** Reload the Branch_Graph's data. Failures are quiet: the Path_View still works without it. */
export async function refreshTree(treeId: string): Promise<void> {
  try {
    const t = await api.tree(treeId);
    if (view.value?.branch.tree_id === treeId) treeDetail.value = t; // ignore a late answer for a Tree we left
  } catch {
    /* the graph keeps what it had */
  }
}

export async function refreshView(): Promise<void> {
  const id = branchId.value;
  if (!id) return;
  try {
    const v = await api.view(id);
    if (branchId.value === id) {
      view.value = v;
      void refreshTree(v.branch.tree_id);
    }
  } catch (e) {
    fail(e);
  }
}

export function toggleExpanded(id: string): void {
  const tree = view.value?.branch.tree_id;
  if (!tree) return;
  const cur = new Set(expandedByTree.value[tree] ?? []);
  if (cur.has(id)) cur.delete(id);
  else cur.add(id);
  expandedByTree.value = { ...expandedByTree.value, [tree]: [...cur] };
}

/** Req 10.1, 18.12: park, resume or reopen the current Branch. Closing has its own panel (step 8). */
export async function changeStatus(action: "park" | "resume" | "reopen"): Promise<void> {
  const id = branchId.value;
  if (!id) return;
  try {
    await api[action](id);
    notice.value = null;
    await refreshView();
    void loadTrees();
  } catch (e) {
    fail(e);
  }
}

async function showBranch(id: string | null): Promise<void> {
  branchId.value = id;
  notice.value = null;
  if (!id) {
    view.value = null;
    treeDetail.value = null;
    return;
  }
  try {
    const v = await api.view(id);
    if (branchId.value !== id) return;
    view.value = v;
    if (treeDetail.value?.id !== v.branch.tree_id) treeDetail.value = null; // a different Tree: do not draw the old one
    void refreshTree(v.branch.tree_id);
    // Req 2.6: a reply that is still being written is picked up again, with the text so far.
    if (v.reply_in_progress && stream.value?.branchId !== id) void follow(id, (on) => api.live(id, on));
  } catch (e) {
    view.value = null;
    fail(e);
  }
}

export async function createTree(): Promise<void> {
  try {
    const t = await api.createTree();
    await loadTrees();
    navigate(t.trunk_branch_id);
  } catch (e) {
    fail(e);
  }
}

export function openTree(item: TreeListItem): void {
  navigate(item.trunk_branch_id);
}

// --- Writing ----------------------------------------------------------------------------------------

type Attach = (onEvent: (e: ReplyEvent) => void) => Promise<void>;

async function follow(id: string, attach: Attach): Promise<void> {
  stream.value = { branchId: id, text: "", error: null };
  let finished = false;
  try {
    await attach((e) => {
      const s = stream.value;
      if (!s || s.branchId !== id) return;
      if (e.type === "delta") stream.value = { ...s, text: s.text + e.text };
      else if (e.type === "error") {
        finished = true;
        stream.value = { ...s, text: "", error: { category: e.error, message: e.message } };
      } else if (e.type === "done") finished = true;
    });
  } catch (e) {
    stream.value = { branchId: id, text: "", error: { category: "error", message: describe(e) } };
    return;
  }
  await refreshView(); // the saved reply replaces the streamed text without a gap
  if (finished && stream.value?.error === null) stream.value = null;
  void loadTrees(); // counts and activity order changed
}

/** Req 2.2: ask for the reply to the Tip and show it as it is written. */
export function requestReply(id: string): Promise<void> {
  return follow(id, (on) => api.reply(id, on));
}

/** Req 2.1: persist the message first, then ask for the reply. Returns false if the send was refused. */
export async function sendMessage(id: string, content: string): Promise<boolean> {
  try {
    await api.send(id, content);
  } catch (e) {
    fail(e);
    return false;
  }
  notice.value = null;
  await refreshView();
  void requestReply(id);
  return true;
}

/** Req 4.2: parked spawns leave the view unchanged apart from the new marker; open spawns navigate. */
export async function spawnTangent(req: SpawnRequest): Promise<boolean> {
  try {
    const b = await api.spawn(req);
    void loadTrees();
    if (req.status === "open") navigate(b.id);
    else await refreshView();
    return true;
  } catch (e) {
    fail(e);
    return false;
  }
}

/** Req 3.2-3.3: edit or regenerate makes an Alternative; go there and get its reply. */
export async function makeAlternative(messageId: string, content?: string): Promise<boolean> {
  try {
    const alt = content === undefined ? await api.regenerate(messageId) : await api.edit(messageId, content);
    navigate(alt.id);
    // navigate() loads the view asynchronously; ask for the reply once the Branch exists on screen.
    void requestReply(alt.id);
    return true;
  } catch (e) {
    fail(e);
    return false;
  }
}
