# CoM-Kennzahlen-Leiste (Pfadlänge, Wackeln, Flow) — Design

**Datum:** 2026-06-16
**Branch:** `two-climber`
**Ziel:** Ersetzt die entfernte, kaputte Stats-Leiste (`P2 NaN% effizienter`) durch eine funktionierende Kennzahlen-Leiste unterhalb des Videos, basierend auf den Schwerpunkt-Konzepten aus `research/deep-research-report_visualsierung.md`.

## Kontext

Die alte Stats-Leiste (`#winner`, entfernt in Commit `c1e0cd3`) berechnete `com_path_length / route_duration` als "Effizienz" — das brach mit `NaN`, weil `route_duration` `null` ist, solange die Top-Hold-Erkennung nicht jeden Kletterer als "Route beendet" erkennt (bekanntes, separates Problem). Die neue Leiste verwendet ausschließlich Metriken, die unabhängig von `route_duration` sind.

## Entscheidungen aus dem Brainstorming

| Frage | Entscheidung |
|---|---|
| Reicht der bestehende CoM-Punkt+Trail im Video? | Nein, zusätzlich eine Kennzahlen-Leiste unterhalb des Videos |
| Welche Metriken? | Pfadlänge, seitliches Wackeln (beide bereits vorhanden), Flow/geometrische Entropie (neu) |
| Trittfestigkeit (BoS) mit aufnehmen? | Nein — nicht im Scope |
| Trail-Länge im Video verlängern (über 40 Frames)? | Nein — nicht angefragt, bleibt wie es ist |

## Was bleibt unverändert

- CoM-Punkt + 40-Frame-Trail im Video (`draw_skeleton()` in `src/overlay.py`) — unverändert
- `_com_path_length()`, `_com_lateral_jitter()` in `src/compare.py` — unverändert, nur ein neues Feld kommt dazu
- Keine neue Python-Dependency (konvexe Hülle wird in reinem Python implementiert, kein `scipy`/`numpy` nötig in `compare.py`)

## Was sich ändert

### 1. Backend: `_com_geometric_entropy()` (`src/compare.py`)

Neue Funktion, die die geometrische Entropie nach Cordier et al. berechnet: `GE = ln(2L/C)`, wobei `L` die bereits vorhandene Pfadlänge ist und `C` der Umfang der konvexen Hülle des CoM-Pfads (Punkte `{x, y}` in Source-Pixeln).

```python
def _convex_hull(points):
    """Monotone-chain convex hull. points: list of (x, y). Returns hull as list of (x, y), CCW order."""
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


def _com_geometric_entropy(com_path: list) -> float | None:
    """
    Geometric entropy of the CoM trail (Cordier et al.): GE = ln(2L / C),
    L = path length, C = perimeter of the path's convex hull.
    Lower = straighter / more fluid path. Returns None if degenerate
    (fewer than 3 unique points, or zero-perimeter hull).
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

`build_player()` ruft das zusätzlich auf und legt das Ergebnis unter `com_flow` ab (neben den bestehenden `com_path_length`/`com_lateral_jitter`-Feldern). `None` bleibt `None` in der JSON-Ausgabe (JS muss damit umgehen, siehe unten) — kein künstlicher Default, der eine falsche Zahl suggeriert.

### 2. Frontend: `#metrics`-Leiste (`viewer/compare.html`)

Neue Sektion unterhalb von `#stage` (an der Position, wo früher `#winner` war), eine Zeile pro Metrik:

```html
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
```

`buildMetrics()` (ersetzt das entfernte `buildStats()`) füllt jede Zeile aus `data.player1`/`data.player2`. Für jede Metrik gilt: niedriger = besser (kürzerer Pfad = effizienter, weniger Wackeln = stabiler, niedrigere Entropie = flüssiger). Ist einer der beiden Werte `null` oder `undefined`, zeigt die Zeile `—` für beide Seiten statt zu rechnen — es gibt keinen Pfad, der zu einer `NaN`- oder `Infinity`-Anzeige führen kann, weil nirgendwo dividiert wird (im Gegensatz zur alten `l1/d1`-Logik).

```js
const METRICS = [
  { key: 'com_path_length',   label: 'Pfadlänge' },
  { key: 'com_lateral_jitter', label: 'Wackeln' },
  { key: 'com_flow',          label: 'Flow' },
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
```

Aufruf: `onComparisonLoaded()` ruft `buildMetrics()` statt des entfernten `buildStats()`.

## Nicht im Scope

- Trittfestigkeit/Base-of-Support-Berechnung
- Verlängerung der In-Video-Trail-Länge über 40 Frames
- Routenzeit-Vergleich (war die Quelle des NaN-Bugs, bleibt draußen)
- Jerk-basierte Glättungs-Metrik (Alternative zur geometrischen Entropie im Doc) — Entropie reicht für den PoC

## Erfolgskriterium

Tester öffnet `compare.html`: unterhalb des Videos erscheinen drei Zeilen (Pfadlänge, Wackeln, Flow) mit echten Zahlen für P1 und P2, der jeweils bessere Wert ist farblich hervorgehoben. Kein `NaN`, kein `Infinity`, keine kaputte Anzeige — fehlt eine Metrik, steht dort `—`.
