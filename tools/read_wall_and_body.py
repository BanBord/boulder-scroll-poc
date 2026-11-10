"""Read the wall and the body in one video: stabilise, pose, masks, contacts, render.

Stages (each cached in --work-dir; delete the stage file or pass --force to redo):
  A  stabilise every frame to the reference still (ECC, Euclidean)
  B  full-frame YOLO pass: person box per frame (used for crops and as fallback)
  C  pose on a crop around the climber, keypoints mapped back to full-frame pixels
  D  person silhouette: Vision (personseg binary) on upscaled crops, pasted back
  E  centre of mass (existing weights), smoothed; balance signals (pipeline._balance_data)
  F  limb-to-hold contacts with per-limb radius, contact intervals
  G  JSON sidecar and render (ffmpeg pipe, H.264, crf 18)

Example:
  .venv/bin/python tools/read_wall_and_body.py \
    --video VIDEO --masks GT_COCO --image-name wall-v2-000.png \
    --reference-image STILL.png --pose-weights YOLO.pt \
    --personseg-bin BIN --route-color blue --out-dir OUT --work-dir WORK
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.com_path import smooth_path                       # noqa: E402
from src.contact_timeline import contact_intervals, frame_contacts  # noqa: E402
from src.masks_io import label_map, load_holds             # noqa: E402
from src.stabilize import ecc_input_mask, reference_gray, stabilise_frame  # noqa: E402
from src.detector import Detector                          # noqa: E402
from src.pipeline import _balance_data                     # noqa: E402
from src import render_reading as rr                       # noqa: E402

FPS = 30.0
W, H = 1080, 1920
ECC_EXCLUDE = (800, 900, 1080, 1920)   # corner ignored by ECC (climber area), as in the experiment
HAND_RADIUS = 45.0                     # px at 1080 px width
FOOT_RADIUS = 30.0
CONF_MIN = 0.2
CROP_PAD = 0.35
CROP_MIN_W, CROP_MIN_H = 480, 640
POSE_IMGSZ = 1024
PERSON_LONG_SIDE = 1536
MEDIAN_WIN = 9


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def stage_done(path):
    return os.path.exists(path)


def _fill_nan_rows(arr):
    """Forward then backward fill rows that contain NaN (any column)."""
    out = arr.copy()
    last = None
    for i in range(len(out)):
        if np.isnan(out[i]).any():
            if last is not None:
                out[i] = last
        else:
            last = out[i]
    last = None
    for i in range(len(out) - 1, -1, -1):
        if np.isnan(out[i]).any():
            if last is not None:
                out[i] = last
        else:
            last = out[i]
    return out


# ---------------------------------------------------------------- A: stabilise
def stage_stabilise(args, n_frames, work):
    aligned_path = os.path.join(work, "aligned.npy")
    meta_path = os.path.join(work, "aligned_meta.json")
    if stage_done(meta_path) and not args.force:
        meta = json.load(open(meta_path))
        return np.load(aligned_path, mmap_mode="r")[:len(meta)], meta
    ref_rgb = cv2.cvtColor(cv2.imread(args.reference_image), cv2.COLOR_BGR2RGB)
    if ref_rgb.shape[:2] != (H, W):
        raise SystemExit(f"reference {ref_rgb.shape[:2]} != video {(H, W)}")
    ref_small = reference_gray(ref_rgb)
    mask_small = ecc_input_mask((H, W), ECC_EXCLUDE)
    out = np.lib.format.open_memmap(aligned_path, mode="w+", dtype=np.uint8, shape=(n_frames, H, W, 3))
    cap = cv2.VideoCapture(args.video)
    meta = []
    for f in range(n_frames):
        ok, bgr = cap.read()
        if not ok:
            log(f"video ended after {f} decodable frames (container reports {n_frames}); truncating")
            break
        if bgr.shape[:2] != (H, W):
            raise SystemExit(f"frame size {bgr.shape[:2]} != {(H, W)}")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        aligned, warp, cc = stabilise_frame(rgb, ref_small, mask_small)
        out[f] = aligned
        meta.append({"cc": round(cc, 4), "tx": round(float(warp[0, 2]), 2),
                     "ty": round(float(warp[1, 2]), 2)})
    cap.release()
    out.flush()
    n_dec = len(meta)
    json.dump(meta, open(meta_path, "w"))
    ccs = np.array([m["cc"] for m in meta])
    log(f"A stabilised {n_dec} frames; cc min {ccs.min():.3f}, median {np.median(ccs):.3f}, "
        f"frames below 0.5: {(ccs < 0.5).sum()}")
    return np.load(aligned_path, mmap_mode="r")[:n_dec], meta


# ---------------------------------------------------------------- B/C: pose
def _best_box_and_kp(result):
    """(xyxy box, keypoints (17,2), conf (17,)) for the most confident person, or None."""
    if result.boxes is None or len(result.boxes) == 0:
        return None
    boxes = result.boxes
    best = int(np.argmax(boxes.conf.cpu().numpy()))
    xyxy = boxes.xyxy[best].cpu().numpy()
    if result.keypoints is None or len(result.keypoints) <= best:
        return xyxy, None, None
    xy = result.keypoints.xy[best].cpu().numpy()
    conf = result.keypoints.conf[best].cpu().numpy()
    return xyxy, xy, conf


def stage_pose(args, aligned, det, work):
    pose_path = os.path.join(work, "pose.npz")
    if stage_done(pose_path) and not args.force:
        z = np.load(pose_path)
        return z["kp"], z["src"], z["box_crop"]
    n = aligned.shape[0]
    boxes = np.full((n, 4), np.nan)
    kp_full = np.zeros((n, 17, 3))
    for f in range(n):
        bgr = cv2.cvtColor(np.asarray(aligned[f]), cv2.COLOR_RGB2BGR)
        res = det.model(bgr, verbose=False)
        got = _best_box_and_kp(res[0]) if res else None
        if got is None:
            continue
        xyxy, xy, conf = got
        boxes[f] = xyxy
        if xy is not None:
            kp_full[f, :, :2] = xy
            kp_full[f, :, 2] = conf
    log(f"B full-frame person boxes: {int(np.isfinite(boxes[:, 0]).sum())} of {n} frames")

    # temporal median of the box, then padded crop
    filled = _fill_nan_rows(boxes)
    half = MEDIAN_WIN // 2
    med = np.stack([np.median(filled[max(0, i - half):i + half + 1], axis=0) for i in range(n)])
    crops = np.zeros((n, 4), int)
    for i, (x0, y0, x1, y1) in enumerate(med):
        bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        bw = max(bw * (1 + 2 * CROP_PAD), CROP_MIN_W)
        bh = max(bh * (1 + 2 * CROP_PAD), CROP_MIN_H)
        X0, Y0 = int(max(0, cx - bw / 2)), int(max(0, cy - bh / 2))
        X1, Y1 = int(min(W, cx + bw / 2)), int(min(H, cy + bh / 2))
        crops[i] = (X0, Y0, X1, Y1)

    kp = np.zeros((n, 17, 3))
    src = np.zeros(n, np.uint8)     # 0 none, 1 crop pose, 2 full-frame fallback
    for f in range(n):
        X0, Y0, X1, Y1 = crops[f]
        bgr = cv2.cvtColor(np.asarray(aligned[f, Y0:Y1, X0:X1]), cv2.COLOR_RGB2BGR)
        res = det.model(bgr, imgsz=POSE_IMGSZ, verbose=False)
        got = _best_box_and_kp(res[0]) if res else None
        if got is not None and got[1] is not None:
            xy, conf = got[1], got[2]
            kp[f, :, 0] = xy[:, 0] + X0
            kp[f, :, 1] = xy[:, 1] + Y0
            kp[f, :, 2] = conf
            src[f] = 1
        elif kp_full[f, :, 2].any():
            kp[f] = kp_full[f]
            src[f] = 2
    np.savez(pose_path, kp=kp, src=src, box_crop=crops)
    log(f"C pose: crop {int((src == 1).sum())}, full-frame fallback {int((src == 2).sum())}, "
        f"none {int((src == 0).sum())} of {n}")
    return kp, src, crops


# ---------------------------------------------------------------- D: silhouette
def stage_person(args, aligned, crops, work):
    person_path = os.path.join(work, "person.npy")
    if stage_done(person_path) and not args.force:
        return np.load(person_path, mmap_mode="r")
    n = aligned.shape[0]
    crop_dir = os.path.join(work, "crops")
    mask_dir = os.path.join(work, "masks_crop")
    shutil.rmtree(crop_dir, ignore_errors=True)
    shutil.rmtree(mask_dir, ignore_errors=True)
    os.makedirs(crop_dir)
    os.makedirs(mask_dir)
    scales = []
    for f in range(n):
        X0, Y0, X1, Y1 = crops[f]
        crop = np.asarray(aligned[f, Y0:Y1, X0:X1])
        cw, ch = X1 - X0, Y1 - Y0
        s = PERSON_LONG_SIDE / max(cw, ch)
        up = cv2.resize(crop, (int(round(cw * s)), int(round(ch * s))), interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(os.path.join(crop_dir, f"f{f:05d}.png"), cv2.cvtColor(up, cv2.COLOR_RGB2BGR))
        scales.append(s)
    subprocess.run([args.personseg_bin, crop_dir, mask_dir], check=True, capture_output=True)

    raw = np.zeros((n, H, W), np.uint8)
    ok = np.zeros(n, bool)
    for f in range(n):
        p = os.path.join(mask_dir, f"f{f:05d}.png")
        if not os.path.exists(p):
            continue
        X0, Y0, X1, Y1 = crops[f]
        m = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        m = cv2.resize(m, (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_LINEAR)
        m = (m >= 128).astype(np.uint8)
        if m.sum() < 500:
            continue
        k, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        m = (lab == big).astype(np.uint8)
        pad = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
        pad[1:-1, 1:-1] = m
        cv2.floodFill(pad, None, (0, 0), 2)
        m = (m.astype(bool) | (pad[1:-1, 1:-1] == 0)).astype(np.uint8)
        raw[f, Y0:Y1, X0:X1] = m
        ok[f] = True
    # fallback: frames without a usable mask keep the previous mask; then temporal majority over 3
    for f in range(n):
        if not ok[f] and f > 0:
            raw[f] = raw[f - 1]
    out = np.zeros((n, H, W), np.uint8)
    for f in range(n):
        lo, hi = max(0, f - 1), min(n, f + 2)
        out[f] = (raw[lo:hi].sum(axis=0, dtype=np.uint16) * 2 >= (hi - lo)).astype(np.uint8)
    np.save(person_path, out)
    log(f"D person masks: Vision ok on {int(ok.sum())} of {n} frames; "
        f"mean area {out.reshape(n, -1).mean(axis=1).mean() * 100:.1f} % of frame")
    return np.load(person_path, mmap_mode="r")


# ---------------------------------------------------------------- E/F: CoM, balance, contacts
def stage_contacts(args, kp, src, det, holds, n):
    com_raw = []
    for f in range(n):
        if src[f] == 0:
            com_raw.append(None)
            continue
        c = det._calculate_com(kp[f, :, :2], kp[f, :, 2])
        com_raw.append(c)
    com_smooth = smooth_path(com_raw, window=9)
    com_arr = np.array([[np.nan, np.nan] if p is None else p for p in com_smooth], float)

    balance = np.full((n, 3), np.nan)
    for f in range(n):
        if src[f] == 0:
            continue
        bd = _balance_data(kp[f, :, :2], kp[f, :, 2], com_smooth[f], W)
        if bd is not None:
            balance[f] = [bd["arm"], bd["leg"], bd["com"]]

    lm = label_map(holds, (H, W))
    per_frame = []
    for f in range(n):
        hands = frame_contacts(kp[f], lm, conf_min=CONF_MIN, radius_px=HAND_RADIUS)
        feet = frame_contacts(kp[f], lm, conf_min=CONF_MIN, radius_px=FOOT_RADIUS)
        per_frame.append({**{k: v for k, v in hands.items() if k.endswith("hand")},
                          **{k: v for k, v in feet.items() if k.endswith("foot")}})
    intervals = contact_intervals(per_frame, FPS, min_duration_s=0.5, max_gap_s=0.1)
    for iv in intervals:
        iv["t_start"] = round(iv["t_start"], 3)
        iv["t_end"] = round(iv["t_end"], 3)
    log(f"E/F CoM valid {int(np.isfinite(com_arr[:, 0]).sum())} of {n}; "
        f"contact intervals {len(intervals)}")
    return com_arr, balance, intervals


# ---------------------------------------------------------------- render
def hold_geometry(holds, route_color):
    order = sorted(range(len(holds)), key=lambda i: holds[i].centroid[1])
    rank = {i: r + 1 for r, i in enumerate(order)}
    n = len(holds)
    geoms = []
    for i, h in enumerate(holds):
        contours, _ = cv2.findContours(h.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        polys = [c.reshape(-1, 2).astype(np.float64) for c in contours if len(c) >= 3]
        x, y, bw, bh = h.bbox
        appear = rank[i] - 1
        geoms.append(rr.HoldGeom(
            id=h.id, index=rank[i], color=h.color, score=h.score,
            route=(h.color == route_color), polys=polys,
            bbox=(float(x), float(y), float(x + bw), float(y + bh)),
            appear_t=appear / max(n, 1) * rr.INTRO_SPAN_S,
        ))
    return geoms


def render_video(args, aligned, person, com, balance, intervals, holds, n, out_dir, kp):
    scores = [h.score for h in holds if h.score is not None]
    show_scores = len(scores) > 0 and not all(abs(s - 1.0) < 1e-9 for s in scores)
    data = rr.ReadingData(
        fps=FPS, n_frames=n, holds=hold_geometry(holds, args.route_color), intervals=intervals,
        keypoints=kp.astype(np.float64), com=com, balance=balance, person=person, aligned=aligned,
        show_scores=show_scores,
        route_total=sum(1 for h in holds if h.color == args.route_color), holds_total=len(holds),
    )
    renderer = rr.ReadingRenderer(data)
    stills = set(rr.stills_frames(n))
    still_dir = os.path.join(out_dir, "stills")
    os.makedirs(still_dir, exist_ok=True)
    if args.preview_frames:
        for f in [int(x) for x in args.preview_frames.split(",")]:
            img = renderer.render(f)
            cv2.imwrite(os.path.join(args.work_dir, f"preview_{f:04d}.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        log(f"preview frames written to {args.work_dir}")
        return
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    out_mp4 = os.path.join(out_dir, "v2_maschinenblick.mp4")
    proc = subprocess.Popen([
        ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(int(FPS)), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4,
    ], stdin=subprocess.PIPE)
    for f in range(n):
        img = renderer.render(f)
        proc.stdin.write(img.tobytes())
        if f in stills:
            cv2.imwrite(os.path.join(still_dir, f"still_f{f:04d}.png"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        if f % 50 == 0:
            log(f"render {f}/{n}")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    log(f"video -> {out_mp4}")


def write_json(args, out_dir, holds, intervals, com, balance, kp, n):
    geoms = hold_geometry(holds, args.route_color)
    doc = {
        "fps": FPS,
        "frames": n,
        "video_size": [W, H],
        "params": {"hand_radius_px": HAND_RADIUS, "foot_radius_px": FOOT_RADIUS,
                   "conf_min": CONF_MIN, "min_contact_s": 0.5, "max_gap_s": 0.1,
                   "com_smooth_window": 9},
        "holds": [{"id": g.id, "index": g.index, "color": g.color, "score": g.score,
                   "route": g.route, "bbox": [round(v, 1) for v in g.bbox]} for g in geoms],
        "contacts": [{"limb": iv["limb"], "hold_id": iv["hold_id"], "t_start": iv["t_start"],
                      "t_end": iv["t_end"], "f_start": iv["f_start"], "f_end": iv["f_end"]}
                     for iv in intervals],
        "com_path": [{"f": f, "x": round(float(c[0]), 1), "y": round(float(c[1]), 1)}
                     for f, c in enumerate(com) if np.isfinite(c).all()],
        "balance": [{"f": f, "arm": round(float(b[0]), 2), "leg": round(float(b[1]), 2),
                     "com": round(float(b[2]), 2)}
                    for f, b in enumerate(balance) if np.isfinite(b).all()],
        "keypoint_conf": [[round(float(c), 3) for c in kp[f, :, 2]] for f in range(n)],
        "keypoints": [[[round(float(x), 1), round(float(y), 1)] for x, y in kp[f, :, :2]] for f in range(n)],
    }
    path = os.path.join(out_dir, "v2_maschinenblick.json")
    with open(path, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    log(f"json -> {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--masks", required=True, help="COCO JSON with hold masks")
    ap.add_argument("--image-name", required=True, help="file_name of the masked still, e.g. wall-v2-000.png")
    ap.add_argument("--reference-image", required=True, help="the still the masks belong to (ECC template)")
    ap.add_argument("--pose-weights", required=True)
    ap.add_argument("--personseg-bin", required=True)
    ap.add_argument("--route-color", default="blue")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--force", action="store_true", help="recompute all cached stages")
    ap.add_argument("--preview-frames", default="", help="comma list: write these frames as PNG and stop")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.work_dir, exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    n_container = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    holds = load_holds(args.masks, args.image_name)
    log(f"holds on {args.image_name}: {len(holds)}, route ({args.route_color}): "
        f"{sum(1 for h in holds if h.color == args.route_color)}")

    aligned, _ = stage_stabilise(args, n_container, args.work_dir)
    n = aligned.shape[0]
    log(f"using {n} frames (container reports {n_container})")
    det = Detector(args.pose_weights)
    kp, src, crops = stage_pose(args, aligned, det, args.work_dir)
    person = stage_person(args, aligned, crops, args.work_dir)
    com, balance, intervals = stage_contacts(args, kp, src, det, holds, n)
    write_json(args, args.out_dir, holds, intervals, com, balance, kp, n)
    render_video(args, aligned, person, com, balance, intervals, holds, n, args.out_dir, kp)


if __name__ == "__main__":
    main()
