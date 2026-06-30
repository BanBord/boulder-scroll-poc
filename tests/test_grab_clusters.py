import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.grab_clusters import (
    cluster_grabs,
    filter_holds_by_clusters,
    hold_match_distance,
)


def _hold(hid, x, y):
    return {"id": hid, "center": (float(x), float(y)),
            "bbox": (int(x) - 20, int(y) - 20, 40, 40)}


def test_cluster_groups_nearby_points():
    pts = []
    # Cluster A around (100, 100), 8 samples
    for i in range(8):
        pts.append((float(i * 0.1), 100.0 + i * 0.5, 100.0 + i * 0.3))
    # Cluster B around (500, 400), 6 samples
    for i in range(6):
        pts.append((float(1.0 + i * 0.1), 500.0 + i * 0.5, 400.0))
    clusters = cluster_grabs(pts, radius=30.0, min_count=5)
    assert len(clusters) == 2
    centres = sorted([(round(c["x"]), round(c["y"])) for c in clusters])
    assert centres == [(102, 101), (501, 400)]


def test_cluster_drops_singletons():
    # Three isolated points, far apart, all below min_count
    pts = [(0.0, 100.0, 100.0), (1.0, 500.0, 500.0), (2.0, 800.0, 100.0)]
    clusters = cluster_grabs(pts, radius=20.0, min_count=2)
    assert clusters == []


def test_cluster_records_time_range():
    pts = [(1.0, 50.0, 50.0), (2.0, 51.0, 49.0), (5.0, 52.0, 51.0),
           (10.0, 49.0, 50.0), (10.5, 50.0, 50.5)]
    clusters = cluster_grabs(pts, radius=10.0, min_count=3)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["t_first"] == 1.0
    assert c["t_last"] == 10.5
    assert c["count"] == 5


def test_filter_keeps_only_near_holds():
    holds = [
        _hold(0, 100, 100),   # near cluster A
        _hold(1, 500, 400),   # near cluster B
        _hold(2, 200, 200),   # far from both
        _hold(3, 800, 800),   # far
    ]
    clusters = [
        {"x": 102.0, "y": 101.0, "count": 10, "t_first": 0.0, "t_last": 5.0},
        {"x": 498.0, "y": 402.0, "count": 8,  "t_first": 6.0, "t_last": 10.0},
    ]
    kept = filter_holds_by_clusters(holds, clusters, max_dist=30.0)
    ids = sorted(h["id"] for h in kept)
    assert ids == [0, 1]
    by_id = {h["id"]: h for h in kept}
    assert by_id[0]["cluster_count"] == 10
    assert by_id[1]["cluster_t_first"] == 6.0


def test_filter_handles_no_clusters():
    holds = [_hold(0, 100, 100), _hold(1, 200, 200)]
    assert filter_holds_by_clusters(holds, [], max_dist=50.0) == []


def test_hold_match_distance_scales_with_width():
    assert hold_match_distance(1080) > hold_match_distance(360)
    assert abs(hold_match_distance(1000) - 60.0) < 1e-6
