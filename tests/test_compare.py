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
