# Wackel-Kurven in der Rail — Design

**Datum:** 2026-06-16
**Branch:** `two-climber`
**Ziel:** Visualisiert die seitliche Abweichung (gleiche Größe wie `com_lateral_jitter` und die im Video eingebrannte Abweichungslinie) zusätzlich als zwei farbige Kurven direkt in der vertikalen Route-Rail — ein dauerhaft sichtbarer "Graph" statt nur einer Zahl oder einer Momentaufnahme im Video.

## Kontext

Nutzer-Feedback nach der In-Video-Abweichungslinie: gut sichtbar (nach Farbanpassung), aber man sieht nur den aktuellen Moment. Gewünscht ist ein Graph, der sich beim Scrubben aufbaut und den ganzen bisherigen Verlauf zeigt — X-Achse = Routenfortschritt, Y-Achse = Abweichung. Da die Route-Rail bereits eine vertikale Fortschritts-Achse hat (Top oben, Start unten), wird die Kurve dort integriert statt als separates Element.

## Entscheidungen aus dem Brainstorming

| Frage | Entscheidung |
|---|---|
| Graph-Ort | Eigenes Chart-Element im Viewer (JS), kein Pipeline-Eingriff |
| Y-Wert | Signierte Abweichung (`x - mean_x`), nicht nur Betrag |
| P1/P2 gleichzeitig? | Ja, beide Kurven gleichzeitig (blau/orange) |
| Achsen-Orientierung | X-Achse = Routenfortschritt (vertikal, wie die Rail), nicht Zeit |
| Platzierung | In die bestehende Hold-Rail integriert, nicht als neuer Streifen |

## Was bleibt unverändert

- Backend (`src/compare.py`, `src/pipeline.py`) — keine Änderung, alle benötigten Daten (`com_path` pro Spieler) sind schon in `comparison.json`
- Hold-Pips, Klick-zum-Springen (`jumpToHold`), Rail-Drag-Scrubbing — unverändert, Kurven werden nur zusätzlich darunter gezeichnet
- In-Video-Abweichungslinie (`draw_deviation` in `src/overlay.py`) — bleibt bestehen, ist eine separate, schon abgeschlossene Visualisierung derselben Idee

## Was sich ändert

### 1. Mittelwert + Abweichung pro Frame berechnen (`viewer/compare.html`, JS)

Neue Funktion, spiegelt die Filterlogik von `_com_lateral_jitter()`/`climb_com` aus `src/compare.py` (nur Frames ab `route_start_t`):

```js
function climbDeviations(player, route_start_t) {
  const fps = player.fps || 30;
  const climbCom = player.com_path.filter(
    p => route_start_t == null || p.f >= Math.round(route_start_t * fps)
  );
  if (climbCom.length === 0) return [];
  const meanX = climbCom.reduce((s, p) => s + p.x, 0) / climbCom.length;
  return climbCom.map(p => ({ y: p.y, dev: p.x - meanX }));
}
```

### 2. SVG-Kurven in `#rail` (HTML + JS)

`#rail` bekommt ein `<svg>`-Kind, das die beiden Polylinien zeichnet, hinter den `.rail-row`-Elementen (niedrigerer DOM-Order = weiter hinten, da `.rail-row` mit `position:absolute` sowieso über dem SVG liegt solange es nach dem SVG im DOM steht):

```html
<div id="rail">
  <svg id="rail-curves" preserveAspectRatio="none"></svg>
  <div id="rail-fill"></div>
  <!-- .rail-row Elemente werden wie bisher per JS angehängt -->
</div>
```

`buildRail()` ruft zusätzlich eine neue Funktion `buildDeviationCurves()` auf:

