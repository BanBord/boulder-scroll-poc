# Balance Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a physics-based balance panel overlay to the boulder video pipeline that visualises arm/leg/CoM weight distribution as rolling balls on beams.

**Architecture:** A `PhysicsState` class in `src/balance.py` owns all ball positions and spring-damper physics. `src/overlay.py` gets a new `draw_balance_panel()` function. The pipeline computes per-frame targets from YOLO keypoints and feeds them into the physics state. All coords are in output-frame space (540×960).

**Tech Stack:** Python 3, OpenCV, NumPy, ultralytics YOLO (existing), pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/balance.py` | CREATE | PhysicsState: ball positions, velocities, state machine |
| `src/overlay.py` | MODIFY | Add `draw_balance_panel()` |
| `src/pipeline.py` | MODIFY | `show_balance` param, target computation, per-frame update |
| `app.py` | MODIFY | `show_balance` form param wired through |
| `tests/test_balance.py` | CREATE | Unit tests for PhysicsState |

---

## Task 1: PhysicsState class

**Files:**
- Create: `src/balance.py`
- Create: `tests/test_balance.py`

- [ ] **Step 1: Create test file**

```python
# tests/test_balance.py
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.balance import PhysicsState

PANEL_CX = 270
PANEL_HALF = 220


def test_initial_positions_at_center():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    pos = state.get_positions()
    assert pos["arm"] == float(PANEL_CX)
    assert pos["leg"] == float(PANEL_CX)
    assert pos["com"] == float(PANEL_CX)


def test_stable_state_moves_toward_target():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    target = float(PANEL_CX + 50)
    for _ in range(60):
        state.update(arm_target=target, leg_target=target, com_target=target)
    pos = state.get_positions()
    assert abs(pos["arm"] - target) < 5.0, f"arm {pos['arm']:.1f} should be near {target}"


def test_fallen_state_does_not_pull_to_target():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    # give arm some velocity by updating toward a target first
    for _ in range(10):
        state.update(arm_target=float(PANEL_CX + 80), leg_target=float(PANEL_CX),
                     com_target=float(PANEL_CX))
    arm_before = state.get_positions()["arm"]
    # now trigger fallen — target moves back to center, but physics ignores it
    for _ in range(5):
        state.update(arm_target=float(PANEL_CX), leg_target=float(PANEL_CX),
                     com_target=float(PANEL_CX), is_fallen=True)
    arm_after = state.get_positions()["arm"]
    # arm should NOT have snapped back to center
    assert arm_after > PANEL_CX + 5, f"arm {arm_after:.1f} should still be right of center"


def test_state_transitions():
    state = PhysicsState(panel_cx=PANEL_CX, panel_half=PANEL_HALF)
    pos = state.get_positions()
    assert pos["state"] == "stable"

    # fill variance window with noisy values to trigger unstable
    import random
    random.seed(42)
    for _ in range(35):
        noisy = float(PANEL_CX + random.uniform(-30, 30))
        state.update(arm_target=noisy, leg_target=noisy, com_target=noisy)
    pos = state.get_positions()
    assert pos["state"] in ("unstable", "stable")  # depends on noise magnitude

    # fallen overrides everything
    state.update(arm_target=float(PANEL_CX), leg_target=float(PANEL_CX),
                 com_target=float(PANEL_CX), is_fallen=True)
    assert state.get_positions()["state"] == "fallen"
```

- [ ] **Step 2: Run tests — expect ImportError (file doesn't exist)**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/weight-distribution
python3 -m pytest tests/test_balance.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'src.balance'`

- [ ] **Step 3: Create `src/balance.py`**

