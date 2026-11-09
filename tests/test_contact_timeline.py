import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.contact_timeline import contact_intervals, frame_contacts

H, W = 20, 20


def _label_map():
    lm = np.zeros((H, W), dtype=np.int32)
    lm[5:10, 5:10] = 7     # hold 7: rows 5..9, cols 5..9
    lm[12:15, 2:5] = 3     # hold 3: rows 12..14, cols 2..4
    return lm


def _kps(points):
    """(17, 3) array of (x, y, conf); points maps COCO index -> (x, y, conf)."""
    kp = np.zeros((17, 3), dtype=float)
    for idx, (x, y, c) in points.items():
        kp[idx] = (x, y, c)
    return kp


LH, RH, LF, RF = 9, 10, 15, 16


def test_keypoint_inside_mask_is_contact():
    res = frame_contacts(_kps({LH: (7, 7, 0.9)}), _label_map())
    assert res["left_hand"] == 7
    assert res["right_hand"] is None
    assert res["left_foot"] is None
    assert res["right_foot"] is None


def test_keypoint_outside_mask_is_no_contact():
    res = frame_contacts(_kps({LH: (0, 0, 0.9)}), _label_map())
    assert res["left_hand"] is None


def test_low_confidence_is_ignored_unless_threshold_lowered():
    kp = _kps({LH: (7, 7, 0.1)})
    assert frame_contacts(kp, _label_map())["left_hand"] is None
    assert frame_contacts(kp, _label_map(), conf_min=0.05)["left_hand"] == 7


def test_out_of_image_bounds_is_no_contact():
    lm = _label_map()
    assert frame_contacts(_kps({RH: (-1, 7, 1.0)}), lm)["right_hand"] is None
    assert frame_contacts(_kps({RH: (W, 7, 1.0)}), lm)["right_hand"] is None
    assert frame_contacts(_kps({RH: (7, H, 1.0)}), lm)["right_hand"] is None


def test_ankles_map_to_feet():
    res = frame_contacts(_kps({LF: (5, 5, 1.0), RF: (3, 13, 1.0)}), _label_map())
    assert res["left_foot"] == 7
    assert res["right_foot"] == 3


def test_radius_hit_counts_near_misses():
    lm = _label_map()
    kp = _kps({LH: (11, 7, 1.0)})   # 2 px right of hold 7's edge (col 9)
    assert frame_contacts(kp, lm, radius_px=0)["left_hand"] is None
    assert frame_contacts(kp, lm, radius_px=1.5)["left_hand"] is None
    assert frame_contacts(kp, lm, radius_px=2.5)["left_hand"] == 7


def test_radius_nearest_hold_wins():
    lm = _label_map()
    kp = _kps({LH: (3, 11, 1.0)})   # hold 3 is 1 px away, hold 7 about 2.8 px
    assert frame_contacts(kp, lm, radius_px=3)["left_hand"] == 3


def test_consecutive_frames_merge_into_one_interval():
    per_frame = [{"left_hand": 7}] * 6
    ivs = contact_intervals(per_frame, fps=10.0)
    assert len(ivs) == 1
    iv = ivs[0]
    assert set(iv) == {"limb", "hold_id", "t_start", "t_end", "f_start", "f_end"}
    assert iv["limb"] == "left_hand"
    assert iv["hold_id"] == 7
    assert (iv["f_start"], iv["f_end"]) == (0, 5)
    assert iv["t_start"] == pytest.approx(0.0)
    assert iv["t_end"] == pytest.approx(0.6)   # end is exclusive: (f_end + 1) / fps


def test_gap_within_max_gap_is_bridged():
    per_frame = [{"left_hand": 7}] * 5 + [{"left_hand": None}] + [{"left_hand": 7}] * 5
    ivs = contact_intervals(per_frame, fps=10.0, max_gap_s=0.1)
    assert len(ivs) == 1
    assert (ivs[0]["f_start"], ivs[0]["f_end"]) == (0, 10)


def test_gap_longer_than_max_gap_splits():
    per_frame = [{"left_hand": 7}] * 5 + [{"left_hand": None}] * 2 + [{"left_hand": 7}] * 5
    ivs = contact_intervals(per_frame, fps=10.0, max_gap_s=0.1)
    assert [(i["f_start"], i["f_end"]) for i in ivs] == [(0, 4), (7, 11)]


def test_short_interval_is_dropped():
    assert contact_intervals([{"left_hand": 7}] * 4, fps=10.0, min_duration_s=0.5) == []
    assert len(contact_intervals([{"left_hand": 7}] * 5, fps=10.0, min_duration_s=0.5)) == 1


def test_two_limbs_on_same_hold_give_two_intervals():
    per_frame = [{"left_hand": 7, "right_hand": 7}] * 6
    ivs = contact_intervals(per_frame, fps=10.0)
    assert sorted((i["limb"], i["hold_id"]) for i in ivs) == [("left_hand", 7), ("right_hand", 7)]


def test_hold_change_without_gap_splits_intervals():
    per_frame = [{"left_hand": 7}] * 6 + [{"left_hand": 3}] * 6
    ivs = contact_intervals(per_frame, fps=10.0)
    assert [(i["hold_id"], i["f_start"], i["f_end"]) for i in ivs] == [(7, 0, 5), (3, 6, 11)]
