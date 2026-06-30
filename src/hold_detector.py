import os
import cv2
import numpy as np
from typing import List, Dict, Optional, Tuple

_CHECKPOINT_URL  = "https://github.com/ChaoningZhang/MobileSAM/releases/download/v1.0/mobile_sam.pt"
_CHECKPOINT_PATH = os.path.expanduser("~/.cache/mobile_sam/mobile_sam.pt")
_HF_REPO         = "dhkim2810/MobileSAM"

# ── Default Green HSV thresholds (only used if color_filter="green") ─────────
_GREEN_HSV = ((35, 22, 30), (105, 255, 220))
_MIN_AREA      = 200    # px²
_MAX_AREA_FRAC = 0.05   # ignore segments > 5% of frame (floor, wall panels)

# Shape sanity: rule out long thin streaks (volumes/wall edges)
_MAX_ASPECT    = 6.0    # bbox max/min side ratio
_MIN_SOLIDITY  = 0.5    # contour_area / convex_hull_area

# Hard absolute size cap: hold radius is bounded by frame width
# (real holds rarely exceed ~7% of frame width even close to camera)
_MAX_RADIUS_FRAC = 0.07
# Mat-zone exclusion: drop segments whose centre lies in the bottom slice of
# the frame — crash mats, floor and ground volumes live there.
_MAT_ZONE_FRAC = 0.92

# IOU threshold: SAM mask and HSV blob are "same hold" if overlap > this
_IOU_MERGE = 0.3

# Number of frames sampled when picking a clean reference frame
_CLEAN_FRAME_SAMPLES = 30


def _get_checkpoint() -> str:
    if os.path.exists(_CHECKPOINT_PATH) and os.path.getsize(_CHECKPOINT_PATH) > 1_000_000:
        return _CHECKPOINT_PATH
    os.makedirs(os.path.dirname(_CHECKPOINT_PATH), exist_ok=True)
    print("Downloading MobileSAM checkpoint via HuggingFace Hub…")
    from huggingface_hub import hf_hub_download
    path = hf_hub_download(repo_id=_HF_REPO, filename="mobile_sam.pt",
                           local_dir=os.path.dirname(_CHECKPOINT_PATH))
    if path != _CHECKPOINT_PATH:
        import shutil
        shutil.copy(path, _CHECKPOINT_PATH)
    return _CHECKPOINT_PATH


# ── Reference-frame selection ────────────────────────────────────────────────

