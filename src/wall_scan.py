"""Wall scan: detect all holds in a single image; emit tags and a routes hint.

Pipeline:
    image → MobileSAM masks (single pass, points_per_side=48)
          → hold filter + tag filter (fan-out from same segments)
          → per-hold Lab colour + kNN neighbours
          → JSON payload

Output schema (see ``scan()``):
    {
        "image":       "<path>",
        "image_size":  [W, H],
        "holds":       [{id, polygon, bbox, center, color_hex, color_lab,
                         neighbors}, ...],
        "tags":        [{id, bbox, center, nearest_hold_id}, ...],
        "routes_hint": {"count": <int>}
    }

Start/top selection has moved to the client; ``route_id`` and ``role`` are gone.
"""

import json
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# Lab-space distance threshold for "same route" (perceptually ≈ JND of 2.3,
# but route paints differ enough that 18 keeps holds of the same colour together
# while still separating e.g. red from orange).
_LAB_CLUSTER_EPS = 18.0
_MIN_HOLDS_PER_ROUTE = 3

# A hold whose extracted Lab colour has chroma below this value is treated as
# grey / wall fragment (rejected from any route, kept as noise).
_MIN_CHROMA = 14.0


# ── Per-hold colour ─────────────────────────────────────────────────────────

def extract_hold_color(frame_bgr: np.ndarray, mask: np.ndarray,
                       erode_px: int = 3,
                       chroma_top_frac: float = 0.3) -> Tuple[float, float, float]:
    """Median Lab colour inside the mask, biased toward chromatic pixels.

    Coloured climbing holds sit on grey walls — SAM masks often leak into
    shadow / wall pixels along the hold's silhouette, which drags a plain
    median toward the wall colour. To counter that we keep only the pixels
    with above-median chroma (distance from the neutral axis a=b=128 in
    OpenCV's Lab encoding) and take the median over that subset.

    chroma_top_frac:
        Keep the top fraction of pixels by chroma before computing the
        median. 0.5 retains the saturated half; lower for stricter bias
        toward the hold body, higher to mix in neutrals.

    Erodes the mask by ``erode_px`` first so the contour boundary doesn't
    contaminate the sample.
    """
    bin_u8 = (mask.astype(np.uint8) * 255) if mask.dtype != np.uint8 else mask
    if erode_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1,) * 2)
        eroded = cv2.erode(bin_u8, k, iterations=1)
        if eroded.sum() > 0:
            bin_u8 = eroded
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    sel = bin_u8.astype(bool)
    pixels = lab[sel]
    if pixels.size == 0:
        return (0.0, 128.0, 128.0)

    # Chroma = distance from neutral grey axis. Keep the top `chroma_top_frac`
    # of pixels so wall/shadow pixels (chroma ~ 0) drop out of the median.
    chroma = np.sqrt((pixels[:, 1].astype(np.float32) - 128.0) ** 2 +
                     (pixels[:, 2].astype(np.float32) - 128.0) ** 2)
    if pixels.shape[0] > 4 and 0 < chroma_top_frac < 1:
        thr = np.quantile(chroma, 1.0 - chroma_top_frac)
        keep = chroma >= thr
        if keep.sum() >= 4:
            pixels = pixels[keep]

    # For L (luminance): take the brighter half. Hold bodies are lit; shadows
    # are dark. Median over the upper half lifts the result away from shadow.
    L_vals = pixels[:, 0]
    if L_vals.size > 4:
        L_thr = np.quantile(L_vals, 0.5)
        L_bright = L_vals[L_vals >= L_thr]
        L = float(np.median(L_bright))
    else:
        L = float(np.median(L_vals))
    a = float(np.median(pixels[:, 1]))
    b = float(np.median(pixels[:, 2]))
    return (L, a, b)


def _chroma(lab) -> float:
    """Distance from the neutral grey axis in OpenCV's Lab encoding."""
    return float(np.sqrt((lab[1] - 128.0) ** 2 + (lab[2] - 128.0) ** 2))


# Tag filter thresholds (see spec).
_TAG_AREA_FRAC_MIN = 0.0005
_TAG_AREA_FRAC_MAX = 0.005
_TAG_ASPECT_MIN    = 1.5
_TAG_ASPECT_MAX    = 5.0
_TAG_CHROMA_MAX    = 12.0
_TAG_L_MIN         = 140.0
_TAG_HOLD_DIST_FRAC = 0.04


