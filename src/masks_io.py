"""Read hold masks from a COCO JSON file (RLE segmentation) and build label maps.

Only the masks for one image are decoded. Both compressed RLE (string counts)
and uncompressed RLE (list counts) are supported.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from pycocotools import mask as mask_util


@dataclass
class Hold:
    """One annotated hold on a single image."""

    id: int
    mask: np.ndarray                      # bool, HxW
    bbox: Tuple[float, float, float, float]  # x, y, w, h
    centroid: Tuple[float, float]         # centre of the largest component
    color: Optional[str]
    score: Optional[float]
    role: Optional[str]


def _decode_segmentation(seg: Dict[str, Any]) -> np.ndarray:
    """Decode a COCO RLE dict (compressed string or uncompressed list) to bool HxW."""
    h, w = seg["size"]
    if isinstance(seg["counts"], list):
        rle = mask_util.frPyObjects(seg, h, w)
    else:
        rle = {"size": [h, w], "counts": seg["counts"].encode("ascii")}
    return mask_util.decode(rle).astype(bool)


def _largest_component_centroid(mask: np.ndarray) -> Optional[Tuple[float, float]]:
    """Centroid (x, y) of the largest 8-connected component, or None if empty."""
    if not mask.any():
        return None
    n, _, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    cx, cy = centroids[largest]
    return float(cx), float(cy)


def _mask_bbox(mask: np.ndarray) -> Tuple[float, float, float, float]:
    ys, xs = np.nonzero(mask)
    x0, y0 = int(xs.min()), int(ys.min())
    return float(x0), float(y0), float(xs.max() - x0 + 1), float(ys.max() - y0 + 1)


def load_holds(coco_path: str, image_name: str) -> List[Hold]:
    """Return all holds annotated on the image whose file_name equals image_name."""
    with open(coco_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    image_id = None
    for img in data.get("images", []):
        if img.get("file_name") == image_name:
            image_id = img["id"]
            break
    if image_id is None:
        raise ValueError(f"image '{image_name}' is not in {coco_path}")

    holds: List[Hold] = []
    for ann in data.get("annotations", []):
        if ann.get("image_id") != image_id:
            continue
        mask = _decode_segmentation(ann["segmentation"])
        centroid = _largest_component_centroid(mask)
        if centroid is None:
            centroid = (float(ann["bbox"][0]) + ann["bbox"][2] / 2,
                        float(ann["bbox"][1]) + ann["bbox"][3] / 2) if "bbox" in ann else (0.0, 0.0)
        bbox = tuple(float(v) for v in ann["bbox"]) if "bbox" in ann else _mask_bbox(mask)
        holds.append(Hold(
            id=int(ann["id"]),
            mask=mask,
            bbox=bbox,
            centroid=centroid,
            color=ann.get("color"),
            score=float(ann["score"]) if ann.get("score") is not None else None,
            role=ann.get("role"),
        ))
    return holds


def label_map(holds: List[Hold], shape: Tuple[int, int]) -> np.ndarray:
    """int32 map: 0 = no hold, otherwise the hold id. Earlier holds win on overlap."""
    out = np.zeros(shape, dtype=np.int32)
    for hold in holds:
        if hold.mask.shape != tuple(shape):
            raise ValueError(f"hold {hold.id} mask {hold.mask.shape} != label map {tuple(shape)}")
        out[hold.mask & (out == 0)] = hold.id
    return out
