# Press-and-Hold-Vergleich + vertikale Route-Rail — Design

**Datum:** 2026-06-16
**Branch:** `two-climber`
**Ziel:** Ersetzt den bisherigen Dauer-Overlay-Modus ("Beide"/Mode-Button) und die horizontale Hold-Timeline in `viewer/compare.html` durch das im Climbrr-Designdokument beschriebene Interaktionsmodell: Standardmäßig nur das eigene Video (P1), Vergleich (P2) erscheint nur, solange man gedrückt hält. Die Route wird über eine vertikale Rail am Bildrand abgefahren statt über eine horizontale Leiste unten.

## Kontext

Nutzer-Feedback nach dem ersten Scrub-PoC (siehe `2026-06-16-com-scrub-poc-design.md`): Das Dauer-Overlay beider Videos ("Beide"-Modus mit Warmton-Blend) wirkt "verschmolzen" und unübersichtlich. Die horizontale Hold-Timeline unterhalb des Videos fühlt sich falsch platziert an. Das ursprüngliche Climbrr-Designdokument (`research/# Climbrr — Video-Analyse & Material-3-Sheets/`) beschreibt bereits die richtige Lösung für beide Punkte: Hold-to-Compare-Gesture (Abschnitt 4) und vertikale Strecken-Rail (Abschnitt 2) — beide waren in der ersten PoC-Spec bewusst aus dem Scope genommen worden.

## Entscheidungen aus dem Brainstorming

| Frage | Entscheidung |
|---|---|
| Default-Ansicht | Nur P1, volle Breite |
| Ghost-Inhalt beim Halten | P2s komplettes Video, halbtransparent (kein zweites separates Video-Fenster, kein Parameter-Punkt-only) |
| Warmton-Filter | Entfällt komplett — nur Transparenz, keine Farbüberlagerung |
| Mode-Button (👁 Beide/P1/P2) | Entfernt — Press-and-Hold ersetzt ihn vollständig |
| Timeline-Platzierung | Vertikale Route-Rail am Bildrand statt horizontaler Leiste unten |
| Rail-Inhalt | Pro Hold weiterhin P1-Zeitpunkt (blauer Punkt) + P2-Zeitpunkt (oranger Punkt), wie bisher in der horizontalen Timeline |
| Horizontaler Progress-Balken unten | Entfernt — Rail übernimmt diese Funktion (zeigt Fortschritt + ist selbst Scrubber) |

## Was bleibt unverändert

- `setRouteTime(rt)` als einzige Quelle der Wahrheit für die Videoposition (aus dem letzten PoC)
- Maus-Drag-Scrub auf dem Video (`mousedown`/`mousemove`/`mouseup` auf `#stage`)
- Scrollrad-Scrub auf dem Video
- "↩ Start"-Button
- Stats-Kacheln (Routenzeit / CoM-Pfad) unterhalb des Videos
- Hold-Tap-Sprung (`jumpToHold`) — wandert nur von der horizontalen Timeline auf die Rail
- Keine Backend-/Pipeline-Änderungen

## Was sich ändert

### 1. Press-and-Hold-Gesture (`viewer/compare.html`)

Ein neuer State `holding` (boolean), gesetzt auf `mousedown` über `#stage` ODER `#rail`, zurückgesetzt im globalen `mouseup`-Listener — unabhängig davon, wo losgelassen wird (wie im Designdokument beschrieben: `holding`, gesetzt in `onDown`, zurückgesetzt im globalen `pointerup`).

`mousedown` auf `#stage` setzt **gleichzeitig** `dragging = true` (für Scrub) **und** `holding = true` (für Ghost-Anzeige) — beide Gesten sind während eines gedrückten Mausklicks gleichzeitig aktiv: man kann durch die Route ziehen, während der Vergleich eingeblendet ist.