def _passes_tag_filter(seg_bool: np.ndarray,
                       bbox: Tuple[int, int, int, int],
                       frame_bgr: np.ndarray,
                       nearest_hold_dist_px: Optional[float],
                       image_diag_px: float) -> bool:
    """A SAM segment is a Start/Top tag if all of:

    - Area within [TAG_AREA_FRAC_MIN, TAG_AREA_FRAC_MAX] of the frame
    - Bounding-box aspect (w/h) within [TAG_ASPECT_MIN, TAG_ASPECT_MAX]
    - Median Lab chroma ≤ TAG_CHROMA_MAX (white/grey paper, not coloured)
    - Median Lab L ≥ TAG_L_MIN (excludes wall dots, dark shadows)
    - Centre within TAG_HOLD_DIST_FRAC × image_diag of the nearest hold

    nearest_hold_dist_px = None means no holds in the scene → reject.
    """
    if nearest_hold_dist_px is None:
        return False
    h_img, w_img = frame_bgr.shape[:2]
    frame_area = float(h_img * w_img)

    _, _, w, h = bbox
    if w <= 0 or h <= 0:
        return False

    area = float(seg_bool.sum())
    area_frac = area / frame_area
    if not (_TAG_AREA_FRAC_MIN <= area_frac <= _TAG_AREA_FRAC_MAX):
        return False

    aspect = float(w) / float(h)
    if not (_TAG_ASPECT_MIN <= aspect <= _TAG_ASPECT_MAX):
        return False

    if nearest_hold_dist_px > _TAG_HOLD_DIST_FRAC * image_diag_px:
        return False

    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    pixels = lab[seg_bool]
    if pixels.size == 0:
        return False
    L = float(np.median(pixels[:, 0]))
    a = float(np.median(pixels[:, 1]))
    b = float(np.median(pixels[:, 2]))
    if L < _TAG_L_MIN:
        return False
    if _chroma((L, a, b)) > _TAG_CHROMA_MAX:
        return False
    return True


def detect_tags(segments: List[Dict], holds: List[Dict],
                frame_bgr: np.ndarray) -> List[Dict]:
    """Walk SAM segments, classify Start/Top tags, attach nearest hold.

    Returns ``[{id, bbox, center, nearest_hold_id}]``. IDs sequential.
    Empty list when no holds were detected (no anchor for nearest-hold check).
    """
    if not holds:
        return []

    h_img, w_img = frame_bgr.shape[:2]
    diag = float(np.sqrt(w_img * w_img + h_img * h_img))
    hold_centres = np.array([h["center"] for h in holds], dtype=np.float32)
    hold_ids     = [h["id"] for h in holds]

    tags = []
    for m in segments:
        seg = m["segmentation"].astype(bool)
        x, y, w, hh = m["bbox"]
        bbox = (int(x), int(y), int(w), int(hh))
        cx, cy = float(x + w / 2.0), float(y + hh / 2.0)

        d = np.linalg.norm(hold_centres - np.array([cx, cy], dtype=np.float32), axis=1)
        nearest_idx = int(np.argmin(d))
        nearest_dist = float(d[nearest_idx])

        if not _passes_tag_filter(seg, bbox, frame_bgr,
                                  nearest_hold_dist_px=nearest_dist,
                                  image_diag_px=diag):
            continue
        tags.append({
            "id":              len(tags),
            "bbox":            [bbox[0], bbox[1], bbox[2], bbox[3]],
            "center":          [cx, cy],
            "nearest_hold_id": int(hold_ids[nearest_idx]),
        })
    return tags


def compute_hold_neighbors(holds: List[Dict], k: int = 8) -> List[List[int]]:
    """For each hold, return the k closest hold IDs by centre Euclidean
    distance. Ties broken by ascending id.

    Output[i] excludes i itself. Length min(k, len(holds) - 1).
    """
    if not holds:
        return []
    centres = np.array([h["center"] for h in holds], dtype=np.float32)
    ids     = [int(h["id"]) for h in holds]
    n = len(holds)
    out: List[List[int]] = []
    for i in range(n):
        d = np.linalg.norm(centres - centres[i], axis=1)
        # Sort by (distance, id) to break ties deterministically.
        order = sorted(
            (j for j in range(n) if j != i),
            key=lambda j: (float(d[j]), ids[j]),
        )
        out.append([ids[j] for j in order[:k]])
    return out


def _lab_to_hex(lab: Tuple[float, float, float]) -> str:
    """OpenCV-encoded Lab (L: 0..255, a/b: 0..255 offset 128) → sRGB hex."""
    lab_u8 = np.array([[[int(round(lab[0])), int(round(lab[1])), int(round(lab[2]))]]],
                      dtype=np.uint8)
    bgr = cv2.cvtColor(lab_u8, cv2.COLOR_LAB2BGR)[0, 0]
    r, g, b = int(bgr[2]), int(bgr[1]), int(bgr[0])
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Module-level constants for the new pipeline ───────────────────────────

