import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "preact";
import { act } from "preact/test-utils";
import { Chat, branchHint, composerState } from "./Chat";
import { path, stream, treeId } from "../state";
import { msg, pathOf } from "../fixtures";

let host: HTMLElement;
let calls: { method: string; url: string; body: unknown }[];

function mount(): HTMLElement {
  host = document.createElement("div");
  document.body.append(host);
  act(() => render(<Chat />, host));
  return host;
}

beforeEach(() => {
  calls = [];
  treeId.value = "tree1";
  stream.value = null;
  location.hash = "";
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(init.body as string) : undefined });
    if (url.endsWith("/path")) return new Response(JSON.stringify(pathOf([msg("u1", "user"), msg("a1", "assistant")])), { status: 200 });
    return new Response(JSON.stringify(msg("new", "user")), { status: 201 });
  });
});
afterEach(() => {
  render(null, host);
  host.remove();
  vi.unstubAllGlobals();
});

const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(text));
const click = async (el: Element) => act(async () => void el.dispatchEvent(new MouseEvent("click", { bubbles: true })));

const conversation = () =>
  pathOf([msg("u1", "user", "**not bold**"), msg("a1", "assistant", "**bold**"), msg("u2", "user"), msg("a2", "assistant")]);

describe("the chat shows the Path (Req 2.1, 2.6)", () => {
  it("shows every Message oldest first, assistant as markdown and user as typed", () => {
    path.value = conversation();
    mount();
    const ids = [...host.querySelectorAll("[data-message-id]")].map((e) => e.getAttribute("data-message-id"));
    expect(ids).toEqual(["u1", "a1", "u2", "a2"]);
    expect(host.querySelector('[data-message-id="u1"]')!.textContent).toContain("**not bold**");
    expect(host.querySelector('[data-message-id="a1"] strong')!.textContent).toBe("bold");
  });

  it("offers 'go back to here' on earlier replies only, and going back creates nothing (Req 2.3, 2.5)", async () => {
    path.value = conversation();
    mount();
    const a1 = host.querySelector('[data-message-id="a1"]')!;
    const a2 = host.querySelector('[data-message-id="a2"]')!;
    expect(a1.textContent).toContain("Go back to here");
    expect(a2.textContent).not.toContain("Go back to here");
    expect(host.querySelector('[data-message-id="u1"] .msg-actions')).toBeNull(); // user Messages have no actions
    await click([...a1.querySelectorAll("button")].find((b) => b.textContent === "Go back to here")!);
    expect(location.hash).toBe("#/t/tree1/m/a1");
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("marks a Reply that was cut off (Req 3.6)", () => {
    path.value = pathOf([msg("u1", "user"), msg("a1", "assistant", "partial", { cut_off: true, stop_reason: "max_tokens" })]);
    mount();
    expect(host.querySelector(".cutoff")).not.toBeNull();
  });
});

describe("sending (Req 2.4, 3.1, 3.4)", () => {
  it("sends from the Current_Point and asks for the Reply at once", async () => {
    path.value = conversation();
    mount();
    const ta = host.querySelector("textarea")!;
    await act(async () => {
      ta.value = "next question";
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => void ta.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    await act(async () => void (await new Promise((r) => setTimeout(r, 0))));
    expect(calls[0]).toEqual({ method: "POST", url: "/api/trees/tree1/messages", body: { parent_id: "a2", content: "next question" } });
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/messages/new/reply")).toBe(true);
    expect(location.hash).toBe("#/t/tree1/m/new");
  });

  it("says when sending will start a new branch, and jumps to the latest Message below (Req 2.4)", async () => {
    path.value = pathOf([msg("u1", "user"), msg("a1", "assistant", "x", { child_count: 2 })], { latest_below: "a9" });
    mount();
    expect(host.querySelector(".branch-hint")!.textContent).toContain("new branch");
    await click(button("Jump to the latest")!);
    expect(location.hash).toBe("#/t/tree1/m/a9");
  });

  it("shows no hint at a Leaf", () => {
    path.value = conversation();
    mount();
    expect(host.querySelector(".branch-hint")).toBeNull();
  });
});

describe("a question without a Reply (Req 3.5, 3.10)", () => {
  it("offers to request the Reply and keeps the composer off", async () => {
    path.value = pathOf([msg("u1", "user")]);
    mount();
    expect(host.querySelector("textarea")!.disabled).toBe(true);
    await click(button("Request reply")!);
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/messages/u1/reply")).toBe(true);
  });

  it("shows the error that ended a Reply, with Try again", () => {
    path.value = pathOf([msg("u1", "user")]);
    stream.value = { userId: "u1", text: "", error: { category: "refused", message: "The model declined." } };
    mount();
    expect(host.textContent).toContain("The model declined.");
    expect(button("Try again")).toBeTruthy();
  });

  it("shows the Reply as it is written (Req 3.3)", () => {
    path.value = pathOf([msg("u1", "user")]);
    stream.value = { userId: "u1", text: "Half a *reply*", error: null };
    mount();
    expect(host.querySelector(".writing em")!.textContent).toBe("reply");
    expect(button("Request reply")).toBeUndefined();
  });
});

describe("composerState and branchHint", () => {
  it("allows sending on the New tree page and after a Reply, not after a pending question", () => {
    expect(composerState(null, null).disabled).toBe(false);
    expect(composerState(conversation(), null).disabled).toBe(false);
    expect(composerState(pathOf([msg("u", "user")]), null)).toEqual({ disabled: true, reason: expect.stringContaining("no reply") });
    expect(composerState(pathOf([msg("u", "user")], { reply_in_progress: true }), null).reason).toContain("being written");
    expect(composerState(pathOf([msg("u", "user")]), { userId: "u", text: "", error: null }).reason).toContain("being written");
  });

  it("hints only at a reply that already has children", () => {
    expect(branchHint(null)).toBeNull();
    expect(branchHint(conversation())).toBeNull();
    expect(branchHint(pathOf([msg("u", "user", "x", { child_count: 0 })]))).toBeNull();
    expect(branchHint(pathOf([msg("a", "assistant", "x", { child_count: 1 })], { latest_below: "z" }))).toEqual({ latest: "z" });
  });
});
