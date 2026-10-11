import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { groupMarkers, intentLabel, overlaps } from "./markers";
import { marker } from "./fixtures";

describe("groupMarkers (Req 5.3)", () => {
  it("makes one marker per distinct passage, with a count where passages coincide", () => {
    const g = groupMarkers([marker("a", 5, 9), marker("b", 0, 3), marker("c", 5, 9, "open"), marker("d", 5, 10)]);
    expect(g.map((x) => [x.start, x.end, x.markers.length])).toEqual([[0, 3, 1], [5, 9, 2], [5, 10, 1]]);
    expect(g[1]!.status).toBe("open"); // the most active Status wins
  });

  it("keeps every branch exactly once (property)", () => {
    const m = fc.record({ id: fc.uuid(), s: fc.nat(20), len: fc.integer({ min: 1, max: 5 }), st: fc.constantFrom("open", "parked", "closed" as const) });
    fc.assert(
      fc.property(fc.array(m, { maxLength: 30 }), (ms) => {
        const g = groupMarkers(ms.map((x) => marker(x.id, x.s, x.s + x.len, x.st as "open")));
        expect(g.flatMap((x) => x.markers.map((y) => y.branch_id)).sort()).toEqual(ms.map((x) => x.id).sort());
        const keys = g.map((x) => `${x.start}:${x.end}`);
        expect(new Set(keys).size).toBe(keys.length);
      }),
    );
  });
});

it("overlaps is half-open", () => {
  expect(overlaps(0, 3, 3, 5)).toBe(false);
  expect(overlaps(0, 4, 3, 5)).toBe(true);
});

it("labels the user's intent first and marks generated ones (Req 11.4)", () => {
  expect(intentLabel({ intent: "mine", generated_intent: "g" })).toEqual({ text: "mine", generated: false });
  expect(intentLabel({ intent: null, generated_intent: "g" })).toEqual({ text: "g", generated: true });
  expect(intentLabel({ intent: null, generated_intent: null })).toBeNull();
});
