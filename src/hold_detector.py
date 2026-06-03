import os
import subprocess
import cv2
import numpy as np
from typing import List, Dict

_CHECKPOINT_URL  = "https://github.com/ChaoningZhang/MobileSAM/releases/download/v1.0/mobile_sam.pt"
_CHECKPOINT_PATH = os.path.expanduser("~/.cache/mobile_sam/mobile_sam.pt")
_HF_REPO         = "dhkim2810/MobileSAM"

# ── Green HSV thresholds (OpenCV: H 0-179, S/V 0-255) ────────────────────────
_H_MIN, _H_MAX = 35, 105
_S_MIN         = 22
_V_MIN, _V_MAX = 30, 220
_MIN_AREA      = 200    # px²
_MAX_AREA_FRAC = 0.05   # ignore segments > 5% of frame (floor, wall panels)

# IOU threshold: SAM mask and HSV blob are "same hold" if overlap > this
_IOU_MERGE = 0.3


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


def _green_mask(frame_hsv: np.ndarray) -> np.ndarray:
    """Binary mask of green pixels via HSV thresholding."""
    lo = np.array([_H_MIN, _S_MIN, _V_MIN], dtype=np.uint8)
    hi = np.array([_H_MAX, _S_MIN * 10, _V_MAX], dtype=np.uint8)  # S upper = 255
    hi[1] = 255
    mask = cv2.inRange(frame_hsv, lo, hi)
    # Morphological cleanup
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=1)
    return mask


def _hsv_holds(frame: np.ndarray, frame_area: int) -> List[Dict]:
    """Fallback: find green holds via HSV contours."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    binary = _green_mask(hsv)
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    holds = []
    h_img, w_img = frame.shape[:2]
    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if area < _MIN_AREA or area > frame_area * _MAX_AREA_FRAC:
            continue
        mask = np.zeros((h_img, w_img), dtype=bool)
        cv2.drawContours(mask.view(np.uint8) * 0 + 0, [cnt], -1, 1, -1)
        # rebuild properly
        m = np.zeros((h_img, w_img), dtype=np.uint8)
        cv2.drawContours(m, [cnt], -1, 255, -1)
        mask = m.astype(bool)
        x, y, w, hh = cv2.boundingRect(cnt)
        cx, cy = x + w / 2, y + hh / 2
        holds.append({"mask": mask, "center": (float(cx), float(cy)),
                      "bbox": (int(x), int(y), int(w), int(hh)), "source": "hsv"})
    return holds


def _is_green_segment(seg: np.ndarray, frame_hsv: np.ndarray, frame_area: int) -> bool:
    area = int(seg.sum())
    if area < _MIN_AREA or area > frame_area * _MAX_AREA_FRAC:
        return False
    pixels = frame_hsv[seg]
    h = np.median(pixels[:, 0])
    s = np.median(pixels[:, 1])
    v = np.median(pixels[:, 2])
    return (_H_MIN <= h <= _H_MAX and s >= _S_MIN and _V_MIN <= v <= _V_MAX)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / float(union) if union > 0 else 0.0


def detect_holds(reference_frame: np.ndarray) -> List[Dict]:
    """
    Hybrid SAM + HSV hold detector.
    SAM provides high-quality masks; HSV fills in holds SAM misses.
    Returns list of hold dicts: {id, mask (H×W bool), center (x,y), bbox, source}.
    """
    from mobile_sam import sam_model_registry, SamAutomaticMaskGenerator

    h_img, w_img = reference_frame.shape[:2]
    frame_area = h_img * w_img
    frame_hsv = cv2.cvtColor(reference_frame, cv2.COLOR_BGR2HSV)

    # ── SAM pass ──────────────────────────────────────────────────────────────
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
        if _is_green_segment(seg, frame_hsv, frame_area):
            x, y, w, hh = m["bbox"]
            sam_holds.append({
                "mask":   seg,
                "center": (float(x + w / 2), float(y + hh / 2)),
                "bbox":   (int(x), int(y), int(w), int(hh)),
                "source": "sam",
            })

    print(f"SAM green holds: {len(sam_holds)}")

    # ── HSV fallback pass ─────────────────────────────────────────────────────
    hsv_candidates = _hsv_holds(reference_frame, frame_area)
    print(f"HSV candidates:  {len(hsv_candidates)}")

    # Add HSV hold only if it doesn't overlap with any SAM hold (IoU < threshold)
    added = 0
    for hc in hsv_candidates:
        covered = any(_iou(hc["mask"], sh["mask"]) >= _IOU_MERGE for sh in sam_holds)
        if not covered:
            sam_holds.append(hc)
            added += 1

    print(f"HSV added {added} extra holds")

    # ── Assign sequential IDs sorted top→bottom ───────────────────────────────
    sam_holds.sort(key=lambda h: h["center"][1])
    for i, h in enumerate(sam_holds):
        h["id"] = i

    print(f"Total holds detected: {len(sam_holds)}")
    return sam_holds
