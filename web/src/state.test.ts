// The send / stream / error flow against a scripted fetch (Req 2.1-2.3, 2.6, 4.2).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { branchId, notice, requestReply, sendMessage, spawnTangent, stream, view } from "./state";
import { msg, summary, trunkView } from "./fixtures";

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;
let calls: string[] = [];

function sse(...events: object[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });

function script(h: Handler): void {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    return h(url, init);
  });
}

beforeEach(() => {
  calls = [];
  branchId.value = "b1";
  view.value = null;
  stream.value = null;
  notice.value = null;
});
afterEach(() => vi.unstubAllGlobals());

describe("replies", () => {
  it("streams the text, then refreshes the view and clears the stream", async () => {
    const final = trunkView([msg("u", "user", "hi"), msg("a", "assistant", "hello there")]);
    script((url) => {
      if (url.endsWith("/reply")) return sse({ type: "started", job_id: "j" }, { type: "delta", text: "hello " }, { type: "delta", text: "there" }, { type: "done", message: msg("a", "assistant", "hello there") });
      if (url.endsWith("/view")) return json(final);
      return json([]);
    });
    const seen: string[] = [];
    const stop = stream.subscribe((s) => s && seen.push(s.text));
    await requestReply("b1");
    stop();
    expect(seen).toContain("hello there");
    expect(stream.value).toBeNull();
    expect(view.value?.messages.map((m) => m.id)).toEqual(["u", "a"]);
  });

  it("keeps the error and leaves the user message in place when the model fails (Req 2.3)", async () => {
    script((url) => {
      if (url.endsWith("/reply")) return sse({ type: "started", job_id: "j" }, { type: "error", error: "provider_error", message: "The provider failed." });
      if (url.endsWith("/view")) return json(trunkView([msg("u", "user", "hi")], { awaiting_reply: true }));
      return json([]);
    });
    await requestReply("b1");
    expect(stream.value?.error).toEqual({ category: "provider_error", message: "The provider failed." });
    expect(view.value?.awaiting_reply).toBe(true);
  });

  it("shows a refused request as an ordinary message, not a crash (Req 2.5)", async () => {
    script(() => json({ error: "busy", fields: [], message: "A reply is already being generated in this branch." }, 409));
    await requestReply("b1");
    expect(stream.value?.error?.message).toMatch(/already being generated/);
  });

  it("saves the message, then asks for the reply (Req 2.1)", async () => {
    script((url, init) => {
      if (url.endsWith("/messages")) return json(msg("u", "user", "hi"), 201);
      if (url.endsWith("/reply")) return sse({ type: "done", message: msg("a", "assistant", "ok") });
      return json(trunkView([]));
    });
    expect(await sendMessage("b1", "hi")).toBe(true);
    await vi.waitFor(() => expect(stream.value).toBeNull());
    expect(calls.filter((c) => /messages|reply/.test(c))).toEqual(["POST /api/branches/b1/messages", "POST /api/branches/b1/reply"]);
  });

  it("does not ask for a reply when the send is rejected, and says why (Req 2.7, 2.9)", async () => {
    script(() => json({ error: "conflict", fields: [], message: "Wait for the reply." }, 409));
    expect(await sendMessage("b1", "hi")).toBe(false);
    expect(notice.value).toBe("Wait for the reply.");
    expect(calls).toEqual(["POST /api/branches/b1/messages"]);
  });
});

describe("spawning (Req 4.2)", () => {
  const req = { anchor: { message_id: "m", start: 0, end: 1, quoted_text: "x" }, fork_at: "anchor" as const };

  it("a parked tangent keeps the current view; an open one navigates", async () => {
    script((url) => (url.endsWith("/branches") ? json(summary("t1"), 201) : json(trunkView([]))));
    location.hash = "#/b/b1";
    expect(await spawnTangent({ ...req, status: "parked" })).toBe(true);
    expect(location.hash).toBe("#/b/b1");
    expect(await spawnTangent({ ...req, status: "open" })).toBe(true);
    expect(location.hash).toBe("#/b/t1");
  });

  it("reports a refused anchor and creates nothing", async () => {
    script(() => json({ error: "validation", fields: ["anchor"], message: "quoted_text does not match" }, 422));
    expect(await spawnTangent({ ...req, status: "parked" })).toBe(false);
    expect(notice.value).toMatch(/does not match/);
  });
});
