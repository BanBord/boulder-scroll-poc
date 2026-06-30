import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.hold_detector import (
    _passes_size_cap,
    _passes_mat_zone,
    _MAX_RADIUS_FRAC,
    _MAT_ZONE_FRAC,
    mask_to_polygon,
)


def test_size_cap_accepts_typical_hold():
    frame_w = 1080
    # A 60×60 hold → r=30, well below 7% of 1080 = 75.6
    assert _passes_size_cap((100, 100, 60, 60), frame_w)


def test_size_cap_rejects_oversize_segment():
    frame_w = 360  # matches v5_attempt
    # h33-style: r=108.9 → bbox ~220×220, in a 360-wide frame that's r=110
    # cap = 360 * 0.07 = 25.2 → must reject
    assert not _passes_size_cap((10, 10, 220, 220), frame_w)


def test_size_cap_boundary():
    frame_w = 1000
    cap_radius_px = _MAX_RADIUS_FRAC * frame_w  # 70
    # bbox 140×140 → r=70 exactly → accept (<=)
    assert _passes_size_cap((0, 0, 140, 140), frame_w)
    # bbox 142×142 → r=71 → reject
    assert not _passes_size_cap((0, 0, 142, 142), frame_w)


def test_mat_zone_accepts_wall_hold():
    frame_h = 640
    # Hold centred at y ≈ 300 → well above 92% threshold (588.8)
    assert _passes_mat_zone((100, 280, 40, 40), frame_h)


def test_mat_zone_rejects_floor_blob():
    frame_h = 640
    # Segment centred at y=600 → above the 92% line (588.8) — reject
    assert not _passes_mat_zone((50, 580, 100, 40), frame_h)


def test_mat_zone_boundary():
    frame_h = 1000
    cutoff = _MAT_ZONE_FRAC * frame_h  # 920
    # Centre at y=919 → accept
    assert _passes_mat_zone((0, 909, 0, 20), frame_h)
    # Centre at y=921 → reject
    assert not _passes_mat_zone((0, 911, 0, 20), frame_h)


def test_mat_zone_configurable():
    """mat_zone_frac=1.0 disables the floor cutoff (used for wall-scan photos
    where start holds may sit near the bottom)."""
    frame_h = 640
    # Hold centred near the bottom — rejected with default, accepted at 1.0
    assert not _passes_mat_zone((50, 600, 100, 40), frame_h)
    assert _passes_mat_zone((50, 600, 100, 40), frame_h, mat_zone_frac=1.0)


def _disk_mask(shape, center, r):
    m = np.zeros(shape, dtype=np.uint8)
    cv2.circle(m, center, r, 1, -1)
    return m.astype(bool)


def test_mask_to_polygon_disk_area_matches():
    """Polygon area should be ≥ 90 % of the original mask area."""
    mask = _disk_mask((200, 200), (100, 100), 30)
    poly = mask_to_polygon(mask)
    assert len(poly) >= 6, f"too few polygon points: {len(poly)}"
    # Shoelace area
    n = len(poly)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    area = 0.5 * abs(sum(xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i] for i in range(n)))
    mask_area = float(mask.sum())
    assert area / mask_area >= 0.90, f"polygon area {area} vs mask {mask_area}"


def test_mask_to_polygon_irregular_shape():
    """An L-shaped mask should produce a polygon with corners at the bends."""
    mask = np.zeros((200, 200), dtype=bool)
    mask[40:80, 40:160] = True   # horizontal bar
    mask[40:160, 40:80] = True   # vertical bar
    poly = mask_to_polygon(mask)
    assert len(poly) >= 6, f"L-shape should have ≥ 6 corners, got {len(poly)}"


def test_mask_to_polygon_empty_mask():
    """Empty mask returns an empty polygon (no contour to extract)."""
    mask = np.zeros((50, 50), dtype=bool)
    assert mask_to_polygon(mask) == []


def test_mask_to_polygon_picks_largest_contour():
    """When the mask has multiple disconnected blobs, return the largest one."""
    mask = _disk_mask((200, 200), (150, 150), 25)
    # Tiny stray island that should be ignored
    mask |= _disk_mask((200, 200), (20, 20), 3)
    poly = mask_to_polygon(mask)
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    # Centroid should sit near the large disk, not the stray
    assert abs(cx - 150) < 5 and abs(cy - 150) < 5


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