```js
function buildDeviationCurves() {
  const holds = data.route.holds;
  const ys = holds.map(h => h.y);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  const p1dev = climbDeviations(data.player1, data.player1.route_start_t);
  const p2dev = climbDeviations(data.player2, data.player2.route_start_t);

  const maxAbsDev = Math.max(
    1, // avoid divide-by-zero
    ...p1dev.map(p => Math.abs(p.dev)),
    ...p2dev.map(p => Math.abs(p.dev)),
  );

  const svg = document.getElementById('rail-curves');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.innerHTML = '';

  function toPoints(devs) {
    return devs.map(p => {
      const yPct = (p.y - minY) / (maxY - minY) * 100;
      const xPct = 50 + (p.dev / maxAbsDev) * 48; // 48 = leave a small margin
      return `${xPct.toFixed(2)},${yPct.toFixed(2)}`;
    }).join(' ');
  }

  const poly1 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  poly1.setAttribute('points', toPoints(p1dev));
  poly1.setAttribute('class', 'curve-p1');
  svg.appendChild(poly1);

  const poly2 = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  poly2.setAttribute('points', toPoints(p2dev));
  poly2.setAttribute('class', 'curve-p2');
  svg.appendChild(poly2);
}
```

CSS:

```css
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

### 3. "Baut sich auf" — Clip an den aktuellen Scrub-Fortschritt koppeln

Ein `<clipPath>` mit einem `<rect>`, dessen Höhe exakt wie der bestehende `#rail-fill`-Balken berechnet wird (gleiche Prozent-Formel: `routeTime() / maxRouteTime() * 100`, von unten gemessen — da unten = Routenstart):

```html
<svg id="rail-curves" preserveAspectRatio="none">
  <defs>
    <clipPath id="rail-clip">
      <rect id="rail-clip-rect" x="0" y="0" width="100" height="0" />
    </clipPath>
  </defs>
  <g clip-path="url(#rail-clip)">
    <!-- polylines werden hier von buildDeviationCurves() eingehängt -->
  </g>
</svg>
```

`buildDeviationCurves()` hängt die beiden `<polyline>`-Elemente in das `<g clip-path="...">` statt direkt ins `<svg>`.

`updateRouteTime()` bekommt eine Zeile dazu, direkt neben der bestehenden `rail-fill`-Höhenberechnung:

```js
function updateRouteTime() {
  const rt = routeTime();
  document.getElementById('route-time').textContent = `t +${rt.toFixed(1)}s`;

  const maxDur = maxRouteTime();
  if (maxDur > 0) {
    const pct = Math.min(100, rt / maxDur * 100);
    document.getElementById('rail-fill').style.height = pct + '%';
    // Clip grows from the bottom (route start) upward, mirroring rail-fill
    document.getElementById('rail-clip-rect').setAttribute('y', 100 - pct);
    document.getElementById('rail-clip-rect').setAttribute('height', pct);
  }
}
```

Scrubt man zurück, schrumpft das Clip-Rechteck wieder mit — die Kurve "verschwindet" rückwärts genauso, wie der Rail-Fill-Balken es heute schon tut. Das ist bewusst dasselbe Verhalten wie der Rest der App (reaktiv auf den aktuellen Scrub-Stand, keine "Einbahnstraßen-Historie").

## Nicht im Scope

- Achsen-Beschriftung/Legende im Chart selbst (Farbcodierung blau=P1/orange=P2 ist im Rest der App schon etabliert)
- Tooltip/Hover-Werte auf der Kurve
- Glättung der Kurve (Bezier) — rohe Polyline reicht für den PoC

## Erfolgskriterium

In der Rail erscheinen zwei dünne farbige Linien (blau/orange), die links/rechts der Mittelachse ausschlagen, je nachdem wie stark der jeweilige Kletterer von seiner eigenen durchschnittlichen seitlichen Position abweicht. Beim Scrubben nach oben (Richtung Top) wächst die sichtbare Kurve von unten nach oben mit; beim Zurückscrubben schrumpft sie wieder. Hold-Punkte bleiben weiterhin klar erkennbar und klickbar über den Kurven.
