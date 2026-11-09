"""Per-frame limb-to-hold contacts and merged contact intervals.

A limb is the COCO-17 wrist or ankle keypoint. It touches a hold if the keypoint
lies inside the hold mask, or within radius_px of it (nearest hold wins).
Intervals are computed per limb from the per-frame results.
"""

import math
from typing import Dict, List, Optional

import numpy as np

# COCO-17 keypoint index per limb
LIMB_KEYPOINTS: Dict[str, int] = {
    "left_hand": 9,
    "right_hand": 10,
    "left_foot": 15,
    "right_foot": 16,
}


def _nearest_hold(label_map: np.ndarray, x: int, y: int, radius_px: float) -> Optional[int]:
    """Hold id at pixel (x, y), or the nearest hold within radius_px, else None."""
    h, w = label_map.shape
    if not (0 <= x < w and 0 <= y < h):
        return None
    if radius_px <= 0:
        value = int(label_map[y, x])
        return value or None
    r = int(math.ceil(radius_px))
    y0, y1 = max(0, y - r), min(h, y + r + 1)
    x0, x1 = max(0, x - r), min(w, x + r + 1)
    window = label_map[y0:y1, x0:x1]
    ys, xs = np.nonzero(window)
    if ys.size == 0:
        return None
    d2 = (xs + x0 - x) ** 2 + (ys + y0 - y) ** 2
    keep = d2 <= radius_px * radius_px
    if not keep.any():
        return None
    ids = window[ys[keep], xs[keep]]
    return int(ids[int(np.argmin(d2[keep]))])


def frame_contacts(
    keypoints: Optional[np.ndarray],   # (17, 3): x, y, conf in image pixels
    label_map: np.ndarray,             # int32 HxW, 0 = no hold
    conf_min: float = 0.2,
    radius_px: float = 0,
) -> Dict[str, Optional[int]]:
    """Return {limb: hold_id or None} for left/right hand and foot."""
    result: Dict[str, Optional[int]] = {limb: None for limb in LIMB_KEYPOINTS}
    if keypoints is None:
        return result
    for limb, idx in LIMB_KEYPOINTS.items():
        x, y, conf = (float(v) for v in keypoints[idx])
        if conf < conf_min or not (math.isfinite(x) and math.isfinite(y)):
            continue
        result[limb] = _nearest_hold(label_map, int(round(x)), int(round(y)), radius_px)
    return result


def contact_intervals(
    per_frame: List[Dict[str, Optional[int]]],
    fps: float,
    min_duration_s: float = 0.5,
    max_gap_s: float = 0.1,
) -> List[dict]:
    """Merge per-frame contacts into intervals per limb and hold.

    Frames with the same hold are merged; gaps of up to max_gap_s without a
    detection are bridged. Hold changes always split. Intervals shorter than
    min_duration_s are dropped. t_end is exclusive: (f_end + 1) / fps.
    """
    max_gap_frames = max_gap_s * fps + 1e-9
    found = []
    for limb in LIMB_KEYPOINTS:
        cur: Optional[dict] = None
        for f, frame in enumerate(per_frame):
            hold = frame.get(limb)
            if hold is None:
                continue
            hold = int(hold)
            if cur is not None and hold == cur["hold"] and (f - cur["f_end"] - 1) <= max_gap_frames:
                cur["f_end"] = f
                continue
            if cur is not None:
                found.append((limb, cur))
            cur = {"hold": hold, "f_start": f, "f_end": f}
        if cur is not None:
            found.append((limb, cur))

    out = []
    for limb, iv in found:
        if (iv["f_end"] - iv["f_start"] + 1) / fps < min_duration_s - 1e-9:
            continue
        out.append({
            "limb": limb,
            "hold_id": iv["hold"],
            "t_start": iv["f_start"] / fps,
            "t_end": (iv["f_end"] + 1) / fps,
            "f_start": iv["f_start"],
            "f_end": iv["f_end"],
        })
    out.sort(key=lambda d: (d["f_start"], d["limb"]))
    return out
