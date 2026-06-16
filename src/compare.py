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
import math
import os
import tempfile

from .pipeline import run as pipeline_run


def _convex_hull(points):
    """Monotone-chain convex hull. points: iterable of (x, y). Returns hull as list of (x, y), CCW order."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _run_player(video_path: str, route_json_path: str, label: str) -> dict:
    """Run pipeline for one video, keep processed video, return extracted data."""
    os.makedirs("output", exist_ok=True)
    slug = "p1" if "1" in label else "p2"
    output_path  = f"output/{slug}_processed.mp4"
    balance_path = f"output/{slug}_balance.json"
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
        show_skeleton=True,
        show_balance=False,
        show_deviation=True,
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

    return {
        "label": label,
        "video": os.path.basename(output_path),
        "balance": balance,
        "timeline": timeline,
    }


def _hold_progress(timeline: dict) -> list:
    """Hold events: first time any limb reaches each hold (ascending route)."""
    if not timeline or "frames" not in timeline:
        return []

    best = -1
    events = []
    for row in timeline["frames"]:
        touched = [v for v in [row.get("LH"), row.get("RH"), row.get("LF"), row.get("RF")] if v is not None]
        if touched:
            min_id = min(touched)
            if best == -1 or min_id < best:
                best = min_id
                events.append({"frame": row["frame"], "t": row["t"], "hold_id": min_id})
    return events


def _route_start(timeline: dict, start_hold_id: int, fps: float) -> float | None:
    """
    Find when both wrists are simultaneously on the start hold (≥3 consecutive frames).
    Falls back to first frame where either wrist is on the start hold.
    """
    if not timeline or "frames" not in timeline:
        return None

    streak = 0
    streak_start_t = None
    first_single = None

    for row in timeline["frames"]:
        lh, rh = row.get("LH"), row.get("RH")
        both = (lh == start_hold_id and rh == start_hold_id)
        either = (lh == start_hold_id or rh == start_hold_id)

        if both:
            if streak == 0:
                streak_start_t = row["t"]
            streak += 1
            if streak >= 3:
                return streak_start_t
        else:
            streak = 0
            streak_start_t = None

        if either and first_single is None:
            first_single = row["t"]

    return first_single  # fallback: first single-hand contact


def _com_path_length(com_path: list) -> float:
    """Total Euclidean distance of CoM trail in source pixels."""
    total = 0.0
    for i in range(1, len(com_path)):
        dx = com_path[i]["x"] - com_path[i-1]["x"]
        dy = com_path[i]["y"] - com_path[i-1]["y"]
        total += math.sqrt(dx*dx + dy*dy)
    return round(total, 1)


def _com_lateral_jitter(com_path: list) -> float:
    """Std-dev of CoM x-position (lateral stability, lower = smoother)."""
    if not com_path:
        return 0.0
    xs = [p["x"] for p in com_path]
    mean = sum(xs) / len(xs)
    variance = sum((x - mean)**2 for x in xs) / len(xs)
    return round(math.sqrt(variance), 1)


def _com_geometric_entropy(com_path: list) -> float | None:
    """
    Geometric entropy of the CoM trail (Cordier et al.): GE = ln(2L / C),
    L = path length, C = perimeter of the path's convex hull.
    Lower = straighter / more fluid path. Returns None if degenerate
    (fewer than 3 unique points in the hull, zero-perimeter hull, or
    zero-length path).
    """
    points = [(p["x"], p["y"]) for p in com_path]
    hull = _convex_hull(points)
    if len(hull) < 3:
        return None

    perimeter = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        perimeter += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    if perimeter == 0:
        return None

    length = _com_path_length(com_path)
    if length == 0:
        return None

    return round(math.log(2 * length / perimeter), 3)


def run_comparison(p1_path: str, p2_path: str, route_json_path: str, out_path: str) -> None:
    with open(route_json_path) as f:
        route = json.load(f)

    start_hold_id = next(h["id"] for h in route["holds"] if h["role"] == "start")
    top_hold_id   = next(h["id"] for h in route["holds"] if h["role"] == "top")

    p1 = _run_player(p1_path, route_json_path, "player1")
    p2 = _run_player(p2_path, route_json_path, "player2")

    def build_player(data):
        fps      = data["balance"].get("fps", 30)
        frames   = data["balance"].get("frames", [])
        com_path = [
            {"f": r["f"], "x": r["sx"], "y": r["sy"]}
            for r in frames if "sx" in r and "sy" in r
        ]
        hold_events  = _hold_progress(data["timeline"])
        route_start  = _route_start(data["timeline"], start_hold_id, fps)
        top_event    = next((e for e in hold_events if e["hold_id"] == top_hold_id), None)
        route_end    = top_event["t"] if top_event else None
        route_duration = round(route_end - route_start, 2) if (route_start and route_end) else None

        # CoM stats only during the climb (after route_start)
        climb_com = [p for p in com_path if route_start is None or p["f"] >= round(route_start * fps)]
        path_len  = _com_path_length(climb_com)
        lat_jitter = _com_lateral_jitter(climb_com)
        flow       = _com_geometric_entropy(climb_com)

        return {
            "label":          data["label"],
            "video":          data["video"],
            "fps":            fps,
            "com_path":       com_path,
            "hold_events":    hold_events,
            "route_start_t":  route_start,
            "route_end_t":    route_end,
            "route_duration": route_duration,
            "com_path_length": path_len,
            "com_lateral_jitter": lat_jitter,
            "com_flow":        flow,
        }

    comparison = {
        "route":   route,
        "player1": build_player(p1),
        "player2": build_player(p2),
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(comparison, f, separators=(",", ":"))

    def _fmt(p):
        d = p["route_duration"]
        return f"{d:.1f}s" if d else "n/a"

    print(f"\nComparison JSON → {out_path}")
    print(f"  P1: start={p1['label']} route_start={comparison['player1']['route_start_t']}  dur={_fmt(comparison['player1'])}")
    print(f"  P2: start={p2['label']} route_start={comparison['player2']['route_start_t']}  dur={_fmt(comparison['player2'])}")
    print(f"  P1 CoM length={comparison['player1']['com_path_length']}  jitter={comparison['player1']['com_lateral_jitter']}  flow={comparison['player1']['com_flow']}")
    print(f"  P2 CoM length={comparison['player2']['com_path_length']}  jitter={comparison['player2']['com_lateral_jitter']}  flow={comparison['player2']['com_flow']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--p1",    required=True)
    ap.add_argument("--p2",    required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--out",   default="output/comparison.json")
    args = ap.parse_args()
    run_comparison(args.p1, args.p2, args.route, args.out)
