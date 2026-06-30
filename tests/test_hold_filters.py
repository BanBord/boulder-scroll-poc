import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.hold_detector import (
    _passes_size_cap,
    _passes_mat_zone,
    _MAX_RADIUS_FRAC,
    _MAT_ZONE_FRAC,
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
