"""Unit tests for src/preprocess.py."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.preprocess import stretch_contrast, flatten_regions


def _solid_color_image(shape, bgr):
    img = np.zeros((*shape, 3), dtype=np.uint8)
    img[:] = bgr
    return img


def test_stretch_solid_color_is_noop():
    img = _solid_color_image((20, 20), (120, 60, 200))
    out = stretch_contrast(img)
    assert np.array_equal(out, img)


def test_stretch_low_contrast_gradient_expands_range():
    row = np.linspace(100, 140, 50, dtype=np.uint8)
    img = np.tile(row[None, :], (50, 1))
    img = np.stack([img, img, img], axis=-1)
    out = stretch_contrast(img)
    assert out.min() < 10
    assert out.max() > 245


def test_stretch_outlier_pixel_does_not_dominate():
    # 1 stray pixel out of 2500 (0.04%) is below the 1% clip threshold, so it
    # must not be treated as the true white point — a naive min/max stretch
    # would blow the whole (otherwise uniform) image out to 0-255 because of
    # this single pixel; the percentile clip should leave the bulk untouched.
    img = np.full((50, 50, 3), 110, dtype=np.uint8)
    img[0, 0] = 255
    out = stretch_contrast(img)
    bulk = out[1:, 1:]
    assert bulk.min() == bulk.max() == 110


def test_stretch_already_full_range_stays_in_bounds():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, size=(30, 30, 3), dtype=np.uint8)
    out = stretch_contrast(img)
    assert out.min() >= 0
    assert out.max() <= 255


def test_stretch_output_dtype_and_shape():
    img = _solid_color_image((15, 25), (10, 20, 30))
    out = stretch_contrast(img)
    assert out.dtype == np.uint8
    assert out.shape == img.shape


# ── flatten_regions ─────────────────────────────────────────────────────────

def test_flatten_solid_color_is_noop():
    img = _solid_color_image((40, 40), (120, 60, 200))
    out = flatten_regions(img)
    assert np.array_equal(out, img)


def test_flatten_smooths_speckle_noise_within_a_region():
    rng = np.random.default_rng(0)
    base = np.full((60, 60, 3), 150, dtype=np.uint8)
    speckle = rng.integers(-15, 16, size=base.shape)
    noisy = np.clip(base.astype(int) + speckle, 0, 255).astype(np.uint8)
    out = flatten_regions(noisy)
    assert out.astype(np.int16).std() < noisy.astype(np.int16).std()


def test_flatten_preserves_a_sharp_colour_boundary():
    img = _solid_color_image((60, 60), (200, 30, 30))  # blue-ish block
    img[:, 30:] = (30, 30, 200)  # red-ish block, right half
    out = flatten_regions(img)
    left = out[:, :10].reshape(-1, 3).astype(np.int16)
    right = out[:, -10:].reshape(-1, 3).astype(np.int16)
    # Each side should stay close to its own original colour, not bleed into
    # an averaged colour in between.
    assert np.abs(left.mean(axis=0) - (200, 30, 30)).max() < 20
    assert np.abs(right.mean(axis=0) - (30, 30, 200)).max() < 20


def test_flatten_output_dtype_and_shape():
    img = _solid_color_image((15, 25), (10, 20, 30))
    out = flatten_regions(img)
    assert out.dtype == np.uint8
    assert out.shape == img.shape
