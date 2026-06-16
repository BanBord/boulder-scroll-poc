# CoM Metrics Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the removed, broken stats bar with a working metrics bar below the video showing CoM path length, lateral jitter, and a new geometric-entropy "flow" metric — all robust to the existing `route_duration` null bug.

**Architecture:** A pure-Python convex-hull helper (`_convex_hull`) and a new `_com_geometric_entropy()` function in `src/compare.py` compute the flow metric from the existing CoM path data; the result is added as a `com_flow` field next to the existing `com_path_length`/`com_lateral_jitter` fields in `comparison.json`. The frontend gets a new `#metrics` panel that reads those three fields directly — no math in JS, so there's no way for it to produce `NaN`.

**Tech Stack:** Python (`src/compare.py`, tested with `pytest` following the existing `tests/test_balance.py` pattern), vanilla JS in `viewer/compare.html`.

---

## Spec reference

See `docs/superpowers/specs/2026-06-16-com-metrics-design.md`.

---

### Task 1: `_convex_hull()` helper, TDD

**Files:**
- Modify: `src/compare.py`
- Create: `tests/test_compare.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compare.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.compare import _convex_hull, _com_geometric_entropy


def test_convex_hull_of_square_returns_four_corners():
    points = [(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)]  # (5,5) is interior
    hull = _convex_hull(points)
    assert len(hull) == 4
    assert set(hull) == {(0, 0), (10, 0), (10, 10), (0, 10)}


def test_convex_hull_of_two_points_returns_both():
    points = [(0, 0), (5, 5)]
    hull = _convex_hull(points)
    assert set(hull) == {(0, 0), (5, 5)}


def test_convex_hull_of_collinear_points_returns_endpoints_only():
    points = [(0, 0), (1, 1), (2, 2), (3, 3)]
    hull = _convex_hull(points)
    assert len(hull) <= 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
pytest tests/test_compare.py -v
```