def _frame_sharpness(frame: np.ndarray) -> float:
    """Variance of Laplacian — higher = sharper."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def pick_clean_frame(cap, detector=None, n_samples: int = _CLEAN_FRAME_SAMPLES) -> Optional[np.ndarray]:
    """Sample frames across the video; return the sharpest one without a person.

    Falls back to a per-pixel median composite of all samples if every sample
    contains a person.
    """
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, fr = cap.read()
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return fr if ok else None

    if detector is None:
        from .detector import Detector
        detector = Detector()

    indices = [int(i * (total - 1) / max(1, n_samples - 1)) for i in range(n_samples)]
    sampled = []
    person_free = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        sampled.append(fr)
        hip, *_ = detector.detect_all(fr)
        if hip is None:
            person_free.append(fr)

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    if person_free:
        best = max(person_free, key=_frame_sharpness)
        print(f"[clean-frame] picked person-free sample (sharpness "
              f"{_frame_sharpness(best):.1f}) from {len(person_free)}/{len(sampled)} clean samples")
        return best

    if not sampled:
        return None

    print(f"[clean-frame] no person-free frame in {len(sampled)} samples → median composite")
    stack = np.stack(sampled, axis=0)
    return np.median(stack, axis=0).astype(np.uint8)


# ── Color filter (optional) ──────────────────────────────────────────────────

def _color_mask(frame_hsv: np.ndarray, color: str) -> Optional[np.ndarray]:
    if color == "green":
        lo = np.array(_GREEN_HSV[0], dtype=np.uint8)
        hi = np.array(_GREEN_HSV[1], dtype=np.uint8)
    else:
        return None
    mask = cv2.inRange(frame_hsv, lo, hi)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=1)
    return mask


def _color_holds(frame: np.ndarray, frame_area: int, color: str) -> List[Dict]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    binary = _color_mask(hsv, color)
    if binary is None:
        return []
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    holds = []
    h_img, w_img = frame.shape[:2]
    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if area < _MIN_AREA or area > frame_area * _MAX_AREA_FRAC:
            continue
        x, y, w, hh = cv2.boundingRect(cnt)
        bbox = (int(x), int(y), int(w), int(hh))
        if not _passes_size_cap(bbox, w_img):
            continue
        if not _passes_mat_zone(bbox, h_img):
            continue
        if not _contour_passes_shape(cnt, area):
            continue
        m = np.zeros((h_img, w_img), dtype=np.uint8)
        cv2.drawContours(m, [cnt], -1, 255, -1)
        mask = m.astype(bool)
        cx, cy = x + w / 2, y + hh / 2
        holds.append({"mask": mask, "center": (float(cx), float(cy)),
                      "bbox": bbox, "source": "hsv"})
    return holds


def _segment_matches_color(seg: np.ndarray, frame_hsv: np.ndarray, color: str) -> bool:
    if color == "green":
        lo, hi = _GREEN_HSV
    else:
        return True
    pixels = frame_hsv[seg]
    if pixels.size == 0:
        return False
    h = np.median(pixels[:, 0])
    s = np.median(pixels[:, 1])
    v = np.median(pixels[:, 2])
    return (lo[0] <= h <= hi[0] and s >= lo[1] and lo[2] <= v <= hi[2])


# ── Shape sanity ─────────────────────────────────────────────────────────────

def _bbox_aspect(w: int, h: int) -> float:
    if w <= 0 or h <= 0:
        return float("inf")
    return max(w, h) / min(w, h)


def _segment_passes_shape(seg: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
    _, _, w, h = bbox
    if _bbox_aspect(w, h) > _MAX_ASPECT:
        return False
    cnts, _ = cv2.findContours(seg.astype(np.uint8) * 255, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return False
    cnt = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    return _contour_passes_shape(cnt, area)


def _contour_passes_shape(cnt: np.ndarray, area: float) -> bool:
    if area <= 0:
        return False
    hull = cv2.convexHull(cnt)
    hull_area = cv2.contourArea(hull)
    if hull_area <= 0:
        return False
    solidity = area / hull_area
    if solidity < _MIN_SOLIDITY:
        return False
    x, y, w, h = cv2.boundingRect(cnt)
    return _bbox_aspect(w, h) <= _MAX_ASPECT


def _passes_size_cap(bbox, frame_w: int) -> bool:
    """Reject segments whose effective radius exceeds the absolute cap."""
    _, _, w, h = bbox
    r = 0.5 * max(float(w), float(h))
    return r <= _MAX_RADIUS_FRAC * frame_w


def _passes_mat_zone(bbox, frame_h: int) -> bool:
    """Reject segments whose centre is below the mat-zone threshold."""
    _, y, _, h = bbox
    cy = float(y) + float(h) / 2.0
    return cy < _MAT_ZONE_FRAC * frame_h


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union > 0 else 0.0


# ── Main detector ────────────────────────────────────────────────────────────

def detect_holds(reference_frame: np.ndarray, color_filter: Optional[str] = None) -> List[Dict]:
    """SAM-based hold detector, optionally restricted by colour.

    color_filter: None (default) → accept every SAM segment that passes the
    size + shape sanity filter. "green" → keep only green segments (legacy
    willtopia behaviour) and run an HSV fallback pass.

    Returns: List[{id, mask (H×W bool), center (x,y), bbox, source}].
    """
    from mobile_sam import sam_model_registry, SamAutomaticMaskGenerator

    h_img, w_img = reference_frame.shape[:2]
    frame_area = h_img * w_img
    frame_hsv = cv2.cvtColor(reference_frame, cv2.COLOR_BGR2HSV)

    checkpoint = _get_checkpoint()
    sam = sam_model_registry["vit_t"](checkpoint=checkpoint)
    sam.eval()

    generator = SamAutomaticMaskGenerator(
        sam,
        points_per_side=32,
        pred_iou_thresh=0.82,
        stability_score_thresh=0.88,
        min_mask_region_area=_MIN_AREA,
    )

    frame_rgb = cv2.cvtColor(reference_frame, cv2.COLOR_BGR2RGB)
    print("SAM: segmenting reference frame…")
    all_masks = generator.generate(frame_rgb)
    print(f"SAM: {len(all_masks)} total segments")

    sam_holds = []
    for m in all_masks:
        seg = m["segmentation"].astype(bool)
        area = int(seg.sum())
        if area < _MIN_AREA or area > frame_area * _MAX_AREA_FRAC:
            continue
        x, y, w, hh = m["bbox"]
        bbox = (int(x), int(y), int(w), int(hh))
        if not _passes_size_cap(bbox, w_img):
            continue
        if not _passes_mat_zone(bbox, h_img):
            continue
        if not _segment_passes_shape(seg, bbox):
            continue
        if color_filter and not _segment_matches_color(seg, frame_hsv, color_filter):
            continue
        sam_holds.append({
            "mask":   seg,
            "center": (float(x + w / 2), float(y + hh / 2)),
            "bbox":   bbox,
            "source": "sam",
        })

    print(f"SAM holds after filters: {len(sam_holds)}")

    # HSV fallback only runs when colour-restricted.
    if color_filter:
        candidates = _color_holds(reference_frame, frame_area, color_filter)
        print(f"{color_filter.upper()} HSV candidates: {len(candidates)}")
        added = 0
        for hc in candidates:
            covered = any(_iou(hc["mask"], sh["mask"]) >= _IOU_MERGE for sh in sam_holds)
            if not covered:
                sam_holds.append(hc)
                added += 1
        print(f"HSV added {added} extra holds")

    # Assign sequential IDs sorted top→bottom.
    sam_holds.sort(key=lambda h: h["center"][1])
    for i, h in enumerate(sam_holds):
        h["id"] = i

    print(f"Total holds detected: {len(sam_holds)}")
    return sam_holds


# ── Debug CLI ────────────────────────────────────────────────────────────────

def _debug_overlay(frame: np.ndarray, holds: List[Dict]) -> np.ndarray:
    overlay = frame.copy()
    for h in holds:
        x, y, w, hh = h["bbox"]
        cv2.rectangle(overlay, (x, y), (x + w, y + hh), (0, 255, 0), 2)
        cv2.putText(overlay, f"{h['id']}", (x, max(0, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    return overlay


def _debug_cli(video_path: str, out_path: str = "holds_debug.png",
               color_filter: Optional[str] = None) -> None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    ref = pick_clean_frame(cap)
    cap.release()
    if ref is None:
        raise RuntimeError("no usable reference frame")
    holds = detect_holds(ref, color_filter=color_filter)
    overlay = _debug_overlay(ref, holds)
    cv2.imwrite(out_path, overlay)
    print(f"[debug] wrote {out_path} with {len(holds)} holds")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="holds_debug.png")
    ap.add_argument("--color", default=None, help="optional colour filter, e.g. 'green'")
    args = ap.parse_args()
    _debug_cli(args.video, args.out, color_filter=args.color)
