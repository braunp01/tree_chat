import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fc from "fast-check";
import { hashFor, navigate, newTree, notice, openTree, parseHash, path, requestReply, send, shape, stream, treeId } from "./state";
import { branch, msg, pathOf, tree } from "./fixtures";

type Handler = (method: string, url: string, body: unknown) => Response | undefined;
let calls: string[];

const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });
const sse = (...events: unknown[]) =>
  new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""), { status: 200, headers: { "content-type": "text/event-stream" } });

function server(h: Handler): void {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    const r = h(method, url, init?.body ? JSON.parse(init.body as string) : undefined);
    return r ?? json({ error: "not_found", fields: [], message: "no" }, 404);
  });
}

/** Let the hashchange-free navigation and the stream promises settle. */
const settle = () => new Promise((r) => setTimeout(r, 10));

beforeEach(() => {
  calls = [];
  treeId.value = null;
  shape.value = null;
  path.value = null;
  stream.value = null;
  location.hash = "";
});
afterEach(() => vi.unstubAllGlobals());

describe("the address (design: Current_Point in the address)", () => {
  it("round-trips every Route", () => {
    const id = fc.stringMatching(/^[0-9a-f-]{1,40}$/);
    fc.assert(
      fc.property(fc.option(id, { nil: null }), fc.option(id, { nil: null }), (tree, point) => {
        const r = { tree, point: tree ? point : null };
        expect(parseHash(hashFor(r))).toEqual(r);
      }),
    );
    expect(parseHash("#/garbage")).toEqual({ tree: null, point: null });
  });
});

describe("navigation (Req 2.2, 2.3)", () => {
  it("opening a Tree shows the Path to its default point, the latest Reply", async () => {
    server((m, url) => {
      if (url === "/api/trees/tree1") return json(tree([branch("r")], { default_point: "r-r" }));
      if (url === "/api/messages/r-r/path") return json(pathOf([msg("r", "user"), msg("r-r", "assistant")]));
    });
    navigate({ tree: "tree1", point: null });
    await settle();
    expect(path.value?.messages.at(-1)?.id).toBe("r-r");
    expect(calls.every((c) => c.startsWith("GET"))).toBe(true);
  });
});

describe("leaving a point (Req 1.1, 3.1)", () => {
  it("takes effect at once: after New tree, a send creates a Tree and adds nothing to the old one", async () => {
    treeId.value = "tree1";
    shape.value = tree([branch("r")]);
    path.value = pathOf([msg("r", "user"), msg("r-r", "assistant")]);
    location.hash = "#/t/tree1/m/r-r";
    server((m, url) => {
      if (m === "POST" && url === "/api/trees") return json({ tree: { id: "t9", title: "Hi" }, message: msg("root", "user") }, 201);
      if (url === "/api/trees") return json([]);
    });
    newTree(); // no hashchange has been handled yet
    expect(treeId.value).toBeNull();
    expect(path.value).toBeNull();
    await send("Hi");
    expect(calls).toContain("POST /api/trees");
    expect(calls.some((c) => c.includes("/api/trees/tree1/messages"))).toBe(false);
  });

  it("opening another Tree clears the old Path before the new one arrives", () => {
    treeId.value = "tree1";
    shape.value = tree([branch("r")]);
    path.value = pathOf([msg("r", "user"), msg("r-r", "assistant")]);
    server(() => undefined);
    openTree("tree2");
    expect(treeId.value).toBe("tree2");
    expect(path.value).toBeNull();
  });
});

describe("sending (Req 1.1, 3.1, 3.4)", () => {
  it("adds a child of the Current_Point, streams the Reply, and makes the Reply the Current_Point", async () => {
    treeId.value = "tree1";
    shape.value = tree([branch("r")]);
    path.value = pathOf([msg("r", "user"), msg("r-r", "assistant")]);
    location.hash = "#/t/tree1/m/r-r";
    const saw: string[] = [];
    server((m, url, body) => {
      if (m === "POST" && url === "/api/trees/tree1/messages") {
        expect(body).toEqual({ parent_id: "r-r", content: "and then?" });
        return json(msg("u2", "user"), 201);
      }
      if (m === "POST" && url === "/api/messages/u2/reply") {
        return sse({ type: "started", job_id: "j" }, { type: "delta", text: "Then " }, { type: "delta", text: "this." }, { type: "done", message: msg("a2", "assistant") });
      }
      if (url === "/api/trees/tree1") return json(tree([branch("r")]));
      if (url === "/api/trees") return json([]);
      if (url.endsWith("/path")) return json(pathOf([msg("r", "user"), msg("r-r", "assistant"), msg("u2", "user")]));
    });
    const unwatch = stream.subscribe((s) => s?.text && saw.push(s.text));
    expect(await send("and then?")).toBe(true);
    await settle();
    unwatch();
    expect(saw).toContain("Then this.");
    expect(location.hash).toBe("#/t/tree1/m/a2");
    expect(stream.value).toBeNull();
  });

  it("from the New tree page creates a Tree whose Root is the Message (Req 1.1)", async () => {
    server((m, url) => {
      if (m === "POST" && url === "/api/trees") return json({ tree: { id: "t9", title: "Hi" }, message: msg("root", "user") }, 201);
      if (m === "POST" && url === "/api/messages/root/reply") return sse({ type: "error", error: "provider_unavailable", message: "No key." });
      if (url === "/api/trees") return json([]);
    });
    expect(await send("Hi")).toBe(true);
    await settle();
    expect(calls).toContain("POST /api/trees");
    expect(location.hash).toBe("#/t/t9/m/root");
    // Req 3.5: the error is reported, the question stays, and the Reply can be asked for again.
    expect(stream.value).toEqual({ userId: "root", text: "", error: { category: "provider_unavailable", message: "No key." } });
  });

  it("shows the server's refusal and moves nowhere (Req 3.2, 3.10)", async () => {
    treeId.value = "tree1";
    path.value = pathOf([msg("r", "user")]);
    location.hash = "#/t/tree1/m/r";
    server(() => json({ error: "conflict", fields: [], message: "Send from a reply." }, 409));
    expect(await send("x")).toBe(false);
    expect(notice.value).toBe("Send from a reply.");
    expect(location.hash).toBe("#/t/tree1/m/r");
  });

  it("a second request for the same Reply reports busy (Req 3.7)", async () => {
    server(() => json({ error: "busy", fields: [], message: "The reply to this message is already being written." }, 409));
    await requestReply("u1");
    expect(stream.value?.error?.message).toContain("already being written");
  });
});
