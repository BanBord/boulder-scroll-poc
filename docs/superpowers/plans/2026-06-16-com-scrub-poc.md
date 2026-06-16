# CoM Scrub PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Play/Pause control in `viewer/compare.html` with a scrub interaction (mouse-drag on the video, scroll wheel, draggable progress bar) so a tester can move through the climbing route step-by-step and compare two climbers' centre-of-mass side by side.

**Architecture:** Single new function `setRouteTime(rt)` becomes the one source of truth for "where are we in the route" — it sets both videos' `currentTime` from a shared route-relative time `rt` (seconds since each player's own `route_start_t`). Every input handler (drag, wheel, progress-bar, hold-tap) calls `setRouteTime()` instead of touching `currentTime` directly. No backend/pipeline changes — `draw_skeleton()` already renders the CoM dot + trail when `show_skeleton=True`, which `_run_player()` already sets.

**Tech Stack:** Vanilla JS in `viewer/compare.html`, served by the existing Flask app (`app.py`, port 5001). No build step, no JS test framework in this repo — verification is manual in the browser (matches existing project convention; `tests/` only covers pure-Python `src/balance.py`).

---

## Spec reference

See `docs/superpowers/specs/2026-06-16-com-scrub-poc-design.md`. This plan implements section "viewer/compare.html — Scrub-Steuerung statt Play/Pause" only — the pipeline/`compare.py` part of that spec was already completed and committed (`7f41513`).

## Before you start

The route data (`output/comparison.json`, `output/p1_processed.mp4`, `output/p2_processed.mp4`) on disk was generated **before** the `_com_path_length()`/`_com_lateral_jitter()` metrics existed. Task 0 regenerates it so the stats panel in the viewer has real numbers instead of `—`.

---

### Task 0: Regenerate comparison data with current pipeline

**Files:** none changed — this just re-runs an existing script.

- [ ] **Step 1: Run the comparison pipeline**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 -m src.compare --p1 player_1_attempt.mov --p2 player_2_attempt.mov \
  --route routes/green_route.json --out output/comparison.json
```

Expected: ends with a summary block, e.g.

```
Comparison JSON → output/comparison.json
  P1: start=player1 route_start=... dur=...s
  P2: start=player2 route_start=... dur=...s
  P1 CoM length=...  jitter=...
  P2 CoM length=...  jitter=...
```

If any value after `length=` or `jitter=` is missing/`None`, stop and check `_com_path_length()`/`_com_lateral_jitter()` in `src/compare.py` before continuing — the viewer's stats panel depends on these.

- [ ] **Step 2: Confirm output files were refreshed**

```bash
ls -la output/p1_processed.mp4 output/p2_processed.mp4 output/comparison.json
```

Expected: all three timestamps are from the run you just did (just now), not 2026-06-08.

---

### Task 1: Add `setRouteTime()` as the single source of truth, remove Play/Pause

**Files:**
- Modify: `viewer/compare.html:144-148` (controls HTML)
- Modify: `viewer/compare.html:94-100` (`#btn-play` CSS rule)
- Modify: `viewer/compare.html:162-241` (state vars, `loop()`)
- Modify: `viewer/compare.html:328-355` (`pauseBoth`, play button listener, `ended` listener)

- [ ] **Step 1: Remove the Play button from the controls markup**

Find this block (around line 144):

```html
  <!-- Controls -->
  <div id="controls">
    <button class="ctrl-btn" id="btn-play">▶ Play</button>
    <button class="ctrl-btn" id="btn-start">↩ Start</button>
    <div id="route-progress"><div id="rp-fill"></div></div>
  </div>
```

Replace with:

```html
  <!-- Controls -->
  <div id="controls">
    <button class="ctrl-btn" id="btn-start">↩ Start</button>
    <div id="route-progress"><div id="rp-fill"></div></div>
  </div>
```

- [ ] **Step 2: Remove the now-unused `#btn-play` CSS rule**

Find (around line 100):

```css
#btn-play { min-width: 76px; }
```

Delete this line entirely.

- [ ] **Step 3: Replace the `playing` state and RAF loop**

Find (around line 162):

```js
let data = null, playing = false;
let p1s = 0, p2s = 0; // route_start_t offsets
```

Replace with:

```js
let data = null;
let p1s = 0, p2s = 0; // route_start_t offsets
```

Find the `loop()` function (around line 226):

```js
// ── RAF loop ──────────────────────────────────────────────
function loop() {
  resize(); // no-op if size unchanged since we only set once
  drawFrame();
  if (data) {
    updateRouteTime();
    // Keep v2 in sync with v1 (route-time based)
    if (playing && !v1.paused) {
      const target2 = v1.currentTime - p1s + p2s;
      if (Math.abs(v2.currentTime - target2) > 0.15) {
        v2.currentTime = Math.max(0, target2);
      }
    }
  }
  requestAnimationFrame(loop);
}
```

Replace with:

```js
// ── Route-time control: the one place that sets currentTime ─
// rt = seconds since route_start_t, shared by both players.
function maxRouteDuration() {
  return Math.max(
    data?.player1?.route_duration || 0,
    data?.player2?.route_duration || 0
  );
}

function setRouteTime(rt) {
  if (!data) return;
  rt = Math.max(0, Math.min(rt, maxRouteDuration()));
  v1.currentTime = Math.max(0, Math.min(p1s + rt, v1.duration || Infinity));
  v2.currentTime = Math.max(0, Math.min(p2s + rt, v2.duration || Infinity));
  updateRouteTime();
}

// ── RAF loop ──────────────────────────────────────────────
function loop() {
  resize(); // no-op if size unchanged since we only set once
  drawFrame();
  if (data) updateRouteTime();
  requestAnimationFrame(loop);
}
```

- [ ] **Step 4: Remove `pauseBoth()`, the Play button listener, and the `ended` listener**

Find (around line 328):

```js
// ── Controls ──────────────────────────────────────────────
function pauseBoth() {
  v1.pause(); v2.pause(); playing = false;
  document.getElementById('btn-play').textContent = '▶ Play';
}

document.getElementById('btn-play').addEventListener('click', function () {
  playing = !playing;
  this.textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) { v1.play(); v2.play(); }
  else pauseBoth();
});

document.getElementById('btn-start').addEventListener('click', () => {
  v1.currentTime = p1s;
  v2.currentTime = p2s;
  pauseBoth();
  document.querySelectorAll('.hcol').forEach(c => c.classList.remove('active'));
  const startCol = document.querySelector('.hcol.is-start');
  if (startCol) startCol.classList.add('active');
});

document.getElementById('mode-btn').addEventListener('click', function () {
  modeIdx = (modeIdx + 1) % MODES.length;
  this.textContent = '👁 ' + MODES[modeIdx];
});

[v1, v2].forEach(v => v.addEventListener('ended', pauseBoth));
```

Replace with:

```js
// ── Controls ──────────────────────────────────────────────
document.getElementById('btn-start').addEventListener('click', () => {
  setRouteTime(0);
  document.querySelectorAll('.hcol').forEach(c => c.classList.remove('active'));
  const startCol = document.querySelector('.hcol.is-start');
  if (startCol) startCol.classList.add('active');
});

document.getElementById('mode-btn').addEventListener('click', function () {
  modeIdx = (modeIdx + 1) % MODES.length;
  this.textContent = '👁 ' + MODES[modeIdx];
});
```

- [ ] **Step 5: Update init code to use `setRouteTime()`**

Find the `fetch('/output/comparison.json')` block near the end of the script (around line 358):

```js
fetch('/output/comparison.json')
  .then(r => r.json())
  .then(d => {
    data = d;
    p1s = d.player1.route_start_t ?? 0;
    p2s = d.player2.route_start_t ?? 0;

    buildTimeline();
    buildStats();
    resize();

    // Jump both to start hold moment
    v1.currentTime = p1s;
    v2.currentTime = p2s;

    // Highlight start hold
    const startHold = d.route.holds.find(h => h.role === 'start');
    if (startHold) {
      const col = document.querySelector(`[data-id="${startHold.id}"]`);
      if (col) col.classList.add('active');
    }

    loop();
  });
```

Replace the two `v1.currentTime = p1s; v2.currentTime = p2s;` lines with `setRouteTime(0);`:

```js
fetch('/output/comparison.json')
  .then(r => r.json())
  .then(d => {
    data = d;
    p1s = d.player1.route_start_t ?? 0;
    p2s = d.player2.route_start_t ?? 0;

    buildTimeline();
    buildStats();
    resize();

    // Jump both to start hold moment
    setRouteTime(0);

    // Highlight start hold
    const startHold = d.route.holds.find(h => h.role === 'start');
    if (startHold) {
      const col = document.querySelector(`[data-id="${startHold.id}"]`);
      if (col) col.classList.add('active');
    }

    loop();
  });
```

- [ ] **Step 6: Manual check — page loads with no console errors**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 app.py
```

Open `http://localhost:5001/compare` in a browser. Open the browser console (Cmd+Option+J in Chrome).

Expected: both videos appear composited on the canvas at the start-hold frame, route-time shows `t +0.0s`, hold timeline renders, no red errors in console, no Play button visible. Stop the server with Ctrl+C when done (keep it in mind — later steps need it running again).

- [ ] **Step 7: Commit**

```bash
git add viewer/compare.html
git commit -m "Replace Play/Pause with setRouteTime() as single source of truth

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Mouse-drag scrubbing on the video

**Files:**
- Modify: `viewer/compare.html` — add a new script block after the `setRouteTime`/`loop` functions added in Task 1 (insert after the `loop()` function, before the `// ── Hold timeline ─` comment)

- [ ] **Step 1: Add the drag handlers**

Insert this new block right after the `loop()` function (added in Task 1, Step 3) and before `// ── Hold timeline ─────`:

```js
// ── Mouse-drag scrubbing on the video ────────────────────
// Drag up = move forward along the route (climbing up).
const DRAG_PX_PER_SEC = 200; // 200px vertical drag ≈ 1s of route time
const stageEl = document.getElementById('stage');
let dragging = false;
let dragStartY = 0;
let dragStartRt = 0;

stageEl.addEventListener('mousedown', (e) => {
  if (!data) return;
  dragging = true;
  dragStartY = e.clientY;
  dragStartRt = routeTime();
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  const deltaY = e.clientY - dragStartY;
  const deltaSec = -deltaY / DRAG_PX_PER_SEC;
  setRouteTime(dragStartRt + deltaSec);
});

window.addEventListener('mouseup', () => { dragging = false; });
```

- [ ] **Step 2: Manual check — drag scrubs both videos**

```bash
python3 app.py
```

Open `http://localhost:5001/compare`. Click and hold on the video, drag the mouse upward ~100px, release.

Expected: `t +Xs` label increases roughly proportionally (100px / 200 px-per-sec ≈ 0.5s), both composited frames visibly advance, progress bar fill grows. Drag downward: `t +Xs` decreases (clamped at 0, doesn't go negative — try dragging far down from the very start and confirm it stays at `t +0.0s`).

- [ ] **Step 3: Commit**

```bash
git add viewer/compare.html
git commit -m "Add mouse-drag scrubbing on the video stage

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Scroll-wheel scrubbing

**Files:**
- Modify: `viewer/compare.html` — extend the block added in Task 2

- [ ] **Step 1: Add the wheel handler**

Append directly after the `mouseup` listener added in Task 2, Step 1:

```js
stageEl.addEventListener('wheel', (e) => {
  if (!data) return;
  e.preventDefault();
  const deltaSec = -e.deltaY / (DRAG_PX_PER_SEC * 4); // finer than drag
  setRouteTime(routeTime() + deltaSec);
}, { passive: false });
```

- [ ] **Step 2: Manual check — scroll wheel scrubs both videos**

```bash
python3 app.py
```

Open `http://localhost:5001/compare`. Hover over the video and scroll up (trackpad: two-finger swipe up, or mouse wheel up).

Expected: `t +Xs` increases in small increments, both frames advance smoothly. Scroll down: time decreases, clamped at 0.

- [ ] **Step 3: Commit**

```bash
git add viewer/compare.html
git commit -m "Add scroll-wheel scrubbing on the video stage

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Draggable/clickable progress bar for absolute jumps

**Files:**
- Modify: `viewer/compare.html` — extend the block added in Task 3

- [ ] **Step 1: Add the progress-bar handlers**

Append directly after the `wheel` listener added in Task 3, Step 1:

```js
// ── Progress bar: click/drag for absolute jumps ──────────
const progressEl = document.getElementById('route-progress');
let progressDragging = false;

function progressEventToRt(e) {
  const rect = progressEl.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  return frac * maxRouteDuration();
}

progressEl.addEventListener('mousedown', (e) => {
  if (!data) return;
  progressDragging = true;
  setRouteTime(progressEventToRt(e));
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!progressDragging) return;
  setRouteTime(progressEventToRt(e));
});

