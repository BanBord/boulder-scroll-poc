import cv2
import json
import os
import numpy as np
from collections import deque
from tqdm import tqdm

from .detector import Detector
from .reframer import smooth_position, crop_fixed, transform_keypoints
from .overlay import draw_com, draw_skeleton

TRAIL_LEN = 40   # frames of CoM history to show


def _balance_data(
    keypoints,          # np.ndarray (17,2) output coords, or None
    kp_conf,            # np.ndarray (17,), or None
    com_out,            # (x,y) or None
    out_w: int,
    conf_thresh: float = 0.2,
):
    """
    CoM-centred balance signals for the tower visualisation.
    Returns dict {"arm": float, "leg": float, "com": float} or None.

    arm = com_x − arm_midpoint   (wrists 9,10)     + → CoM right of hands
    leg = com_x − foot_midpoint  (ankles 15,16 or knees 13,14 as fallback)
                                                    + → CoM right of feet
    com = com_x − out_w/2        absolute offset,  + → body right of frame centre
    """
    if keypoints is None or kp_conf is None or com_out is None:
        return None

    com_x = float(com_out[0])

    def kp_x(idx):
        return float(keypoints[idx, 0]) if kp_conf[idx] > conf_thresh else None

    # Arm midpoint: wrists
    arm_pts = [x for x in [kp_x(9), kp_x(10)] if x is not None]
    arm_mid  = float(np.mean(arm_pts)) if arm_pts else None

    # Foot midpoint: ankles first, knees as fallback
    foot_pts = [x for x in [kp_x(15), kp_x(16)] if x is not None]
    if not foot_pts:
        foot_pts = [x for x in [kp_x(13), kp_x(14)] if x is not None]
    foot_mid = float(np.mean(foot_pts)) if foot_pts else None

    arm_sig  = round(com_x - arm_mid,        2) if arm_mid  is not None else 0.0
    leg_sig  = round(com_x - foot_mid,       2) if foot_mid is not None else 0.0
    com_off  = round(com_x - out_w / 2,      2)

    return {"arm": arm_sig, "leg": leg_sig, "com": com_off}


