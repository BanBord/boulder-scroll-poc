import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.pipeline import estimate_mean_com_x


class _FakeDetector:
    """Returns a fixed sequence of com_src x-values, one per detect_all() call."""
    def __init__(self, xs):
        self.xs = list(xs)
        self.calls = 0

    def detect_all(self, frame):
        x = self.xs[self.calls] if self.calls < len(self.xs) else None
        self.calls += 1
        if x is None:
            return None, None, None, None
        return (x, 0.0), None, None, (x, 0.0)


def test_estimate_mean_com_x_averages_detected_frames(tmp_path):
    # Build a tiny 3-frame video so cv2.VideoCapture has real frames to iterate.
    import cv2
    video_path = str(tmp_path / "tiny.mp4")
    writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16))
    for _ in range(3):
        writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
    writer.release()

    detector = _FakeDetector([100.0, 200.0, 300.0])
    mean_x = estimate_mean_com_x(video_path, detector)
    assert mean_x == 200.0


def test_estimate_mean_com_x_returns_none_when_no_detections(tmp_path):
    import cv2
    video_path = str(tmp_path / "tiny2.mp4")
    writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16))
    writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
    writer.release()

    detector = _FakeDetector([None])
    assert estimate_mean_com_x(video_path, detector) is None


def test_estimate_mean_com_x_returns_none_for_unreadable_file():
    detector = _FakeDetector([])
    assert estimate_mean_com_x("/nonexistent/path.mp4", detector) is None
