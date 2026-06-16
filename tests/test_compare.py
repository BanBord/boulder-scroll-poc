import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.compare import _convex_hull, _com_geometric_entropy


def test_convex_hull_of_square_returns_four_corners():
    points = [(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)]  # (5,5) is interior
    hull = _convex_hull(points)
    assert len(hull) == 4
    assert set(hull) == {(0, 0), (10, 0), (10, 10), (0, 10)}


def test_convex_hull_of_two_points_returns_both():
    points = [(0, 0), (5, 5)]
    hull = _convex_hull(points)
    assert set(hull) == {(0, 0), (5, 5)}


def test_convex_hull_of_collinear_points_returns_endpoints_only():
    points = [(0, 0), (1, 1), (2, 2), (3, 3)]
    hull = _convex_hull(points)
    assert len(hull) <= 2


def test_geometric_entropy_straight_line_is_low():
    # A perfectly straight path: hull degenerates to 2 points → entropy is None
    com_path = [{"x": float(i), "y": 0.0} for i in range(10)]
    assert _com_geometric_entropy(com_path) is None


def test_geometric_entropy_zigzag_is_higher_than_straight_square_path():
    # A path that zigzags inside a bounding square has a real, computable entropy
    com_path = [
        {"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 10.0},
        {"x": 0.0, "y": 10.0}, {"x": 10.0, "y": 0.0},
        {"x": 0.0, "y": 0.0},
    ]
    ge = _com_geometric_entropy(com_path)
    assert ge is not None
    assert ge > 0


def test_geometric_entropy_empty_path_returns_none():
    assert _com_geometric_entropy([]) is None


def test_geometric_entropy_single_point_returns_none():
    assert _com_geometric_entropy([{"x": 1.0, "y": 1.0}]) is None
