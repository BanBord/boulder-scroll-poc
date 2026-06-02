import cv2
import numpy as np


def smooth_position(
    new_pos: tuple[float, float],
    prev_pos: tuple[float, float],
    alpha: float = 0.15,
) -> tuple[float, float]:
    """Exponential moving average — higher alpha = more reactive."""
    return (
        alpha * new_pos[0] + (1 - alpha) * prev_pos[0],
        alpha * new_pos[1] + (1 - alpha) * prev_pos[1],
    )


def _extract_region(frame: np.ndarray, cx: float, cy: float, rw: int, rh: int) -> np.ndarray:
    """Cut a rw×rh region centred on (cx,cy), padding with black as needed."""
    h, w = frame.shape[:2]
    half_w, half_h = rw // 2, rh // 2

    x1, y1 = int(round(cx)) - half_w, int(round(cy)) - half_h
    x2, y2 = x1 + rw, y1 + rh

    pad_left   = max(0, -x1)
    pad_top    = max(0, -y1)
    pad_right  = max(0, x2 - w)
    pad_bottom = max(0, y2 - h)

    patch = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]

    if pad_left or pad_top or pad_right or pad_bottom:
        patch = cv2.copyMakeBorder(
            patch, pad_top, pad_bottom, pad_left, pad_right,
            cv2.BORDER_CONSTANT, value=(0, 0, 0),
        )

    return patch


def crop_fixed(
    frame: np.ndarray,
    cx: float,
    cy: float,
    crop_w: int,
    crop_h: int,
    out_w: int,
    out_h: int,
) -> np.ndarray:
    """
    Crop a fixed crop_w×crop_h region centred on (cx,cy), then resize to (out_w,out_h).
    Constant focal length: only position changes, never the crop dimensions.
    """
    patch = _extract_region(frame, cx, cy, crop_w, crop_h)
    if patch.shape[1] != out_w or patch.shape[0] != out_h:
        patch = cv2.resize(patch, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    return patch


def transform_keypoints(
    keypoints: np.ndarray,   # (17, 2) source coords
    cx: float,
    cy: float,
    crop_w: int,
    crop_h: int,
    out_w: int,
    out_h: int,
) -> np.ndarray:
    """
    Map YOLO keypoints from source-frame coords to output-frame coords,
    matching the same crop window used by crop_fixed().
    """
    x1 = cx - crop_w / 2
    y1 = cy - crop_h / 2
    sx = out_w / crop_w
    sy = out_h / crop_h
    out = keypoints.copy().astype(float)
    out[:, 0] = (keypoints[:, 0] - x1) * sx
    out[:, 1] = (keypoints[:, 1] - y1) * sy
    return out


def crop_centered(
    frame: np.ndarray,
    cx: float,
    cy: float,
    out_w: int,
    out_h: int,
) -> np.ndarray:
    """Fallback: crop fixed out_w×out_h centred on (cx, cy), no zoom."""
    patch = _extract_region(frame, cx, cy, out_w, out_h)
    if patch.shape[1] != out_w or patch.shape[0] != out_h:
        patch = cv2.resize(patch, (out_w, out_h))
    return patch