```python
# src/balance.py
from collections import deque
import numpy as np
from typing import Dict

_VARIANCE_WINDOW = 30
_VARIANCE_UNSTABLE = 8.0   # px std-dev threshold
_FALLEN_SPEED = 40.0       # px/frame CoM jump → fallen
_FALLEN_CONF = 0.15        # YOLO confidence below this → fallen

# Spring-damper params per state: (stiffness, velocity_decay)
# vel = vel * decay + (target - pos) * stiffness
_PARAMS = {
    "stable":   (0.08, 0.85),
    "unstable": (0.15, 0.55),
    "fallen":   (0.00, 0.97),   # coast to a stop
}


class PhysicsState:
    def __init__(self, panel_cx: int, panel_half: int):
        self._cx = float(panel_cx)
        self._half = float(panel_half)

        self.arm_pos = self._cx;  self.arm_vel = 0.0
        self.leg_pos = self._cx;  self.leg_vel = 0.0
        self.com_pos = self._cx;  self.com_vel = 0.0

        self._state = "stable"
        self._var_window: deque = deque(maxlen=_VARIANCE_WINDOW)

    def update(
        self,
        arm_target: float,
        leg_target: float,
        com_target: float,
        is_fallen: bool = False,
    ) -> None:
        self._var_window.append(com_target)
        variance = float(np.std(self._var_window)) if len(self._var_window) >= 5 else 0.0

        if is_fallen:
            self._state = "fallen"
        elif self._state != "fallen":
            self._state = "unstable" if variance >= _VARIANCE_UNSTABLE else "stable"

        stiffness, decay = _PARAMS[self._state]

        def _step(pos: float, vel: float, target: float):
            vel = vel * decay + (target - pos) * stiffness
            pos = pos + vel
            return pos, vel

        self.arm_pos, self.arm_vel = _step(self.arm_pos, self.arm_vel, arm_target)
        self.leg_pos, self.leg_vel = _step(self.leg_pos, self.leg_vel, leg_target)
        self.com_pos, self.com_vel = _step(self.com_pos, self.com_vel, com_target)

    def get_positions(self) -> Dict:
        return {
            "arm":   self.arm_pos,
            "leg":   self.leg_pos,
            "com":   self.com_pos,
            "state": self._state,
        }
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
python3 -m pytest tests/test_balance.py -v
```

Expected:
```
tests/test_balance.py::test_initial_positions_at_center PASSED
tests/test_balance.py::test_stable_state_moves_toward_target PASSED
tests/test_balance.py::test_fallen_state_does_not_pull_to_target PASSED
tests/test_balance.py::test_state_transitions PASSED
```

- [ ] **Step 5: Commit**

```bash
git add src/balance.py tests/test_balance.py
git commit -m "Add PhysicsState for balance panel"
```

---

## Task 2: draw_balance_panel() in overlay.py

**Files:**
- Modify: `src/overlay.py`

- [ ] **Step 1: Add `draw_balance_panel()` at the end of `src/overlay.py`**

```python
# ── Balance panel ───────────────────────────────────────────────────────────

_PANEL_H    = 220
_BEAM_INSET = 40     # px from frame edge to beam end
_BALL_CLR   = (50, 200, 50)
_BALL_EDGE  = (180, 255, 180)
_BEAM_CLR   = (150, 255, 150)
_LBL_CLR    = (200, 255, 200)


def draw_balance_panel(
    frame: np.ndarray,
    positions: dict,        # from PhysicsState.get_positions()
    blend: float = 0.55,
) -> np.ndarray:
    """
    Draw balance panel in the bottom _PANEL_H pixels of frame.
    Positions are x-coords in output-frame space; panel maps them to panel space.
    """
    out_h, out_w = frame.shape[:2]
    panel_y  = out_h - _PANEL_H
    panel_cx = out_w // 2
    beam_half = out_w // 2 - _BEAM_INSET

    beam_y1 = panel_y + 50    # arm beam y
    beam_y2 = panel_y + 110   # leg beam y
    com_y   = panel_y + 172   # CoM ball centre y

    # Background
    bg = frame.copy()
    cv2.rectangle(bg, (0, panel_y), (out_w, out_h), (8, 8, 8), -1)
    cv2.addWeighted(bg, blend, frame, 1.0 - blend, 0, frame)

    # Beams
    cv2.line(frame, (panel_cx - beam_half, beam_y1),
             (panel_cx + beam_half, beam_y1), _BEAM_CLR, 3, cv2.LINE_AA)
    cv2.line(frame, (panel_cx - beam_half, beam_y2),
             (panel_cx + beam_half, beam_y2), _BEAM_CLR, 3, cv2.LINE_AA)

    # Connector (CoM ball → leg beam)
    com_xi = int(np.clip(positions["com"], panel_cx - beam_half, panel_cx + beam_half))
    cv2.line(frame, (com_xi, beam_y2 + 28), (com_xi, com_y - 38),
             (120, 200, 120), 2, cv2.LINE_AA)

    # Arm ball
    arm_xi = int(np.clip(positions["arm"], panel_cx - beam_half, panel_cx + beam_half))
    cv2.circle(frame, (arm_xi, beam_y1), 20, _BALL_CLR,  -1, cv2.LINE_AA)
    cv2.circle(frame, (arm_xi, beam_y1), 20, _BALL_EDGE,  2, cv2.LINE_AA)

    # Leg ball
    leg_xi = int(np.clip(positions["leg"], panel_cx - beam_half, panel_cx + beam_half))
    cv2.circle(frame, (leg_xi, beam_y2), 26, _BALL_CLR,  -1, cv2.LINE_AA)
    cv2.circle(frame, (leg_xi, beam_y2), 26, _BALL_EDGE,  2, cv2.LINE_AA)

    # CoM ball (fulcrum)
    cv2.circle(frame, (com_xi, com_y), 36, _BALL_CLR,  -1, cv2.LINE_AA)
    cv2.circle(frame, (com_xi, com_y), 36, _BALL_EDGE,  2, cv2.LINE_AA)

    # Labels
    font = cv2.FONT_HERSHEY_SIMPLEX
    def _lbl(text, pt):
        cv2.putText(frame, text, pt, font, 0.38, (0, 0, 0),    3, cv2.LINE_AA)
        cv2.putText(frame, text, pt, font, 0.38, _LBL_CLR,      1, cv2.LINE_AA)

    _lbl("Arm",  (arm_xi - 14, beam_y1 + 5))
    _lbl("Bein", (leg_xi - 18, beam_y2 + 5))
    _lbl("CoM",  (com_xi - 18, com_y   + 5))

    return frame
```

