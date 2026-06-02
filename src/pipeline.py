import cv2
import numpy as np
from collections import deque
from tqdm import tqdm

from .detector import Detector
from .reframer import smooth_position, crop_fixed, transform_keypoints
from .overlay import draw_com, draw_skeleton

TRAIL_LEN = 40   # frames of CoM history to show


def run(
    input_path: str,
    output_path: str,
    out_w: int,
    out_h: int,
    smoothing_alpha: float,
    person_fill: float = 0.65,
    show_com: bool = False,
    show_skeleton: bool = False,
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

        if show_skeleton:
            # Single YOLO call — get hip, keypoints, CoM all at once
            hip, keypoints, kp_conf, com_src = detector.detect_all(frame)
        else:
            hip = detector.detect_hip_center(frame)
            keypoints = kp_conf = com_src = None

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

        writer.write(cropped)

    cap.release()
    writer.release()
    print(f"Saved → {output_path}")