def run(
    input_path: str,
    output_path: str,
    out_w: int,
    out_h: int,
    smoothing_alpha: float,
    person_fill: float = 0.65,
    show_com: bool = False,
    show_skeleton: bool = False,
    show_balance: bool = False,
    balance_json_path: str = None,
    track_holds: bool = False,
    route_json_path: str = None,
    progress_callback=None,
    max_seconds: float = None,
) -> None:
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    detector = Detector()

    # --- Hold detection (optional) ---
    holds = []        # SAM-mask holds (legacy path)
    route_holds = []  # pre-saved distance-based holds
    if track_holds:
        if route_json_path:
            # Fast path: load pre-saved route holds, no SAM needed
            from .contact import check_contacts_distance
            with open(route_json_path) as f:
                _route = json.load(f)
            route_holds = _route["holds"]
            print(f"Loaded {len(route_holds)} route holds from {route_json_path}")
        else:
            from .hold_detector import detect_holds
            from .contact import check_contacts
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps))
            _, ref_frame = cap.read()
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            if ref_frame is not None:
                holds = detect_holds(ref_frame)
        timeline_frames = []

    # --- Calibration pass ---
    print("Calibrating focal length + anchor position from sample frames...")
    cal = detector.calibrate(cap, n_samples=60)

    heights     = cal["heights"]
    y_positions = cal["y_positions"]

    canonical_h  = float(np.percentile(heights, 90)) if heights else src_h * person_fill
    fixed_cy     = float(np.median(y_positions)) if y_positions else float(src_h / 2)
    fixed_crop_h = int(canonical_h / person_fill)
    fixed_crop_w = int(fixed_crop_h * out_w / out_h)

    print(f"  Canonical person height : {canonical_h:.0f}px")
    print(f"  Fixed vertical anchor   : Y={fixed_cy:.0f}px  (median hip position in source)")
    print(f"  Fixed crop window       : {fixed_crop_w}×{fixed_crop_h}px")
    print(f"  Person fills            : ~{person_fill*100:.0f}% of frame height")

    # --- Main processing pass ---
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))

    # Balance JSON accumulation
    _balance_frames = [] if (show_balance or balance_json_path) else None

    smooth_cx  = float(src_w / 2)
    smooth_cy  = fixed_cy
    com_trail  = deque(maxlen=TRAIL_LEN)   # CoM positions in output coords

    max_frames = total
    if max_seconds is not None and max_seconds > 0:
        max_frames = min(total, int(max_seconds * fps))

    print(f"Processing {max_frames} frames  ({src_w}x{src_h} → {out_w}x{out_h})")
    print(f"  show_skeleton={show_skeleton}  show_com={show_com}")

    for frame_idx in tqdm(range(max_frames), unit="frame"):
        if progress_callback and frame_idx % 10 == 0:
            progress_callback(frame_idx, max_frames)

        ok, frame = cap.read()
        if not ok:
            break

        if show_skeleton or show_balance or track_holds:
            hip, keypoints, kp_conf, com_src = detector.detect_all(frame)
        else:
            hip = detector.detect_hip_center(frame)
            keypoints = kp_conf = com_src = None

        if track_holds:
            if route_holds:
                contacts = check_contacts_distance(keypoints, kp_conf, route_holds)
            elif holds:
                contacts = check_contacts(keypoints, kp_conf, holds)
            else:
                contacts = {"LH": None, "RH": None, "LF": None, "RF": None}
            timeline_frames.append({
                "frame": frame_idx,
                "t":     round(frame_idx / fps, 3),
                **{k: v for k, v in contacts.items()},
            })

        if hip is not None:
            smooth_cx, smooth_cy = smooth_position(
                (hip[0], hip[1]), (smooth_cx, smooth_cy), alpha=smoothing_alpha
            )

        # Crop centred on tracked hip position
        cropped = crop_fixed(frame, smooth_cx, smooth_cy, fixed_crop_w, fixed_crop_h, out_w, out_h)

        if show_skeleton:
            # Coordinate transform helper
            x1 = smooth_cx - fixed_crop_w / 2
            y1 = smooth_cy - fixed_crop_h / 2
            sx = out_w / fixed_crop_w
            sy = out_h / fixed_crop_h

            def to_out(px, py):
                return ((px - x1) * sx, (py - y1) * sy)

            # CoM in output coords — fall back to hip centre if CoM not available
            com_out = None
            if com_src is not None:
                com_out = to_out(*com_src)
            elif hip is not None:
                com_out = to_out(*hip)

            com_trail.append(com_out)

            if keypoints is not None:
                kps_out = transform_keypoints(
                    keypoints, smooth_cx, smooth_cy,
                    fixed_crop_w, fixed_crop_h, out_w, out_h,
                )
                draw_skeleton(cropped, kps_out, kp_conf, com_out, list(com_trail))
            else:
                # No keypoints — draw just the CoM dot so something is always visible
                draw_skeleton(cropped, None, None, com_out, list(com_trail))

        elif show_com:
            draw_com(cropped, out_w // 2, out_h // 2)

        if _balance_frames is not None:
            # Ensure com_out is available even when show_skeleton is False
            if not show_skeleton:
                com_out = None
                if com_src is not None:
                    x1_b = smooth_cx - fixed_crop_w / 2
                    y1_b = smooth_cy - fixed_crop_h / 2
                    sx_b = out_w / fixed_crop_w
                    sy_b = out_h / fixed_crop_h
                    com_out = ((com_src[0] - x1_b) * sx_b, (com_src[1] - y1_b) * sy_b)

            kps_out_bal = None
            if keypoints is not None:
                kps_out_bal = transform_keypoints(
                    keypoints, smooth_cx, smooth_cy,
                    fixed_crop_w, fixed_crop_h, out_w, out_h,
                )

            bd = _balance_data(kps_out_bal, kp_conf, com_out, out_w)
            if bd is not None:
                bd["f"] = frame_idx
                if com_src is not None:
                    bd["sx"] = round(float(com_src[0]), 1)
                    bd["sy"] = round(float(com_src[1]), 1)
                _balance_frames.append(bd)

        writer.write(cropped)

    cap.release()
    writer.release()
    print(f"Saved → {output_path}")

    # Write balance JSON sidecar
    if _balance_frames is not None:
        out_json = balance_json_path or (output_path.rsplit(".", 1)[0] + "_balance.json")
        with open(out_json, "w") as f:
            json.dump({"fps": fps, "frames": _balance_frames}, f, separators=(",", ":"))
        print(f"Balance JSON → {out_json}")

    if track_holds and (holds or route_holds):
        timeline_path = os.path.splitext(output_path)[0] + "_timeline.json"
        hold_meta = (
            [{"id": h["id"], "x": h["x"], "y": h["y"], "r": h["r"], "role": h.get("role", "mid")} for h in route_holds]
            if route_holds
            else [{"id": h["id"], "center": list(h["center"]), "bbox": list(h["bbox"])} for h in holds]
        )
        timeline = {"fps": fps, "holds": hold_meta, "frames": timeline_frames}
        with open(timeline_path, "w") as f:
            json.dump(timeline, f)
        print(f"Timeline → {timeline_path}")
