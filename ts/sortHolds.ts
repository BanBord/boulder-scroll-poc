import type { THold } from "./TInputs.ts";

/**
 * Sorts holds from the bottom of the wall image to the top.
 * Image y grows downward, so "bottom" = largest center y. Reuses each hold's
 * precomputed `center` (the bbox center the detector already sorts by).
 * Non-mutating: returns a new array.
 */
export function sortHoldsBottomToTop(holds: THold[]): THold[] {
  return [...holds].sort((a, b) => b.center[1] - a.center[1]);
}
