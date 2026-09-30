# Boulder Scroll

A computer-vision proof-of-concept for bouldering video. It has two independent
subsystems:

1. **Video reframing** — pose-tracks a climber in a clip and renders a stabilised
   portrait (9:16) crop that follows them up the wall, with optional skeleton,
   center-of-mass and balance overlays, plus an optional hold-contact timeline.
2. **Wall scan** — detects all holds in a single wall photo (MobileSAM), extracts
   each hold's colour/box, and emits a JSON description plus a routes hint.

## Setup

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Model weights download on first use: the YOLOv8 pose model (`yolov8n-pose.pt`)
and the MobileSAM checkpoint (cached under `~/.cache/mobile_sam/`).

## Running

### Web app (both subsystems)

```sh
python app.py            # http://localhost:5001
```

- `/` — reframing viewer: upload a clip, tune fill/smoothing, toggle
  skeleton / hold-tracking / balance, then download the rendered video.
- `/scan` — wall-scan viewer: upload a wall photo. Scanning is two-phase —
  `POST /scan_preprocess` returns a fast preprocessed preview, then
  `POST /scan_run/<scan_id>` runs the slower MobileSAM segmentation.

### Reframing from the CLI

```sh
python run.py --input clip.mp4                # CoM dot overlay (default)
python run.py --input clip.mp4 --skeleton     # full skeleton + CoM trail
python run.py --input clip.mp4 --no-com       # no overlay
```

Other flags: `--output`, `--width`, `--height`, `--alpha` (smoothing),
`--fill` (target fraction of frame height the person fills). Defaults live in
[`src/config.py`](src/config.py).

### Wall scan from the CLI

```sh
python -m tools.scan_wall path/to/wall.jpg --out output/wall_scan.json
```

Writes `<out>.json` (canonical) and `<out_basename>_overlay.png` (debug).

## Layout

| Path | What |
|---|---|
| `app.py` | Flask app — serves the viewers and all `/render` / `/scan_*` endpoints |
| `run.py` | CLI entry point for the reframing pipeline |
| `serve.py` | Static-only viewer server (fallback; no backend — see its docstring) |
| `src/` | Library: `pipeline`, `detector`, `reframer`, `overlay`, `balance`, `contact`, `hold_detector`, `wall_scan`, `route_aggregator`, `preprocess`, `grab_clusters`, `config` |
| `tools/scan_wall.py` | CLI wrapper around `src/wall_scan.py` |
| `viewer/` | Front-end HTML/JS served by `app.py` |
| `ts/` | TypeScript mirror of the wall-scan JSON schema (reference only — see `ts/README.md`) |
| `tests/` | pytest suite |
| `research/`, `docs/` | Session reports, deep-research notes, and design specs/plans |

Runtime artifacts land in `output/` and `uploads/` (both gitignored). Large
sample videos and design assets live at the repo root but are gitignored (too
big for git) — `run.py`'s default input (`v5_attempt.mp4`) expects one there.

## Tests

```sh
python -m pytest        # Python suite
cd ts && node --experimental-strip-types sortHolds.test.ts   # TS helper
```