`drawFrame()` zeichnet:
```
P1 immer, volle Deckkraft.
Wenn holding: P2 zusätzlich, alpha ≈ 0.5, kein Blend-Filter, kein Farbüberlagerung.
```

Der `#mode-btn` und die `MODES`/`modeIdx`-Variablen werden komplett entfernt.

### 2. Vertikale Route-Rail (ersetzt `#timeline`/`#hold-track` und `#route-progress`)

Neues Element `#rail`, absolut positioniert am rechten Rand von `#stage` (z.B. `right: 12px; top: 40px; bottom: 40px; width: 28px`).

**Positionierung der Holds:** Direkte Skalierung der existierenden `hold.y`-Pixelwerte aus `routes/green_route.json` (Top-Hold y=55 klein, Start-Hold y=818 groß) auf die Rail-Höhe:

```js
function holdRailPct(hold, holds) {
  const ys = holds.map(h => h.y);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  return (hold.y - minY) / (maxY - minY) * 100; // 0% = TOP oben, 100% = START unten
}
```

Das ist eine direkte Übertragung der vorhandenen `buildTimeline()`-Sortierung (`b.y - a.y`) von einer horizontalen `left`-Prozent-Position auf eine vertikale `top`-Prozent-Position — keine neue Dateninfrastruktur nötig.

**Pro Hold-Reihe** (vormals `.hcol`, jetzt horizontal statt vertikal angeordnet): linker Punkt = P1-Touch (blau, wenn `hold_events` einen Eintrag hat), Mitte = Hold-Node (Touch-Status), rechter Punkt = P2-Touch (orange). Klick auf die Reihe ruft weiterhin `jumpToHold(hold.id)` auf.

**Fortschritts-Fill:** Ein Balken/Linie innerhalb der Rail von `START` (unten) bis zur aktuellen Scrub-Position wird im Akzent eingefärbt — ersetzt den bisherigen `#rp-fill`. Berechnung: aktuelle `routeTime()` als Bruchteil von `maxRouteTime()`, von unten nach oben gefüllt (da unten = 0, oben = `maxRouteTime()`).

**Rail als Scrubber:** `mousedown`/`mousemove` auf `#rail` setzt `holding = true` (Ghost erscheint) und berechnet `rt` aus der vertikalen Cursor-Position:

```js
function railEventToRt(e) {
  const rect = railEl.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
  return (1 - frac) * maxRouteTime(); // oben (frac=0) = maxRouteTime, unten (frac=1) = 0
}
```

### 3. Entfernte CSS/HTML

- `#timeline`, `#tl-label`, `#hold-track`, `.hcol`, `.hdot*`, `.hnode` (CSS-Klassen werden für die neue `.rail-row`-Struktur wiederverwendet/umbenannt, nicht 1:1 entfernt — siehe Implementierungsplan)
- `#route-progress`, `#rp-fill`
- `#mode-btn`

## Nicht im Scope

- Textueller Hinweis "● Vergleich mit P2" (wie im Designdokument beschrieben) — nicht angefragt, kann später ergänzt werden
- Touch-Events (Smartphone) — Zielgerät bleibt Laptop/Maus (siehe vorherige Spec)
- Gestrichelter Erstnutzungs-Hinweis-Pfeil ("☟ Zum Vergleich gedrückt halten") aus dem Designdokument — nicht angefragt
- Lösung des Top-Hold-Erkennungsproblems (Routenzeit-Stat bleibt `—`) — separates, bereits dokumentiertes Problem

## Erfolgskriterium

Tester öffnet `compare.html`: sieht nur P1 in voller Breite plus eine vertikale Rail rechts mit Hold-Punkten. Drag/Scroll auf dem Video bewegt die Route wie bisher. Hält man die Maustaste (auf Video oder Rail) gedrückt, erscheint P2 transparent darüber — ohne Farbfilter, ohne dass das Bild "verschmilzt" wirkt wie zuvor. Loslassen blendet P2 wieder aus.
