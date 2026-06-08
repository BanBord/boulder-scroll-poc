import numpy as np
from typing import Dict, List, Optional

# COCO keypoint indices for limb endpoints
LIMBS: Dict[str, int] = {
    "LH": 9,   # left wrist
    "RH": 10,  # right wrist
    "LF": 15,  # left ankle
    "RF": 16,  # right ankle
}

_CONF_THRESH = 0.2


def check_contacts(
    keypoints: Optional[np.ndarray],  # (17, 2) source-frame coords
    kp_conf: Optional[np.ndarray],    # (17,)
    holds: List[Dict],
) -> Dict[str, Optional[int]]:
    """
    Returns {limb: hold_id or None} for each of LH/RH/LF/RF.
    Contact = keypoint pixel lies inside the hold's SAM mask.
    All coordinates are in source-frame space.
    """
    result: Dict[str, Optional[int]] = {limb: None for limb in LIMBS}
    if keypoints is None or kp_conf is None or not holds:
        return result

    mask_h, mask_w = holds[0]["mask"].shape

    for limb, kp_idx in LIMBS.items():
        if kp_conf[kp_idx] < _CONF_THRESH:
            continue
        x = int(round(keypoints[kp_idx, 0]))
        y = int(round(keypoints[kp_idx, 1]))
        if not (0 <= x < mask_w and 0 <= y < mask_h):
            continue
        for hold in holds:
            if hold["mask"][y, x]:
                result[limb] = hold["id"]
                break

    return result


def check_contacts_distance(
    keypoints: Optional[np.ndarray],  # (17, 2) source-frame coords
    kp_conf: Optional[np.ndarray],    # (17,)
    route_holds: List[Dict],          # [{id, x, y, r}, ...] pre-saved holds
) -> Dict[str, Optional[int]]:
    """Distance-based contact for pre-saved route holds (no SAM masks needed)."""
    result: Dict[str, Optional[int]] = {limb: None for limb in LIMBS}
    if keypoints is None or kp_conf is None or not route_holds:
        return result

    for limb, kp_idx in LIMBS.items():
        if kp_conf[kp_idx] < _CONF_THRESH:
            continue
        kx = float(keypoints[kp_idx, 0])
        ky = float(keypoints[kp_idx, 1])
        for hold in route_holds:
            dist = ((kx - hold["x"]) ** 2 + (ky - hold["y"]) ** 2) ** 0.5
            if dist <= hold["r"]:
                result[limb] = hold["id"]
                break

    return result
