// Req 9.4: a node's Branch_Summary replaces its question label within seconds, without a reload.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SUMMARY_POLL_FOR_MS, SUMMARY_POLL_MS, newTree, path, refreshShape, shape, stream, treeId } from "./state";
import { branch, tree } from "./fixtures";
import type { TreeShape } from "./api";

let gets: number;
let reply: () => TreeShape;

const pending = () => tree([branch("r", { question: "Why is the sky blue?", label: "Why is the sky blue?", summary_pending: true })]);
const named = () =>
  tree([branch("r", { question: "Why is the sky blue?", label: "Rayleigh scattering of sunlight", summary: "Rayleigh scattering of sunlight" })]);

beforeEach(() => {
  vi.useFakeTimers();
  gets = 0;
  reply = pending;
  treeId.value = "tree1";
  shape.value = null;
  path.value = null;
  stream.value = null;
  vi.stubGlobal("fetch", async (url: string) => {
    if (url === "/api/trees/tree1") gets++;
    return new Response(JSON.stringify(url === "/api/trees/tree1" ? reply() : []), { status: 200 });
  });
});
afterEach(() => {
  newTree(); // leaves the Tree, which stops any polling
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("waiting for Branch summaries (Req 9.4)", () => {
  it("fetches the shape again until the summary arrives, then stops", async () => {
    await refreshShape();
    expect(shape.value?.branches[0]?.label).toBe("Why is the sky blue?");
    expect(gets).toBe(1);
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_MS);
    expect(gets).toBe(2); // still pending: asked again
    reply = named;
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_MS);
    expect(gets).toBe(3);
    expect(shape.value?.branches[0]?.label).toBe("Rayleigh scattering of sunlight");
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_MS * 5);
    expect(gets).toBe(3); // nothing pending: no more requests
  });

  it("gives up after a minute if a summary never comes", async () => {
    await refreshShape();
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_FOR_MS + SUMMARY_POLL_MS * 3);
    const after = gets;
    expect(after).toBeLessThanOrEqual(SUMMARY_POLL_FOR_MS / SUMMARY_POLL_MS + 2);
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_MS * 10);
    expect(gets).toBe(after);
  });

  it("stops when the user leaves the Tree", async () => {
    await refreshShape();
    newTree();
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_MS * 5);
    expect(gets).toBe(1);
  });

  it("does not poll when nothing is pending", async () => {
    reply = named;
    await refreshShape();
    await vi.advanceTimersByTimeAsync(SUMMARY_POLL_MS * 5);
    expect(gets).toBe(1);
  });
});