_SAM_POINTS_PER_SIDE = 48
_ROUTES_HINT_MIN_HOLDS = _MIN_HOLDS_PER_ROUTE


# ── Orchestrator ───────────────────────────────────────────────────────────

def assemble_scan_payload(*, image_path: str, image_size: Tuple[int, int],
                          holds_internal: List[Dict],
                          tags: List[Dict],
                          per_hold_color_lab: List[Tuple[float, float, float]],
                          neighbors: List[List[int]],
                          routes_hint_count: int) -> Dict:
    """Build the wall_scan JSON dict.

    Pure function: takes already-extracted features, returns the payload.
    Drops the internal ``mask`` field; emits exactly the spec's schema.
    """
    w_img, h_img = image_size
    holds_out = []
    for h, lab, nb in zip(holds_internal, per_hold_color_lab, neighbors):
        holds_out.append({
            "id":        int(h["id"]),
            "polygon":   [[float(x), float(y)] for x, y in h["polygon"]],
            "bbox":      [int(v) for v in h["bbox"]],
            "center":    [float(h["center"][0]), float(h["center"][1])],
            "color_hex": _lab_to_hex(lab),
            "color_lab": [round(lab[0], 1), round(lab[1], 1), round(lab[2], 1)],
            "neighbors": [int(j) for j in nb],
        })
    return {
        "image":       image_path,
        "image_size":  [int(w_img), int(h_img)],
        "holds":       holds_out,
        "tags":        tags,
        "routes_hint": {"count": int(routes_hint_count)},
    }


def scan(image_path: str, *, mat_zone_frac: float = 1.0,
         points_per_side: int = _SAM_POINTS_PER_SIDE) -> Dict:
    """Run the full wall scan on a single image."""
    from .hold_detector import run_sam_segments, filter_as_holds

    frame = cv2.imread(image_path)
    if frame is None:
        raise RuntimeError(f"cannot read image: {image_path}")
    h_img, w_img = frame.shape[:2]

    segments = run_sam_segments(frame, points_per_side=points_per_side)
    holds = filter_as_holds(segments, frame, color_filter=None,
                            mat_zone_frac=mat_zone_frac)
    tags  = detect_tags(segments, holds, frame)
    print(f"Holds: {len(holds)}  Tags: {len(tags)}")

    per_hold_lab = [extract_hold_color(frame, h["mask"]) for h in holds]
    chromatic_count = sum(1 for lab in per_hold_lab if _chroma(lab) >= _MIN_CHROMA)
    routes_hint_count = max(1, chromatic_count // _ROUTES_HINT_MIN_HOLDS)

    neighbors = compute_hold_neighbors(holds, k=8)

    return assemble_scan_payload(
        image_path=os.path.abspath(image_path),
        image_size=(w_img, h_img),
        holds_internal=holds,
        tags=tags,
        per_hold_color_lab=per_hold_lab,
        neighbors=neighbors,
        routes_hint_count=routes_hint_count,
    )


def write_scan_json(scan_dict: Dict, out_path: str) -> None:
    with open(out_path, "w") as f:
        json.dump(scan_dict, f, indent=2)


# ── Debug overlay ──────────────────────────────────────────────────────────

def draw_overlay(frame_bgr: np.ndarray, scan_dict: Dict) -> np.ndarray:
    """Draw all hold polygons in their per-hold colour, plus tag rectangles.

    No route grouping at this stage — colour-clustering is now the client's
    job. The overlay shows raw detection quality only.
    """
    out = frame_bgr.copy()
    h_img, w_img = frame_bgr.shape[:2]
    line_thickness = max(2, int(round(min(w_img, h_img) / 400)))
    tag_thickness  = max(2, line_thickness)

    for h in scan_dict["holds"]:
        poly = np.array(h["polygon"], dtype=np.int32)
        if len(poly) < 3:
            continue
        bgr = _hex_to_bgr(h["color_hex"])
        cv2.polylines(out, [poly], isClosed=True, color=bgr,
                      thickness=line_thickness, lineType=cv2.LINE_AA)

    for t in scan_dict["tags"]:
        x, y, w, hh = t["bbox"]
        cv2.rectangle(out, (x, y), (x + w, y + hh),
                      (0, 220, 255), tag_thickness, lineType=cv2.LINE_AA)

    return out


def _hex_to_bgr(hex_: str) -> Tuple[int, int, int]:
    hex_ = hex_.lstrip("#")
    r = int(hex_[0:2], 16); g = int(hex_[2:4], 16); b = int(hex_[4:6], 16)
    return (b, g, r)
