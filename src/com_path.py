"""Smooth a per-frame centre-of-mass path and measure its length.

Gaps (None) of up to `window` frames are filled by linear interpolation.
Longer gaps stay None. The centred moving average runs only over
neighbours in the same unbroken segment, so it does not smear across gaps.
"""

import math
from typing import List, Optional, Sequence, Tuple

Point = Optional[Tuple[float, float]]


def _fill_short_gaps(pts: List[Point], window: int) -> List[Point]:
    """Linearly interpolate None runs of length <= window that have points on both sides."""
    out = list(pts)
    n = len(pts)
    i = 0
    while i < n:
        if pts[i] is not None:
            i += 1
            continue
        start = i
        while i < n and pts[i] is None:
            i += 1
        end = i - 1                       # inclusive
        length = end - start + 1
        if start == 0 or end == n - 1 or length > window:
            continue
        ax, ay = pts[start - 1]
        bx, by = pts[end + 1]
        for k in range(length):
            t = (k + 1) / (length + 1)
            out[start + k] = (ax + (bx - ax) * t, ay + (by - ay) * t)
    return out


def smooth_path(points: Sequence[Point], window: int = 9) -> List[Point]:
    """Fill short gaps, then apply a centred moving average within each segment."""
    pts = [None if p is None else (float(p[0]), float(p[1])) for p in points]
    filled = _fill_short_gaps(pts, window)
    n = len(filled)
    half = max(0, window // 2)
    out: List[Point] = [None] * n
    for i in range(n):
        if filled[i] is None:
            continue
        lo = i
        while lo - 1 >= 0 and i - lo < half and filled[lo - 1] is not None:
            lo -= 1
        hi = i
        while hi + 1 < n and hi - i < half and filled[hi + 1] is not None:
            hi += 1
        seg = filled[lo:hi + 1]
        out[i] = (sum(p[0] for p in seg) / len(seg), sum(p[1] for p in seg) / len(seg))
    return out


def path_length(points: Sequence[Point]) -> float:
    """Sum of segment lengths between consecutive points; None breaks the path."""
    total = 0.0
    for a, b in zip(points, points[1:]):
        if a is None or b is None:
            continue
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total
