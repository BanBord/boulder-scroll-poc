"""Wall scan: detect all holds in a single image, group by colour into routes,
assign start/top within each route.

Pipeline:
    image → MobileSAM masks → per-hold Lab colour → single-link cluster
    in Lab-space → routes → bottom-cluster heuristic for start/top → JSON.

Output schema (see ``scan()``):
    {
        "image":      "<path>",
        "image_size": [W, H],
        "holds":      [{id, polygon, bbox, center, color_hex, color_lab,
                        route_id, role}, ...],
        "routes":     [{id, hex, hold_count, hold_ids, start_hold_ids,
                        top_hold_id}, ...]
    }

The renderer in ``viewer/scan.html`` reads this JSON; the per-hold ``role``
field drives the start/top outer ring.
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

# Start/top heuristic windows
_DOUBLE_START_Y_FRAC = 0.12   # 2nd start hold must be within 12 % of image height
_DOUBLE_START_X_FRAC = 0.25   # …and within 25 % of image width horizontally


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


# ── Colour clustering → routes ─────────────────────────────────────────────

def _lab_dist(p: Tuple[float, float, float], q: Tuple[float, float, float]) -> float:
    dl = p[0] - q[0]; da = p[1] - q[1]; db = p[2] - q[2]
    return float(np.sqrt(dl * dl + da * da + db * db))


def cluster_routes(holds: List[Dict], *, eps: float = _LAB_CLUSTER_EPS,
                   min_samples: int = _MIN_HOLDS_PER_ROUTE) -> List[Dict]:
    """Greedy single-link clustering of holds by Lab colour.

    Each hold dict must carry ``color_lab``. Routes shorter than
    ``min_samples`` are dropped (their holds keep ``route_id = None``).

    Returns a list of route dicts: ``{id, lab_center, hex, hold_ids}``.
    Routes are numbered 0..N in descending size order so route 0 is the
    largest cluster (visually the most prominent route on the wall).
    """
    proto: List[Dict] = []  # each: {lab_sum, count, hold_ids}
    for h in holds:
        lab = h["color_lab"]
        best_idx = -1
        best_d = eps
        for i, c in enumerate(proto):
            center = (c["lab_sum"][0] / c["count"],
                      c["lab_sum"][1] / c["count"],
                      c["lab_sum"][2] / c["count"])
            d = _lab_dist(lab, center)
            if d < best_d:
                best_d = d
                best_idx = i
        if best_idx >= 0:
            c = proto[best_idx]
            c["lab_sum"] = (c["lab_sum"][0] + lab[0],
                            c["lab_sum"][1] + lab[1],
                            c["lab_sum"][2] + lab[2])
            c["count"] += 1
            c["hold_ids"].append(h["id"])
        else:
            proto.append({
                "lab_sum":  (lab[0], lab[1], lab[2]),
                "count":    1,
                "hold_ids": [h["id"]],
            })

    routes = []
    for c in proto:
        if c["count"] < min_samples:
            continue
        lab_center = (c["lab_sum"][0] / c["count"],
                      c["lab_sum"][1] / c["count"],
                      c["lab_sum"][2] / c["count"])
        routes.append({
            "lab_center": lab_center,
            "hex":        _lab_to_hex(lab_center),
            "hold_ids":   list(c["hold_ids"]),
        })

    routes.sort(key=lambda r: -len(r["hold_ids"]))
    for i, r in enumerate(routes):
        r["id"] = i
    return routes


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


# ── Start/Top heuristic ────────────────────────────────────────────────────

def assign_start_top(route_holds: List[Dict], image_h: int, image_w: int
                     ) -> Tuple[List[int], Optional[int]]:
    """Bottom-cluster heuristic for start, single-top heuristic for top.

    Inputs are the hold dicts that belong to one route (must carry ``center``
    and ``id``). Returns ``(start_hold_ids, top_hold_id)``:

    - top: hold with the smallest y (highest position on the wall)
    - start: hold with the largest y; if a second hold lies within
      ``_DOUBLE_START_Y_FRAC * image_h`` vertically AND within
      ``_DOUBLE_START_X_FRAC * image_w`` horizontally, it joins as a
      second start (two-hand start).
    - 1-hold route: returns ``([id], id)`` — same hold is both.
    """
    if not route_holds:
        return [], None

    if len(route_holds) == 1:
        only = int(route_holds[0]["id"])
        return [only], only

    sorted_by_y = sorted(route_holds, key=lambda h: h["center"][1])
    top_id = int(sorted_by_y[0]["id"])

    by_y_desc = list(reversed(sorted_by_y))
    bottom = by_y_desc[0]
    starts = [int(bottom["id"])]
    by, bx = bottom["center"][1], bottom["center"][0]
    dy_max = _DOUBLE_START_Y_FRAC * image_h
    dx_max = _DOUBLE_START_X_FRAC * image_w
    for h in by_y_desc[1:]:
        cy, cx = h["center"][1], h["center"][0]
        if (by - cy) <= dy_max and abs(cx - bx) <= dx_max:
            starts.append(int(h["id"]))
            break

    return starts, top_id


# ── Orchestrator ───────────────────────────────────────────────────────────

def scan(image_path: str, *,
         mat_zone_frac: float = 1.0,
         lab_eps: float = _LAB_CLUSTER_EPS,
         min_holds_per_route: int = _MIN_HOLDS_PER_ROUTE) -> Dict:
    """Run the full scan on a single image and return the wall_scan dict.

    ``mat_zone_frac`` defaults to 1.0 (no mat exclusion) because the scan use
    case explicitly cares about the start holds near the floor.
    """
    from .hold_detector import detect_holds  # lazy: SAM import is slow

    frame = cv2.imread(image_path)
    if frame is None:
        raise RuntimeError(f"cannot read image: {image_path}")
    h_img, w_img = frame.shape[:2]

    holds = detect_holds(frame, color_filter=None, mat_zone_frac=mat_zone_frac)

    holds_out = []
    for h in holds:
        lab = extract_hold_color(frame, h["mask"])
        holds_out.append({
            "id":        int(h["id"]),
            "polygon":   [[float(x), float(y)] for x, y in h["polygon"]],
            "bbox":      [int(v) for v in h["bbox"]],
            "center":    [float(h["center"][0]), float(h["center"][1])],
            "color_hex": _lab_to_hex(lab),
            "color_lab": [round(lab[0], 1), round(lab[1], 1), round(lab[2], 1)],
            "route_id":  None,
            "role":      "mid",
        })

    # Drop achromatic holds before clustering — they pollute every route by
    # binding loosely to whichever cluster they're closest to in Lab space.
    chromatic = [h for h in holds_out if _chroma(h["color_lab"]) >= _MIN_CHROMA]
    holds_for_cluster = [{"id": h["id"], "color_lab": tuple(h["color_lab"])} for h in chromatic]
    routes_raw = cluster_routes(holds_for_cluster, eps=lab_eps,
                                min_samples=min_holds_per_route)

    by_id = {h["id"]: h for h in holds_out}
    routes_out = []
    for r in routes_raw:
        route_holds = [by_id[hid] for hid in r["hold_ids"]]
        starts, top = assign_start_top(route_holds, h_img, w_img)
        for hid in r["hold_ids"]:
            by_id[hid]["route_id"] = r["id"]
            by_id[hid]["role"] = "mid"
        for sid in starts:
            by_id[sid]["role"] = "start"
        if top is not None:
            if top in starts:
                by_id[top]["role"] = "start_top"
            else:
                by_id[top]["role"] = "top"
        routes_out.append({
            "id":              r["id"],
            "hex":             r["hex"],
            "hold_count":      len(r["hold_ids"]),
            "hold_ids":        r["hold_ids"],
            "start_hold_ids":  starts,
            "top_hold_id":     top,
        })

    return {
        "image":      os.path.abspath(image_path),
        "image_size": [int(w_img), int(h_img)],
        "holds":      holds_out,
        "routes":     routes_out,
    }


def write_scan_json(scan_dict: Dict, out_path: str) -> None:
    with open(out_path, "w") as f:
        json.dump(scan_dict, f, indent=2)


# ── Debug overlay ──────────────────────────────────────────────────────────

def draw_overlay(frame_bgr: np.ndarray, scan_dict: Dict) -> np.ndarray:
    """Return a copy of the frame with all holds drawn in their route colours.

    Used by ``tools/scan_wall.py`` for a quick visual sanity check without
    spinning up the viewer.
    """
    out = frame_bgr.copy()
    h_img, w_img = frame_bgr.shape[:2]
    line_thickness = max(2, int(round(min(w_img, h_img) / 400)))
    ring_radius    = max(14, int(round(min(w_img, h_img) / 80)))
    ring_thickness = max(2, int(round(line_thickness * 1.5)))
    routes_by_id = {r["id"]: r for r in scan_dict["routes"]}
    for h in scan_dict["holds"]:
        poly = np.array(h["polygon"], dtype=np.int32)
        if len(poly) < 3:
            continue
        if h["route_id"] is None:
            color = (200, 200, 200)  # noise: grey
        else:
            hex_ = routes_by_id[h["route_id"]]["hex"]
            color = _hex_to_bgr(hex_)
        cv2.polylines(out, [poly], isClosed=True, color=color,
                      thickness=line_thickness, lineType=cv2.LINE_AA)
        cx, cy = int(h["center"][0]), int(h["center"][1])
        if h["role"] == "start":
            cv2.circle(out, (cx, cy), ring_radius, (153, 211, 52),
                       ring_thickness, lineType=cv2.LINE_AA)
        elif h["role"] == "top":
            cv2.circle(out, (cx, cy), ring_radius, (113, 113, 248),
                       ring_thickness, lineType=cv2.LINE_AA)
        elif h["role"] == "start_top":
            cv2.circle(out, (cx, cy), ring_radius, (160, 160, 248),
                       ring_thickness, lineType=cv2.LINE_AA)
    return out


def _hex_to_bgr(hex_: str) -> Tuple[int, int, int]:
    hex_ = hex_.lstrip("#")
    r = int(hex_[0:2], 16); g = int(hex_[2:4], 16); b = int(hex_[4:6], 16)
    return (b, g, r)
