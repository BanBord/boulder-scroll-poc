# Anchor-Based Route Selection + Tag-Based Start/Top
**Date:** 2026-06-30
**Status:** Spec — pending user approval before plan/implementation

---

## Context

Phase 1 of the wall scan (commit `adf31bd`) detects holds with MobileSAM, extracts polygons and Lab colours, clusters by colour into routes, and assigns start/top via a bottom-cluster spatial heuristic. The user-facing flow follows the Climbrr mockups: scan → highlight all holds → tap a hold → route lights up → start/top get coloured outer rings → "Start Sending!".

After a first browser test the user reported two pain points:

1. **Small holds segment unreliably.** Their masks leak into shadow, the extracted Lab colour drifts toward grey, and they fall out of their actual route's cluster. The pre-computed `route_id` from offline DBSCAN is therefore wrong for ~25–40 % of small holds on a typical wall.
2. **Start/top assignment is only ~50 % correct.** The current heuristic (lowest hold = start, highest = top) breaks on routes that traverse, span panel corners, or have non-obvious start positions.

The user has chosen Option 3 from the design discussion — anchor-based route selection — with the eventual goal of Option 1 (fully automatic). Tag detection (the small white paper labels gyms place next to start and top holds) is identified as the right long-term mechanism for start/top, but image resolution prevents OCR-ing whether a tag reads "Start" or "Top". Disambiguation is therefore positional: among tagged holds of one route, the lower one is start, the higher one is top.

This spec replaces the offline route clustering with on-demand anchor-tap region growing, and adds tag detection to anchor start/top reliably.

---

## Goals

- **Robust route selection from a single tap.** Tapping any hold of a route returns the full route, even for small/shadowed holds.
- **Reliable start/top assignment** by reading the gym's existing physical Start/Top tags.
- **Graceful degradation** when tags are absent (older gyms, poorly lit photos): fall back to the current spatial heuristic.
- **Path to fully automatic mode**: the Pencil-correction interaction logs distances of user-corrected holds, which feeds threshold tuning in Phase 2.

## Non-Goals

- OCR or text recognition on the tags. We rely on geometry alone.
- Multi-wall stitching, route progression detection, or video-based scanning. Phase 1 stays single-still-photo.
- Live camera feed. The renderer is built frame-space-agnostic so live can dock on later, but no real-time work in this spec.

---

## Architecture

```
              POST /scan (image)
                    │
                    ▼
       ┌─────────────────────────┐
       │  src/wall_scan.scan()   │
       │  (server, ~15 s)        │
       │                         │
       │  • MobileSAM            │
       │    points_per_side=48   │
       │  • Hold filter →        │
       │    holds[]              │
       │  • Tag filter →         │
       │    tags[]               │
       │  • routes_hint{count}   │
       │    (rough offline       │
       │     cluster, advisory)  │
       └─────────────────────────┘
                    │
                    ▼
          wall_scan.json
                    │
                    ▼
       ┌─────────────────────────┐
       │  viewer/scan.html       │
       │  (client)               │
       │                         │
       │  Initial: all holds in  │
       │  white glow, sheet      │
       │  shows hint count.      │
       │                         │
       │  On tap(hold H):        │
       │    1. growRoute(H)      │
       │    2. assignStartTop(   │
       │         route, tags)    │
       │    3. render(route,     │
       │         start, top)     │
       └─────────────────────────┘
```

Two server-side units now run on the same SAM output (one inference pass): hold filter (existing) and tag filter (new). The viewer is the home of all selection logic — server provides a static feature index, client does anchor-tap region growing and start/top resolution per tap.

---

## Detection: holds + tags from one SAM pass

### SAM tuning

`points_per_side` rises from 32 to 48. On a 2160×3840 photo this gives ~9000 sample points instead of ~4000 — enough to catch tags around 40 px wide reliably. Other SAM thresholds unchanged. Expected inference time: ~15 s on the M3 Pro CPU (was ~10 s).

### Hold pipeline

Unchanged from current `detect_holds()`:
- Area between `_MIN_AREA` (200 px²) and 5 % of frame
- Radius cap at 7 % of frame width
- Mat-zone exclusion (configurable; off for scan use case)
- Shape aspect ≤ 6, solidity ≥ 0.5
- Polygon extracted via `mask_to_polygon()`
- Per-hold Lab colour via `extract_hold_color()` (chroma-top-30 % + brighter-half-L median)

### Tag pipeline (new, in `src/wall_scan.py`)

A SAM segment is a **tag candidate** if all of the following hold:

| Criterion | Threshold | Reason |
|---|---|---|
| Area fraction | 0.05 % – 0.5 % of image | Empirical from sample photo |
| Aspect ratio | 1.5 ≤ w/h ≤ 5.0 | Text labels are wider than tall |
| Chroma of median Lab | ≤ 12 | White/grey paper, not coloured |
| Brightness L | ≥ 140 | Excludes wall dots and dark shadows |
| Distance to nearest hold centre | ≤ 4 % of image diagonal | Tags sit next to their hold |

