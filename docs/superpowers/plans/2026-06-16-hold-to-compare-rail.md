# Press-and-Hold-Vergleich + Vertikale Rail + Video-Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-on dual-video overlay and horizontal hold-timeline in `viewer/compare.html` with a press-and-hold comparison gesture and a vertical route rail, and let testers swap in new climber videos through a browser upload form instead of the terminal.

**Architecture:** A new `holding` boolean (set on mousedown over the video or rail, cleared globally on mouseup) gates whether P2's video is drawn as a semi-transparent overlay on top of P1's. The horizontal hold-timeline and progress bar are replaced by one absolutely-positioned `#rail` element on the right edge of `#stage`, built from the same `hold.y` pixel data already in `routes/green_route.json`. A new `/compare/render` Flask endpoint mirrors the existing `/render` upload→background-thread→status-poll pattern (`app.py:41-69`) but calls `run_comparison()` for two files instead of `pipeline_run()` for one.

**Tech Stack:** Vanilla JS in `viewer/compare.html` (no build step, no JS test framework — see prior plan's rationale), Flask in `app.py`. No backend changes beyond the new endpoint — `src/compare.py`'s `run_comparison()` is reused unchanged.

---

## Spec reference

See `docs/superpowers/specs/2026-06-16-hold-to-compare-rail-design.md`. This plan implements all four sections of that spec.

## Current file state assumed by this plan

This plan picks up from `viewer/compare.html` as it stands after the previous plan (`2026-06-16-com-scrub-poc.md`) was executed — i.e. `setRouteTime()`/`maxRouteTime()`/`routeTime()` already exist, Play/Pause is already gone, drag-scrub and wheel-scrub on `#stage` already work. Each step below shows the exact "Find"/"Replace" text so it doesn't matter whether you're reading this top-to-bottom or jumping to a single task.

---

### Task 1: Press-and-hold ghost overlay, remove mode toggle

**Files:**
- Modify: `viewer/compare.html` (CSS `#mode-btn` rule, HTML mode button, JS `drawFrame`/`MODES`/mousedown/mouseup listeners)

- [ ] **Step 1: Remove the `#mode-btn` CSS rule**

Find:

```css
/* Mode toggle */
#mode-btn {
  position: absolute; top: 10px; right: 10px;
  background: rgba(0,0,0,.6); border: 1px solid #444; color: #fff;
  border-radius: 8px; padding: 5px 10px; font-size: 12px; cursor: pointer;
}
```

Delete this block entirely (including the `/* Mode toggle */` comment).

- [ ] **Step 2: Remove the mode button from the HTML**

Find:

```html
  <!-- Overlay canvas -->
  <div id="stage">
    <canvas id="composite"></canvas>
    <div id="route-time">t +0.0s</div>
    <button id="mode-btn">👁 Beide</button>
  </div>
```

Replace with:

```html
  <!-- Overlay canvas -->
  <div id="stage">
    <canvas id="composite"></canvas>
    <div id="route-time">t +0.0s</div>
  </div>
```

- [ ] **Step 3: Remove `MODES`/`modeIdx`, add `holding` state**

Find:

```js
const SRC_W = 540, SRC_H = 960;
const MODES = ['Beide', 'P1', 'P2'];
let modeIdx = 0;

const v1 = document.getElementById('v1');
const v2 = document.getElementById('v2');
const cvs = document.getElementById('composite');
const ctx = cvs.getContext('2d');

let data = null;
let p1s = 0, p2s = 0; // route_start_t offsets
```

Replace with:

```js
const SRC_W = 540, SRC_H = 960;

const v1 = document.getElementById('v1');
const v2 = document.getElementById('v2');
const cvs = document.getElementById('composite');
const ctx = cvs.getContext('2d');

let data = null;
let p1s = 0, p2s = 0; // route_start_t offsets
let holding = false;  // true while mouse is pressed on video or rail → show P2 ghost
```

- [ ] **Step 4: Rewrite `drawFrame()` to use `holding` instead of mode cycling**

Find:

```js
// ── Composite draw ────────────────────────────────────────
function drawFrame() {
  ctx.clearRect(0, 0, cvs.width, cvs.height);
  const mode = MODES[modeIdx];

  if (mode === 'Beide' || mode === 'P1') {
    ctx.globalAlpha = 1.0;
    ctx.drawImage(v1, 0, 0, cvs.width, cvs.height);
  }
  if (mode === 'Beide' || mode === 'P2') {
    ctx.globalAlpha = mode === 'Beide' ? 0.55 : 1.0;
    // Warm tint for P2
    ctx.drawImage(v2, 0, 0, cvs.width, cvs.height);
    if (mode === 'Beide') {
      ctx.globalCompositeOperation = 'multiply';
      ctx.fillStyle = 'rgba(255,190,100,0.18)';
      ctx.fillRect(0, 0, cvs.width, cvs.height);
      ctx.globalCompositeOperation = 'source-over';
    }
  }
  ctx.globalAlpha = 1.0;
}
```

Replace with:

```js
// ── Composite draw ────────────────────────────────────────
const GHOST_ALPHA = 0.5; // P2 opacity while holding, no colour filter

function drawFrame() {
  ctx.clearRect(0, 0, cvs.width, cvs.height);
  ctx.globalAlpha = 1.0;
  ctx.drawImage(v1, 0, 0, cvs.width, cvs.height);

  if (holding) {
    ctx.globalAlpha = GHOST_ALPHA;
    ctx.drawImage(v2, 0, 0, cvs.width, cvs.height);
    ctx.globalAlpha = 1.0;
  }
}
```

- [ ] **Step 5: Set `holding` on stage press, clear on global release**

Find:

```js
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

Replace with:

```js
stageEl.addEventListener('mousedown', (e) => {
  if (!data) return;
  dragging = true;
  holding = true;
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

window.addEventListener('mouseup', () => { dragging = false; holding = false; });
```

- [ ] **Step 6: Remove the mode-button click listener**

Find:

```js
document.getElementById('mode-btn').addEventListener('click', function () {
  modeIdx = (modeIdx + 1) % MODES.length;
  this.textContent = '👁 ' + MODES[modeIdx];
});
```

Delete this block entirely.

- [ ] **Step 7: Syntax-check and verify in browser**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
python3 -c "
import re
html = open('viewer/compare.html').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/compare_script.js','w').write(m.group(1))
"
node --check /tmp/compare_script.js && echo "JS SYNTAX OK"
grep -n "MODES\|modeIdx\|mode-btn" viewer/compare.html
```

Expected: `JS SYNTAX OK`, and the `grep` finds nothing (empty output, exit code 1).

Then manually in browser at `http://localhost:5001/compare`: press and hold the mouse anywhere on the video — P2 should fade in semi-transparent over P1 with no colour tint. Release — P2 disappears. Dragging while held still scrubs the route.

- [ ] **Step 8: Commit**

```bash
git add viewer/compare.html
git commit -m "Replace mode toggle with press-and-hold P2 ghost overlay

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Vertical route rail (replaces horizontal timeline + progress bar)

**Files:**
- Modify: `viewer/compare.html` (CSS hold-timeline/progress-bar rules, HTML timeline/progress markup, JS `buildTimeline`/`jumpToHold`/progress-bar listeners/`updateRouteTime`)

- [ ] **Step 1: Replace the hold-timeline and progress-bar CSS with rail CSS**

Find:

```css
/* ── Hold timeline ──────────────────────────────────────── */
#timeline {
  flex-shrink: 0; padding: 8px 16px 10px; background: #0d0d0d;
  border-top: 1px solid #1e1e1e;
}
#tl-label { font-size: 10px; opacity: .35; text-transform: uppercase;
  letter-spacing: .06em; margin-bottom: 6px; }
#hold-track {
  position: relative; height: 52px;
}
#hold-track::before {
  content: ''; position: absolute; top: 50%; left: 0; right: 0;
  height: 1px; background: #2a2a2a; transform: translateY(-50%);
}
.hcol {
  position: absolute; top: 0; bottom: 0; width: 32px; margin-left: -16px;
  display: flex; flex-direction: column; align-items: center;
  justify-content: space-between; cursor: pointer;
}
.hcol:active .hnode { transform: scale(1.2); }
.hdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.hdot-p1 { background: #4aaeff; }
.hdot-p2 { background: #ffaa44; }
.hdot-empty { background: transparent; border: 1px solid #333; }
.hnode {
  width: 24px; height: 24px; border-radius: 50%;
  border: 1.5px solid #333; background: #111;
  display: flex; align-items: center; justify-content: center;
  font-size: 9px; font-weight: 700; color: #666;
  transition: transform .12s, border-color .12s;
  flex-shrink: 0;
}
.hcol.active .hnode { border-color: #fff; color: #fff; background: #2a2a2a; }
.hcol.is-top   .hnode { border-color: #ffe44a; color: #ffe44a; }
.hcol.is-start .hnode { border-color: #66ff88; color: #66ff88; }

/* ── Controls ───────────────────────────────────────────── */
#controls {
  flex-shrink: 0; display: flex; gap: 8px; align-items: center;
  padding: 8px 12px; background: #080808; border-top: 1px solid #1a1a1a;
}
.ctrl-btn {
  background: #1c1c1c; border: none; color: #fff;
  padding: 9px 16px; border-radius: 8px; font-size: 13px;
  font-weight: 600; cursor: pointer; flex-shrink: 0;
}
.ctrl-btn:active { background: #333; }
#route-progress {
  flex: 1; height: 3px; background: #2a2a2a; border-radius: 2px;
  position: relative; cursor: pointer;
}
#rp-fill { height: 100%; border-radius: 2px;
  background: linear-gradient(90deg, #4aaeff, #ffaa44); width: 0%; }
```

Replace with:

```css
/* ── Vertical route rail ───────────────────────────────── */
#rail {
  position: absolute; right: 12px; top: 40px; bottom: 40px; width: 36px;
  cursor: pointer;
}
#rail::before {
  content: ''; position: absolute; left: 50%; top: 0; bottom: 0;
  width: 2px; background: #2a2a2a; transform: translateX(-50%);
}
#rail-fill {
  position: absolute; left: 50%; bottom: 0; width: 2px; height: 0%;
  background: linear-gradient(180deg, #4aaeff, #ffaa44);
  transform: translateX(-50%);
}
.rail-row {
  position: absolute; left: 0; right: 0; height: 28px; margin-top: -14px;
  display: flex; align-items: center; justify-content: space-between;
  cursor: pointer;
}
.rail-row:active .rail-node { transform: scale(1.2); }
.rail-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.rail-dot-p1 { background: #4aaeff; }
.rail-dot-p2 { background: #ffaa44; }
.rail-dot-empty { background: transparent; border: 1px solid #333; }
.rail-node {
  width: 18px; height: 18px; border-radius: 50%;
  border: 1.5px solid #333; background: #111;
  display: flex; align-items: center; justify-content: center;
  font-size: 8px; font-weight: 700; color: #666;
  transition: transform .12s, border-color .12s;
  flex-shrink: 0;
}
.rail-row.active .rail-node { border-color: #fff; color: #fff; background: #2a2a2a; }
.rail-row.is-top   .rail-node { border-color: #ffe44a; color: #ffe44a; }
.rail-row.is-start .rail-node { border-color: #66ff88; color: #66ff88; }

/* ── Controls ───────────────────────────────────────────── */
#controls {
  flex-shrink: 0; display: flex; gap: 8px; align-items: center;
  padding: 8px 12px; background: #080808; border-top: 1px solid #1a1a1a;
}
.ctrl-btn {
  background: #1c1c1c; border: none; color: #fff;
  padding: 9px 16px; border-radius: 8px; font-size: 13px;
  font-weight: 600; cursor: pointer; flex-shrink: 0;
}
.ctrl-btn:active { background: #333; }
```

- [ ] **Step 2: Replace the timeline/progress-bar HTML with the rail**

Find:

```html
  <!-- Overlay canvas -->
  <div id="stage">
    <canvas id="composite"></canvas>
    <div id="route-time">t +0.0s</div>
  </div>

  <!-- Stats -->
  <div id="winner">
    <div class="stat-pill" id="sp-time">
      <div class="label">Routenzeit</div>
      <div class="value neutral">—</div>
      <div class="sub">—</div>
    </div>
    <div class="stat-pill" id="sp-com">
      <div class="label">CoM-Pfad</div>
      <div class="value neutral">—</div>
      <div class="sub">—</div>
    </div>
  </div>

  <!-- Hold timeline -->
  <div id="timeline">
    <div id="tl-label">Holds — Tippen zum Springen</div>
    <div id="hold-track"></div>
  </div>

  <!-- Controls -->
  <div id="controls">
    <button class="ctrl-btn" id="btn-start">↩ Start</button>
    <div id="route-progress"><div id="rp-fill"></div></div>
  </div>
```

Replace with:

```html
  <!-- Overlay canvas -->
  <div id="stage">
    <canvas id="composite"></canvas>
    <div id="route-time">t +0.0s</div>
    <div id="rail"><div id="rail-fill"></div></div>
  </div>

  <!-- Stats -->
  <div id="winner">
    <div class="stat-pill" id="sp-time">
      <div class="label">Routenzeit</div>
      <div class="value neutral">—</div>
      <div class="sub">—</div>
    </div>
    <div class="stat-pill" id="sp-com">
      <div class="label">CoM-Pfad</div>
      <div class="value neutral">—</div>
      <div class="sub">—</div>
    </div>
  </div>

  <!-- Controls -->
  <div id="controls">
    <button class="ctrl-btn" id="btn-start">↩ Start</button>
  </div>
```

- [ ] **Step 3: Update `updateRouteTime()` to fill the rail instead of the progress bar**

Find:

```js
function updateRouteTime() {
  const rt = routeTime();
  document.getElementById('route-time').textContent = `t +${rt.toFixed(1)}s`;

  // Update progress bar
  const maxDur = Math.max(
    data?.player1?.route_duration || 0,
    data?.player2?.route_duration || 0
  );
  if (maxDur > 0) {
    document.getElementById('rp-fill').style.width = Math.min(100, rt / maxDur * 100) + '%';
  }
}
```

Replace with:

```js
function updateRouteTime() {
  const rt = routeTime();
  document.getElementById('route-time').textContent = `t +${rt.toFixed(1)}s`;

  // Fill the rail from the bottom (route start) up to the current position
  const maxDur = maxRouteTime();
  if (maxDur > 0) {
    document.getElementById('rail-fill').style.height = Math.min(100, rt / maxDur * 100) + '%';
  }
}
```

Note: `maxRouteTime()` is defined further down in the file (it already exists from the previous plan) — JS function declarations are hoisted, so calling it here before its source position is fine.

- [ ] **Step 4: Remove the progress-bar drag handlers**

Find:

```js
// ── Progress bar: click/drag for absolute jumps ──────────
const progressEl = document.getElementById('route-progress');
let progressDragging = false;

function progressEventToRt(e) {
  const rect = progressEl.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  return frac * maxRouteTime();
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

Replace with:

```js
// ── Rail: click/drag for absolute jumps + ghost while held ─
const railEl = document.getElementById('rail');
let railDragging = false;

function railEventToRt(e) {
  const rect = railEl.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
  return (1 - frac) * maxRouteTime(); // top (frac=0) = max, bottom (frac=1) = 0
}

railEl.addEventListener('mousedown', (e) => {
  if (!data) return;
  e.stopPropagation(); // don't also trigger the stage's video-drag scrub
  railDragging = true;
  holding = true;
  setRouteTime(railEventToRt(e));
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!railDragging) return;
  setRouteTime(railEventToRt(e));
});

window.addEventListener('mouseup', () => { railDragging = false; holding = false; });
```

Note: this adds a *second* global `mouseup` listener (the first one, from Task 1 Step 5, resets `dragging`/`holding` for the video-drag case). Two independent listeners both firing on `mouseup` is fine — they reset different state and neither depends on the other's order.

- [ ] **Step 5: Replace `buildTimeline()` with `buildRail()`**

Find:

```js
// ── Hold timeline ─────────────────────────────────────────
function buildTimeline() {
  const track = document.getElementById('hold-track');
  track.innerHTML = '';
  const holds = [...data.route.holds].sort((a, b) => b.y - a.y); // start left
  const n = holds.length;

  holds.forEach((hold, i) => {
    const pct = n === 1 ? 50 : (i / (n - 1)) * 100;
    const col = document.createElement('div');
    col.className = 'hcol' +
      (hold.role === 'top'   ? ' is-top'   : '') +
      (hold.role === 'start' ? ' is-start' : '');
    col.style.left = pct + '%';
    col.dataset.id = hold.id;

    const ev1 = data.player1.hold_events.find(e => e.hold_id === hold.id);
    const ev2 = data.player2.hold_events.find(e => e.hold_id === hold.id);

    const d1 = document.createElement('div');
    d1.className = 'hdot ' + (ev1 ? 'hdot-p1' : 'hdot-empty');
    d1.title = ev1 ? `P1: ${ev1.t.toFixed(1)}s` : 'P1: —';

    const node = document.createElement('div');
    node.className = 'hnode';
    node.textContent = hold.role === 'top' ? '▲' : (hold.role === 'start' ? 'S' : hold.id);

    const d2 = document.createElement('div');
    d2.className = 'hdot ' + (ev2 ? 'hdot-p2' : 'hdot-empty');
    d2.title = ev2 ? `P2: ${ev2.t.toFixed(1)}s` : 'P2: —';

    col.append(d1, node, d2);
    col.addEventListener('click', () => jumpToHold(hold.id));
    track.appendChild(col);
  });
}

function jumpToHold(holdId) {
  const ev1 = data.player1.hold_events.find(e => e.hold_id === holdId);

  // Jump to 1.5s before P1 reached this hold (or route start)
  const absT1 = ev1 ? Math.max(0, ev1.t - 1.5) : p1s;
  setRouteTime(absT1 - p1s);

  document.querySelectorAll('.hcol').forEach(c =>
    c.classList.toggle('active', parseInt(c.dataset.id) === holdId));
}
```

Replace with:

```js
// ── Vertical route rail ───────────────────────────────────
function holdRailPct(hold, holds) {
  const ys = holds.map(h => h.y);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  if (maxY === minY) return 50;
  return (hold.y - minY) / (maxY - minY) * 100; // 0% = TOP (top of rail), 100% = START (bottom)
}

function buildRail() {
  const holds = data.route.holds;
  railEl.querySelectorAll('.rail-row').forEach(el => el.remove());

  holds.forEach((hold) => {
    const pct = holdRailPct(hold, holds);
    const row = document.createElement('div');
    row.className = 'rail-row' +
      (hold.role === 'top'   ? ' is-top'   : '') +
      (hold.role === 'start' ? ' is-start' : '');
    row.style.top = pct + '%';
    row.dataset.id = hold.id;

    const ev1 = data.player1.hold_events.find(e => e.hold_id === hold.id);
    const ev2 = data.player2.hold_events.find(e => e.hold_id === hold.id);

    const d1 = document.createElement('div');
    d1.className = 'rail-dot ' + (ev1 ? 'rail-dot-p1' : 'rail-dot-empty');
    d1.title = ev1 ? `P1: ${ev1.t.toFixed(1)}s` : 'P1: —';

    const node = document.createElement('div');
    node.className = 'rail-node';
    node.textContent = hold.role === 'top' ? '▲' : (hold.role === 'start' ? 'S' : hold.id);

    const d2 = document.createElement('div');
    d2.className = 'rail-dot ' + (ev2 ? 'rail-dot-p2' : 'rail-dot-empty');
    d2.title = ev2 ? `P2: ${ev2.t.toFixed(1)}s` : 'P2: —';

    row.append(d1, node, d2);
    row.addEventListener('click', () => jumpToHold(hold.id));
    railEl.appendChild(row);
  });
}

function jumpToHold(holdId) {
  const ev1 = data.player1.hold_events.find(e => e.hold_id === holdId);

  // Jump to 1.5s before P1 reached this hold (or route start)
  const absT1 = ev1 ? Math.max(0, ev1.t - 1.5) : p1s;
  setRouteTime(absT1 - p1s);

  document.querySelectorAll('.rail-row').forEach(c =>
    c.classList.toggle('active', parseInt(c.dataset.id) === holdId));
}
```

Note: `railEl` is declared in Step 4 above, earlier in the same script than `buildRail()`'s call sites further down — but `buildRail()` itself (a function declaration) is hoisted, so call-order in the file doesn't matter; only `railEl`'s `const` needs to be evaluated before `buildRail()` is *called* (not before it's *defined*), which holds true since the init code at the bottom of the file runs last.

- [ ] **Step 6: Update the two remaining call sites of `buildTimeline()`/`.hcol`**

Find (in the `btn-start` click listener):

```js
document.getElementById('btn-start').addEventListener('click', () => {
  setRouteTime(0);
  document.querySelectorAll('.hcol').forEach(c => c.classList.remove('active'));
  const startCol = document.querySelector('.hcol.is-start');
  if (startCol) startCol.classList.add('active');
});
```

Replace with:

```js
document.getElementById('btn-start').addEventListener('click', () => {
  setRouteTime(0);
  document.querySelectorAll('.rail-row').forEach(c => c.classList.remove('active'));
  const startRow = document.querySelector('.rail-row.is-start');
  if (startRow) startRow.classList.add('active');
});
```

Find (in the init block at the bottom of the file):

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

Replace with:

```js
fetch('/output/comparison.json')
  .then(r => r.json())
  .then(d => {
    data = d;
    p1s = d.player1.route_start_t ?? 0;
    p2s = d.player2.route_start_t ?? 0;

    buildRail();
    buildStats();
    resize();

    // Jump both to start hold moment
    setRouteTime(0);

    // Highlight start hold
    const startHold = d.route.holds.find(h => h.role === 'start');
    if (startHold) {
      const row = document.querySelector(`[data-id="${startHold.id}"]`);
      if (row) row.classList.add('active');
    }

    loop();
  });
```

- [ ] **Step 7: Syntax-check and verify in browser**

```bash
python3 -c "
import re
html = open('viewer/compare.html').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/compare_script.js','w').write(m.group(1))
"
node --check /tmp/compare_script.js && echo "JS SYNTAX OK"
grep -n "hold-track\|hcol\|hdot\|hnode\|route-progress\|rp-fill\|buildTimeline" viewer/compare.html
```

Expected: `JS SYNTAX OK`, and the `grep` finds nothing.

Then manually in browser: a vertical rail with 10 dots appears on the right edge of the video, TOP marker (▲, yellow) near the top, START marker (S, green) near the bottom. Dragging up/down on the rail scrubs the route and shows the P2 ghost while held. Clicking a rail row jumps to that hold. The "↩ Start" button highlights the start row.

- [ ] **Step 8: Commit**

```bash
git add viewer/compare.html
git commit -m "Replace horizontal hold-timeline and progress bar with vertical route rail

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Backend — `/compare/render` upload endpoint

**Files:**
- Modify: `app.py` (add two routes + one helper function)

- [ ] **Step 1: Add the upload + status endpoints**

Find (the existing `/balance/<filename>` route, near the end of the file, right before the `if __name__ == "__main__":` block):

```python
@app.route("/balance/<filename>")
def serve_balance(filename):
    return send_from_directory(OUTPUT_DIR, filename, mimetype="application/json")


if __name__ == "__main__":
```

Replace with:

```python
@app.route("/balance/<filename>")
def serve_balance(filename):
    return send_from_directory(OUTPUT_DIR, filename, mimetype="application/json")


@app.route("/compare/render", methods=["POST"])
def compare_render():
    p1_file = request.files.get("p1")
    p2_file = request.files.get("p2")
    if not p1_file or not p2_file:
        return jsonify({"error": "p1 and p2 files are required"}), 400

    job_id = uuid.uuid4().hex[:8]
    ext1 = os.path.splitext(p1_file.filename)[1] or ".mp4"
    ext2 = os.path.splitext(p2_file.filename)[1] or ".mp4"
    p1_path = os.path.join(UPLOAD_DIR, f"{job_id}_p1{ext1}")
    p2_path = os.path.join(UPLOAD_DIR, f"{job_id}_p2{ext2}")
    p1_file.save(p1_path)
    p2_file.save(p2_path)

    with _lock:
        _jobs[job_id] = {"status": "running"}

    t = threading.Thread(
        target=_run_compare,
        args=(job_id, p1_path, p2_path),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


def _run_compare(job_id, p1_path, p2_path):
    try:
        from src.compare import run_comparison

        run_comparison(
            p1_path, p2_path,
            route_json_path="routes/green_route.json",
            out_path=os.path.join(OUTPUT_DIR, "comparison.json"),
        )
        with _lock:
            _jobs[job_id]["status"] = "done"
    except Exception as exc:
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)


@app.route("/compare/status/<job_id>")
def compare_status(job_id):
    with _lock:
        job = dict(_jobs.get(job_id, {"status": "not_found"}))
    return jsonify(job)


if __name__ == "__main__":
```

- [ ] **Step 2: Verify the endpoint end-to-end with curl**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
pkill -f "python3 app.py" 2>/dev/null; sleep 1
(python3 app.py > /tmp/flask.log 2>&1 &)
sleep 2

JOB=$(curl -s -F "p1=@../../player_1_attempt.mov" -F "p2=@../../player_2_attempt.mov" \
  http://localhost:5001/compare/render | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
echo "job_id=$JOB"

# Poll until done (videos take ~30-40s to process)
for i in $(seq 1 30); do
  STATUS=$(curl -s http://localhost:5001/compare/status/$JOB | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  echo "status=$STATUS"
  if [ "$STATUS" = "done" ] || [ "$STATUS" = "error" ]; then break; fi
  sleep 5
done
curl -s http://localhost:5001/compare/status/$JOB
```

Expected: status progresses from `running` to `done`. If `error`, the response includes an `error` field — read it before continuing (most likely cause: a typo in the route path or missing route file).

- [ ] **Step 3: Confirm output files were overwritten**

```bash
ls -la output/comparison.json output/p1_processed.mp4 output/p2_processed.mp4
```

Expected: all three timestamps are from the curl test you just ran (within the last minute).

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Add /compare/render and /compare/status endpoints for browser video upload

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Frontend — upload panel + reload-after-render

**Files:**
- Modify: `viewer/compare.html` (CSS upload panel, HTML upload form, JS upload/poll/reload logic, DRY refactor of init code)

- [ ] **Step 1: Add upload-panel CSS**

Find (the very first CSS rule, right after the opening `<style>` tag):

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: #0a0a0a; color: #fff;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif; overflow: hidden; }

#app { display: flex; flex-direction: column; height: 100dvh; }
```

Replace with:

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: #0a0a0a; color: #fff;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif; overflow: hidden; }

#app { display: flex; flex-direction: column; height: 100dvh; }

/* ── Video upload panel ────────────────────────────────── */
#upload-panel {
  flex-shrink: 0; padding: 8px 12px; background: #080808;
  border-bottom: 1px solid #1a1a1a; display: flex; align-items: center; gap: 8px;
}
#upload-form { display: none; gap: 8px; align-items: center; flex-wrap: wrap; }
#upload-panel.open #upload-form { display: flex; }
#upload-form input[type="file"] { color: #ccc; font-size: 12px; max-width: 140px; }
#upload-status { font-size: 12px; opacity: .7; }
```

- [ ] **Step 2: Add the upload-panel HTML**

Find:

```html
<body>
<div id="app">

  <!-- Hidden videos -->
```

Replace with:

```html
<body>
<div id="app">

  <!-- Video upload panel -->
  <div id="upload-panel">
    <button class="ctrl-btn" id="upload-toggle">🔁 Andere Videos</button>
    <form id="upload-form">
      <input type="file" id="file-p1" accept="video/*" required>
      <input type="file" id="file-p2" accept="video/*" required>
      <button type="submit" class="ctrl-btn">Render</button>
      <span id="upload-status"></span>
    </form>
  </div>

  <!-- Hidden videos -->
```

- [ ] **Step 3: Extract `onComparisonLoaded()` and rewrite the init block (DRY)**

Find:

```js
// ── Init ──────────────────────────────────────────────────
fetch('/output/comparison.json')
  .then(r => r.json())
  .then(d => {
    data = d;
    p1s = d.player1.route_start_t ?? 0;
    p2s = d.player2.route_start_t ?? 0;

    buildRail();
    buildStats();
    resize();

    // Jump both to start hold moment
    setRouteTime(0);

    // Highlight start hold
    const startHold = d.route.holds.find(h => h.role === 'start');
    if (startHold) {
      const row = document.querySelector(`[data-id="${startHold.id}"]`);
      if (row) row.classList.add('active');
    }

    loop();
  });
```

Replace with:

```js
// ── Shared setup after comparison.json (re)loads ──────────
function onComparisonLoaded(d) {
  data = d;
  p1s = d.player1.route_start_t ?? 0;
  p2s = d.player2.route_start_t ?? 0;

  buildRail();
  buildStats();
  resize();

  // Jump both to start hold moment
  setRouteTime(0);

  // Highlight start hold
  document.querySelectorAll('.rail-row').forEach(c => c.classList.remove('active'));
  const startHold = d.route.holds.find(h => h.role === 'start');
  if (startHold) {
    const row = document.querySelector(`[data-id="${startHold.id}"]`);
    if (row) row.classList.add('active');
  }
}

// ── Video upload panel ──────────────────────────────────
const uploadPanel  = document.getElementById('upload-panel');
const uploadToggle = document.getElementById('upload-toggle');
const uploadForm   = document.getElementById('upload-form');
const uploadStatus = document.getElementById('upload-status');

uploadToggle.addEventListener('click', () => {
  uploadPanel.classList.toggle('open');
});

uploadForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const p1File = document.getElementById('file-p1').files[0];
  const p2File = document.getElementById('file-p2').files[0];
  if (!p1File || !p2File) return;

  const formData = new FormData();
  formData.append('p1', p1File);
  formData.append('p2', p2File);

  uploadStatus.textContent = 'Lade hoch...';
  fetch('/compare/render', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(({ job_id, error }) => {
      if (error) { uploadStatus.textContent = `Fehler: ${error}`; return; }
      uploadStatus.textContent = 'Verarbeite...';
      pollRenderStatus(job_id);
    })
    .catch(err => { uploadStatus.textContent = `Fehler: ${err}`; });
});

function pollRenderStatus(jobId) {
  fetch(`/compare/status/${jobId}`)
    .then(r => r.json())
    .then(job => {
      if (job.status === 'running') {
        setTimeout(() => pollRenderStatus(jobId), 2000);
      } else if (job.status === 'done') {
        uploadStatus.textContent = 'Fertig!';
        reloadComparisonData();
      } else {
        uploadStatus.textContent = `Fehler: ${job.error || job.status}`;
      }
    });
}

function reloadComparisonData() {
  const bust = Date.now();
  fetch(`/output/comparison.json?t=${bust}`)
    .then(r => r.json())
    .then(d => {
      v1.src = `/output/p1_processed.mp4?t=${bust}`;
      v2.src = `/output/p2_processed.mp4?t=${bust}`;
      onComparisonLoaded(d);
      uploadPanel.classList.remove('open');
    });
}

// ── Init ──────────────────────────────────────────────────
fetch('/output/comparison.json')
  .then(r => r.json())
  .then(d => {
    onComparisonLoaded(d);
    loop();
  });
```

- [ ] **Step 4: Syntax-check and verify in browser**

```bash
python3 -c "
import re
html = open('viewer/compare.html').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/compare_script.js','w').write(m.group(1))
"
node --check /tmp/compare_script.js && echo "JS SYNTAX OK"
```

Expected: `JS SYNTAX OK`.

Then manually in browser at `http://localhost:5001/compare`:
1. Click "🔁 Andere Videos" — the upload form expands below the button.
2. Pick two video files (e.g. the same `player_1_attempt.mov`/`player_2_attempt.mov` from the repo root, or any other video filmed from the same fixed camera setup), click "Render".
3. Status text goes "Lade hoch..." → "Verarbeite..." → "Fertig!" (this takes as long as processing two videos through the pipeline — roughly 20-40s for short clips).
4. The video, rail, and stats refresh to the new comparison without a full page reload.

- [ ] **Step 5: Commit**

```bash
git add viewer/compare.html
git commit -m "Add browser upload panel for swapping comparison videos

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end manual verification

**Files:** none — verification only.

- [ ] **Step 1: Full walkthrough**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
pkill -f "python3 app.py" 2>/dev/null; sleep 1
(python3 app.py > /tmp/flask.log 2>&1 &)
sleep 2
curl -s -o /dev/null -w "compare: %{http_code}\n" http://localhost:5001/compare
```

Expected: `compare: 200`. Open `http://localhost:5001/compare` and check each in order:

1. Page loads at `t +0.0s`, only P1's video visible, no mode button anywhere.
2. Vertical rail visible on the right edge: ▲ (yellow) near top, S (green) near bottom, 8 unlabeled dots between.
3. Drag up/down on the video → route time changes, P2 ghost (50% transparent, no colour tint) appears while the mouse is held, disappears on release.
4. Scroll on the video → fine-grained time changes (no ghost — scroll doesn't press the mouse).
5. Drag up/down on the rail → route time jumps to the dragged position, P2 ghost appears while held, rail fill bar grows/shrinks from the bottom.
6. Click a rail dot/row → both videos jump to ~1.5s before P1 reached that hold, row highlights.
7. "↩ Start" → back to `t +0.0s`, start row highlighted.
8. Click "🔁 Andere Videos" → form expands. Submit with the same two videos again → status cycles "Lade hoch..." → "Verarbeite..." → "Fertig!", viewer refreshes in place.

Expected: all 8 pass.

- [ ] **Step 2: Run the existing Python test suite (regression check)**

```bash
pytest tests/ -v
```

Expected: `4 passed` (these cover `src/balance.py`, unaffected by this plan, but confirm nothing else broke).

- [ ] **Step 3: Final commit if any fixes were needed during verification**

```bash
git add -A
git status --short   # confirm only viewer/compare.html or app.py changed
git commit -m "Fix issues found during end-to-end verification

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

(Skip this commit if Step 1 passed with no code changes.)
