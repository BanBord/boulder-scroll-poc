"""Align video frames to a reference still with OpenCV ECC (Euclidean motion).

ECC runs at half resolution for speed; the estimated translation is scaled
back to full resolution. Frames whose ECC correlation is below min_cc are
passed through unchanged (identity), so a bad estimate never moves a frame.
"""

from typing import Optional, Tuple

import cv2
import numpy as np

ECC_SCALE = 2          # estimate at 1/2 resolution
MIN_CC = 0.5           # below this correlation the frame stays unwarped
ECC_ITERS = 200
ECC_EPS = 1e-6


def reference_gray(ref_rgb: np.ndarray) -> np.ndarray:
    """Half-resolution, blurred grey template used for ECC."""
    gray = cv2.cvtColor(ref_rgb, cv2.COLOR_RGB2GRAY) if ref_rgb.ndim == 3 else ref_rgb
    small = cv2.resize(gray, (gray.shape[1] // ECC_SCALE, gray.shape[0] // ECC_SCALE),
                       interpolation=cv2.INTER_AREA).astype(np.float32)
    return cv2.GaussianBlur(small, (5, 5), 0)


def _prep(gray: np.ndarray) -> np.ndarray:
    small = cv2.resize(gray, (gray.shape[1] // ECC_SCALE, gray.shape[0] // ECC_SCALE),
                       interpolation=cv2.INTER_AREA).astype(np.float32)
    return cv2.GaussianBlur(small, (5, 5), 0)


def ecc_input_mask(shape: Tuple[int, int], exclude: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
    """Half-resolution uint8 mask (1 = use for ECC). exclude = (x0, y0, x1, y1) full-res box to ignore."""
    h, w = shape[0] // ECC_SCALE, shape[1] // ECC_SCALE
    mask = np.ones((h, w), np.uint8)
    if exclude is not None:
        x0, y0, x1, y1 = (v // ECC_SCALE for v in exclude)
        mask[y0:y1, x0:x1] = 0
    return mask


def estimate_warp(ref_small: np.ndarray, frame_rgb: np.ndarray, mask_small: np.ndarray) -> Tuple[np.ndarray, float]:
    """Return (2x3 full-resolution warp, ECC correlation). Identity on failure."""
    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, ECC_ITERS, ECC_EPS)
    try:
        cc, warp = cv2.findTransformECC(ref_small, _prep(gray), warp, cv2.MOTION_EUCLIDEAN,
                                        criteria, mask_small, 5)
    except cv2.error:
        return np.eye(2, 3, dtype=np.float32), -1.0
    full = warp.copy()
    full[0, 2] *= ECC_SCALE
    full[1, 2] *= ECC_SCALE
    return full, float(cc)


def apply_warp(frame_rgb: np.ndarray, warp: np.ndarray) -> np.ndarray:
    """Warp so that the output lines up with the reference used for ECC."""
    h, w = frame_rgb.shape[:2]
    return cv2.warpAffine(frame_rgb, warp, (w, h),
                          flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def stabilise_frame(frame_rgb: np.ndarray, ref_small: np.ndarray, mask_small: np.ndarray,
                    min_cc: float = MIN_CC) -> Tuple[np.ndarray, np.ndarray, float]:
    """Return (aligned frame, warp used, ECC correlation)."""
    warp, cc = estimate_warp(ref_small, frame_rgb, mask_small)
    if cc < min_cc:
        warp = np.eye(2, 3, dtype=np.float32)
    return apply_warp(frame_rgb, warp), warp, cc
