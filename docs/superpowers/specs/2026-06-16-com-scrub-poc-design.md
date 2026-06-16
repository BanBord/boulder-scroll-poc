# Schwerpunkt-Vergleichs-PoC für User-Testing — Design

**Datum:** 2026-06-16
**Branch:** `two-climber`
**Ziel:** Technischer PoC für User-Testing, der das Climbrr-Designkonzept (`research/# Climbrr — Video-Analyse & Material-3-Sheets/`) mit echten Videodaten umsetzt — zwei Personen klettern dieselbe grüne Route, Schwerpunkt (CoM) wird verglichen.

## Kontext

Die Datenpipeline (`src/compare.py`, `src/pipeline.py`, `routes/green_route.json`) liefert bereits CoM-Pfade, Hold-Events und `route_start_t` pro Spieler. Der bestehende Viewer (`viewer/compare.html`) nutzt Play/Pause. Das Climbrr-Designdokument beschreibt stattdessen ein Scrubbing-Modell ("Ziehen = Route abfahren"). Dieser PoC überträgt das Scrubbing-Modell auf die echte Datenpipeline, mit minimalem Aufwand ("bug-arm").

## Entscheidungen aus dem Brainstorming

| Frage | Entscheidung |
|---|---|
| Basis-Code | Bestehenden `two-climber`-Code erweitern, nicht neu bauen |
| Parameter-Scope | Nur Schwerpunkt (CoM) |
| Zielgerät | Laptop/Desktop, Maus |
| Route-Rail vs. Scrub-Balken | Einfacher Scrub-Balken (bestehender `#route-progress`) |
| Kamera-Setup | Fixierte Kamera für beide Testvideos → eine gemeinsame `green_route.json` reicht, keine Pro-Video-Kalibrierung nötig |
| Sync-Modell P1/P2 | Gleiche verstrichene Zeit seit `route_start_t` (bereits implementiert) |
| Overlay | CoM-Punkt + komplettes Skelett (nicht nur CoM) |

## Was bleibt unverändert

- `src/compare.py` Datenpipeline: CoM-Pfade, Hold-Events, `route_start_t`, `comparison.json`
- `routes/green_route.json`: eine Route-Datei für beide Videos (Kamera fix während der Aufnahme)
- `app.py` / `serve.py` Server-Setup
- Hold-Timeline in `compare.html` (Tippen zum Springen — setzt bereits direkt `currentTime`, bleibt kompatibel)
- Sync-Modell `v2.currentTime = v1.currentTime - p1s + p2s`

## Was sich ändert

### Vorbereitender Schritt: Uncommitted-Diff sichern
Im `two-climber`-Worktree liegen unkommittete Änderungen (robusterer `route_start_t` via Doppelhand-Streak, `com_path_length`, `com_lateral_jitter`, persistente `output/p1_processed.mp4`/`p2_processed.mp4` statt Temp-Dateien). Diese sind Grundlage für die Stats-Anzeige im Viewer und werden zuerst committed, bevor neue Änderungen draufgesetzt werden.

### `src/compare.py` — keine Änderung nötig
Geprüft: `draw_skeleton()` (`src/overlay.py:99-159`) zeichnet den CoM-Punkt + Trail bereits mit, wenn `show_skeleton=True` (aktuelle Konfiguration in `_run_player()`). Der ursprünglich geplante `show_com=True`-Zusatz entfällt — er würde ohnehin nie greifen, da `pipeline.py:203` ein `elif show_com` ist (nur relevant wenn `show_skeleton=False`).

### `viewer/compare.html` — Scrub-Steuerung statt Play/Pause
- **Play/Pause-Button entfällt.**
- **Maus-Drag auf dem Video (`#stage`):** `mousedown` startet Drag, `mousemove`-Delta-Y wird in Sekunden umgerechnet (Kalibrierung z.B. 200px ≈ 1s) und auf `v1.currentTime` addiert/subtrahiert; `v2.currentTime` folgt über das bestehende Sync-Modell.
- **Scrollrad (`wheel`-Event) über `#stage`:** feinere Schrittweite, gleiche Zielvariable wie Drag.
- **`#route-progress`-Balken:** bleibt bestehen, wird zum direkten Klick/Drag-Scrubber für absolute Sprünge (Klick-Position → Sekunden via `maxDur`-Mapping, das bereits in `updateRouteTime()` für die Füllbreite genutzt wird).
- **`requestAnimationFrame`-Loop:** bleibt für Redraw/Compositing bestehen, reagiert aber nur noch auf `currentTime`-Änderungen statt auf eine laufende Wiedergabe (`v1.paused` wird nicht mehr als Gate für die Sync-Logik gebraucht, da kein "Play"-Zustand mehr existiert — Sync läuft immer, sobald `currentTime` sich ändert).
- **Mode-Toggle (Beide/P1/P2):** bleibt unverändert.

## Nicht im Scope

- Route-Rail (vertikale Streckenkarte mit Hold-Pips)
- Hold-to-Compare-Geist (gedrückt halten zum Einblenden)
- Weitere Parameter (Trittfestigkeit, Arm & Schulter, Kraft, Flüssigkeit)
- Mobile/Touch-Unterstützung
- Pro-Video-Hold-Kalibrierung (setzt fixierte Kamera für beide Testaufnahmen voraus)

## Erfolgskriterium für den User-Test

Zwei Testpersonen klettern dieselbe grüne Route vor fixierter Kamera. `compare.py` erzeugt `comparison.json` + Output-Videos. Eine Testperson öffnet `compare.html` im Laptop-Browser und kann durch Ziehen oder Scrollen die Route abfahren, dabei den Schwerpunkt beider Kletterer (CoM-Punkt + Skelett) im Vergleich sehen, inklusive Zeit- und CoM-Pfad-Stats.
