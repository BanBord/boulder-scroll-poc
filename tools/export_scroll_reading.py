"""Export a compact data file for the browser scroll prototype (portfolio, Craxxl page).

Input is what tools/read_wall_and_body.py produced: the reading JSON, the person masks
(work dir person.npy) plus the hold masks and the wall still they belong to.
Output is one JSON with hold outlines (simplified polygons), contacts, centre of mass,
keypoints and a coarse person silhouette per frame, and the wall still as webp.

Usage:
  python tools/export_scroll_reading.py --reading READING.json --masks GT_COCO \
    --image-name wall-v2-000.png --wall-image STILL.png --person PERSON.npy --out-dir OUT
"""

import argparse
import base64
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.masks_io import load_holds  # noqa: E402

LIMB = {"left_hand": "lh", "right_hand": "rh", "left_foot": "lf", "right_foot": "rf"}


def hold_polygon(mask: np.ndarray, eps: float) -> list:
    """Outline of the largest component, simplified, as flat [x, y, ...] ints."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return []
    c = max(contours, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
    return [int(v) for xy in c for v in xy]


def silhouette(mask: np.ndarray, cell: int):
    """Coarse dot grid of the person: [x0, y0, cols, rows, base64 bits] or None."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return None
    x0, y0 = (xs.min() // cell) * cell, (ys.min() // cell) * cell
    cols = (xs.max() - x0) // cell + 1
    rows = (ys.max() - y0) // cell + 1
    crop = mask[y0:y0 + rows * cell, x0:x0 + cols * cell]
    crop = np.pad(crop, ((0, rows * cell - crop.shape[0]), (0, cols * cell - crop.shape[1])))
    grid = crop.reshape(rows, cell, cols, cell).mean(axis=(1, 3)) > 0.35
    bits = np.packbits(grid.reshape(-1))
    return [int(x0), int(y0), int(cols), int(rows), base64.b64encode(bits.tobytes()).decode("ascii")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reading", required=True, help="JSON from read_wall_and_body.py")
    ap.add_argument("--masks", required=True, help="COCO JSON with hold masks")
    ap.add_argument("--image-name", required=True)
    ap.add_argument("--wall-image", required=True, help="the still the masks belong to")
    ap.add_argument("--person", required=True, help="person.npy (frames x H x W) from the work dir")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cell", type=int, default=12, help="silhouette grid cell in px")
    ap.add_argument("--eps", type=float, default=1.5, help="polygon simplification in px")
    a = ap.parse_args()

    with open(a.reading, encoding="utf-8") as f:
        r = json.load(f)
    n, fps = r["frames"], r["fps"]
    conf_min = r["params"]["conf_min"]

    masks = {h.id: h.mask for h in load_holds(a.masks, a.image_name)}
    holds = []
    for h in r["holds"]:
        poly = hold_polygon(masks[h["id"]], a.eps) if h["id"] in masks else []
        if poly:
            holds.append({"id": h["id"], "i": h["index"], "s": round(h["score"] or 0, 2),
                          "r": 1 if h["route"] else 0, "c": h["color"], "p": poly})

    contacts = [{"l": LIMB[c["limb"]], "h": c["hold_id"], "a": c["f_start"], "b": c["f_end"]}
                for c in r["contacts"]]

    com = [None] * n
    for e in r["com_path"]:
        com[e["f"]] = [round(e["x"]), round(e["y"])]
    for i in range(n):  # fill gaps with the nearest earlier (or first) value
        if com[i] is None:
            com[i] = com[i - 1] if i and com[i - 1] else next(c for c in com if c)
    com_flat = [v for xy in com for v in xy]

    kp = []
    for pts, conf in zip(r["keypoints"], r["keypoint_conf"]):
        for (x, y), c in zip(pts, conf):
            kp += [round(x), round(y)] if c >= conf_min else [-1, -1]

    person = np.load(a.person, mmap_mode="r")
    sil = [silhouette(np.asarray(person[i]) > 0, a.cell) for i in range(min(n, len(person)))]

    out = {
        "v": 1, "fps": fps, "frames": n, "w": r["video_size"][0], "h": r["video_size"][1],
        "holds": holds, "contacts": contacts, "com": com_flat, "kp": kp,
        "person": {"cell": a.cell, "frames": sil},
    }
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, "scroll-reading.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    wall = Image.open(a.wall_image).convert("L")
    wall.save(os.path.join(a.out_dir, "wall.webp"), "WEBP", quality=72, method=6)

    print(f"holds {len(holds)} (route {sum(h['r'] for h in holds)}), contacts {len(contacts)}, "
          f"frames {n}, silhouettes {sum(s is not None for s in sil)}, json {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    main()