window.addEventListener('mouseup', () => { progressDragging = false; });
```

- [ ] **Step 2: Manual check — progress bar jumps to absolute position**

```bash
python3 app.py
```

Open `http://localhost:5001/compare`. Click on the progress bar roughly at its midpoint.

Expected: `t +Xs` jumps to approximately half of the longer player's `route_duration`, both frames update. Click-and-drag left/right along the bar: time follows the cursor continuously.

- [ ] **Step 3: Commit**

```bash
git add viewer/compare.html
git commit -m "Add draggable progress bar for absolute route-time jumps

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Route hold-timeline taps use `setRouteTime()`

**Files:**
- Modify: `viewer/compare.html:279-292` (`jumpToHold`)

- [ ] **Step 1: Rewrite `jumpToHold()`**

Find (around line 279):

```js
function jumpToHold(holdId) {
  const ev1 = data.player1.hold_events.find(e => e.hold_id === holdId);
  const ev2 = data.player2.hold_events.find(e => e.hold_id === holdId);

  // Jump v1 to 1.5s before this hold (or start)
  const t1 = ev1 ? Math.max(0, ev1.t - 1.5) : (p1s || 0);
  v1.currentTime = t1;
  v2.currentTime = Math.max(0, t1 - p1s + p2s);

  pauseBoth();

  document.querySelectorAll('.hcol').forEach(c =>
    c.classList.toggle('active', parseInt(c.dataset.id) === holdId));
}
```

Replace with:

```js
function jumpToHold(holdId) {
  const ev1 = data.player1.hold_events.find(e => e.hold_id === holdId);

  // Jump to 1.5s before P1 reached this hold (or route start)
  const absT1 = ev1 ? Math.max(0, ev1.t - 1.5) : p1s;
  setRouteTime(absT1 - p1s);

  document.querySelectorAll('.hcol').forEach(c =>
    c.classList.toggle('active', parseInt(c.dataset.id) === holdId));
}
```

- [ ] **Step 2: Manual check — tapping a hold jumps both videos**

```bash
python3 app.py
```

Open `http://localhost:5001/compare`. Click one of the hold nodes in the timeline at the bottom (not the start/top one).

Expected: both videos jump to ~1.5s before P1 touched that hold, the clicked hold node gets highlighted (white border), progress bar fill updates to match.

- [ ] **Step 3: Commit**

```bash
git add viewer/compare.html
git commit -m "Route hold-timeline taps through setRouteTime()

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end manual verification

**Files:** none — verification only.

- [ ] **Step 1: Full walkthrough**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 app.py
```

Open `http://localhost:5001/compare` and check each in order:

1. Page loads at `t +0.0s`, start hold highlighted, no Play button anywhere.
2. Drag up on the video → time advances; drag down → time retreats, clamps at 0.
3. Scroll on the video → time moves in fine steps, both directions.
4. Drag the bottom progress bar → time jumps to the dragged position.
5. Click a hold node → both videos jump to ~1.5s before P1 reached it.
6. Click the mode button (👁) → cycles Beide/P1/P2, composite still respects current `t`.
7. Click "↩ Start" → returns to `t +0.0s`.
8. Stats panel (Routenzeit / CoM-Pfad) shows real numbers, not `—` (confirms Task 0's regenerated `comparison.json` is being read).

Expected: all 8 pass. If stats show `—`, re-check Task 0 ran successfully and `output/comparison.json` has `com_path_length` fields:

```bash
python3 -c "import json; d=json.load(open('output/comparison.json')); print(d['player1']['com_path_length'], d['player2']['com_path_length'])"
```

Expected: two non-null numbers.

- [ ] **Step 2: Final commit if any fixes were needed during verification**

```bash
git add -A
git status --short   # confirm only viewer/compare.html or output/comparison.json changed
git commit -m "Fix issues found during end-to-end scrub verification

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

(Skip this commit if Step 1 passed with no code changes.)