Expected: `ImportError: cannot import name '_convex_hull'` (function doesn't exist yet).

- [ ] **Step 3: Implement `_convex_hull()`**

In `src/compare.py`, add right after the imports (after `from .pipeline import run as pipeline_run`):

```python


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
```

- [ ] **Step 4: Run tests to verify the hull tests pass**

```bash
pytest tests/test_compare.py -v -k convex_hull
```

Expected: 3 passed (the `_com_geometric_entropy` tests still fail/error — that's Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/compare.py tests/test_compare.py
git commit -m "Add _convex_hull() monotone-chain helper, TDD

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: `_com_geometric_entropy()`, TDD

**Files:**
- Modify: `src/compare.py`
- Modify: `tests/test_compare.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_compare.py`:

```python


def test_geometric_entropy_straight_line_is_low():
    # A perfectly straight path: hull degenerates to 2 points → entropy is None
    com_path = [{"x": float(i), "y": 0.0} for i in range(10)]
    assert _com_geometric_entropy(com_path) is None


def test_geometric_entropy_zigzag_is_higher_than_straight_square_path():
    # A path that zigzags inside a bounding square has a real, computable entropy
    com_path = [
        {"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 10.0},
        {"x": 0.0, "y": 10.0}, {"x": 10.0, "y": 0.0},
        {"x": 0.0, "y": 0.0},
    ]
    ge = _com_geometric_entropy(com_path)
    assert ge is not None
    assert ge > 0


def test_geometric_entropy_empty_path_returns_none():
    assert _com_geometric_entropy([]) is None


def test_geometric_entropy_single_point_returns_none():
    assert _com_geometric_entropy([{"x": 1.0, "y": 1.0}]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_compare.py -v -k geometric_entropy
```

Expected: `ImportError` or `NameError` — `_com_geometric_entropy` doesn't exist yet.

- [ ] **Step 3: Implement `_com_geometric_entropy()`**

In `src/compare.py`, add right after `_com_lateral_jitter()`:

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_compare.py -v
```

Expected: all 7 tests in the file pass (3 hull + 4 entropy).

- [ ] **Step 5: Commit**

```bash
git add src/compare.py tests/test_compare.py
git commit -m "Add _com_geometric_entropy() flow metric, TDD

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Wire `com_flow` into `build_player()`, regenerate data

**Files:**
- Modify: `src/compare.py:142-191`

- [ ] **Step 1: Add the `com_flow` field**

Find:

```python
        # CoM stats only during the climb (after route_start)
        climb_com = [p for p in com_path if route_start is None or p["f"] >= round(route_start * fps)]
        path_len  = _com_path_length(climb_com)
        lat_jitter = _com_lateral_jitter(climb_com)

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
        }
```

Replace with:

```python
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
```

- [ ] **Step 2: Add `com_flow` to the console summary print**

Find:

```python
    print(f"  P1 CoM length={comparison['player1']['com_path_length']}  jitter={comparison['player1']['com_lateral_jitter']}")
    print(f"  P2 CoM length={comparison['player2']['com_path_length']}  jitter={comparison['player2']['com_lateral_jitter']}")
```

Replace with:

```python
    print(f"  P1 CoM length={comparison['player1']['com_path_length']}  jitter={comparison['player1']['com_lateral_jitter']}  flow={comparison['player1']['com_flow']}")
    print(f"  P2 CoM length={comparison['player2']['com_path_length']}  jitter={comparison['player2']['com_lateral_jitter']}  flow={comparison['player2']['com_flow']}")
```

- [ ] **Step 3: Run the full test suite (regression check)**

```bash
pytest tests/ -v
```

Expected: all tests pass (4 from `test_balance.py` + 7 from `test_compare.py` = 11 passed).

- [ ] **Step 4: Regenerate `comparison.json` with the new field**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 -m src.compare --p1 ../../player_1_attempt.mov --p2 ../../player_2_attempt.mov \
  --route routes/green_route.json --out output/comparison.json
```

Expected: the final summary line now includes `flow=<number>` for both players (not `flow=None` — if it prints `None`, the climb CoM path is degenerate for that player, which would be unexpected for a real climbing video; investigate before continuing).

- [ ] **Step 5: Commit**

```bash
git add src/compare.py
git commit -m "Wire com_flow into build_player() output

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Frontend `#metrics` panel

**Files:**
- Modify: `viewer/compare.html`

- [ ] **Step 1: Add `#metrics` CSS**

Find (the `/* ── Controls ── */` block, near the end of `<style>`):

```css
/* ── Controls ───────────────────────────────────────────── */
#controls {
  flex-shrink: 0; display: flex; gap: 8px; align-items: center;
  padding: 8px 12px; background: #080808; border-top: 1px solid #1a1a1a;
}
```

Replace with:

```css
/* ── CoM metrics bar ──────────────────────────────────── */
#metrics {
  flex-shrink: 0; display: flex; flex-direction: column; gap: 1px;
  background: #111; border-top: 1px solid #1e1e1e;
}
.metric-row {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  padding: 8px 12px; background: #0d0d0d; align-items: center;
}
.metric-label { font-size: 11px; opacity: .5; text-transform: uppercase; letter-spacing: .05em; }
.metric-p1, .metric-p2 { font-size: 14px; font-weight: 700; text-align: right; color: #888; }
.metric-p1.better, .metric-p2.better { color: #66ff88; }

/* ── Controls ───────────────────────────────────────────── */
#controls {
  flex-shrink: 0; display: flex; gap: 8px; align-items: center;
  padding: 8px 12px; background: #080808; border-top: 1px solid #1a1a1a;
}
```

- [ ] **Step 2: Add the `#metrics` HTML**

Find:

```html
  <!-- Controls -->
  <div id="controls">
    <button class="ctrl-btn" id="btn-start">↩ Start</button>
  </div>
```

Replace with:

```html
  <!-- CoM metrics -->
  <div id="metrics">
    <div class="metric-row" data-metric="com_path_length">
      <span class="metric-label">Pfadlänge</span>
      <span class="metric-p1">—</span>
      <span class="metric-p2">—</span>
    </div>
    <div class="metric-row" data-metric="com_lateral_jitter">
      <span class="metric-label">Wackeln</span>
      <span class="metric-p1">—</span>
      <span class="metric-p2">—</span>
    </div>
    <div class="metric-row" data-metric="com_flow">
      <span class="metric-label">Flow</span>
      <span class="metric-p1">—</span>
      <span class="metric-p2">—</span>
    </div>
  </div>

  <!-- Controls -->
  <div id="controls">
    <button class="ctrl-btn" id="btn-start">↩ Start</button>
  </div>
```

- [ ] **Step 3: Add `buildMetrics()` and wire it into `onComparisonLoaded()`**

Find:

```js
// ── Shared setup after comparison.json (re)loads ──────────
function onComparisonLoaded(d) {
  data = d;
  p1s = d.player1.route_start_t ?? 0;
  p2s = d.player2.route_start_t ?? 0;

  buildRail();
  resize();
```

Replace with:

```js
// ── CoM metrics ───────────────────────────────────────────
const METRICS = [
  { key: 'com_path_length',    label: 'Pfadlänge' },
  { key: 'com_lateral_jitter', label: 'Wackeln' },
  { key: 'com_flow',           label: 'Flow' },
];

function buildMetrics() {
  const p1 = data.player1, p2 = data.player2;
  METRICS.forEach(({ key }) => {
    const row = document.querySelector(`.metric-row[data-metric="${key}"]`);
    const v1 = p1[key], v2 = p2[key];
    const elP1 = row.querySelector('.metric-p1');
    const elP2 = row.querySelector('.metric-p2');
    if (v1 == null || v2 == null) {
      elP1.textContent = '—';
      elP2.textContent = '—';
      elP1.className = 'metric-p1';
      elP2.className = 'metric-p2';
      return;
    }
    elP1.textContent = v1;
    elP2.textContent = v2;
    elP1.className = 'metric-p1' + (v1 <= v2 ? ' better' : '');
    elP2.className = 'metric-p2' + (v2 <= v1 ? ' better' : '');
  });
}

// ── Shared setup after comparison.json (re)loads ──────────
function onComparisonLoaded(d) {
  data = d;
  p1s = d.player1.route_start_t ?? 0;
  p2s = d.player2.route_start_t ?? 0;

  buildRail();
  buildMetrics();
  resize();
```

- [ ] **Step 4: Syntax-check**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 -c "
import re
html = open('viewer/compare.html').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/compare_script.js','w').write(m.group(1))
"
node --check /tmp/compare_script.js && echo OK
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add viewer/compare.html
git commit -m "Add CoM metrics panel (path length, jitter, flow)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end verification

**Files:** none — verification only.

- [ ] **Step 1: Restart server and load the page**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
lsof -ti:5001 | xargs kill -9 2>/dev/null; sleep 1
(python3 app.py > /tmp/flask.log 2>&1 &)
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/compare
```

Expected: `200`.

- [ ] **Step 2: Confirm the metrics data is present and sane**

```bash
curl -s http://localhost:5001/output/comparison.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for key in ('com_path_length', 'com_lateral_jitter', 'com_flow'):
    print(key, '→ P1:', d['player1'][key], ' P2:', d['player2'][key])
"
```

Expected: six numeric values printed, none of them the string `NaN` or `Infinity` (Python would print `None` for a missing value, which is the correct degenerate case — not a crash).

- [ ] **Step 3: Manual browser check**

Open `http://localhost:5001/compare`. Confirm:
1. No JS console errors.
2. Below the video (where the old broken bar used to be), three rows: Pfadlänge, Wackeln, Flow — each showing two numbers, with the lower one highlighted green.
3. Dismiss the onboarding card, scrub the route — the metrics rows stay static (they're climb-totals, not per-frame — this is expected, not a bug).

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git status --short   # confirm only src/compare.py or viewer/compare.html changed
git commit -m "Fix issues found during end-to-end verification

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

(Skip this commit if Steps 1-3 passed with no code changes.)
