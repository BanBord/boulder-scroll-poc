# Anchor-Based Route Selection + Tag-Based Start/Top Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the offline route clustering with on-demand anchor-tap region growing in Lab a/b + spatial space, and add tag detection (the gym's white Start/Top paper labels) for reliable start/top assignment.

**Architecture:** One SAM inference pass produces segments that fan out into two filter pipelines (holds + tags) on the server. The client gets a static feature index (holds with polygons, colours, k-nearest neighbours; tags with their nearest hold) and runs all selection logic in JavaScript per tap.

**Tech Stack:** Python 3.14, OpenCV, MobileSAM, Flask. Browser side: vanilla JavaScript, ES modules, Canvas 2D. No new dependencies.

## Global Constraints

- All thresholds named in the spec (`ΔE_AB=18`, `MAX_NEIGHBOR_FRAC=0.18`, `TAG_AREA_FRAC=(0.0005, 0.005)`, `TAG_S_MAX=12` chroma, `TAG_L_MIN=140`, `TAG_TO_HOLD_MAX_FRAC=0.04`, `points_per_side=48`) ship as module-level constants. Do NOT make them function args yet — that lands when we wire dev-mode sliders in a later iteration.
- `src/hold_detector.detect_holds()` keeps its existing signature so the video pipeline (`src/pipeline.py`) keeps working unchanged.
- No new Python dependencies; no new npm/Node tooling on the client.
- Plan deliberately drops `route_id`, `role`, and the server-side `routes[]` array — replace, don't add-and-deprecate.
- Existing tests in `tests/test_wall_scan.py` that exercise `assign_start_top` will be moved to the client; the server-side function gets deleted in this work.
- Commit after every passing test.

---

## File Structure

**Create:**
- `viewer/scan_selection.js` — pure-function module: `growRoute`, `pointInPolygon`, `assignStartTopFromTags`, `assignStartTopSpatial`, `assignStartTop`. No DOM, no Canvas. Reusable from the main viewer and the test page.
- `viewer/scan_tests.html` — self-contained assert-style test page importing `scan_selection.js`. No test framework dependency.

**Modify:**
- `src/hold_detector.py` — expose `run_sam_segments()` and `filter_as_holds()` so a single SAM pass can fan out to two filters.
- `src/wall_scan.py` — add `_passes_tag_filter()`, `detect_tags()`, `compute_hold_neighbors()`. Rewire `scan()` to the new schema. Delete `assign_start_top()` and the colour-clustering route-assembly code. Update `draw_overlay()`.
- `tools/scan_wall.py` — adapt CLI print statements to the new schema.
- `tests/test_wall_scan.py` — add tests for the new server units; delete the obsolete `assign_start_top` and `cluster_routes` tests.
- `viewer/scan.html` — load `scan_selection.js` as an ES module; replace inline `holdAt`/render/click logic; add pencil edit mode.
- `app.py` — add `GET /scan_tests` route.
- `research/session_report_wall_scan_2026-06-30.md` — final validation notes.

---

## Task 1: Expose raw SAM segments in `hold_detector`

The video pipeline keeps calling `detect_holds(frame)`. `wall_scan.scan()` needs to run SAM once and filter the same segments as both holds AND tags. Split the current `detect_holds()` into a raw-segments helper plus a filter.

**Files:**
- Modify: `src/hold_detector.py`
- Test: `tests/test_hold_filters.py`

**Interfaces produced (used by Task 3 and Task 5):**
- `run_sam_segments(frame_bgr: np.ndarray, points_per_side: int = 32) -> List[Dict]` — returns raw `SamAutomaticMaskGenerator.generate()` output, one dict per segment with `"segmentation": HxW bool array` and `"bbox": [x, y, w, h]`.
- `filter_as_holds(segments: List[Dict], frame_bgr: np.ndarray, color_filter: Optional[str] = None, mat_zone_frac: float = _MAT_ZONE_FRAC) -> List[Dict]` — applies the existing hold filters, attaches polygon, returns hold dicts in the current format. Re-numbers `id` top-to-bottom.
- `detect_holds(frame, color_filter=None, mat_zone_frac=_MAT_ZONE_FRAC)` — thin wrapper: `filter_as_holds(run_sam_segments(frame), frame, color_filter, mat_zone_frac)`. **Signature unchanged.**

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hold_filters.py`:

```python
def test_filter_as_holds_drops_oversize_segment():
    """filter_as_holds should reject a SAM segment that fails the size cap."""
    from src.hold_detector import filter_as_holds
    # 100×100 frame, one segment covering the whole left half — radius too large
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    seg = np.zeros((100, 100), dtype=bool)
    seg[:, :50] = True
    segments = [{"segmentation": seg, "bbox": [0, 0, 50, 100]}]
    out = filter_as_holds(segments, frame)
    assert out == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hold_filters.py::test_filter_as_holds_drops_oversize_segment -v`
Expected: FAIL with `ImportError: cannot import name 'filter_as_holds'`.

- [ ] **Step 3: Refactor `detect_holds` to expose the two pieces**

In `src/hold_detector.py`, replace the body of `detect_holds()` with the two helpers. Keep the file's existing imports and constants.

```python
def run_sam_segments(frame_bgr: np.ndarray, points_per_side: int = 32) -> List[Dict]:
    """Run MobileSAM's AutomaticMaskGenerator on a frame, return raw segments.

    Each returned dict has at least:
      - "segmentation": H×W bool array
      - "bbox":         [x, y, w, h] in pixel coords
    """
    from mobile_sam import sam_model_registry, SamAutomaticMaskGenerator
    checkpoint = _get_checkpoint()
    sam = sam_model_registry["vit_t"](checkpoint=checkpoint)
    sam.eval()
    generator = SamAutomaticMaskGenerator(
        sam,
        points_per_side=points_per_side,
        pred_iou_thresh=0.82,
        stability_score_thresh=0.88,
        min_mask_region_area=_MIN_AREA,
    )
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    print(f"SAM: segmenting frame (points_per_side={points_per_side}) …")
    segs = generator.generate(rgb)
    print(f"SAM: {len(segs)} total segments")
    return segs


def filter_as_holds(segments: List[Dict], frame_bgr: np.ndarray,
                    color_filter: Optional[str] = None,
                    mat_zone_frac: float = _MAT_ZONE_FRAC) -> List[Dict]:
    """Apply the climbing-hold filter chain to raw SAM segments.

    Returns hold dicts in the existing format: {id, mask, polygon, center,
    bbox, source}. IDs are reassigned top-to-bottom.
    """
    h_img, w_img = frame_bgr.shape[:2]
    frame_area = h_img * w_img
    frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

    sam_holds = []
    for m in segments:
        seg = m["segmentation"].astype(bool)
        area = int(seg.sum())
        if area < _MIN_AREA or area > frame_area * _MAX_AREA_FRAC:
            continue
        x, y, w, hh = m["bbox"]
        bbox = (int(x), int(y), int(w), int(hh))
        if not _passes_size_cap(bbox, w_img):
            continue
        if not _passes_mat_zone(bbox, h_img, mat_zone_frac):
            continue
        if not _segment_passes_shape(seg, bbox):
            continue
        if color_filter and not _segment_matches_color(seg, frame_hsv, color_filter):
            continue
        sam_holds.append({
            "mask":    seg,
            "center":  (float(x + w / 2), float(y + hh / 2)),
            "bbox":    bbox,
            "polygon": mask_to_polygon(seg),
            "source":  "sam",
        })

    if color_filter:
        candidates = _color_holds(frame_bgr, frame_area, color_filter,
                                  mat_zone_frac=mat_zone_frac)
        for hc in candidates:
            covered = any(_iou(hc["mask"], sh["mask"]) >= _IOU_MERGE for sh in sam_holds)
            if not covered:
                sam_holds.append(hc)

    sam_holds.sort(key=lambda h: h["center"][1])
    for i, h in enumerate(sam_holds):
        h["id"] = i
    return sam_holds


