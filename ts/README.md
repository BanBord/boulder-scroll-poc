# TypeScript schema & helpers

Reference TypeScript for the **wall scan** JSON contract. No build is wired up —
these files exist as the canonical typed mirror of what `src/wall_scan.py`
emits, plus one pure helper.

- **`TInputs.ts`** — the `TInputs` shape (`{ image, image_size, holds, tags,
  routes_hint }`) and its building blocks (`THold`, `TBBox`, `TPoint2D`, …).
  Keep this in sync with the dict written by `src/wall_scan.py`.
- **`sortHolds.ts`** — `sortHoldsBottomToTop(holds)`, mirroring the
  bottom-to-top hold ordering used in `src/pipeline.py` / `src/wall_scan.py`
  (image `y` grows downward, so "bottom" = largest `center[1]`).
- **`sortHolds.test.ts`** — a tiny self-contained test.

## Run the test

Node ≥ 22 strips the types natively, so no compiler/toolchain is required:

```sh
cd ts
node --experimental-strip-types sortHolds.test.ts
```
