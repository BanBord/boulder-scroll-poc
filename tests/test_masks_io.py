import json
import os
import sys

import numpy as np
import pytest

# Skip (not error) under interpreters without pycocotools, e.g. the system python3.
pytest.importorskip("pycocotools")
from pycocotools import mask as mask_util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.masks_io import Hold, label_map, load_holds

H, W = 12, 10


def _mask(rows, cols):
    m = np.zeros((H, W), dtype=bool)
    m[rows[0]:rows[1] + 1, cols[0]:cols[1] + 1] = True
    return m


def _rle_compressed(arr):
    rle = mask_util.encode(np.asfortranarray(arr.astype(np.uint8)))
    return {"size": [H, W], "counts": rle["counts"].decode("ascii")}


def _rle_uncompressed(arr):
    flat = arr.astype(np.uint8).flatten(order="F")
    runs, current, count = [], 0, 0
    for v in flat:
        if v == current:
            count += 1
        else:
            runs.append(count)
            current, count = int(v), 1
    runs.append(count)
    return {"size": [H, W], "counts": runs}


MASK_A = _mask((1, 3), (2, 5))             # rectangle, bbox (2, 1, 4, 3)
MASK_B = _mask((6, 8), (6, 8))             # rectangle, no bbox field in JSON
MASK_C = _mask((9, 10), (0, 3))            # block ...
MASK_C[0, 9] = True                        # ... plus a stray single pixel
MASK_E = _mask((4, 5), (7, 9))             # uncompressed counts list
MASK_D = _mask((0, 1), (0, 1))             # belongs to the other image


@pytest.fixture
def coco_path(tmp_path):
    data = {
        "images": [
            {"id": 1, "file_name": "wall.png", "width": W, "height": H},
            {"id": 2, "file_name": "other.png", "width": W, "height": H},
        ],
        "categories": [{"id": 1, "name": "climbing_hold"}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "segmentation": _rle_compressed(MASK_A),
             "bbox": [2, 1, 4, 3], "score": 0.9, "color": "red", "role": "start"},
            {"id": 2, "image_id": 1, "category_id": 1, "segmentation": _rle_compressed(MASK_B)},
            {"id": 3, "image_id": 1, "category_id": 1, "segmentation": _rle_compressed(MASK_C),
             "bbox": [0, 9, 4, 2], "score": 0.5, "color": "blue"},
            {"id": 4, "image_id": 1, "category_id": 1, "segmentation": _rle_uncompressed(MASK_E),
             "bbox": [7, 4, 3, 2], "color": "green"},
            {"id": 5, "image_id": 2, "category_id": 1, "segmentation": _rle_compressed(MASK_D),
             "bbox": [0, 0, 2, 2]},
        ],
    }
    path = tmp_path / "gt.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_returns_holds_of_requested_image(coco_path):
    holds = load_holds(coco_path, "wall.png")
    assert [h.id for h in holds] == [1, 2, 3, 4]
    assert all(isinstance(h, Hold) for h in holds)
    assert holds[0].mask.dtype == bool and holds[0].mask.shape == (H, W)
    assert np.array_equal(holds[0].mask, MASK_A)
    assert np.array_equal(holds[2].mask, MASK_C)


def test_uncompressed_rle_decodes_to_same_mask(coco_path):
    holds = load_holds(coco_path, "wall.png")
    assert np.array_equal(holds[3].mask, MASK_E)


def test_only_requested_image_is_returned(coco_path):
    holds = load_holds(coco_path, "other.png")
    assert [h.id for h in holds] == [5]


def test_unknown_image_name_raises(coco_path):
    with pytest.raises(ValueError, match="not in"):
        load_holds(coco_path, "missing.png")


def test_bbox_from_field_and_computed_when_missing(coco_path):
    holds = load_holds(coco_path, "wall.png")
    assert holds[0].bbox == (2, 1, 4, 3)
    assert holds[1].bbox == (6, 6, 3, 3)


def test_centroid_uses_largest_component_only(coco_path):
    holds = load_holds(coco_path, "wall.png")
    assert holds[0].centroid == pytest.approx((3.5, 2.0))
    assert holds[1].centroid == pytest.approx((7.0, 7.0))
    # The stray pixel at (row 0, col 9) must not pull the centroid.
    assert holds[2].centroid == pytest.approx((1.5, 9.5))


def test_optional_fields_default_to_none(coco_path):
    holds = load_holds(coco_path, "wall.png")
    assert holds[1].color is None and holds[1].score is None and holds[1].role is None
    assert holds[0].color == "red" and holds[0].score == pytest.approx(0.9)
    assert holds[0].role == "start"


def test_label_map_marks_hold_ids(coco_path):
    holds = load_holds(coco_path, "wall.png")
    lm = label_map(holds, (H, W))
    assert lm.shape == (H, W) and lm.dtype == np.int32
    assert lm[1, 2] == 1
    assert lm[7, 7] == 2
    assert lm[9, 0] == 3
    assert lm[4, 7] == 4
    assert lm[0, 0] == 0


def test_label_map_earlier_hold_wins_on_overlap():
    m1 = np.zeros((H, W), dtype=bool)
    m1[0:2, 0:2] = True
    m2 = np.zeros((H, W), dtype=bool)
    m2[1:3, 1:3] = True
    holds = [
        Hold(id=1, mask=m1, bbox=(0, 0, 2, 2), centroid=(0.5, 0.5), color=None, score=None, role=None),
        Hold(id=2, mask=m2, bbox=(1, 1, 2, 2), centroid=(1.5, 1.5), color=None, score=None, role=None),
    ]
    lm = label_map(holds, (H, W))
    assert lm[1, 1] == 1
    assert lm[2, 2] == 2


def test_label_map_rejects_shape_mismatch():
    m = np.zeros((5, 5), dtype=bool)
    holds = [Hold(id=1, mask=m, bbox=(0, 0, 0, 0), centroid=(0.0, 0.0), color=None, score=None, role=None)]
    with pytest.raises(ValueError):
        label_map(holds, (H, W))
