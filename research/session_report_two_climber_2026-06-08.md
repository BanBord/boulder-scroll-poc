# Session Report — Two-Climber Comparison
**Datum:** 2026-06-08  
**Branch:** `two-climber`  
**Status:** Vergleich funktioniert, Compositing als nächster Schritt

---

## Was wurde gemacht

### Branch-Konsolidierung
- `weight-distribution` (Balance-Turm) → `main` gemergt (fast-forward)
- `claude/amazing-kilby-47a127` (Hold-Tracking) → `main` gemergt (Konflikte in `pipeline.py` + `app.py` manuell gelöst)
- Neuer Worktree `two-climber` von `main` (30f3786)

### Route-Definition
- `routes/green_route.json`: 10 grüne Holds aus `wall_bg.jpg` (Frame 0 von `player_1_attempt.mov`) extrahiert
- Koordinaten in Source-Space 1080×1920
- Hold 0 = TOP (oben), Hold 9 = Start-Hold (Hände)
- Radius 80px für distanzbasierte Kontakt-Detection

### Pipeline-Erweiterungen (`src/pipeline.py`)
- `route_json_path` Parameter: lädt pre-saved Holds statt SAM → kein MobileSAM-Download nötig
- `com_src` (sx, sy) wird jetzt in Balance-JSON exportiert (Source-Koordinaten, nicht Output-Coords)
- Detection-Condition: `show_skeleton OR show_balance OR track_holds`

### `src/contact.py`
- `check_contacts_distance()`: distanzbasierter Contact-Check für pre-saved Holds (keine SAM-Masken)

### `src/compare.py`
- Verarbeitet beide Videos, speichert `p1_processed.mp4` + `p2_processed.mp4` (mit Skeleton, Scrolling)
- `_route_start()`: erkennt `route_start_t` — beide Handgelenke gleichzeitig auf Start-Hold (≥3 Frames), Fallback auf erste Einzelhand
- `_hold_progress()`: Hold-Events (wann wurde welcher Hold zuerst berührt)
- `_com_path_length()`: Gesamtlänge des CoM-Pfades in Source-Pixeln
- `_com_lateral_jitter()`: Std-Abweichung der X-Koordinate (Seitwärtsbewegung)
- Output: `output/comparison.json` mit route_start_t, route_duration, com_path_length, com_lateral_jitter

### `viewer/compare.html`
- Single-Canvas Overlay: P1 normal, P2 als Ghost (50% + Warmton)
- Route-Zeit-Sync: beide Videos laufen auf Route-Zeit (T = video_time - route_start_t)
- Hold-Timeline: Holds als horizontale Marker, Klick springt beide Videos
- Stats: "P2 Xs schneller" + "P2 X% effizienter"
- Toggle: Beide / P1 / P2
- Mobile-first Layout

### Ergebnisse der Comparison

| Metrik | Player 1 | Player 2 |
|--------|----------|----------|
| Erste Hold-Berührung | Hold 7, t=1.6s | Hold 9 (Start), t=2.7s |
| Letzte Hold-Berührung | Hold 1, t=32.4s | Hold 1, t=14.0s |
| CoM-Frames | 1122 | 531 |
| Hold-Events | 7 | 7 |

Player 2 ist deutlich schneller (~18s Differenz bis Hold 1).

---

## Offene Probleme

### 1. route_start_t Detection zu früh
**Problem:** Player 1 testet Hold kurz bevor echter Attempt-Start → `route_start_t` feuert beim Testen, nicht beim echten Klettern.  
**Lösung A (sofort):** Manuell in `comparison.json` korrigieren.  
**Lösung B (robust):** Nach Hold-Kontakt prüfen ob Knöchel Y-Koordinate innerhalb 2s signifikant steigt (Füße verlassen Boden).

### 2. Overlay-Qualität
**Problem:** Full-Frame-Blend sieht unübersichtlich aus — beide Kletterer verschmelzen visuell.  
**Lösung:** Person-Segmentierung (YOLO-Seg `yolov8n-seg.pt`) → nur P2's Silhouette compositen, Hintergrund von P2 transparent.

---

## Nächste Schritte (priorisiert)

1. **Two-Layer-Compositing** (Hauptziel nächste Session):
   - `yolov8n-seg.pt` für P2-Person-Maske
   - `src/compositor.py`: Source-Videos frame-by-frame compositen (route-time aligned)
   - P2 farbig getönt (z.B. Blau), P1 normal → Ein Output-Video
   - Pipeline-Run auf Composite (Scrolling folgt P1's CoM)

2. **route_start_t Robustheit** (Option B):
   - Ankle-Y-Anstieg als Bestätigung dass echter Attempt startet

3. **Viewer-Polish** (nach Compositing):
   - Route-Zeit-Anzeige verfeinern
   - Hold-Timeline zeigt Zeitdifferenz zwischen P1 und P2 pro Hold

---

## Output-Dateien
- `output/p1_processed.mp4` — Player 1 Scrolling + Skeleton
- `output/p2_processed.mp4` — Player 2 Scrolling + Skeleton  
- `output/comparison.json` — CoM-Pfade, Hold-Events, Sync-Daten
- `output/wall_bg.jpg` — Referenz-Frame für Hold-Koordinaten
- `routes/green_route.json` — 10 Holds der grünen Route
