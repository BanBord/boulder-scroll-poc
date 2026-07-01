import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.route_aggregator import aggregate


def _write_timeline(tmp_path, holds, frames, fps=30.0, video_size=(1080, 1920)):
    path = os.path.join(tmp_path, "test_timeline.json")
    with open(path, "w") as f:
        json.dump({"fps": fps, "video_size": list(video_size),
                   "holds": holds, "frames": frames}, f)
    return path


def _frame(idx, fps=30.0, LH=None, RH=None, LF=None, RF=None):
    return {"frame": idx, "t": round(idx / fps, 3),
            "LH": LH, "RH": RH, "LF": LF, "RF": RF}


def test_picks_lowest_for_start_and_highest_hand_run_for_top(tmp_path):
    # Three holds at y=100 (top), y=300 (mid), y=500 (start spatially-lowest)
    holds = [
        {"id": 0, "center": [400.0, 100.0], "bbox": [380, 80, 40, 40]},
        {"id": 1, "center": [400.0, 500.0], "bbox": [380, 480, 40, 40]},
        {"id": 2, "center": [400.0, 300.0], "bbox": [380, 280, 40, 40]},
    ]
    fps = 30.0
    frames = []
    # Frames 0-19 (start window = 0-20% of 100): hands+feet on h1 (low/start)
    for i in range(20):
        frames.append(_frame(i, fps, LH=1, RH=1, LF=1, RF=1))
    # Frames 20-29: still touching h1 with feet to push above 15-touch threshold
    for i in range(20, 30):
        frames.append(_frame(i, fps, LF=1, RF=1))
    # Frames 30-49: foot on h2 (mid)
    for i in range(30, 50):
        frames.append(_frame(i, fps, LF=2, RF=2))
    # Frames 50-79: hands on h0 (top)
    for i in range(50, 80):
        frames.append(_frame(i, fps, LH=0, RH=0))
    # Frames 80-99 (top window): continuous hand-hold on h0
    for i in range(80, 100):
        frames.append(_frame(i, fps, LH=0, RH=0))

    path = _write_timeline(str(tmp_path), holds, frames, fps=fps)
    route_path = aggregate(path)
    with open(route_path) as f:
        result = json.load(f)

    assert result["start_hold_id"] == 1
    assert result["top_hold_id"] == 0
    ids = sorted(h["id"] for h in result["holds"])
    assert ids == [0, 1, 2]
    by_id = {h["id"]: h for h in result["holds"]}
    assert by_id[0]["role"] == "top"
    assert by_id[1]["role"] == "start"
    assert by_id[2]["role"] == "mid"


def test_drops_holds_below_touch_threshold(tmp_path):
    holds = [
        {"id": 0, "center": [400.0, 100.0], "bbox": [380, 80, 40, 40]},
        {"id": 1, "center": [400.0, 500.0], "bbox": [380, 480, 40, 40]},
    ]
    fps = 30.0
    # h0 only briefly touched (5 frames), below the 15-frame floor.
    # h1 touched for the whole 50-frame video.
    frames = []
    for i in range(50):
        kwargs = {"LH": 1, "LF": 1}
        if 10 <= i < 15:
            kwargs["RH"] = 0
        frames.append(_frame(i, fps, **kwargs))

    path = _write_timeline(str(tmp_path), holds, frames, fps=fps)
    route_path = aggregate(path)
    with open(route_path) as f:
        result = json.load(f)
    ids = [h["id"] for h in result["holds"]]
    assert ids == [1]
    assert result["start_hold_id"] == 1


def test_empty_frames_raises(tmp_path):
    holds = [{"id": 0, "center": [0.0, 0.0], "bbox": [0, 0, 10, 10]}]
    path = _write_timeline(str(tmp_path), holds, [])
    with pytest.raises(RuntimeError, match="no frames"):
        aggregate(path)


def test_empty_holds_raises(tmp_path):
    path = _write_timeline(str(tmp_path), [], [_frame(0)])
    with pytest.raises(RuntimeError, match="no holds"):
        aggregate(path)


def test_top_window_ignores_earlier_hand_contact(tmp_path):
    # h0 has long hand contact early but none late.
    # h1 has short hand contact only in last 20%.
    # Top should be h1.
    holds = [
        {"id": 0, "center": [400.0, 100.0], "bbox": [380, 80, 40, 40]},
        {"id": 1, "center": [400.0, 200.0], "bbox": [380, 180, 40, 40]},
    ]
    fps = 30.0
    frames = []
    for i in range(60):
        frames.append(_frame(i, fps, LH=0, RH=0))  # hands on h0 early
    for i in range(60, 80):
        frames.append(_frame(i, fps, LF=1))  # only foot on h1 mid
    for i in range(80, 100):
        frames.append(_frame(i, fps, LH=1))  # hand on h1 in top window

    path = _write_timeline(str(tmp_path), holds, frames, fps=fps)
    route_path = aggregate(path)
    with open(route_path) as f:
        result = json.load(f)
    assert result["top_hold_id"] == 1