Surviving candidates get assigned `nearest_hold_id`. If a single SAM segment passes both pipelines (theoretically impossible due to disjoint area bands but checked defensively), tag classification wins.

### Routes hint (advisory only)

The existing offline DBSCAN-style cluster still runs and produces a `routes_hint.count`. It is **not** load-bearing — it is shown in the initial sheet as "≈ N routes detected" only as a hint. If wrong, the user proceeds via anchor tap and the count visually corrects itself once they have explored a few taps.

---

## JSON schema (revised)

```json
{
  "image": "/uploads/<scan_id>_wall.<ext>",
  "image_size": [W, H],
  "holds": [
    {
      "id": 0,
      "polygon": [[x,y], ...],
      "bbox": [x, y, w, h],
      "center": [cx, cy],
      "color_hex": "#3b82f6",
      "color_lab": [L, a, b],
      "neighbors": [3, 7, 11, 5, 22, 9, 14, 18]
    }
  ],
  "tags": [
    {
      "id": 0,
      "bbox": [x, y, w, h],
      "center": [cx, cy],
      "nearest_hold_id": 14
    }
  ],
  "routes_hint": { "count": 7 }
}
```

Two intentional removals from the previous schema:

- `route_id` and `role` no longer pre-set on holds. They were unreliable; the client computes them per tap.
- `routes[]` array is gone in favour of `routes_hint.count` because routes are now ephemeral (per-tap), not stored objects.

`neighbors[i]` is the list of the 8 nearest holds to hold `i` by centre Euclidean distance, sorted closest-first. Precomputed server-side because computing this in the browser per tap on every hold would be quadratic and wasteful when it never changes.

---

## Selection: anchor-tap region growing (client)

On `pointerdown` over hold `H`:

```
anchor = H
ab_target = (H.color_lab.a, H.color_lab.b)
route = {H}
frontier = [H]
diag = sqrt(W² + H²)

while frontier not empty:
    next_frontier = []
    for F in frontier:
        for N_id in F.neighbors:
            N = holds[N_id]
            if N.id in route: continue
            d_ab = sqrt((N.a - ab_target.a)² + (N.b - ab_target.b)²)
            d_spatial = euclid(N.center, F.center) / diag
            if d_ab ≤ ΔE_AB and d_spatial ≤ MAX_NEIGHBOR_FRAC:
                route.add(N.id)
                next_frontier.append(N)
    frontier = next_frontier

return route
```

**Key properties:**

- L-channel (luminance) is dropped from the colour distance entirely. Bright and shadowed holds of the same paint match.
- Region grows from anchor, so isolated holds of the right colour but far away (e.g., a stray red volume on a different wall section) don't pollute the route.
- Spatial step is measured between F (current frontier hold) and N (candidate), not anchor-to-N — this lets the route trace a path across the wall rather than confining to a radius around the anchor.

**Default thresholds** (tunable, both via slider in dev mode for empirical tuning):

| Parameter | Default | Reasoning |
|---|---|---|
| `ΔE_AB` | 18 | Saturated paints are 30–40 apart in a/b; same-paint variation under shading is ~10–14. 18 splits cleanly. |
| `MAX_NEIGHBOR_FRAC` | 0.18 | Maximum step between two holds on the same route ≈ 18 % of image diagonal on typical climbing-gym shots. |

---

## Start/Top assignment

After region growing produces `route_holds`:

1. **Collect tags** whose `nearest_hold_id ∈ route_holds`.
2. **Decide** based on count:

| Tags found | Logic |
|---|---|
| 0 | Fallback: existing bottom-cluster heuristic (`assign_start_top` in current `wall_scan.py`). Port to JS. |
| 1 | Compare the tagged hold's y to the route's median y. Below median → `start`; above → `top`. |
| 2 | Lowest y = `start`, highest y = `top`. |
| ≥ 3 | Same as 2 (ignore extras with a console warning — typical gyms tag exactly start and top; 3+ likely means a misdetected tag). |

**Double-start handling** is preserved: if two tags are within 12 % of image height and 25 % of image width of each other, both are `start`. (Some routes mark two start holds for two-hand starts.)

`start_top` (a single hold acting as both) only applies in the trivial 1-hold-route edge case.

---

## UX impact

| Aspect | Before | After |
|---|---|---|
| Initial sheet text | "N routes detected" (load-bearing N) | "≈ N routes · Tap a hold" (advisory N, "≈" prefix communicates uncertainty) |
| Tap behaviour | Look up pre-set `route_id` | Run region growing on the fly |
| Render in "all" mode | Subtle role hints on `start`/`top` based on pre-set roles | No role hints — roles only known after tap |
| Pencil icon | Static dead button | Functional: toggles edit mode where tap toggles a hold's membership in the active route; logs the toggled hold's Lab distance to the anchor (telemetry stored in `localStorage`) |
| `Start Sending!` CTA | Dummy | Still dummy in this spec; persists the selected route (hold IDs + start/top assignment + anchor) to `localStorage` for Phase 2 pickup |

---

## Components and interfaces

### Server: `src/wall_scan.py` (modified)

