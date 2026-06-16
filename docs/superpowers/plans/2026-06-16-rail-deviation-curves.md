# Deviation Curves in Route Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw two persistent, scrub-synced curves (P1 blue, P2 orange) inside the existing vertical route rail, showing each climber's lateral deviation from their own mean CoM-x position — a graph that "builds up" as you scrub through the route.

**Architecture:** An SVG element (`#rail-curves`) sits inside `#rail`, behind the existing hold-row elements. Two `<polyline>`s (full climb, computed once from `comparison.json`'s already-present `com_path` data) live inside a `<clipPath>` whose reveal height is driven by the same progress fraction that already feeds `#rail-fill`, so scrubbing forward/backward grows/shrinks the visible curve exactly like the existing fill bar.

**Tech Stack:** Vanilla JS + inline SVG in `viewer/compare.html`. No backend changes — `com_path` is already in `comparison.json`.

---

## Spec reference

See `docs/superpowers/specs/2026-06-16-rail-deviation-curves-design.md`.

---

### Task 1: HTML/CSS scaffolding for the SVG curves

**Files:**
- Modify: `viewer/compare.html` (CSS `#rail`/`.rail-row` block, HTML `#rail` markup)

- [ ] **Step 1: Add CSS for the SVG curves**

Find:

```css
.rail-row.active .rail-node { border-color: #fff; color: #fff; background: #2a2a2a; }
.rail-row.is-top   .rail-node { border-color: #ffe44a; color: #ffe44a; }
.rail-row.is-start .rail-node { border-color: #66ff88; color: #66ff88; }
```

Replace with:

```css
.rail-row.active .rail-node { border-color: #fff; color: #fff; background: #2a2a2a; }
.rail-row.is-top   .rail-node { border-color: #ffe44a; color: #ffe44a; }
.rail-row.is-start .rail-node { border-color: #66ff88; color: #66ff88; }

#rail-curves {
  position: absolute; left: 0; top: 0; width: 100%; height: 100%;
  overflow: visible;
}
.curve-p1, .curve-p2 {
  fill: none; stroke-width: 1.5; vector-effect: non-scaling-stroke;
}
.curve-p1 { stroke: #4aaeff; opacity: 0.7; }
.curve-p2 { stroke: #ffaa44; opacity: 0.7; }
```

- [ ] **Step 2: Add the SVG markup inside `#rail`**

Find:

```html
    <div id="rail"><div id="rail-fill"></div></div>
```

Replace with:

```html
    <div id="rail">
      <svg id="rail-curves" viewBox="0 0 100 100" preserveAspectRatio="none">
        <defs>
          <clipPath id="rail-clip">
            <rect id="rail-clip-rect" x="0" y="0" width="100" height="0" />
          </clipPath>
        </defs>
        <g clip-path="url(#rail-clip)" id="rail-curve-group"></g>
      </svg>
      <div id="rail-fill"></div>
    </div>
```

- [ ] **Step 3: Syntax-check**

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

Expected: `OK` (this step only touched HTML/CSS, so the script should still be byte-identical and pass — this just guards against an accidental typo elsewhere).

- [ ] **Step 4: Commit**

```bash
git add viewer/compare.html
git commit -m "Add SVG scaffolding for deviation curves inside route rail

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Compute and draw the curves

**Files:**
- Modify: `viewer/compare.html` (JS: new `climbDeviations()`/`buildDeviationCurves()`, call from `buildRail()`)

- [ ] **Step 1: Add `climbDeviations()` and `buildDeviationCurves()`**

Find:

```js
function buildRail() {
  const holds = data.route.holds;
  railEl.querySelectorAll('.rail-row').forEach(el => el.remove());
```

Replace with:

```js
// ── Deviation curves (lateral wobble vs own mean, per player) ────────────
function climbDeviations(player) {
  const fps = player.fps || 30;
  const routeStart = player.route_start_t;
  const climbCom = player.com_path.filter(
    p => routeStart == null || p.f >= Math.round(routeStart * fps)
  );
  if (climbCom.length === 0) return [];
  const meanX = climbCom.reduce((s, p) => s + p.x, 0) / climbCom.length;
  return climbCom.map(p => ({ y: p.y, dev: p.x - meanX }));
}

function buildDeviationCurves() {
  const holds = data.route.holds;
  const ys = holds.map(h => h.y);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  const p1dev = climbDeviations(data.player1);
  const p2dev = climbDeviations(data.player2);

  const maxAbsDev = Math.max(
    1, // avoid divide-by-zero when a path is perfectly straight
    ...p1dev.map(p => Math.abs(p.dev)),
    ...p2dev.map(p => Math.abs(p.dev)),
  );

  function toPoints(devs) {
    return devs.map(p => {
      const yPct = (p.y - minY) / (maxY - minY) * 100;
      const xPct = 50 + (p.dev / maxAbsDev) * 48; // 48 = leave a small margin
      return `${xPct.toFixed(2)},${yPct.toFixed(2)}`;
    }).join(' ');
  }

  const group = document.getElementById('rail-curve-group');
  group.innerHTML = '';

  const poly1 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  poly1.setAttribute('points', toPoints(p1dev));
  poly1.setAttribute('class', 'curve-p1');
  group.appendChild(poly1);

  const poly2 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  poly2.setAttribute('points', toPoints(p2dev));
  poly2.setAttribute('class', 'curve-p2');
  group.appendChild(poly2);
}

function buildRail() {
  const holds = data.route.holds;
  railEl.querySelectorAll('.rail-row').forEach(el => el.remove());
```

- [ ] **Step 2: Call `buildDeviationCurves()` from `onComparisonLoaded()`**

Find:

```js
  buildRail();
  buildMetrics();
  resize();
```

Replace with:

```js
  buildRail();
  buildDeviationCurves();
  buildMetrics();
  resize();
```

- [ ] **Step 3: Syntax-check**

```bash
python3 -c "
import re
html = open('viewer/compare.html').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/compare_script.js','w').write(m.group(1))
"
node --check /tmp/compare_script.js && echo OK
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add viewer/compare.html
git commit -m "Compute and draw per-player deviation curves in the rail

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Sync the reveal clip to scrub progress

**Files:**
- Modify: `viewer/compare.html:222-231` (`updateRouteTime()`)

- [ ] **Step 1: Update `updateRouteTime()` to also drive the clip rect**

Find:

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

Replace with:

```js
function updateRouteTime() {
  const rt = routeTime();
  document.getElementById('route-time').textContent = `t +${rt.toFixed(1)}s`;

  // Fill the rail from the bottom (route start) up to the current position
  const maxDur = maxRouteTime();
  if (maxDur > 0) {
    const pct = Math.min(100, rt / maxDur * 100);
    document.getElementById('rail-fill').style.height = pct + '%';
    // Reveal the deviation curves from the bottom up, in lockstep with rail-fill
    document.getElementById('rail-clip-rect').setAttribute('y', 100 - pct);
    document.getElementById('rail-clip-rect').setAttribute('height', pct);
  }
}
```

- [ ] **Step 2: Syntax-check**

```bash
python3 -c "
import re
html = open('viewer/compare.html').read()
m = re.search(r'<script>(.*)</script>', html, re.S)
open('/tmp/compare_script.js','w').write(m.group(1))
"
node --check /tmp/compare_script.js && echo OK
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add viewer/compare.html
git commit -m "Sync deviation-curve reveal clip to scrub progress

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: End-to-end verification

**Files:** none — verification only.

- [ ] **Step 1: Restart server and confirm data shape**

```bash
cd /Users/brunogross/Documents/Studium/01_semester/6_semester/1_lean_design/lean_after_reframing/scrolling-poc/.worktrees/two-climber
lsof -ti:5001 | xargs kill -9 2>/dev/null; sleep 1
(python3 app.py > /tmp/flask.log 2>&1 &)
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5001/compare
curl -s http://localhost:5001/output/comparison.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('player1 com_path len:', len(d['player1']['com_path']))
print('player2 com_path len:', len(d['player2']['com_path']))
print('sample point:', d['player1']['com_path'][0])
"
```

Expected: `200`, both `com_path` lengths > 0, sample point shaped like `{'f': 0, 'x': ..., 'y': ...}`.

- [ ] **Step 2: Manual browser check**

Open `http://localhost:5001/compare`. Confirm:
1. Two thin colored lines (blue, orange) are visible inside the rail, weaving left/right around the central spine.
2. At `t +0.0s` (page load / after "↩ Start"), the curves are fully hidden (clip height 0%) — only the spine and hold dots are visible.
3. Drag up on the video (or rail) to scrub forward — the curves grow upward from the bottom in lockstep with the `rail-fill` bar.
4. Drag back down toward the start — the curves shrink back down, same as `rail-fill`.
5. Hold dots/nodes remain fully visible and clickable on top of the curves (not obscured).
6. No JS console errors.

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git status --short   # confirm only viewer/compare.html changed
git commit -m "Fix issues found during end-to-end verification

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

(Skip this commit if Steps 1-2 passed with no code changes.)
