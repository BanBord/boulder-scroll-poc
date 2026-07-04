"""CLI entry point for the video reframing pipeline.

    python run.py --input clip.mp4 --skeleton

By default the pipeline draws the legacy center-of-mass dot; pass ``--skeleton``
to draw the full skeleton + CoM trail instead, or ``--no-com`` to draw neither.
"""

import argparse

from src import config
from src.pipeline import run

# --- Defaults (overridable via CLI flags) ---
INPUT_VIDEO  = "v5_attempt.mp4"
OUTPUT_VIDEO = "output/scrolling_output.mp4"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Boulder Scrolling POC")
    parser.add_argument("--input",    default=INPUT_VIDEO)
    parser.add_argument("--output",   default=OUTPUT_VIDEO)
    parser.add_argument("--width",    type=int,   default=config.OUT_W)
    parser.add_argument("--height",   type=int,   default=config.OUT_H)
    parser.add_argument("--alpha",    type=float, default=config.SMOOTHING_ALPHA)
    parser.add_argument("--fill",     type=float, default=config.PERSON_FILL,
                        help="Target fraction of frame height the person should fill (0.5–0.85)")
    parser.add_argument("--skeleton", action="store_true", help="Draw skeleton + CoM trail overlay")
    parser.add_argument("--no-com",   action="store_true", help="Disable legacy CoM dot")
    args = parser.parse_args()

    run(
        input_path=args.input,
        output_path=args.output,
        out_w=args.width,
        out_h=args.height,
        smoothing_alpha=args.alpha,
        person_fill=args.fill,
        # Default: show the CoM dot. --skeleton switches to the full overlay;
        # --no-com suppresses the dot when the skeleton isn't requested.
        show_com=not args.no_com and not args.skeleton,
        show_skeleton=args.skeleton,
    )
