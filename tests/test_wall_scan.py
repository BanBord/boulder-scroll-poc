"""Unit tests for wall_scan.

The orchestrating ``scan()`` function calls into MobileSAM, which is too heavy
for a unit test. We test the pure functions individually: colour extraction,
route clustering, and start/top assignment.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.wall_scan import (
    extract_hold_color,
    cluster_routes,
    assign_start_top,
    _lab_to_hex,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _solid_color_image(shape, bgr):
    img = np.zeros((*shape, 3), dtype=np.uint8)
    img[:] = bgr
    return img


def _disk_mask(shape, center, r):
    m = np.zeros(shape, dtype=np.uint8)
    cv2.circle(m, center, r, 1, -1)
    return m.astype(bool)


def _hold(id_, lab, cx, cy):
    return {"id": id_, "color_lab": lab, "center": (cx, cy)}


# ── extract_hold_color ─────────────────────────────────────────────────────

def test_extract_color_pure_blue():
    """A blue disk on a blue background should produce a Lab vector clearly in
    the blue quadrant (b component < 128 in OpenCV's encoding)."""
    img = _solid_color_image((100, 100), (200, 60, 60))  # BGR blue-ish
    mask = _disk_mask((100, 100), (50, 50), 20)
    L, a, b = extract_hold_color(img, mask, erode_px=0)
    assert b < 128, f"blue should give b<128, got b={b}"


def test_extract_color_pure_red():
    img = _solid_color_image((100, 100), (40, 40, 220))  # BGR red
    mask = _disk_mask((100, 100), (50, 50), 20)
    L, a, b = extract_hold_color(img, mask, erode_px=0)
    assert a > 140, f"red should give a>140, got a={a}"


def test_extract_color_erode_falls_back_for_tiny_hold():
    """A 5px-radius mask vanishes under default 3px erosion — should fall
    back to the un-eroded mask, not return the neutral default."""
    img = _solid_color_image((50, 50), (40, 40, 220))
    mask = _disk_mask((50, 50), (25, 25), 5)
    L, a, b = extract_hold_color(img, mask)  # default erode_px=3
    assert a > 140, "erosion fallback should still report the red colour"


# ── cluster_routes ─────────────────────────────────────────────────────────

def test_clustering_three_distinct_colours():
    """4 red + 4 blue + 4 green holds → exactly 3 routes."""
    red, blue, green = (50, 180, 60), (40, 80, 200), (180, 100, 60)
    holds = []
    hid = 0
    for lab in [red] * 4 + [blue] * 4 + [green] * 4:
        # add tiny jitter so the clusterer sees real points
        lab_j = (lab[0] + np.random.uniform(-1, 1),
                 lab[1] + np.random.uniform(-1, 1),
                 lab[2] + np.random.uniform(-1, 1))
        holds.append(_hold(hid, lab_j, 100, 100))
        hid += 1
    routes = cluster_routes(holds, eps=14.0, min_samples=3)
    assert len(routes) == 3, f"expected 3 routes, got {len(routes)}"
    for r in routes:
        assert len(r["hold_ids"]) == 4


def test_clustering_drops_noise():
    """A single isolated hold should be dropped as noise (below min_samples)."""
    holds = [_hold(i, (100, 130, 130), 0, 0) for i in range(5)]
    holds.append(_hold(99, (40, 80, 200), 0, 0))  # lone outlier
    routes = cluster_routes(holds, eps=14.0, min_samples=3)
    assert len(routes) == 1
    assert 99 not in routes[0]["hold_ids"]


def test_clustering_sorts_by_size_descending():
    holds = []
    for i in range(3):
        holds.append(_hold(i, (50, 180, 60), 0, 0))    # small route
    for i in range(3, 10):
        holds.append(_hold(i, (40, 80, 200), 0, 0))    # big route
    routes = cluster_routes(holds, eps=14.0, min_samples=3)
    assert routes[0]["hold_count" if "hold_count" in routes[0] else "hold_ids"] is not None
    # route 0 is the larger cluster
    assert len(routes[0]["hold_ids"]) >= len(routes[1]["hold_ids"])


# ── assign_start_top ───────────────────────────────────────────────────────

def test_start_top_single_start():
    """Vertical line of 4 holds → tiefstes = start, höchstes = top."""
    holds = [
        {"id": 0, "center": (100, 100)},  # top
        {"id": 1, "center": (100, 200)},
        {"id": 2, "center": (100, 300)},
        {"id": 3, "center": (100, 400)},  # start
    ]
    starts, top = assign_start_top(holds, image_h=500, image_w=500)
    assert starts == [3]
    assert top == 0


def test_start_top_double_start():
    """Two holds at similar low y, close horizontally → both are start."""
    holds = [
        {"id": 0, "center": (250, 50)},   # top
        {"id": 1, "center": (200, 450)},  # bottom-left start
        {"id": 2, "center": (300, 420)},  # bottom-right, 30 px above, 100 px right
        {"id": 3, "center": (250, 250)},  # mid
    ]
    # image is 500×500: dy threshold = 60 px, dx threshold = 125 px.
    # (450-420) = 30 < 60 ✓  |300-200| = 100 < 125 ✓ → double-start
    starts, top = assign_start_top(holds, image_h=500, image_w=500)
    assert sorted(starts) == [1, 2]
    assert top == 0


def test_start_top_no_double_when_far_apart():
    """Two low holds but horizontally too far apart → only one start."""
    holds = [
        {"id": 0, "center": (250, 50)},
        {"id": 1, "center": (50, 450)},   # bottom-left
        {"id": 2, "center": (450, 420)},  # bottom-right, |450-50|=400 px (≥ 125)
    ]
    starts, top = assign_start_top(holds, image_h=500, image_w=500)
    assert starts == [1]
    assert top == 0


def test_start_top_no_double_when_y_too_far():
    """Second-low hold sits well above the bottom → no double start."""
    holds = [
        {"id": 0, "center": (250, 50)},
        {"id": 1, "center": (200, 450)},
        {"id": 2, "center": (220, 280)},  # dy=170 > 60 threshold
    ]
    starts, top = assign_start_top(holds, image_h=500, image_w=500)
    assert starts == [1]
    assert top == 0


def test_start_top_single_hold_route():
    """Edge case: a route with one hold → both start and top point to it."""
    holds = [{"id": 7, "center": (100, 200)}]
    starts, top = assign_start_top(holds, image_h=500, image_w=500)
    assert starts == [7]
    assert top == 7


def test_start_top_empty_route():
    starts, top = assign_start_top([], image_h=500, image_w=500)
    assert starts == []
    assert top is None


# ── lab → hex round-trip sanity ────────────────────────────────────────────

def test_lab_to_hex_blue():
    """Vector clearly in blue territory should produce a hex starting with #
    and have its B channel as the dominant one."""
    # Lab for a saturated blue (OpenCV encoding)
    h = _lab_to_hex((40.0, 130.0, 60.0))
    assert h.startswith("#") and len(h) == 7
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    assert b > r and b > g, f"expected blue dominant, got {h}"


# ── _passes_tag_filter ────────────────────────────────────────────────────────

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


# ── detect_tags ────────────────────────────────────────────────────────────────

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


# ── compute_hold_neighbors ────────────────────────────────────────────────────

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