def detect_holds(reference_frame: np.ndarray, color_filter: Optional[str] = None,
                 mat_zone_frac: float = _MAT_ZONE_FRAC) -> List[Dict]:
    """SAM-based hold detector — backward-compatible wrapper."""
    segments = run_sam_segments(reference_frame)
    holds = filter_as_holds(segments, reference_frame,
                            color_filter=color_filter,
                            mat_zone_frac=mat_zone_frac)
    print(f"Total holds detected: {len(holds)}")
    return holds
```

- [ ] **Step 4: Run all hold-filter tests**

Run: `pytest tests/test_hold_filters.py -v`
Expected: 12 PASS (11 existing + 1 new). The new `filter_as_holds` test passes because the 50×100 segment fails `_passes_size_cap`.

- [ ] **Step 5: Commit**

```bash
git add src/hold_detector.py tests/test_hold_filters.py
git commit -m "Refactor: expose run_sam_segments + filter_as_holds

So a single SAM pass can fan out into both the hold filter and the
upcoming tag filter in wall_scan. detect_holds() keeps its signature
to leave the video pipeline untouched."
```

---

## Task 2: `_passes_tag_filter()` predicate

Pure predicate on a SAM segment plus the frame, with the distance to the
nearest already-detected hold as a separate argument. Fully unit-testable
without SAM.

**Files:**
- Modify: `src/wall_scan.py`
- Test: `tests/test_wall_scan.py`

**Interfaces produced (used by Task 3):**
- `_passes_tag_filter(seg_bool: np.ndarray, bbox: Tuple[int, int, int, int], frame_bgr: np.ndarray, nearest_hold_dist_px: Optional[float], image_diag_px: float) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wall_scan.py`:

```python
from src.wall_scan import _passes_tag_filter


def _rect_segment(shape, x, y, w, h):
    seg = np.zeros(shape, dtype=bool)
    seg[y:y + h, x:x + w] = True
    return seg


def test_tag_filter_accepts_typical_sticker():
    """Bright low-saturation rectangle, 60×30, near a hold → passes."""
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)  # grey wall
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    frame[200:230, 200:260] = (235, 235, 235)            # bright white-ish patch
    diag = float(np.sqrt(600 ** 2 + 600 ** 2))
    assert _passes_tag_filter(seg, (200, 200, 60, 30), frame,
                              nearest_hold_dist_px=8.0, image_diag_px=diag)


def test_tag_filter_rejects_coloured_hold():
    """Saturated red rectangle, even if size matches → rejected."""
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    frame[200:230, 200:260] = (40, 40, 220)              # saturated red
    diag = float(np.sqrt(600 ** 2 + 600 ** 2))
    assert not _passes_tag_filter(seg, (200, 200, 60, 30), frame,
                                  nearest_hold_dist_px=8.0, image_diag_px=diag)


def test_tag_filter_rejects_wall_dot():
    """Tiny dark dot (8×8) → fails area minimum."""
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    seg = _rect_segment((600, 600), 100, 100, 8, 8)
    frame[100:108, 100:108] = (40, 40, 40)
    diag = float(np.sqrt(600 ** 2 + 600 ** 2))
    assert not _passes_tag_filter(seg, (100, 100, 8, 8), frame,
                                  nearest_hold_dist_px=8.0, image_diag_px=diag)


def test_tag_filter_rejects_far_from_any_hold():
    """Otherwise-valid tag patch sitting 20 % of the image away from any hold → rejected."""
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    frame[200:230, 200:260] = (235, 235, 235)
    diag = float(np.sqrt(600 ** 2 + 600 ** 2))
    far = 0.20 * diag
    assert not _passes_tag_filter(seg, (200, 200, 60, 30), frame,
                                  nearest_hold_dist_px=far, image_diag_px=diag)


def test_tag_filter_rejects_when_no_hold_in_scene():
    """nearest_hold_dist=None (no holds anywhere) → reject conservatively."""
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    frame[200:230, 200:260] = (235, 235, 235)
    diag = float(np.sqrt(600 ** 2 + 600 ** 2))
    assert not _passes_tag_filter(seg, (200, 200, 60, 30), frame,
                                  nearest_hold_dist_px=None, image_diag_px=diag)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wall_scan.py -k tag_filter -v`
Expected: 5 FAIL with `ImportError: cannot import name '_passes_tag_filter'`.

- [ ] **Step 3: Implement `_passes_tag_filter`**

Append to `src/wall_scan.py`, just below the `_chroma` helper:

```python
# Tag filter thresholds (see spec).
_TAG_AREA_FRAC_MIN = 0.0005
_TAG_AREA_FRAC_MAX = 0.005
_TAG_ASPECT_MIN    = 1.5
_TAG_ASPECT_MAX    = 5.0
_TAG_CHROMA_MAX    = 12.0
_TAG_L_MIN         = 140.0
_TAG_HOLD_DIST_FRAC = 0.04


def _passes_tag_filter(seg_bool: np.ndarray,
                       bbox: Tuple[int, int, int, int],
                       frame_bgr: np.ndarray,
                       nearest_hold_dist_px: Optional[float],
                       image_diag_px: float) -> bool:
    """A SAM segment is a Start/Top tag if all of:

    - Area within [TAG_AREA_FRAC_MIN, TAG_AREA_FRAC_MAX] of the frame
    - Bounding-box aspect (w/h) within [TAG_ASPECT_MIN, TAG_ASPECT_MAX]
    - Median Lab chroma ≤ TAG_CHROMA_MAX (white/grey paper, not coloured)
    - Median Lab L ≥ TAG_L_MIN (excludes wall dots, dark shadows)
    - Centre within TAG_HOLD_DIST_FRAC × image_diag of the nearest hold

    nearest_hold_dist_px = None means no holds in the scene → reject.
    """
    if nearest_hold_dist_px is None:
        return False
    h_img, w_img = frame_bgr.shape[:2]
    frame_area = float(h_img * w_img)

    _, _, w, h = bbox
    if w <= 0 or h <= 0:
        return False

    area = float(seg_bool.sum())
    area_frac = area / frame_area
    if not (_TAG_AREA_FRAC_MIN <= area_frac <= _TAG_AREA_FRAC_MAX):
        return False

    aspect = float(w) / float(h)
    if not (_TAG_ASPECT_MIN <= aspect <= _TAG_ASPECT_MAX):
        return False

    if nearest_hold_dist_px > _TAG_HOLD_DIST_FRAC * image_diag_px:
        return False

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    pixels = lab[seg_bool]
    if pixels.size == 0:
        return False
    L = float(np.median(pixels[:, 0]))
    a = float(np.median(pixels[:, 1]))
    b = float(np.median(pixels[:, 2]))
    if L < _TAG_L_MIN:
        return False
    if _chroma((L, a, b)) > _TAG_CHROMA_MAX:
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wall_scan.py -k tag_filter -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wall_scan.py tests/test_wall_scan.py
git commit -m "Add _passes_tag_filter predicate

Small bright low-chroma rectangle near a hold = Start/Top tag.
Five tests covering accept, reject coloured, reject tiny, reject far,
reject when no holds in scene."
```

---

## Task 3: `detect_tags()` orchestrator

Walk the raw SAM segments, find tag candidates that pass `_passes_tag_filter`, attach `nearest_hold_id`. Returns a list of tag dicts.

**Files:**
- Modify: `src/wall_scan.py`
- Test: `tests/test_wall_scan.py`

**Interfaces produced (used by Task 5):**
- `detect_tags(segments: List[Dict], holds: List[Dict], frame_bgr: np.ndarray) -> List[Dict]`
  - Returns `[{id, bbox, center, nearest_hold_id}]`, IDs sequential 0..N.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wall_scan.py`:

