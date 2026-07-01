// Run with: node --experimental-strip-types sortHolds.test.ts
import type { THold } from "./TInputs.ts";
import { sortHoldsBottomToTop } from "./sortHolds.ts";

const cases: { name: string; fn: () => void }[] = [];
function it(name: string, fn: () => void) { cases.push({ name, fn }); }
function eq(a: unknown, b: unknown, msg?: string) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error(`${msg || "expected equal"}\n  got: ${sa}\n  exp: ${sb}`);
}
function ok(x: unknown, msg?: string) { if (!x) throw new Error(msg || "expected truthy"); }

function mkHold(id: number, bbox: THold["bbox"]): THold {
  return {
    id,
    bbox,
    center: [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2],
    polygon: [],
    color_hex: "#888888",
    color_lab: [0, 0, 0],
    neighbors: [],
  };
}

it("orders holds from bottom of the image (large y) to top (small y)", () => {
  const top = mkHold(0, [10, 10, 20, 20]);
  const topRightSmall = mkHold(1, [200, 10, 10, 10]);
  const middle = mkHold(2, [100, 100, 40, 40]);
  const bottomLeft = mkHold(3, [10, 300, 20, 20]);
  const sorted = sortHoldsBottomToTop([top, topRightSmall, middle, bottomLeft]);
  eq(sorted.map(h => h.id), [3, 2, 0, 1]);
});

it("uses the bbox's vertical center, not just its top edge", () => {
  // Tall hold starts higher (smaller y) but its center sits lower than the short hold's.
  const tall = mkHold(0, [0, 100, 10, 200]);   // center y = 200
  const short = mkHold(1, [0, 150, 10, 10]);   // center y = 155
  const sorted = sortHoldsBottomToTop([short, tall]);
  eq(sorted.map(h => h.id), [0, 1]);
});

it("does not mutate the input array", () => {
  const a = mkHold(0, [0, 0, 10, 10]);
  const b = mkHold(1, [0, 100, 10, 10]);
  const input = [a, b];
  const sorted = sortHoldsBottomToTop(input);
  eq(input.map(h => h.id), [0, 1], "input order must be untouched");
  eq(sorted.map(h => h.id), [1, 0]);
  ok(sorted !== input, "must return a new array, not the same reference");
});

it("handles holds with equal vertical center without throwing", () => {
  const a = mkHold(0, [0, 50, 10, 10]);
  const b = mkHold(1, [100, 50, 10, 10]);
  const sorted = sortHoldsBottomToTop([a, b]);
  eq(sorted.map(h => h.id).slice().sort(), [0, 1]);
});

it("handles an empty array", () => {
  eq(sortHoldsBottomToTop([]), []);
});

it("handles a single-hold array", () => {
  const a = mkHold(0, [1, 2, 3, 4]);
  eq(sortHoldsBottomToTop([a]).map(h => h.id), [0]);
});

let pass = 0;
for (const c of cases) {
  try {
    c.fn();
    pass++;
    console.log(`\x1b[32m✓\x1b[0m ${c.name}`);
  } catch (e) {
    console.log(`\x1b[31m✗\x1b[0m ${c.name}`);
    console.log(`  ${(e as Error).message.split("\n").join("\n  ")}`);
  }
}
console.log(`\nsortHolds — ${pass}/${cases.length} pass`);
if (pass !== cases.length) process.exit(1);
