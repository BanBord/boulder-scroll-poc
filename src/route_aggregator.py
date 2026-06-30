"""Aggregate per-frame contact timeline into route holds + start/top assignment.

Input  : `<video>_timeline.json` written by pipeline.py (track_holds=True).
Output : `<video>_route.json` with filtered route holds, plus start/top ids.

Heuristic (touched-only filter, longest-end-contact for top):
- Route hold = any detected hold touched (any limb) for >= MIN_TOUCH_FRAMES.
- Start hold = lowest-positioned (max y) route hold touched in the first 20%
               of the video. Tiebreak: longest contact duration in that window.
- Top hold   = route hold with the longest *continuous* hand-only (LH/RH)
               contact run in the last 20% of the video. Tiebreak: total
               hand-contact frame count in that window.
"""

import json
import os
from typing import Dict, List, Optional, Tuple

_LIMBS = ("LH", "RH", "LF", "RF")
_HAND_LIMBS = ("LH", "RH")
_MIN_TOUCH_SECONDS = 0.5
_MIN_TOUCH_FRAMES_FLOOR = 15
_START_WINDOW_FRAC = 0.20
_TOP_WINDOW_FRAC = 0.20


def _hold_radius(bbox: List[float]) -> float:
    _, _, w, h = bbox
    return 0.5 * max(float(w), float(h)) * 1.1


def _build_per_hold_index(holds: List[Dict]) -> Dict[int, Dict]:
    return {int(h["id"]): h for h in holds}


def _count_touches(frames: List[Dict], hold_ids: List[int]) -> Dict[int, Dict]:
    """For each hold id, accumulate {touch_frames, hand_frames, foot_frames,
    first_touch_t, last_touch_t}."""
    stats = {hid: {"touch_frames": 0, "hand_frames": 0, "foot_frames": 0,
                   "first_touch_t": None, "last_touch_t": None} for hid in hold_ids}
    for fr in frames:
        t = fr.get("t")
        touched_this_frame = set()
        for limb in _LIMBS:
            hid = fr.get(limb)
            if hid is None:
                continue
            hid = int(hid)
            if hid not in stats:
                continue
            touched_this_frame.add(hid)
            if limb in _HAND_LIMBS:
                stats[hid]["hand_frames"] += 1
            else:
                stats[hid]["foot_frames"] += 1
        for hid in touched_this_frame:
            stats[hid]["touch_frames"] += 1
            if stats[hid]["first_touch_t"] is None:
                stats[hid]["first_touch_t"] = t
            stats[hid]["last_touch_t"] = t
    return stats


def _pick_start(
    holds_by_id: Dict[int, Dict],
    route_ids: List[int],
    frames: List[Dict],
    start_cutoff_frame: int,
) -> Optional[int]:
    """Lowest-positioned (max y) hold touched (any limb) in the start window."""
    window = [f for f in frames if f["frame"] < start_cutoff_frame]
    in_window: Dict[int, int] = {hid: 0 for hid in route_ids}
    for fr in window:
        for limb in _LIMBS:
            hid = fr.get(limb)
            if hid is None:
                continue
            hid = int(hid)
            if hid in in_window:
                in_window[hid] += 1
    candidates = [hid for hid, n in in_window.items() if n > 0]
    if not candidates:
        return None
    # Sort by (-y, -count): largest y first (lowest spatially), break ties by contact count
    candidates.sort(key=lambda hid: (-holds_by_id[hid]["center"][1], -in_window[hid]))
    return candidates[0]


def _pick_top(
    holds_by_id: Dict[int, Dict],
    route_ids: List[int],
    frames: List[Dict],
    top_cutoff_frame: int,
) -> Optional[int]:
    """Longest *continuous* hand-only contact run in the top window."""
    window = [f for f in frames if f["frame"] >= top_cutoff_frame]
    if not window:
        return None

    longest_run: Dict[int, int] = {hid: 0 for hid in route_ids}
    total_hand: Dict[int, int] = {hid: 0 for hid in route_ids}
    current_run: Dict[int, int] = {hid: 0 for hid in route_ids}

    for fr in window:
        hand_ids_this_frame = set()
        for limb in _HAND_LIMBS:
            hid = fr.get(limb)
            if hid is not None and int(hid) in longest_run:
                hand_ids_this_frame.add(int(hid))
        for hid in longest_run:
            if hid in hand_ids_this_frame:
                current_run[hid] += 1
                total_hand[hid] += 1
                if current_run[hid] > longest_run[hid]:
                    longest_run[hid] = current_run[hid]
            else:
                current_run[hid] = 0

    candidates = [hid for hid, run in longest_run.items() if run > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda hid: (-longest_run[hid], -total_hand[hid]))
    return candidates[0]


def aggregate(timeline_path: str, out_path: Optional[str] = None) -> str:
    """Read timeline JSON, write route JSON, return route path."""
    if not os.path.exists(timeline_path):
        raise RuntimeError(f"timeline not found: {timeline_path}")
    with open(timeline_path) as f:
        timeline = json.load(f)

    fps = float(timeline.get("fps") or 0)
    if fps <= 0:
        raise RuntimeError(f"invalid fps in timeline: {fps}")
    holds: List[Dict] = timeline.get("holds") or []
    frames: List[Dict] = timeline.get("frames") or []
    if not holds:
        raise RuntimeError("timeline has no holds")
    if not frames:
        raise RuntimeError("timeline has no frames")

    min_touch_frames = max(_MIN_TOUCH_FRAMES_FLOOR, int(_MIN_TOUCH_SECONDS * fps))

    holds_by_id = _build_per_hold_index(holds)
    all_ids = list(holds_by_id.keys())
    stats = _count_touches(frames, all_ids)

    route_ids = [hid for hid in all_ids if stats[hid]["touch_frames"] >= min_touch_frames]

    last_frame_idx = max((f["frame"] for f in frames), default=0)
    n_frames = last_frame_idx + 1
    start_cutoff = max(1, int(n_frames * _START_WINDOW_FRAC))
    top_cutoff = int(n_frames * (1.0 - _TOP_WINDOW_FRAC))

    start_id = _pick_start(holds_by_id, route_ids, frames, start_cutoff)
    top_id = _pick_top(holds_by_id, route_ids, frames, top_cutoff)

    route_holds_out = []
    for hid in route_ids:
        h = holds_by_id[hid]
        cx, cy = h["center"]
        bbox = h["bbox"]
        role = "mid"
        if hid == start_id:
            role = "start"
        elif hid == top_id:
            role = "top"
        route_holds_out.append({
            "id": hid,
            "x": float(cx),
            "y": float(cy),
            "r": _hold_radius(bbox),
            "role": role,
            "touch_frames": stats[hid]["touch_frames"],
            "first_touch_t": stats[hid]["first_touch_t"],
            "last_touch_t": stats[hid]["last_touch_t"],
        })

    route_holds_out.sort(key=lambda h: h["y"])  # top-to-bottom

    video_size = timeline.get("video_size")  # may be absent
    out = {
        "fps": fps,
        "video_size": video_size,
        "holds": route_holds_out,
        "start_hold_id": start_id,
        "top_hold_id": top_id,
        "filter": {
            "min_touch_frames": min_touch_frames,
            "start_window_frac": _START_WINDOW_FRAC,
            "top_window_frac": _TOP_WINDOW_FRAC,
        },
    }

    if out_path is None:
        base, _ = os.path.splitext(timeline_path)
        if base.endswith("_timeline"):
            base = base[: -len("_timeline")]
        out_path = base + "_route.json"

    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    return out_path