```python
def test_detect_tags_assigns_nearest_hold():
    """Two holds, one tag closer to hold 1 → nearest_hold_id == 1."""
    from src.wall_scan import detect_tags
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    frame[200:230, 200:260] = (235, 235, 235)  # tag at (230, 215)
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    segments = [{"segmentation": seg, "bbox": (200, 200, 60, 30)}]
    holds = [
        {"id": 0, "center": (500.0, 500.0)},
        {"id": 1, "center": (210.0, 230.0)},  # near the tag
    ]
    tags = detect_tags(segments, holds, frame)
    assert len(tags) == 1
    assert tags[0]["nearest_hold_id"] == 1
    assert tags[0]["id"] == 0


def test_detect_tags_skips_segments_failing_filter():
    """Coloured segment → skipped."""
    from src.wall_scan import detect_tags
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    frame[200:230, 200:260] = (40, 40, 220)    # red, not a tag
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    segments = [{"segmentation": seg, "bbox": (200, 200, 60, 30)}]
    holds = [{"id": 0, "center": (210.0, 230.0)}]
    tags = detect_tags(segments, holds, frame)
    assert tags == []


def test_detect_tags_empty_when_no_holds():
    """No holds in scene → no tags (conservative)."""
    from src.wall_scan import detect_tags
    frame = np.full((600, 600, 3), 110, dtype=np.uint8)
    frame[200:230, 200:260] = (235, 235, 235)
    seg = _rect_segment((600, 600), 200, 200, 60, 30)
    segments = [{"segmentation": seg, "bbox": (200, 200, 60, 30)}]
    tags = detect_tags(segments, [], frame)
    assert tags == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wall_scan.py -k detect_tags -v`
Expected: 3 FAIL with `ImportError: cannot import name 'detect_tags'`.

- [ ] **Step 3: Implement `detect_tags`**

Append to `src/wall_scan.py`, below `_passes_tag_filter`:

```python
def detect_tags(segments: List[Dict], holds: List[Dict],
                frame_bgr: np.ndarray) -> List[Dict]:
    """Walk SAM segments, classify Start/Top tags, attach nearest hold.

    Returns ``[{id, bbox, center, nearest_hold_id}]``. IDs sequential.
    Empty list when no holds were detected (no anchor for nearest-hold check).
    """
    if not holds:
        return []

    h_img, w_img = frame_bgr.shape[:2]
    diag = float(np.sqrt(w_img * w_img + h_img * h_img))
    hold_centres = np.array([h["center"] for h in holds], dtype=np.float32)
    hold_ids     = [h["id"] for h in holds]

    tags = []
    for m in segments:
        seg = m["segmentation"].astype(bool)
        x, y, w, hh = m["bbox"]
        bbox = (int(x), int(y), int(w), int(hh))
        cx, cy = float(x + w / 2.0), float(y + hh / 2.0)

        d = np.linalg.norm(hold_centres - np.array([cx, cy], dtype=np.float32), axis=1)
        nearest_idx = int(np.argmin(d))
        nearest_dist = float(d[nearest_idx])

        if not _passes_tag_filter(seg, bbox, frame_bgr,
                                  nearest_hold_dist_px=nearest_dist,
                                  image_diag_px=diag):
            continue
        tags.append({
            "id":              len(tags),
            "bbox":            [bbox[0], bbox[1], bbox[2], bbox[3]],
            "center":          [cx, cy],
            "nearest_hold_id": int(hold_ids[nearest_idx]),
        })
    return tags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wall_scan.py -k detect_tags -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wall_scan.py tests/test_wall_scan.py
git commit -m "Add detect_tags orchestrator

Walks SAM segments, applies _passes_tag_filter, returns tag dicts with
nearest_hold_id. Empty when no holds were detected first."
```

---

## Task 4: `compute_hold_neighbors()`

Precompute the k nearest holds for each hold by centre distance. Server-side because computing this per tap in the browser would be quadratic and the structure never changes after the scan.

**Files:**
- Modify: `src/wall_scan.py`
- Test: `tests/test_wall_scan.py`

**Interfaces produced (used by Task 5):**
- `compute_hold_neighbors(holds: List[Dict], k: int = 8) -> List[List[int]]`
  - Returns a list where entry `i` is the k closest hold IDs to hold `i`, closest first, excluding `i` itself.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wall_scan.py`:

```python
def test_compute_neighbors_orders_by_distance():
    from src.wall_scan import compute_hold_neighbors
    # Holds laid out in a row at x = 0, 10, 30, 60, 100
    holds = [
        {"id": 0, "center": (0.0,   100.0)},
        {"id": 1, "center": (10.0,  100.0)},
        {"id": 2, "center": (30.0,  100.0)},
        {"id": 3, "center": (60.0,  100.0)},
        {"id": 4, "center": (100.0, 100.0)},
    ]
    nb = compute_hold_neighbors(holds, k=3)
    # Hold 0's nearest: 1 (10), 2 (30), 3 (60)
    assert nb[0] == [1, 2, 3]
    # Hold 2's nearest: 1 (20), 3 (30), 0 (30) — 0 and 3 are tied at 30,
    # ties broken by id ascending → 0 before 3
    assert nb[2] == [1, 0, 3]


def test_compute_neighbors_clamps_k_to_available():
    from src.wall_scan import compute_hold_neighbors
    holds = [
        {"id": 0, "center": (0.0, 0.0)},
        {"id": 1, "center": (1.0, 0.0)},
    ]
    nb = compute_hold_neighbors(holds, k=8)
    assert nb[0] == [1]
    assert nb[1] == [0]