- `detect_holds_and_tags(frame)` — single SAM pass, splits output into holds and tags via two filter chains. Replaces the current direct `detect_holds()` call in `scan()`.
- `_passes_tag_filter(segment, frame, nearest_hold_dist)` — pure function, fully unit-testable on synthetic segments.
- `compute_hold_neighbors(holds, k=8)` — per-hold KNN by centre distance.
- `scan()` output gains `tags[]` and per-hold `neighbors[]`; loses `routes[]` and per-hold `route_id`/`role`.

### Client: `viewer/scan.html` (modified)

Replace existing render/selection logic with:

- `growRoute(anchorId)` — returns `Set<number>` of hold IDs.
- `assignStartTop(routeIds, tags, holds, imageSize)` — returns `{startIds: [...], topId, source: 'tags' | 'spatial'}`.
- `renderRoute(routeIds, startIds, topId, anchorHold)` — current draw logic adapted: active holds in anchor's hex (not pre-stored route hex).
- `editMode` toggle on Pencil click: changes pointer behaviour to add/remove holds from current route. Each toggle appends `{action, anchorLab, holdLab, dAB, dSpatial}` to `localStorage["climbrr_corrections"]`.

### Schema and API

- `POST /scan` — unchanged contract; returns `scan_id` etc. Internal pipeline changes are invisible to the client.
- `GET /scan_json/<scan_id>` — payload follows the new schema above.

---

## Testing

Server (`tests/test_wall_scan.py`, extended):

- `test_tag_filter_accepts_typical_sticker` — synthetic 60×30 white patch on grey → passes.
- `test_tag_filter_rejects_coloured_hold` — large saturated red patch → rejected.
- `test_tag_filter_rejects_wall_dot` — tiny dark dot → rejected.
- `test_tag_assigned_to_nearest_hold` — two synthetic holds + a tag closer to one → `nearest_hold_id` correct.
- `test_compute_hold_neighbors_orders_by_distance` — synthetic 5-hold grid → `neighbors[0]` is closest.

Client (`viewer/scan_tests.html`, new — a tiny self-contained HTML page that imports the selection module from `viewer/scan_selection.js` (extracted from `scan.html` during implementation) and runs a flat list of `assert(condition, name)` calls, logging results to the page. No test framework dependency. Reachable at `http://localhost:5001/scan_tests`):

- `test_region_grows_to_linear_route` — 5 same-colour holds linearly arranged via shared `neighbors` → all 5 in route from any anchor.
- `test_region_stops_at_colour_outlier` — same shape but the middle hold has a different colour → growing stops there.
- `test_region_respects_spatial_cap` — chain of same-colour holds with one gap > `MAX_NEIGHBOR_FRAC` → only the contiguous chunk.
- `test_start_top_from_two_tags` — route holds + 2 tags → lower y = start, higher = top.
- `test_start_top_falls_back_without_tags` — route with no tags → bottom-cluster heuristic returns valid start/top.
- `test_start_top_with_one_tag_above_median` — single tag on an upper-y hold → top.
- `test_double_start_from_two_low_tags` — two tags both near bottom, close horizontally → both start.

---

## Verification

```bash
# Server unit tests
python -m pytest tests/test_wall_scan.py -v

# E2E on the user's sample wall photo
python -m tools.scan_wall visual_idea/Wall_Holds_img.png \
    --out output/scan_test.json
jq '.tags | length, .holds[0].neighbors' output/scan_test.json

# Browser
python app.py
# → http://localhost:5001/scan
# Upload the photo with visible tags.
# 1. Verify the initial sheet says "≈ N routes".
# 2. Tap a blue hold. Expect: only blue holds light up; start/top rings sit on
#    the holds whose tags read "Start"/"Top" in real life.
# 3. Tap a red hold. Expect: red route lit, start/top rings correct.
# 4. Click pencil. Tap a hold currently in the route. Expect: removed.
# 5. Tap a hold outside. Expect: added.
# 6. Inspect localStorage["climbrr_corrections"] — entries should record
#    the d_ab and d_spatial of each toggle.
```

---

## Phased delivery

The implementation plan will sequence as:

1. **Tag detection in `wall_scan.py`** + neighbors precomputation + JSON schema update. SAM tuning + tests.
2. **Region growing + render in `scan.html`** (server JSON ignoring pre-set route fields, client computing live).
3. **Tag-based start/top in JS** with fallback path.
4. **Pencil edit mode + correction logging**.
5. **Validation pass** on the user's sample photo + any new ones.

A user-visible result lands after step 3; steps 4–5 polish.

---

## Open questions deferred to implementation

- Should `growRoute` cache results per anchor? Probably yes via a `Map<holdId, Set<holdId>>` — but the cost is trivial (~50 µs per tap on typical N=80), so postpone until benchmarking proves it's needed.
- Should the tag filter use the unsharp-mask trick to boost edge contrast before SAM? Out of scope; revisit if real-photo tests miss obvious tags.
- Should we persist `localStorage["climbrr_corrections"]` to the server? Phase 2 question — answers depend on how much data we want for tuning.
