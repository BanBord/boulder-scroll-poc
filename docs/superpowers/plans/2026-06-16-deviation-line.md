# Deviation Line in Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Burn a dashed "ideal line" (mean lateral CoM position) plus a connector to the current CoM dot into each player's processed video, visualizing the same lateral wobble that the `com_lateral_jitter` metric already reports as a number.

**Architecture:** A new lightweight pre-pass (`estimate_mean_com_x()`) runs pose detection once over the whole video (no writing) to get the mean CoM x in source pixels, reusing the same `Detector` instance the main render pass uses. `pipeline.run()` gets an optional `show_deviation` flag that triggers this pre-pass and then draws the line/connector each frame in the existing `show_skeleton` branch, reusing the `to_out()` coordinate transform already computed there.

**Tech Stack:** Python, OpenCV (`cv2`), pytest (existing pattern in `tests/test_balance.py`/`tests/test_compare.py`).

---

## Spec reference

See `docs/superpowers/specs/2026-06-16-deviation-line-design.md`.

---

### Task 1: `draw_deviation()` overlay function

**Files:**
- Modify: `src/overlay.py` (append at end of file)

This is pure drawing code (OpenCV calls on a numpy array) — the existing `draw_com()`/`draw_skeleton()` in this file have no unit tests (they're visual, verified by looking at rendered frames), so this follows the same convention rather than inventing pixel-comparison tests that would be brittle and add no real confidence.

- [ ] **Step 1: Append the new color constants and function**

At the end of `src/overlay.py`, add:

```python


# ── Deviation line (mean CoM-x reference) ───────────────────────────────────
_IDEAL_LINE_CLR = (180, 180, 180)  # light grey, dashed reference line
_DEVIATION_CLR  = (255, 255, 255)  # white connector


def draw_deviation(frame: np.ndarray, com_out, ideal_x: float) -> np.ndarray:
    """Dashed vertical reference line at the climber's mean lateral position,
    plus a short connector from the current CoM to that line."""
    if com_out is None:
        return frame
    h, w = frame.shape[:2]
    ix = int(round(ideal_x))

    dash_len, gap_len = 10, 8
    y = 0
    while y < h:
        y2 = min(y + dash_len, h)
        cv2.line(frame, (ix, y), (ix, y2), _IDEAL_LINE_CLR, 1, cv2.LINE_AA)
        y += dash_len + gap_len

    cx, cy = int(round(com_out[0])), int(round(com_out[1]))
    cv2.line(frame, (cx, cy), (ix, cy), _DEVIATION_CLR, 1, cv2.LINE_AA)
    return frame
```

- [ ] **Step 2: Smoke-test the function in isolation**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 -c "
import numpy as np
from src.overlay import draw_deviation
frame = np.zeros((960, 540, 3), dtype=np.uint8)
out = draw_deviation(frame, (300.0, 400.0), 250.0)
print('frame mutated:', out is frame, 'nonzero pixels:', (out > 0).sum())
out2 = draw_deviation(np.zeros((960, 540, 3), dtype=np.uint8), None, 250.0)
print('no-com case is no-op:', (out2 == 0).all())
"
```

Expected: `frame mutated: True nonzero pixels: <some number > 0>` and `no-com case is no-op: True`.

- [ ] **Step 3: Commit**

```bash
git add src/overlay.py
git commit -m "Add draw_deviation() overlay for mean-CoM-x reference line

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: `estimate_mean_com_x()` pre-pass

**Files:**
- Modify: `src/pipeline.py`
- Test: `tests/test_pipeline.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline.py`:

```python
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.pipeline import estimate_mean_com_x


class _FakeDetector:
    """Returns a fixed sequence of com_src x-values, one per detect_all() call."""
    def __init__(self, xs):
        self.xs = list(xs)
        self.calls = 0

    def detect_all(self, frame):
        x = self.xs[self.calls] if self.calls < len(self.xs) else None
        self.calls += 1
        if x is None:
            return None, None, None, None
        return (x, 0.0), None, None, (x, 0.0)


def test_estimate_mean_com_x_averages_detected_frames(tmp_path):
    # Build a tiny 3-frame video so cv2.VideoCapture has real frames to iterate.
    import cv2
    video_path = str(tmp_path / "tiny.mp4")
    writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16))
    for _ in range(3):
        writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
    writer.release()

    detector = _FakeDetector([100.0, 200.0, 300.0])
    mean_x = estimate_mean_com_x(video_path, detector)
    assert mean_x == 200.0


def test_estimate_mean_com_x_returns_none_when_no_detections(tmp_path):
    import cv2
    video_path = str(tmp_path / "tiny2.mp4")
    writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16))
    writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
    writer.release()

    detector = _FakeDetector([None])
    assert estimate_mean_com_x(video_path, detector) is None


def test_estimate_mean_com_x_returns_none_for_unreadable_file():
    detector = _FakeDetector([])
    assert estimate_mean_com_x("/nonexistent/path.mp4", detector) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
pytest tests/test_pipeline.py -v
```

Expected: `ImportError: cannot import name 'estimate_mean_com_x' from 'src.pipeline'`.

- [ ] **Step 3: Implement `estimate_mean_com_x()`**

In `src/pipeline.py`, add it right after the `_balance_data()` function and before `def run(`:

```python
def estimate_mean_com_x(input_path: str, detector) -> float | None:
    """
    Run pose detection once over the whole video (no drawing/writing) to get
    the mean horizontal CoM position in source pixels — used as the reference
    'ideal line' x for the deviation overlay in the main render pass.
    """
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    xs = []
    for _ in range(total):
        ok, frame = cap.read()
        if not ok:
            break
        _, _, _, com_src = detector.detect_all(frame)
        if com_src is not None:
            xs.append(com_src[0])
    cap.release()
    if not xs:
        return None
    return sum(xs) / len(xs)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "Add estimate_mean_com_x() pre-pass, TDD

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Wire `show_deviation` into `run()`

**Files:**
- Modify: `src/pipeline.py`

- [ ] **Step 1: Add the `show_deviation` parameter**

Find:

```python
def run(
    input_path: str,
    output_path: str,
    out_w: int,
    out_h: int,
    smoothing_alpha: float,
    person_fill: float = 0.65,
    show_com: bool = False,
    show_skeleton: bool = False,
    show_balance: bool = False,
    balance_json_path: str = None,
    track_holds: bool = False,
    route_json_path: str = None,
    progress_callback=None,
    max_seconds: float = None,
) -> None:
```

Replace with:

```python
def run(
    input_path: str,
    output_path: str,
    out_w: int,
    out_h: int,
    smoothing_alpha: float,
    person_fill: float = 0.65,
    show_com: bool = False,
    show_skeleton: bool = False,
    show_balance: bool = False,
    show_deviation: bool = False,
    balance_json_path: str = None,
    track_holds: bool = False,
    route_json_path: str = None,
    progress_callback=None,
    max_seconds: float = None,
) -> None:
```

- [ ] **Step 2: Run the pre-pass right after the detector is created**

Find:

```python
    detector = Detector()

    # --- Hold detection (optional) ---
```

Replace with:

```python
    detector = Detector()

    mean_com_x = None
    if show_deviation:
        print("Estimating mean CoM x-position (deviation pre-pass)...")
        mean_com_x = estimate_mean_com_x(input_path, detector)
        print(f"  mean CoM x = {mean_com_x}")

    # --- Hold detection (optional) ---
```

- [ ] **Step 3: Draw the deviation line in the main loop**

Find:

```python
            if keypoints is not None:
                kps_out = transform_keypoints(
                    keypoints, smooth_cx, smooth_cy,
                    fixed_crop_w, fixed_crop_h, out_w, out_h,
                )
                draw_skeleton(cropped, kps_out, kp_conf, com_out, list(com_trail))
            else:
                # No keypoints — draw just the CoM dot so something is always visible
                draw_skeleton(cropped, None, None, com_out, list(com_trail))

        elif show_com:
            draw_com(cropped, out_w // 2, out_h // 2)
```

Replace with:

```python
            if keypoints is not None:
                kps_out = transform_keypoints(
                    keypoints, smooth_cx, smooth_cy,
                    fixed_crop_w, fixed_crop_h, out_w, out_h,
                )
                draw_skeleton(cropped, kps_out, kp_conf, com_out, list(com_trail))
            else:
                # No keypoints — draw just the CoM dot so something is always visible
                draw_skeleton(cropped, None, None, com_out, list(com_trail))

            if show_deviation and mean_com_x is not None:
                ideal_x_out = to_out(mean_com_x, smooth_cy)[0]
                draw_deviation(cropped, com_out, ideal_x_out)

        elif show_com:
            draw_com(cropped, out_w // 2, out_h // 2)
```

- [ ] **Step 4: Import `draw_deviation`**

Find:

```python
from .overlay import draw_com, draw_skeleton
```

Replace with:

```python
from .overlay import draw_com, draw_skeleton, draw_deviation
```

- [ ] **Step 5: Run the full test suite (regression check)**

```bash
pytest tests/ -v
```

Expected: all tests pass (4 `test_balance.py` + 7 `test_compare.py` + 3 `test_pipeline.py` = 14 passed).

- [ ] **Step 6: Commit**

```bash
git add src/pipeline.py
git commit -m "Wire show_deviation flag into run(): pre-pass + per-frame draw

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Enable it for the comparison pipeline

**Files:**
- Modify: `src/compare.py:29-42`

- [ ] **Step 1: Add `show_deviation=True` to `_run_player()`'s pipeline call**

Find:

```python
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
        balance_json_path=balance_path,
        track_holds=True,
        route_json_path=route_json_path,
    )
```

Replace with:

```python
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
```

- [ ] **Step 2: Regenerate the comparison videos**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 -m src.compare --p1 ../../player_1_attempt.mov --p2 ../../player_2_attempt.mov \
  --route routes/green_route.json --out output/comparison.json
```

Expected: console output now shows two `Estimating mean CoM x-position...` lines (one per player) before each player's main render starts, and the run takes noticeably longer than before (extra detection pass per video). Ends with the same summary block as before (`P1 CoM length=... flow=...` etc.) — `com_flow`/`com_path_length`/`com_lateral_jitter` values are unaffected by this change since the pre-pass doesn't touch the balance JSON.

- [ ] **Step 3: Commit**

```bash
git add src/compare.py
git commit -m "Enable show_deviation in comparison pipeline

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end verification

**Files:** none — verification only.

- [ ] **Step 1: Restart server and reload the viewer**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
lsof -ti:5001 | xargs kill -9 2>/dev/null; sleep 1
(python3 app.py > /tmp/flask.log 2>&1 &)
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/compare
```

Expected: `200`.

- [ ] **Step 2: Manual browser check**

Open `http://localhost:5001/compare`. Confirm:
1. A dashed grey vertical line is visible somewhere in the frame (the climber's mean lateral position).
2. A thin white line connects the green CoM dot to the dashed line — its length changes as you scrub through the route (longer when the climber leans/shifts away from their average position, shorter when centered).
3. Hold the mouse down to swap to P2 — P2 has their own independent dashed line (own mean), not P1's.
4. No JS console errors, no visual artifacts (e.g., line not flickering wildly frame-to-frame — some jitter is expected since the line tracks the panning camera, but it shouldn't look broken).

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git status --short   # confirm only src/*.py changed
git commit -m "Fix issues found during end-to-end verification

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

(Skip this commit if Steps 1-2 passed with no code changes.)