def test_compute_neighbors_empty():
    from src.wall_scan import compute_hold_neighbors
    assert compute_hold_neighbors([], k=8) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wall_scan.py -k compute_neighbors -v`
Expected: 3 FAIL with `ImportError: cannot import name 'compute_hold_neighbors'`.

- [ ] **Step 3: Implement**

Append to `src/wall_scan.py`, below `detect_tags`:

```python
def compute_hold_neighbors(holds: List[Dict], k: int = 8) -> List[List[int]]:
    """For each hold, return the k closest hold IDs by centre Euclidean
    distance. Ties broken by ascending id.

    Output[i] excludes i itself. Length min(k, len(holds) - 1).
    """
    if not holds:
        return []
    centres = np.array([h["center"] for h in holds], dtype=np.float32)
    ids     = [int(h["id"]) for h in holds]
    n = len(holds)
    out: List[List[int]] = []
    for i in range(n):
        d = np.linalg.norm(centres - centres[i], axis=1)
        # Sort by (distance, id) to break ties deterministically.
        order = sorted(
            (j for j in range(n) if j != i),
            key=lambda j: (float(d[j]), ids[j]),
        )
        out.append([ids[j] for j in order[:k]])
    return out
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_wall_scan.py -k compute_neighbors -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wall_scan.py tests/test_wall_scan.py
git commit -m "Add compute_hold_neighbors: deterministic kNN by centre distance"
```

---

## Task 5: Rewire `scan()` to the new schema; delete dead code

Single SAM pass with `points_per_side=48`. Two filters fan out. Drop `route_id`, `role`, `routes[]`. Add `tags[]`, `routes_hint`, and per-hold `neighbors[]`. Delete `assign_start_top`, `cluster_routes`, and their tests — moving start/top to the client.

**Files:**
- Modify: `src/wall_scan.py`
- Test: `tests/test_wall_scan.py`

**Interfaces produced (used by Task 6 and the client):**
- `scan(image_path, *, mat_zone_frac=1.0, points_per_side=48) -> Dict` with payload:

```json
{
  "image":      "<path>",
  "image_size": [W, H],
  "holds":      [{"id", "polygon", "bbox", "center", "color_hex",
                  "color_lab", "neighbors"}],
  "tags":       [{"id", "bbox", "center", "nearest_hold_id"}],
  "routes_hint": {"count": <int>}
}
```

- [ ] **Step 1: Delete obsolete tests and the dead code they cover**

In `tests/test_wall_scan.py`, **delete** the following test functions wholesale (they exercise logic moving to the client):

- `test_clustering_three_distinct_colours`
- `test_clustering_drops_noise`
- `test_clustering_sorts_by_size_descending`
- `test_start_top_single_start`
- `test_start_top_double_start`
- `test_start_top_no_double_when_far_apart`
- `test_start_top_no_double_when_y_too_far`
- `test_start_top_single_hold_route`
- `test_start_top_empty_route`

Also delete the `from src.wall_scan import (...)` block lines that import `cluster_routes`, `assign_start_top` (keep `extract_hold_color`, `_lab_to_hex`).

In `src/wall_scan.py`, **delete** these functions entirely: `_lab_dist`, `cluster_routes`, `assign_start_top`. Their callers go away in Step 3.

- [ ] **Step 2: Write the test that drives the new `scan()` output shape**

For testability without invoking SAM, `scan()` is rewired into a thin orchestrator plus a pure assembler. Add this test:

```python
def test_assemble_scan_payload_shape():
    """assemble_scan_payload should produce the documented JSON keys."""
    from src.wall_scan import assemble_scan_payload
    holds = [
        {"id": 0, "polygon": [[1.0, 2.0]], "bbox": (1, 2, 3, 4),
         "center": (2.5, 4.0), "mask": np.ones((2, 2), dtype=bool)},
    ]
    tags = [{"id": 0, "bbox": [10, 10, 30, 12], "center": [25.0, 16.0],
             "nearest_hold_id": 0}]
    payload = assemble_scan_payload(
        image_path="/x/y.png", image_size=(800, 600),
        holds_internal=holds, tags=tags,
        per_hold_color_lab=[(180.0, 145.0, 165.0)],
        neighbors=[[]],
        routes_hint_count=1,
    )
    assert payload["image"] == "/x/y.png"
    assert payload["image_size"] == [800, 600]
    assert payload["routes_hint"] == {"count": 1}
    assert len(payload["holds"]) == 1
    h0 = payload["holds"][0]
    assert h0["id"] == 0
    assert h0["polygon"] == [[1.0, 2.0]]
    assert h0["bbox"] == [1, 2, 3, 4]
    assert h0["center"] == [2.5, 4.0]
    assert h0["color_lab"] == [180.0, 145.0, 165.0]
    assert h0["color_hex"].startswith("#") and len(h0["color_hex"]) == 7
    assert h0["neighbors"] == []
    # No legacy fields
    assert "route_id" not in h0
    assert "role"     not in h0
    assert "routes"   not in payload
    assert payload["tags"] == tags
```

- [ ] **Step 3: Rewire `scan()` and add `assemble_scan_payload()`**

Replace the existing `scan()` and remove the dropped helpers. Append `assemble_scan_payload()` for testability.

```python
# Module-level constants for the new pipeline
_SAM_POINTS_PER_SIDE = 48
_ROUTES_HINT_LAB_EPS = _LAB_CLUSTER_EPS  # keep advisory cluster identical to before
_ROUTES_HINT_MIN_HOLDS = _MIN_HOLDS_PER_ROUTE


def assemble_scan_payload(*, image_path: str, image_size: Tuple[int, int],
                          holds_internal: List[Dict],
                          tags: List[Dict],
                          per_hold_color_lab: List[Tuple[float, float, float]],
                          neighbors: List[List[int]],
                          routes_hint_count: int) -> Dict:
    """Build the wall_scan JSON dict.

    Pure function: takes already-extracted features, returns the payload.
    Drops the internal ``mask`` field; emits exactly the spec's schema.
    """
    w_img, h_img = image_size
    holds_out = []
    for h, lab, nb in zip(holds_internal, per_hold_color_lab, neighbors):
        holds_out.append({
            "id":        int(h["id"]),
            "polygon":   [[float(x), float(y)] for x, y in h["polygon"]],
            "bbox":      [int(v) for v in h["bbox"]],
            "center":    [float(h["center"][0]), float(h["center"][1])],
            "color_hex": _lab_to_hex(lab),
            "color_lab": [round(lab[0], 1), round(lab[1], 1), round(lab[2], 1)],
            "neighbors": [int(j) for j in nb],
        })
    return {
        "image":       image_path,
        "image_size":  [int(w_img), int(h_img)],
        "holds":       holds_out,
        "tags":        tags,
        "routes_hint": {"count": int(routes_hint_count)},
    }


