import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { parseSse, type ReplyEvent } from "./api";

const frame = (e: ReplyEvent) => `data: ${JSON.stringify(e)}\n\n`;

describe("parseSse", () => {
  it("returns complete events and keeps the unfinished rest", () => {
    const a: ReplyEvent = { type: "delta", text: "hi" };
    const { events, rest } = parseSse(frame(a) + 'data: {"type":"del');
    expect(events).toEqual([a]);
    expect(rest).toBe('data: {"type":"del');
  });

  it("gives the same events however the stream is chopped up (Req 2.2)", () => {
    const evs: ReplyEvent[] = [
      { type: "started", job_id: "j" },
      { type: "delta", text: "héllo 😀\nworld" },
      { type: "delta", text: "data: not a frame" },
      { type: "error", error: "refused", message: "no" },
    ];
    const whole = evs.map(frame).join("");
    fc.assert(
      fc.property(fc.array(fc.nat({ max: whole.length }), { maxLength: 8 }), (cuts) => {
        const points = [0, ...[...cuts].sort((a, b) => a - b), whole.length];
        let buf = "";
        const got: ReplyEvent[] = [];
        for (let i = 1; i < points.length; i++) {
          buf += whole.slice(points[i - 1]!, points[i]!);
          const r = parseSse(buf);
          buf = r.rest;
          got.push(...r.events);
        }
        expect(got).toEqual(evs);
        expect(buf).toBe("");
      }),
    );
  });
});
