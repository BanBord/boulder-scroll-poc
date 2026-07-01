"""Per-image preprocessing before hold detection / colour extraction."""

import cv2
import numpy as np

# % of pixels per channel, per side, clipped to the true black/white point.
_CLIP_PERCENT = 1.0

# Mean-shift region flattening: sp = spatial window radius (px),
# sr = colour-space window radius. Tuned against a real wall photo so the
# wall's speckle texture and floor mostly flatten out while hold-vs-wall
# colour edges stay sharp.
_MEANSHIFT_SPATIAL_RADIUS = 20
_MEANSHIFT_COLOR_RADIUS = 40


def stretch_contrast(frame_bgr: np.ndarray, clip_percent: float = _CLIP_PERCENT) -> np.ndarray:
    """Per-channel percentile contrast stretch ("simplest color balance").

    Clips the darkest/brightest `clip_percent`% of each B/G/R channel to the
    true black/white point, then linearly rescales the rest to 0-255. Boosts
    saturation as a side effect since channels compressed toward grey by weak
    lighting spread back out independently.
    """
    out = frame_bgr.astype(np.float32)
    for c in range(3):
        ch = out[:, :, c]
        lo, hi = np.percentile(ch, [clip_percent, 100 - clip_percent])
        if hi - lo < 1e-6:
            continue  # solid/degenerate channel: no-op, avoids div-by-zero
        ch[:] = np.clip((ch - lo) * (255.0 / (hi - lo)), 0, 255)
    return out.astype(np.uint8)


def flatten_regions(frame_bgr: np.ndarray,
                    spatial_radius: int = _MEANSHIFT_SPATIAL_RADIUS,
                    color_radius: int = _MEANSHIFT_COLOR_RADIUS) -> np.ndarray:
    """Mean-shift colour-region flattening ("acceptable zero" before segmentation).

    Smooths out small-scale texture/noise (wall speckle, floor grain) within
    each colour region while preserving the edges between differently
    coloured regions (e.g. hold vs. wall), so the wall reads as a near-flat
    surface and each hold stays a clean, distinct colour blob.
    """
    return cv2.pyrMeanShiftFiltering(frame_bgr, sp=spatial_radius, sr=color_radius)