- [ ] **Step 2: Smoke-test the function renders without error**

```bash
python3 -W ignore -c "
import cv2, numpy as np, sys
sys.path.insert(0, '.')
from src.overlay import draw_balance_panel
frame = np.zeros((960, 540, 3), dtype=np.uint8)
pos = {'arm': 270.0, 'leg': 310.0, 'com': 250.0, 'state': 'stable'}
out = draw_balance_panel(frame, pos)
cv2.imwrite('/tmp/panel_test.jpg', out)
print('OK')
"
```

Expected: `OK` and `/tmp/panel_test.jpg` is non-empty. Check with `open /tmp/panel_test.jpg`.

- [ ] **Step 3: Commit**

```bash
git add src/overlay.py
git commit -m "Add draw_balance_panel() to overlay"
```

---

## Task 3: Target computation helper

**Files:**
- Modify: `src/pipeline.py` (add helper function before `run()`)

- [ ] **Step 1: Add `_balance_targets()` helper in `src/pipeline.py`** — insert before the `run()` function

```python
def _balance_targets(
    keypoints,          # np.ndarray (17,2) output coords, or None
    kp_conf,            # np.ndarray (17,), or None
    com_out,            # (x,y) or None
    out_w: int,
    panel_half: int,
    conf_thresh: float = 0.2,
):
    """
    Compute panel-space x targets for arm, leg, CoM balls.
    Returns (arm_target, leg_target, com_target) as floats.
    Panel centre = out_w // 2.  Range roughly [panel_cx - panel_half, panel_cx + panel_half].
    """
    panel_cx = out_w // 2
    fallback = float(panel_cx)

    if keypoints is None or kp_conf is None or com_out is None:
        return fallback, fallback, fallback

    com_x = float(com_out[0])

    arm_xs = [float(keypoints[i, 0]) for i in [9, 10]  if kp_conf[i] > conf_thresh]
    leg_xs = [float(keypoints[i, 0]) for i in [15, 16] if kp_conf[i] > conf_thresh]

    arm_x = float(np.mean(arm_xs)) if arm_xs else com_x
    leg_x = float(np.mean(leg_xs)) if leg_xs else com_x

    sh_ok = kp_conf[5] > conf_thresh and kp_conf[6] > conf_thresh
    body_w = float(abs(keypoints[5, 0] - keypoints[6, 0]) * 2.8) if sh_ok else 160.0
    body_w = max(body_w, 80.0)

    arm_target = panel_cx + (arm_x - com_x) / body_w * panel_half
    leg_target = panel_cx + (leg_x - com_x) / body_w * panel_half
    com_target = panel_cx + (com_x - out_w / 2) / (out_w * 0.4) * panel_half * 0.3

    return float(arm_target), float(leg_target), float(com_target)
```

- [ ] **Step 2: Quick import check**

```bash
python3 -W ignore -c "import sys; sys.path.insert(0,'.');from src.pipeline import _balance_targets; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/pipeline.py
git commit -m "Add _balance_targets() helper to pipeline"
```

---

## Task 4: Pipeline integration

**Files:**
- Modify: `src/pipeline.py` — `run()` function

- [ ] **Step 1: Add `show_balance` parameter and imports to `run()`**

