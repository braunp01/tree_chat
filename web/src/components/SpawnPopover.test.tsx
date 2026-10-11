import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "preact";
import { act } from "preact/test-utils";
import { SpawnPopover } from "./SpawnPopover";
import { msg } from "../fixtures";
import type { SpawnRequest } from "../api";
import type { SpawnTarget } from "../selectionTarget";

const target = (notes = 0): SpawnTarget => ({
  message: msg("m1", "assistant", "prefix caching only helps", { notes_after: notes }),
  anchor: { start: 0, end: 6, quoted_text: "prefix" },
  x: 10,
  y: 10,
});

let host: HTMLElement;
function mount(t: SpawnTarget, onSpawn = vi.fn(async (_: SpawnRequest) => true), onDismiss = vi.fn()) {
  host = document.createElement("div");
  document.body.append(host);
  act(() => render(<SpawnPopover target={t} onSpawn={onSpawn} onDismiss={onDismiss} />, host));
  return { onSpawn, onDismiss, input: host.querySelector<HTMLInputElement>("input[type=text]")! };
}
const key = async (el: Element, init: KeyboardEventInit) => {
  await act(async () => {
    el.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
  });
};
afterEach(() => {
  render(null, host);
  host.remove();
});

describe("SpawnPopover (Req 4.1-4.2)", () => {
  it("has the Intent field focused when it opens", () => {
    const { input } = mount(target());
    expect(document.activeElement).toBe(input);
  });

  it("Enter parks, with the typed Intent, and dismisses", async () => {
    const { onSpawn, onDismiss, input } = mount(target());
    input.value = "  why? ";
    await act(async () => void input.dispatchEvent(new Event("input", { bubbles: true })));
    await key(input, { key: "Enter" });
    expect(onSpawn).toHaveBeenCalledWith({
      anchor: { message_id: "m1", start: 0, end: 6, quoted_text: "prefix" },
      intent: "why?",
      fork_at: "anchor",
      status: "parked",
    });
    expect(onDismiss).toHaveBeenCalled();
  });

  it("Ctrl+Enter and Cmd+Enter open it", async () => {
    for (const mod of [{ ctrlKey: true }, { metaKey: true }]) {
      const { onSpawn, input } = mount(target());
      await key(input, { key: "Enter", ...mod });
      expect(onSpawn.mock.calls[0]![0].status).toBe("open");
      render(null, host);
      host.remove();
    }
  });

  it("Escape creates nothing", async () => {
    const { onSpawn, onDismiss, input } = mount(target());
    await key(input, { key: "Escape" });
    expect(onSpawn).not.toHaveBeenCalled();
    expect(onDismiss).toHaveBeenCalled();
  });

  it("stays open when the server refuses", async () => {
    const { onDismiss, input } = mount(target(), vi.fn(async () => false));
    await key(input, { key: "Enter" });
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("warns about Notes after the passage and offers the latest message (Req 4.10, 9.1)", async () => {
    const { onSpawn, input } = mount(target(2));
    expect(host.textContent).toContain("2 notes come after this passage");
    await act(async () => void host.querySelector<HTMLButtonElement>(".hint button")!.click());
    expect(host.querySelector(".hint")).toBeNull();
    await key(input, { key: "Enter" });
    expect(onSpawn.mock.calls[0]![0].fork_at).toBe("tip");
  });

  it("says nothing about Notes when there are none", () => {
    mount(target(0));
    expect(host.querySelector(".hint")).toBeNull();
  });
});
