"""
compare.py — run two videos through the pipeline and produce a comparison JSON.

Usage:
    python -m src.compare \
        --p1 player_1_attempt.mov \
        --p2 player_2_attempt.mov \
        --route routes/green_route.json \
        --out output/comparison.json
"""
import argparse
import json
import os
import tempfile

from .pipeline import run as pipeline_run


def _run_player(video_path: str, route_json_path: str, label: str) -> dict:
    """Run pipeline for one video, return extracted data (no output video kept)."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as vf:
        output_path = vf.name
    balance_path = output_path.replace(".mp4", "_balance.json")
    timeline_path = output_path.replace(".mp4", "_timeline.json")

    print(f"\n=== Processing {label} ({os.path.basename(video_path)}) ===")
    pipeline_run(
        input_path=video_path,
        output_path=output_path,
        out_w=540,
        out_h=960,
        smoothing_alpha=0.10,
        person_fill=0.65,
        show_com=False,
        show_skeleton=False,
        show_balance=True,
        balance_json_path=balance_path,
        track_holds=True,
        route_json_path=route_json_path,
    )

    balance = {}
    if os.path.exists(balance_path):
        with open(balance_path) as f:
            balance = json.load(f)

    timeline = {}
    if os.path.exists(timeline_path):
        with open(timeline_path) as f:
            timeline = json.load(f)

    # Cleanup temp video
    try:
        os.unlink(output_path)
    except OSError:
        pass

    return {"label": label, "balance": balance, "timeline": timeline}


def _hold_progress(timeline: dict) -> list[dict]:
    """
    Derive per-frame route progress: highest hold id touched (any limb) up to that frame.
    Returns list of {frame, t, hold_id} for frames where a new hold is first touched.
    """
    if not timeline or "frames" not in timeline:
        return []

    best = -1
    events = []
    for row in timeline["frames"]:
        touched = [v for v in [row.get("LH"), row.get("RH"), row.get("LF"), row.get("RF")] if v is not None]
        if touched:
            # lower hold id = higher on wall = more progress (id 0 = top)
            # "best progress" = smallest id seen so far
            min_id = min(touched)
            if best == -1 or min_id < best:
                best = min_id
                events.append({"frame": row["frame"], "t": row["t"], "hold_id": min_id})
    return events


def run_comparison(p1_path: str, p2_path: str, route_json_path: str, out_path: str) -> None:
    with open(route_json_path) as f:
        route = json.load(f)

    p1 = _run_player(p1_path, route_json_path, "player1")
    p2 = _run_player(p2_path, route_json_path, "player2")

    # Build CoM source-coord paths (sx, sy per frame)
    def com_path(balance: dict) -> list:
        frames = balance.get("frames", [])
        return [
            {"f": r["f"], "x": r["sx"], "y": r["sy"]}
            for r in frames
            if "sx" in r and "sy" in r
        ]

    comparison = {
        "route": route,
        "player1": {
            "label": "Player 1",
            "fps": p1["balance"].get("fps", 30),
            "com_path": com_path(p1["balance"]),
            "hold_events": _hold_progress(p1["timeline"]),
        },
        "player2": {
            "label": "Player 2",
            "fps": p2["balance"].get("fps", 30),
            "com_path": com_path(p2["balance"]),
            "hold_events": _hold_progress(p2["timeline"]),
        },
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(comparison, f, separators=(",", ":"))
    print(f"\nComparison JSON → {out_path}")
    print(f"  P1: {len(comparison['player1']['com_path'])} CoM frames, "
          f"{len(comparison['player1']['hold_events'])} hold events")
    print(f"  P2: {len(comparison['player2']['com_path'])} CoM frames, "
          f"{len(comparison['player2']['hold_events'])} hold events")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--p1",    required=True)
    ap.add_argument("--p2",    required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--out",   default="output/comparison.json")
    args = ap.parse_args()
    run_comparison(args.p1, args.p2, args.route, args.out)
