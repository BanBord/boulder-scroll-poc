"""CLI: scan a single wall image, write JSON + debug overlay PNG.

    python -m tools.scan_wall path/to/wall.jpg --out output/wall_scan.json

Outputs are written next to ``--out``: ``<out>.json`` (canonical) and
``<out_basename>_overlay.png`` (visual sanity check).
"""

import argparse
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.wall_scan import scan, write_scan_json, draw_overlay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="path to a wall photo (jpg/png)")
    ap.add_argument("--out", default=None,
                    help="output JSON path (default: output/<basename>_scan.json)")
    ap.add_argument("--overlay", default=None,
                    help="overlay PNG path (default: next to JSON)")
    ap.add_argument("--mat-zone", type=float, default=1.0,
                    help="mat-zone fraction; 1.0 disables floor exclusion (default)")
    args = ap.parse_args()

    if args.out is None:
        base = os.path.splitext(os.path.basename(args.image))[0]
        args.out = os.path.join("output", f"{base}_scan.json")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if args.overlay is None:
        args.overlay = os.path.splitext(args.out)[0] + "_overlay.png"

    print(f"Scanning {args.image} …")
    scan_dict = scan(
        args.image,
        mat_zone_frac=args.mat_zone,
    )
    write_scan_json(scan_dict, args.out)
    print(f"JSON → {args.out}")
    print(f"  {len(scan_dict['holds'])} holds detected")
    print(f"  {len(scan_dict['tags'])} tags detected")
    print(f"  routes_hint.count = {scan_dict['routes_hint']['count']}")

    frame = cv2.imread(args.image)
    overlay = draw_overlay(frame, scan_dict)
    cv2.imwrite(args.overlay, overlay)
    print(f"Overlay → {args.overlay}")


if __name__ == "__main__":
    main()
