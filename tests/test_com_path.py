import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.com_path import path_length, smooth_path


def _close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def test_constant_path_stays_constant():
    out = smooth_path([(5.0, 5.0)] * 20)
    assert all(_close(p, (5.0, 5.0)) for p in out)


def test_straight_line_stays_straight():
    pts = [(float(i), 2.0 * i) for i in range(20)]
    out = smooth_path(pts, window=9)
    assert all(p is not None for p in out)
    for x, y in out:
        assert y == pytest.approx(2.0 * x, abs=1e-6)
    # Interior points have a full symmetric window and stay put.
    for i in range(4, 16):
        assert _close(out[i], pts[i])


def test_short_gap_is_interpolated():
    pts = [(float(i), 0.0) for i in range(20)]
    pts[8] = None
    pts[9] = None
    out = smooth_path(pts, window=9)
    assert out[8] is not None and out[9] is not None
    assert _close(out[8], (8.0, 0.0), tol=1e-6)
    assert _close(out[9], (9.0, 0.0), tol=1e-6)


def test_long_gap_is_preserved_as_none():
    pts = [(0.0, 0.0)] * 5 + [None] * 11 + [(10.0, 10.0)] * 4
    out = smooth_path(pts, window=9)
    assert all(out[i] is None for i in range(5, 16))
    assert out[0] is not None and out[19] is not None


def test_smoothing_does_not_smear_across_gap():
    pts = [(0.0, 0.0)] * 5 + [None] * 11 + [(10.0, 10.0)] * 4
    out = smooth_path(pts, window=9)
    assert _close(out[4], (0.0, 0.0))
    assert _close(out[16], (10.0, 10.0))


def test_noise_is_reduced():
    raw = [(float(i % 2), 0.0) for i in range(40)]   # alternating 0 / 1
    out = smooth_path(raw, window=9)
    interior = [p[0] for p in out[6:34]]
    assert all(abs(x - 0.5) < 0.07 for x in interior)
    assert max(abs(p[0] - 0.5) for p in out[6:34]) < max(abs(p[0] - 0.5) for p in raw)


def test_path_length_of_known_polyline():
    pts = [(0.0, 0.0), (3.0, 4.0), (3.0, 10.0)]   # 5 + 6
    assert path_length(pts) == pytest.approx(11.0)


def test_path_length_skips_none_breaks():
    pts = [(0.0, 0.0), (3.0, 4.0), None, (10.0, 10.0), (13.0, 14.0)]   # 5 + 5
    assert path_length(pts) == pytest.approx(10.0)


def test_path_length_of_empty_or_single_point_is_zero():
    assert path_length([]) == 0.0
    assert path_length([(1.0, 1.0)]) == 0.0