def scan(image_path: str, *, mat_zone_frac: float = 1.0,
         points_per_side: int = _SAM_POINTS_PER_SIDE) -> Dict:
    """Run the full wall scan on a single image."""
    from .hold_detector import run_sam_segments, filter_as_holds

    frame = cv2.imread(image_path)
    if frame is None:
        raise RuntimeError(f"cannot read image: {image_path}")
    h_img, w_img = frame.shape[:2]

    segments = run_sam_segments(frame, points_per_side=points_per_side)
    holds = filter_as_holds(segments, frame, color_filter=None,
                            mat_zone_frac=mat_zone_frac)
    tags  = detect_tags(segments, holds, frame)
    print(f"Holds: {len(holds)}  Tags: {len(tags)}")

    per_hold_lab = [extract_hold_color(frame, h["mask"]) for h in holds]
    chromatic_count = sum(1 for lab in per_hold_lab if _chroma(lab) >= _MIN_CHROMA)
    routes_hint_count = max(1, chromatic_count // _ROUTES_HINT_MIN_HOLDS)

    neighbors = compute_hold_neighbors(holds, k=8)

    return assemble_scan_payload(
        image_path=os.path.abspath(image_path),
        image_size=(w_img, h_img),
        holds_internal=holds,
        tags=tags,
        per_hold_color_lab=per_hold_lab,
        neighbors=neighbors,
        routes_hint_count=routes_hint_count,
    )
```

- [ ] **Step 4: Run all wall_scan tests**

Run: `pytest tests/test_wall_scan.py -v`
Expected: all remaining tests PASS, including the new `test_assemble_scan_payload_shape`.

- [ ] **Step 5: Commit**

```bash
git add src/wall_scan.py tests/test_wall_scan.py
git commit -m "Rewire scan() to new schema: tags, neighbors, no pre-set roles

One SAM pass at points_per_side=48 fans out into holds and tags.
Drops route_id, role, and the routes[] array — start/top selection
moves to the client. routes_hint.count is advisory only.

Deletes cluster_routes and assign_start_top (moving to JS)."
```

---

## Task 6: Update `draw_overlay()` and `tools/scan_wall.py` for the new schema

The CLI's overlay PNG must keep working as a fast debug tool.

**Files:**
- Modify: `src/wall_scan.py` (just `draw_overlay`)
- Modify: `tools/scan_wall.py`

**Interfaces produced:**
- `draw_overlay(frame_bgr, scan_dict)` — unchanged signature, new internals.

- [ ] **Step 1: Replace `draw_overlay` body**

Replace the existing `draw_overlay` function in `src/wall_scan.py`:

```python
def draw_overlay(frame_bgr: np.ndarray, scan_dict: Dict) -> np.ndarray:
    """Draw all hold polygons in their per-hold colour, plus tag rectangles.

    No route grouping at this stage — colour-clustering is now the client's
    job. The overlay shows raw detection quality only.
    """
    out = frame_bgr.copy()
    h_img, w_img = frame_bgr.shape[:2]
    line_thickness = max(2, int(round(min(w_img, h_img) / 400)))
    tag_thickness  = max(2, line_thickness)

    for h in scan_dict["holds"]:
        poly = np.array(h["polygon"], dtype=np.int32)
        if len(poly) < 3:
            continue
        bgr = _hex_to_bgr(h["color_hex"])
        cv2.polylines(out, [poly], isClosed=True, color=bgr,
                      thickness=line_thickness, lineType=cv2.LINE_AA)

    for t in scan_dict["tags"]:
        x, y, w, hh = t["bbox"]
        cv2.rectangle(out, (x, y), (x + w, y + hh),
                      (0, 220, 255), tag_thickness, lineType=cv2.LINE_AA)

    return out
```

- [ ] **Step 2: Update `tools/scan_wall.py` summary print**

Replace the inner `print` loop in `tools/scan_wall.py` (the block that iterates `scan_dict["routes"]`) with:

```python
    print(f"  {len(scan_dict['holds'])} holds detected")
    print(f"  {len(scan_dict['tags'])} tags detected")
    print(f"  routes_hint.count = {scan_dict['routes_hint']['count']}")
```

Also remove the now-broken `--lab-eps` and `--min-holds` CLI flags (the underlying clustering no longer ships) and the corresponding `lab_eps=` / `min_holds_per_route=` kwargs passed to `scan()`.

- [ ] **Step 3: Smoke-test the CLI**

Run: `python -m tools.scan_wall visual_idea/Wall_Holds_img.png --out output/scan_smoke.json`
Expected: exits 0; the printed summary shows holds, tags, and `routes_hint.count`; `output/scan_smoke_overlay.png` exists and shows polygons + yellow tag rectangles.

- [ ] **Step 4: Commit**

```bash
git add src/wall_scan.py tools/scan_wall.py
git commit -m "Adapt draw_overlay and scan_wall CLI to new schema

Overlay now draws each hold in its own colour (no route grouping)
and marks tags as yellow rectangles. CLI flags for clustering
removed — clustering is no longer server-side."
```

---

## Task 7: Pure-function client module `viewer/scan_selection.js`

Selection logic factored out of `scan.html` into an ES module. Both `scan.html` and the new test page import the same code.

**Files:**
- Create: `viewer/scan_selection.js`

**Interfaces produced (used by Tasks 8, 9, 10):**

```js
export function pointInPolygon(x, y, poly) { ... }
export function growRoute({anchorId, holds, abEps=18, maxNeighborFrac=0.18, imageSize}) { ... }
export function assignStartTopFromTags({routeIds, tags, holds, imageSize}) { ... }
export function assignStartTopSpatial({routeIds, holds, imageSize}) { ... }
export function assignStartTop({routeIds, tags, holds, imageSize}) { ... }
```

- [ ] **Step 1: Create the module**

Write the file at `viewer/scan_selection.js`:

```javascript
// Pure-function selection logic for the wall-scan viewer.
// No DOM, no Canvas — usable from scan.html and scan_tests.html alike.

const AB_EPS_DEFAULT = 18;
const MAX_NEIGHBOR_FRAC_DEFAULT = 0.18;
// Double-start window: 2nd start tag within 12 % height + 25 % width of 1st.
const DOUBLE_START_DY_FRAC = 0.12;
const DOUBLE_START_DX_FRAC = 0.25;

export function pointInPolygon(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

export function growRoute({anchorId, holds, abEps = AB_EPS_DEFAULT,
                           maxNeighborFrac = MAX_NEIGHBOR_FRAC_DEFAULT,
                           imageSize}) {
  const byId = new Map(holds.map(h => [h.id, h]));
  const anchor = byId.get(anchorId);
  if (!anchor) return new Set();
  const [W, H] = imageSize;
  const diag = Math.sqrt(W * W + H * H);
  const aTarget = anchor.color_lab[1];
  const bTarget = anchor.color_lab[2];

  const route = new Set([anchorId]);
  let frontier = [anchor];
  while (frontier.length > 0) {
    const next = [];
    for (const F of frontier) {
      for (const nId of (F.neighbors || [])) {
        if (route.has(nId)) continue;
        const N = byId.get(nId);
        if (!N) continue;
        const dA = N.color_lab[1] - aTarget;
        const dB = N.color_lab[2] - bTarget;
        const dAB = Math.sqrt(dA * dA + dB * dB);
        if (dAB > abEps) continue;
        const dx = N.center[0] - F.center[0];
        const dy = N.center[1] - F.center[1];
        const dSpatial = Math.sqrt(dx * dx + dy * dy) / diag;
        if (dSpatial > maxNeighborFrac) continue;
        route.add(nId);
        next.push(N);
      }
    }
    frontier = next;
  }
  return route;
}

export function assignStartTopFromTags({routeIds, tags, holds, imageSize}) {
  const ids = (routeIds instanceof Set) ? routeIds : new Set(routeIds);
  const inRoute = tags.filter(t => ids.has(t.nearest_hold_id));
  if (inRoute.length === 0) return null;

  if (inRoute.length === 1) {
    const t = inRoute[0];
    const ys = [];
    const byId = new Map(holds.map(h => [h.id, h]));
    for (const hid of ids) ys.push(byId.get(hid).center[1]);
    const median = ys.slice().sort((a, b) => a - b)[Math.floor(ys.length / 2)];
    if (t.center[1] >= median) {
      return {startIds: [t.nearest_hold_id], topId: null, source: 'tags'};
    } else {
      return {startIds: [], topId: t.nearest_hold_id, source: 'tags'};
    }
  }

  const sortedByYDesc = inRoute.slice().sort((a, b) => b.center[1] - a.center[1]);
  const bottom = sortedByYDesc[0];
  const second = sortedByYDesc[1];
  const [W, H] = imageSize;
  const dy = (bottom.center[1] - second.center[1]) / H;
  const dx = Math.abs(bottom.center[0] - second.center[0]) / W;
  const startIds = [bottom.nearest_hold_id];
  if (dy <= DOUBLE_START_DY_FRAC && dx <= DOUBLE_START_DX_FRAC) {
    startIds.push(second.nearest_hold_id);
  }
  const sortedByYAsc = inRoute.slice().sort((a, b) => a.center[1] - b.center[1]);
  const topTag = sortedByYAsc.find(t => !startIds.includes(t.nearest_hold_id));
  const topId = topTag ? topTag.nearest_hold_id : null;
  return {startIds, topId, source: 'tags'};
}

export function assignStartTopSpatial({routeIds, holds, imageSize}) {
  const byId = new Map(holds.map(h => [h.id, h]));
  const list = Array.from(routeIds).map(id => byId.get(id)).filter(Boolean);
  if (list.length === 0) return {startIds: [], topId: null, source: 'spatial'};
  if (list.length === 1) {
    return {startIds: [list[0].id], topId: list[0].id, source: 'spatial'};
  }
  const sortedYAsc = list.slice().sort((a, b) => a.center[1] - b.center[1]);
  const topId = sortedYAsc[0].id;
  const sortedYDesc = list.slice().reverse();
  const bottom = sortedYDesc[0];
  const startIds = [bottom.id];
  const [W, H] = imageSize;
  for (const h of sortedYDesc.slice(1)) {
    const dy = (bottom.center[1] - h.center[1]) / H;
    const dx = Math.abs(bottom.center[0] - h.center[0]) / W;
    if (dy <= DOUBLE_START_DY_FRAC && dx <= DOUBLE_START_DX_FRAC) {
      startIds.push(h.id);
      break;
    }
  }
  return {startIds, topId, source: 'spatial'};
}

export function assignStartTop({routeIds, tags, holds, imageSize}) {
  const fromTags = assignStartTopFromTags({routeIds, tags, holds, imageSize});
  if (fromTags && (fromTags.startIds.length > 0 || fromTags.topId !== null)) {
    return fromTags;
  }
  return assignStartTopSpatial({routeIds, holds, imageSize});
}
```

- [ ] **Step 2: Commit**

```bash
git add viewer/scan_selection.js
git commit -m "Add viewer/scan_selection.js: pure-function selection module

growRoute does anchor-tap region growing in Lab a/b + spatial space.
assignStartTop prefers tag-based assignment; falls back to spatial."
```

---

## Task 8: Browser test page `viewer/scan_tests.html` + `/scan_tests` route

Self-contained assert-style test page. Reachable at `http://localhost:5001/scan_tests`.

**Files:**
- Create: `viewer/scan_tests.html`
- Modify: `app.py`

- [ ] **Step 1: Add Flask route**

Append to `app.py`, just below the existing `scan_page()` route:

```python
@app.route("/scan_tests", methods=["GET"])
def scan_tests_page():
    return send_from_directory("viewer", "scan_tests.html")
```

- [ ] **Step 2: Write the test page**

Create `viewer/scan_tests.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>scan_selection tests</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #0b0b0c; color: #fff;
         padding: 20px; max-width: 720px; margin: 0 auto; }
  h1 { font-size: 16px; font-weight: 500; margin: 0 0 16px; }
  .case { padding: 8px 12px; border-radius: 6px; margin-bottom: 4px; font-size: 13px; }
  .pass { background: rgba(52, 211, 153, 0.15); color: #34d399; }
  .fail { background: rgba(248, 113, 113, 0.18); color: #fca5a5; }
  pre { white-space: pre-wrap; margin: 6px 0 0; font-size: 12px; opacity: 0.85; }
</style>
</head>
<body>
<h1 id="header">scan_selection.js — running…</h1>
<div id="out"></div>
<script type="module">
import {
  growRoute, assignStartTop, assignStartTopFromTags, assignStartTopSpatial,
  pointInPolygon
} from './scan_selection.js';

const cases = [];
function it(name, fn) { cases.push({name, fn}); }
function eq(a, b, msg) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error(`${msg || 'expected equal'}\n  got: ${sa}\n  exp: ${sb}`);
}
function ok(x, msg) { if (!x) throw new Error(msg || 'expected truthy'); }

// ── Fixtures ────────────────────────────────────────────────────────────
const IMG = [1000, 1000];
function mkHold(id, x, y, lab, neighbors=[]) {
  return {id, center:[x,y], color_lab:lab, color_hex:'#888888', neighbors,
          polygon:[[x-5,y-5],[x+5,y-5],[x+5,y+5],[x-5,y+5]], bbox:[x-5,y-5,10,10]};
}

// 5 holds same colour, neighbours linked left↔right
const sameColLab = [150, 145, 130];
const linear = [];
for (let i = 0; i < 5; i++) {
  linear.push(mkHold(i, 100 + i * 100, 500, sameColLab));
}
linear[0].neighbors = [1, 2];
linear[1].neighbors = [0, 2, 3];
linear[2].neighbors = [1, 3, 4, 0];
linear[3].neighbors = [2, 4, 1];
linear[4].neighbors = [3, 2];

// Same chain but middle hold is a different colour
const linearOutlier = linear.map((h, i) =>
  i === 2 ? {...h, color_lab: [150, 100, 100]} : h);

// Two same-colour holds far apart in space
const farPair = [
  mkHold(0, 100, 100, sameColLab, [1]),
  mkHold(1, 900, 900, sameColLab, [0]),
];

// Tags fixture: route holds 0..3 vertical, tags at top (near hold 0) and bottom (near hold 3)
const verticalRoute = [];
for (let i = 0; i < 4; i++) verticalRoute.push(mkHold(i, 500, 100 + i * 200, sameColLab));
verticalRoute[0].neighbors = [1]; verticalRoute[1].neighbors = [0,2];
verticalRoute[2].neighbors = [1,3]; verticalRoute[3].neighbors = [2];
const twoTags = [
  {id:0, bbox:[510, 90, 30, 12], center:[525, 95],  nearest_hold_id: 0}, // upper → top
  {id:1, bbox:[510, 690, 30, 12], center:[525, 695], nearest_hold_id: 3}, // lower → start
];
const oneTagBottom = [twoTags[1]];

// ── Cases ──────────────────────────────────────────────────────────────
it('pointInPolygon hit', () => {
  ok(pointInPolygon(0.5, 0.5, [[0,0],[1,0],[1,1],[0,1]]));
});
it('pointInPolygon miss', () => {
  ok(!pointInPolygon(2, 2, [[0,0],[1,0],[1,1],[0,1]]));
});

it('growRoute walks the chain end-to-end', () => {
  const r = growRoute({anchorId: 2, holds: linear, imageSize: IMG});
  eq([...r].sort((a,b)=>a-b), [0,1,2,3,4]);
});
it('growRoute stops at a colour outlier in the middle', () => {
  const r = growRoute({anchorId: 0, holds: linearOutlier, imageSize: IMG});
  eq([...r].sort((a,b)=>a-b), [0, 1]);  // 2 is outlier; 3 and 4 unreachable
});
it('growRoute respects MAX_NEIGHBOR_FRAC even with same colour', () => {
  // 100→900 across a 1000-px image is dSpatial ≈ 1.13 — well over 0.18
  const r = growRoute({anchorId: 0, holds: farPair, imageSize: IMG});
  eq([...r], [0]);
});
it('growRoute returns just anchor when no neighbours', () => {
  const lone = [mkHold(0, 500, 500, sameColLab, [])];
  const r = growRoute({anchorId: 0, holds: lone, imageSize: IMG});
  eq([...r], [0]);
});

it('assignStartTop uses two tags: lower=start, upper=top', () => {
  const out = assignStartTop({routeIds:new Set([0,1,2,3]), tags:twoTags,
                              holds:verticalRoute, imageSize: IMG});
  eq(out.source, 'tags');
  eq(out.startIds, [3]);
  eq(out.topId, 0);
});
it('assignStartTop with single bottom tag → start, top from spatial fallback later', () => {
  const out = assignStartTop({routeIds:new Set([0,1,2,3]), tags:oneTagBottom,
                              holds:verticalRoute, imageSize: IMG});
  eq(out.source, 'tags');
  eq(out.startIds, [3]);
  eq(out.topId, null);
});
it('assignStartTop falls back to spatial when no tags', () => {
  const out = assignStartTop({routeIds:new Set([0,1,2,3]), tags:[],
                              holds:verticalRoute, imageSize: IMG});
  eq(out.source, 'spatial');
  eq(out.topId, 0);     // smallest y
  eq(out.startIds, [3]); // largest y, no double-start
});
it('assignStartTop spatial double-start when two low holds are close', () => {
  // Two low holds at y=900, x=400 and x=600 (Δx=20% width) → both start
  const holds = [
    mkHold(0, 500, 100, sameColLab),
    mkHold(1, 400, 900, sameColLab),
    mkHold(2, 600, 900, sameColLab),
  ];
  const out = assignStartTop({routeIds:new Set([0,1,2]), tags:[],
                              holds, imageSize: IMG});
  eq(out.startIds.slice().sort((a,b)=>a-b), [1, 2]);
});

// ── Runner ─────────────────────────────────────────────────────────────
const out = document.getElementById('out');
let pass = 0;
for (const c of cases) {
  const div = document.createElement('div');
  div.className = 'case';
  try {
    c.fn();
    div.classList.add('pass');
    div.textContent = '✓ ' + c.name;
    pass++;
  } catch (e) {
    div.classList.add('fail');
    div.textContent = '✗ ' + c.name;
    const p = document.createElement('pre');
    p.textContent = e.message;
    div.appendChild(p);
  }
  out.appendChild(div);
}
document.getElementById('header').textContent =
  `scan_selection.js — ${pass}/${cases.length} pass`;
</script>
</body>
</html>
```

- [ ] **Step 3: Boot Flask and load the page**

Run: in one shell, `python3 app.py`. In a browser, open `http://localhost:5001/scan_tests`.
Expected: header shows `10/10 pass`, every case row is green.

- [ ] **Step 4: Commit**

```bash
git add viewer/scan_tests.html app.py
git commit -m "Add /scan_tests browser page exercising scan_selection.js"
```

---

## Task 9: Replace tap+render logic in `scan.html` with the module

Replace inline functions; render holds in their own colours when in `all` mode (no role hints, since the server no longer provides roles). Initial sheet copy becomes `≈ N routes`.

**Files:**
- Modify: `viewer/scan.html`

- [ ] **Step 1: Switch to ES-module script tag and import selection**

In `viewer/scan.html`, change the existing `<script>(() => { ... })()</script>` block to a module:

```html
<script type="module">
import {
  growRoute, assignStartTop, pointInPolygon
} from './scan_selection.js';
```

…and remove the closing IIFE wrapping (`(() => {` and `})();`).

- [ ] **Step 2: Remove the now-unused inline functions**

In the `<script>` body, delete the local `pointInPolygon` function. Leave `holdAt`, `render`, `drawHold`, `outerRing`, etc., in place for now.

- [ ] **Step 3: Update state model and tap handler**

Replace the existing `state` object near the top of the script:

```javascript
const state = {
  scan: null,
  mode: 'all',            // 'all' | 'route' | 'edit'
  selectedRouteIds: null, // Set<id>
  anchorId: null,
  startIds: [],
  topId: null,
  source: null,           // 'tags' | 'spatial'
  editMode: false,
};
```

Replace the existing `canvas.addEventListener('click', ...)` block with:

```javascript
canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const h = holdAt(e.clientX - rect.left, e.clientY - rect.top);

  if (state.editMode) {
    if (!h || state.selectedRouteIds === null) return;
    toggleHoldInRoute(h.id);
    return;
  }

  if (h) {
    selectRouteFromAnchor(h.id);
  } else if (state.mode === 'route') {
    enterAllMode();
  }
});

function selectRouteFromAnchor(anchorId) {
  const routeIds = growRoute({
    anchorId,
    holds: state.scan.holds,
    imageSize: state.scan.image_size,
  });
  const {startIds, topId, source} = assignStartTop({
    routeIds,
    tags: state.scan.tags,
    holds: state.scan.holds,
    imageSize: state.scan.image_size,
  });
  state.mode = 'route';
  state.anchorId = anchorId;
  state.selectedRouteIds = routeIds;
  state.startIds = startIds || [];
  state.topId = topId;
  state.source = source;
  render();
  updateDots();
  setSheetRoute();
}

function enterAllMode() {
  state.mode = 'all';
  state.anchorId = null;
  state.selectedRouteIds = null;
  state.startIds = [];
  state.topId = null;
  state.source = null;
  render();
  updateDots();
  setSheetAll();
}
```

- [ ] **Step 4: Update `render()` and `drawHold()` for the new state shape**

Replace `drawHold()` body with:

```javascript
function drawHold(h, active) {
  if (!h.polygon || h.polygon.length < 3) return;
  const isRouteMode = state.mode === 'route';

  ctx.save();
  if (!isRouteMode) {
    pathPolygon(h.polygon);
    ctx.fillStyle   = 'rgba(255, 255, 255, 0.05)';
    ctx.fill();
    ctx.shadowColor = '#ffffff';
    ctx.shadowBlur  = 14;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth   = 2;
    ctx.stroke();
    ctx.restore();
    return;
  }

  if (active) {
    const anchor = state.scan.holds.find(x => x.id === state.anchorId);
    const hex = anchor ? anchor.color_hex : '#ffffff';
    pathPolygon(h.polygon);
    ctx.fillStyle = hexA(hex, 0.35);
    ctx.fill();
    ctx.shadowColor = '#ffffff';
    ctx.shadowBlur  = 16;
    ctx.strokeStyle = hex;
    ctx.lineWidth   = 2.5;
    ctx.stroke();
    ctx.restore();
    if (state.startIds.includes(h.id)) outerRing(h, 6, '#34d399', 3, 10);
    else if (h.id === state.topId)     outerRing(h, 6, '#f87171', 3, 10);
  } else {
    pathPolygon(h.polygon);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.lineWidth   = 1;
    ctx.stroke();
    ctx.restore();
  }
}
```

Replace the `render()` function body's main loop:

```javascript
function render() {
  if (!state.scan) return;
  const rect = wallImg.getBoundingClientRect();
  ctx.clearRect(0, 0, rect.width, rect.height);
  const inRoute = state.selectedRouteIds || new Set();
  for (const h of state.scan.holds) {
    if (state.mode === 'route' && inRoute.has(h.id)) continue;
    drawHold(h, false);
  }
  for (const h of state.scan.holds) {
    if (state.mode === 'route') {
      if (!inRoute.has(h.id)) continue;
      drawHold(h, true);
    } else {
      drawHold(h, true);
    }
  }
}
```

- [ ] **Step 5: Update sheet text for the new schema**

Replace `setSheetAll()`:

```javascript
function setSheetAll() {
  const n = state.scan.routes_hint?.count ?? 0;
  document.getElementById('sheet-content').innerHTML = `
    <h2>≈ ${n} route${n === 1 ? '' : 's'}</h2>
    <hr>
    <div class="hero">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 14c1-4 11-4 12 0"/><circle cx="12" cy="9" r="3"/>
      </svg>
      <p>Tap a hold to select its route</p>
      <small>Any hold works — colour groups expand from where you tap</small>
    </div>`;
}
```

Add `setSheetRoute()`:

```javascript
function setSheetRoute() {
  const ids = state.selectedRouteIds;
  if (!ids) return;
  const n = ids.size;
  const sourceBadge = state.source === 'tags' ? '· tags' : '· auto';
  document.getElementById('sheet-content').innerHTML = `
    <div class="row">
      <h2>Route</h2>
      <button class="pencil" id="btn-pencil" title="Edit holds in this route">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
      </button>
    </div>
    <p class="sub">${n} holds · start/top from ${state.source} ${sourceBadge}</p>
    <hr>
    <button class="add-grade">Add grade</button>
    <button class="cta">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
      </svg>
      Start Sending!
    </button>`;
  document.getElementById('btn-pencil').addEventListener('click', togglePencil);
}
```

Add a no-op `togglePencil` and `toggleHoldInRoute` stub now (filled in Task 10):

```javascript
function togglePencil()         { /* Task 10 */ }
function toggleHoldInRoute(_id) { /* Task 10 */ }
```

- [ ] **Step 6: Wire up the upload-success path**

The current `file-input change` handler calls `render()` then `setSheetAll()`. Replace those two lines:

```javascript
      $('upload-landing').style.display = 'none';
      $('scan-view').classList.add('active');
      resizeCanvas();
      buildDots();
      enterAllMode();
```

`enterAllMode()` already calls `render()`, `updateDots()`, and `setSheetAll()` — so the call site is one line cleaner.

- [ ] **Step 7: Run the browser smoke test**

Run: `python3 app.py`. Open `http://localhost:5001/scan` in a browser. Upload `visual_idea/Wall_Holds_img.png`. Wait ~15 s.
Expected:
- Sheet says `≈ N routes` (≈ prefix present).
- All holds glow white.
- Tap any hold → only that route's holds light up in the anchor's colour with a green ring on the start hold and a red ring on the top hold.
- Tap outside any hold → back to all.

- [ ] **Step 8: Commit**

```bash
git add viewer/scan.html
git commit -m "Wire scan.html to scan_selection module + new schema

Tap-to-select runs growRoute on demand. Initial sheet shows ≈ N routes
as an advisory count. Render uses the anchor hold's colour for the
active route; no pre-set role hints in 'all' mode."
```

---

## Task 10: Pencil edit mode + correction telemetry

Wire the pencil click, the edit-mode tap handling, and the `localStorage` telemetry. Same Task 9 stubs become real.

**Files:**
- Modify: `viewer/scan.html`

- [ ] **Step 1: Replace the stub functions**

In `viewer/scan.html`, replace `togglePencil()` and `toggleHoldInRoute()` with:

```javascript
const CORRECTIONS_KEY = 'climbrr_corrections';

function togglePencil() {
  if (state.mode !== 'route') return;
  state.editMode = !state.editMode;
  document.body.classList.toggle('edit-mode', state.editMode);
  const btn = document.getElementById('btn-pencil');
  if (btn) btn.style.color = state.editMode ? '#34d399' : '';
}

function toggleHoldInRoute(holdId) {
  const ids = state.selectedRouteIds;
  if (!ids) return;
  const anchor = state.scan.holds.find(h => h.id === state.anchorId);
  const hold   = state.scan.holds.find(h => h.id === holdId);
  if (!anchor || !hold) return;

  const dA = hold.color_lab[1] - anchor.color_lab[1];
  const dB = hold.color_lab[2] - anchor.color_lab[2];
  const dAB = Math.sqrt(dA * dA + dB * dB);
  const [W, H] = state.scan.image_size;
  const diag = Math.sqrt(W * W + H * H);
  const dx = hold.center[0] - anchor.center[0];
  const dy = hold.center[1] - anchor.center[1];
  const dSpatial = Math.sqrt(dx * dx + dy * dy) / diag;

  const action = ids.has(holdId) ? 'remove' : 'add';
  if (action === 'add')    ids.add(holdId);
  else                     ids.delete(holdId);

  logCorrection({action, anchorId: state.anchorId, holdId, dAB, dSpatial});

  // Recompute start/top from the modified route — keep the user's view truthful.
  const {startIds, topId, source} = assignStartTop({
    routeIds: ids,
    tags: state.scan.tags,
    holds: state.scan.holds,
    imageSize: state.scan.image_size,
  });
  state.startIds = startIds || [];
  state.topId = topId;
  state.source = source;
  render();
  setSheetRoute();
  document.getElementById('btn-pencil').style.color = '#34d399';
}

function logCorrection(entry) {
  let arr = [];
  try { arr = JSON.parse(localStorage.getItem(CORRECTIONS_KEY) || '[]'); }
  catch { arr = []; }
  entry.ts = Date.now();
  arr.push(entry);
  // Cap at 1000 so we don't bloat localStorage.
  if (arr.length > 1000) arr = arr.slice(-1000);
  localStorage.setItem(CORRECTIONS_KEY, JSON.stringify(arr));
}
```

- [ ] **Step 2: Add a subtle edit-mode indicator CSS**

Append to the existing `<style>` block in `scan.html`:

```css
body.edit-mode .stage { box-shadow: inset 0 0 0 2px #34d399; }
body.edit-mode .scanned-chip { background: #34d399; color: #0b0b0c; }
body.edit-mode .scanned-chip svg { color: #0b0b0c; }
```

- [ ] **Step 3: Browser smoke test**

Reload `http://localhost:5001/scan` (no server restart needed). Upload a wall photo. Tap a hold. Tap the pencil — green border appears. Tap a hold currently NOT in the route → it joins (becomes coloured + glows). Tap a hold currently in the route → it leaves. Open DevTools → Application → Local Storage → `localStorage["climbrr_corrections"]` shows entries with `action, anchorId, holdId, dAB, dSpatial, ts`.

- [ ] **Step 4: Commit**

```bash
git add viewer/scan.html
git commit -m "Add pencil edit mode + correction telemetry

Pencil toggles edit mode (green inset border). Taps add/remove holds
from the active route; start/top recompute on each toggle. Each
correction appends to localStorage[\"climbrr_corrections\"] with the
Lab a/b distance and spatial distance — feeds Phase-2 threshold tuning."
```

---

## Task 11: Validation pass

Run the new pipeline end-to-end on the user's photo with visible tags, capture findings, and propose next-iteration tuning if needed.

**Files:**
- Modify: `research/session_report_wall_scan_2026-06-30.md`

- [ ] **Step 1: Run the scan and overlay**

Run: `python -m tools.scan_wall <user-provided-photo-with-tags> --out output/scan_v2.json`
Expected: exits 0; reports `routes_hint.count`, number of holds, number of tags.

- [ ] **Step 2: Open the overlay PNG**

Run: `open output/scan_v2_overlay.png`
Inspect: each hold has a polygon outline in its own colour; each tag has a yellow rectangle.

- [ ] **Step 3: Browser smoke test on real walls**

Run: `python3 app.py`. Browser: `http://localhost:5001/scan`. Upload the same photo.
Per route the user knows: tap any hold of that route and capture:

| Route | Holds expected | Holds in tap | Start correct? | Top correct? | Source |
|---|---|---|---|---|---|

Try at least 3 routes (yellow, blue, red on the sample wall) and a small/shadowed hold as the anchor.

- [ ] **Step 4: Update session report**

Replace the "Validierung (TODO)" block in `research/session_report_wall_scan_2026-06-30.md` with the actual table from Step 3 plus 3–6 lines of commentary on what worked, what didn't, and which constant to nudge next (e.g., `ΔE_AB` → 22 if same-colour routes are splitting; `MAX_NEIGHBOR_FRAC` → 0.22 if a route gaps).

- [ ] **Step 5: Commit**

```bash
git add research/session_report_wall_scan_2026-06-30.md
git commit -m "Session report: wall scan v2 validation on real photos"
```

---

## Self-Review

**Spec coverage:** every spec section maps to one or more tasks.

- Detection (holds + tags from one SAM pass) → Tasks 1, 2, 3, 5
- JSON schema (neighbors, tags, routes_hint, no route_id/role) → Tasks 4, 5
- Region growing → Task 7
- Tag-based start/top with spatial fallback → Task 7 (functions) + Task 9 (wiring)
- UX changes (`≈ N routes`, no pre-set role hints, pencil functional) → Tasks 9, 10
- Tests: server unit tests → Tasks 2, 3, 4, 5; client tests → Task 8
- Verification flow → Task 11
- "Path to fully automatic mode" via correction telemetry → Task 10

**Placeholder scan:** every step has actual code or exact commands. No TBD/TODO inside tasks. The only `/* Task 10 */` markers in Task 9 are explicit stubs filled by Task 10, not placeholders.

**Type consistency:**
- `growRoute({anchorId, holds, abEps?, maxNeighborFrac?, imageSize}) → Set<number>` — same signature in Task 7's module and Task 9's caller.
- `assignStartTop({routeIds, tags, holds, imageSize}) → {startIds, topId, source}` — matches in module + caller.
- `compute_hold_neighbors(holds, k=8) → List[List[int]]` — Task 4 emits, Task 5 consumes.
- `detect_tags(segments, holds, frame) → List[Dict]` — Task 3 emits, Task 5 consumes.
- `run_sam_segments(frame, points_per_side=32) → List[Dict]` and `filter_as_holds(segments, frame, color_filter, mat_zone_frac) → List[Dict]` — Task 1 emits, Task 5 consumes.

All good — proceeding to execution handoff.
