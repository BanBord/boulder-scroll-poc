import argparse
from src.pipeline import run

# --- Configuration ---
INPUT_VIDEO        = "v5_attempt.mp4"
OUTPUT_VIDEO       = "output/scrolling_output.mp4"
OUTPUT_WIDTH       = 540
OUTPUT_HEIGHT      = 960
SMOOTHING_ALPHA    = 0.1    # 0.1 = very smooth/slow, 0.4 = reactive
PERSON_FILL_TARGET = 0.65   # person fills this fraction of frame height (0.5–0.85)
SHOW_COM           = True  # legacy dot overlay
SHOW_SKELETON      = True # full skeleton + CoM dot + trail


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Boulder Scrolling POC")
    parser.add_argument("--input",    default=INPUT_VIDEO)
    parser.add_argument("--output",   default=OUTPUT_VIDEO)
    parser.add_argument("--width",    type=int,   default=OUTPUT_WIDTH)
    parser.add_argument("--height",   type=int,   default=OUTPUT_HEIGHT)
    parser.add_argument("--alpha",    type=float, default=SMOOTHING_ALPHA)
    parser.add_argument("--fill",     type=float, default=PERSON_FILL_TARGET,
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
        show_com=not args.no_com and not args.skeleton,
        show_skeleton=args.skeleton or SHOW_SKELETON,
    )