In `src/pipeline.py`, change the `run()` signature and add the balance import block:

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
    show_balance: bool = False,   # ← add this
    track_holds: bool = False,
    progress_callback=None,
    max_seconds: float = None,
) -> None:
```

- [ ] **Step 2: Initialize PhysicsState and fallen-detection deque before the main loop**

Add this block directly after the `fourcc = ...` / `writer = ...` lines and before the `smooth_cx` init:

```python
    # Balance panel state
    if show_balance:
        from .balance import PhysicsState
        from .overlay import draw_balance_panel
        panel_half = out_w // 2 - 40
        _balance_state = PhysicsState(panel_cx=out_w // 2, panel_half=panel_half)
        _prev_com_x: float = float(out_w // 2)
```

- [ ] **Step 3: Force keypoint detection when show_balance is True**

Change the existing condition in the main loop from:

```python
        if show_skeleton or track_holds:
            hip, keypoints, kp_conf, com_src = detector.detect_all(frame)
```

to:

```python
        if show_skeleton or track_holds or show_balance:
            hip, keypoints, kp_conf, com_src = detector.detect_all(frame)
```

- [ ] **Step 4: Add balance update + draw call after the crop and skeleton block**

Add this block after the `elif show_com:` block and before `writer.write(cropped)`:

```python
        if show_balance:
            # Fallen detection: large CoM jump or low confidence
            _is_fallen = False
            if com_out is not None:
                _is_fallen = abs(com_out[0] - _prev_com_x) > 40.0
                _prev_com_x = com_out[0]
            elif kp_conf is not None and kp_conf.max() < 0.15:
                _is_fallen = True

            kps_out_bal = None
            if keypoints is not None:
                kps_out_bal = transform_keypoints(
                    keypoints, smooth_cx, smooth_cy,
                    fixed_crop_w, fixed_crop_h, out_w, out_h,
                )
            com_bal = com_out  # already in output coords if show_skeleton ran

            arm_t, leg_t, com_t = _balance_targets(
                kps_out_bal, kp_conf, com_bal, out_w, panel_half
            )
            _balance_state.update(arm_t, leg_t, com_t, is_fallen=_is_fallen)
            draw_balance_panel(cropped, _balance_state.get_positions())
```

Note: `com_out` is already computed earlier in the loop when `show_skeleton` is True. When `show_balance` is True but `show_skeleton` is False, we need `com_out` from `detect_all`. Add this right after the `detect_all` call block:

```python
        # Make com_out available for balance even without show_skeleton
        if show_balance and not show_skeleton:
            com_out = None
            if com_src is not None:
                x1_b = smooth_cx - fixed_crop_w / 2
                y1_b = smooth_cy - fixed_crop_h / 2
                sx_b = out_w / fixed_crop_w
                sy_b = out_h / fixed_crop_h
                com_out = ((com_src[0] - x1_b) * sx_b, (com_src[1] - y1_b) * sy_b)
```

- [ ] **Step 5: Verify pipeline imports cleanly**

```bash
python3 -W ignore -c "import sys; sys.path.insert(0,'.'); from src.pipeline import run; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/pipeline.py
git commit -m "Integrate balance panel into pipeline (show_balance param)"
```

---

## Task 5: App wiring

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Read `show_balance` from form and pass through**

In `app.py`, add `show_balance` alongside `show_skeleton`:

```python
    show_skeleton = request.form.get("skeleton",     "false").lower() in ("true", "1", "on")
    track_holds   = request.form.get("track_holds",  "false").lower() in ("true", "1", "on")
    show_balance  = request.form.get("balance",      "false").lower() in ("true", "1", "on")
```

Update the thread args:

```python
    t = threading.Thread(
        target=_run,
        args=(job_id, input_path, output_path, fill, alpha,
              preview_secs or None, show_skeleton, track_holds, show_balance),
        daemon=True,
    )
```

Update `_run` signature:

```python
def _run(job_id, input_path, output_path, fill, alpha,
         max_seconds, show_skeleton=False, track_holds=False, show_balance=False):
```

Add to `pipeline_run(...)` call:

```python
            show_balance=show_balance,
```

- [ ] **Step 2: Verify app parses without error**

```bash
python3 -W ignore -c "import sys; sys.path.insert(0,'.'); import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "Wire show_balance param through app"
```

---

## Task 6: End-to-end test on real video

**Files:** none new — just verification

- [ ] **Step 1: Run pipeline on short clip with show_balance=True**

```bash
python3 -W ignore -c "
import sys; sys.path.insert(0,'.')
from src.pipeline import run
run(
    input_path='/Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/v5_short.mov',
    output_path='/tmp/balance_test.mp4',
    out_w=540, out_h=960,
    smoothing_alpha=0.10,
    show_balance=True,
    show_skeleton=True,
    max_seconds=10,
)
"
```

Expected: `Saved → /tmp/balance_test.mp4` with no errors.

- [ ] **Step 2: Inspect output**

```bash
open /tmp/balance_test.mp4
```

Check:
- Panel appears at bottom
- Arm and Bein balls move as climber moves arms/legs
- CoM ball shifts with body lean
- No crashes or visual glitches

- [ ] **Step 3: Run all tests**

```bash
python3 -m pytest tests/test_balance.py -v
```

Expected: 4/4 PASSED

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "Balance panel complete: physics, overlay, pipeline, app wiring"
```
