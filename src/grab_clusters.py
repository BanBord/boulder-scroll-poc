"""Hand-trajectory prior for hold detection.

Idea: while a climber holds a grip, the YOLO wrist keypoint settles into a
tight spatial cluster around that hold. Sampling the wrist keypoints across
the video and clustering them gives us a coarse "where did hands linger"
map *before* we need any per-frame mask check. We then keep only the SAM
holds that sit close to one of those clusters.

This is a recall-vs-precision improvement, not a replacement for the
per-frame contact aggregation — `check_contacts` and `route_aggregator`
still run on the filtered hold set.
"""

import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple

_LH_IDX = 9
_RH_IDX = 10
_HAND_CONF_THRESH = 0.3

# Greedy single-link clustering parameters (tuned for ~1080p source frames;
# scaled by frame width at call time so they generalise).
_CLUSTER_RADIUS_FRAC = 0.04  # ≈ 43px in a 1080-wide frame, ≈ 14px in 360
_MIN_CLUSTER_COUNT = 5
_HOLD_MATCH_DIST_FRAC = 0.06  # accept a hold if a cluster lies within this fraction of frame width


def collect_hand_points(
    cap,
    detector,
    stride: int = 3,
    max_frames: Optional[int] = None,
) -> List[Tuple[float, float, float]]:
    """Iterate the video at ``stride``-frame intervals, return wrist keypoints
    above the confidence threshold. Each entry is ``(t_seconds, x, y)``.

    The capture position is reset to 0 before returning.
    """
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if max_frames is not None and max_frames > 0:
        total = min(total, max_frames)

    points: List[Tuple[float, float, float]] = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    for idx in range(0, total, stride):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        _, kps, conf, _ = detector.detect_all(frame)
        if kps is None or conf is None:
            continue
        t = float(idx) / float(fps)
        for kp_idx in (_LH_IDX, _RH_IDX):
            if conf[kp_idx] >= _HAND_CONF_THRESH:
                points.append((t, float(kps[kp_idx, 0]), float(kps[kp_idx, 1])))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return points


def cluster_grabs(
    points: List[Tuple[float, float, float]],
    radius: float,
    min_count: int = _MIN_CLUSTER_COUNT,
) -> List[Dict]:
    """Greedy single-link clustering by spatial proximity.

    Returns clusters as ``{x, y, count, t_first, t_last}`` filtered by
    ``min_count``. Cluster centres are running means; assignment is to the
    nearest existing cluster within ``radius``, else a new cluster.
    """
    clusters: List[Dict] = []
    r2 = radius * radius
    for t, x, y in points:
        best_idx = -1
        best_d2 = r2
        for i, c in enumerate(clusters):
            d2 = (x - c["x"]) ** 2 + (y - c["y"]) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_idx = i
        if best_idx >= 0:
            c = clusters[best_idx]
            n = c["count"]
            c["x"] = (c["x"] * n + x) / (n + 1)
            c["y"] = (c["y"] * n + y) / (n + 1)
            c["count"] = n + 1
            c["t_first"] = min(c["t_first"], t)
            c["t_last"] = max(c["t_last"], t)
        else:
            clusters.append({"x": x, "y": y, "count": 1, "t_first": t, "t_last": t})
    return [c for c in clusters if c["count"] >= min_count]


def filter_holds_by_clusters(
    holds: List[Dict],
    clusters: List[Dict],
    max_dist: float,
) -> List[Dict]:
    """Keep only holds whose centre lies within ``max_dist`` of some cluster.

    Annotates surviving holds with ``cluster_count``, ``cluster_t_first``,
    ``cluster_t_last`` from the nearest matching cluster.
    """
    if not clusters:
        return []
    d2_cap = max_dist * max_dist
    kept = []
    for h in holds:
        cx, cy = h["center"]
        best = None
        best_d2 = d2_cap
        for c in clusters:
            d2 = (cx - c["x"]) ** 2 + (cy - c["y"]) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best = c
        if best is None:
            continue
        out = dict(h)
        out["cluster_count"] = best["count"]
        out["cluster_t_first"] = best["t_first"]
        out["cluster_t_last"] = best["t_last"]
        kept.append(out)
    return kept


def build_trajectory_prior(
    cap,
    detector,
    frame_w: int,
    stride: int = 3,
    max_frames: Optional[int] = None,
) -> Tuple[List[Dict], List[Tuple[float, float, float]]]:
    """Convenience: collect hand points and cluster them.

    Returns ``(clusters, raw_points)``. ``radius`` and the hold-match distance
    used downstream are derived from ``frame_w`` so the prior generalises
    across resolutions.
    """
    radius = _CLUSTER_RADIUS_FRAC * frame_w
    points = collect_hand_points(cap, detector, stride=stride, max_frames=max_frames)
    clusters = cluster_grabs(points, radius=radius)
    return clusters, points


def hold_match_distance(frame_w: int) -> float:
    return _HOLD_MATCH_DIST_FRAC * frame_w
