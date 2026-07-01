import type { THold } from "./TInputs.ts";

/**
 * Sorts holds by their vertical bbox position, from the bottom of the wall
 * image to the top. Image y-coordinates grow downward, so "bottom" means
 * the largest bbox y (using the bbox's vertical center to account for
 * differently sized holds).
 */
export function sortHoldsBottomToTop(holds: THold[]): THold[] {
  return [...holds].sort((a, b) => {
    const centerYA = a.bbox[1] + a.bbox[3] / 2;
    const centerYB = b.bbox[1] + b.bbox[3] / 2;
    return centerYB - centerYA;
  });
}
