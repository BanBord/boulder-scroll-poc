# Session Report — Wall Scan v1
**Datum:** 2026-06-30
**Branch:** main (vorgesehen für commit nach Validierung)
**Status:** Phase 1 implementiert, manuelle Validierung im Browser ausstehend

---

## Was wurde implementiert

### Backend
- `src/hold_detector.py` — `mask_to_polygon()` Helper; `polygon`-Feld an jedes Hold-Dict; `mat_zone_frac` als Parameter konfigurierbar (Default 0.92 für Climb-Videos, im Scan-Use-Case auf 1.0 gesetzt).
- `src/wall_scan.py` — neue Datei:
  - `extract_hold_color()` — Lab-Median über die hellste Hälfte der chromatischsten 30 % Pixel innerhalb der erodierten Maske. Zwei-Stufen-Filter schützt gegen Schatten/Wand-Pollution.
  - `cluster_routes()` — greedy Single-Link in Lab-Space (eps=18, min_samples=3). Sortiert nach Größe.
  - `assign_start_top()` — Bottom-Cluster-Heuristik: tiefstes Hold + ggf. zweites Hold (≤12 % Bildhöhe + ≤25 % Bildbreite Abstand) als Doppelstart; höchstes Hold als Top.
  - `scan()` — Orchestrator; `draw_overlay()` für Debug-PNG.
  - Achromatische Holds (chroma < 14) werden vor dem Clustering ausgesondert.
- `tools/scan_wall.py` — CLI, schreibt JSON + skalierte Debug-Overlay-PNG.

### Frontend
- `viewer/scan.html` — mobile-first Layout:
  - Upload-Landing mit File-Picker
  - `<img>` + überlagertem `<canvas>`
  - Modi `all` / `route` mit weißem Glow-Outline und doppeltem Außenring (grün=start, rot=top) im route-Modus
  - Tap-to-select-Route, Tap außerhalb → zurück
  - Bottom-Sheet reagiert auf state (Anzahl Routes vs. Route #N)
  - Hover-Tooltip mit Hold-Metadaten (Debug-Hilfe in Phase 1)

### Flask
- `POST /scan` (sync, ~10s) → Upload → `wall_scan.scan()` → JSON
- `GET /scan` → liefert die Viewer-Page
- `GET /scan_json/<id>` → Sidecar
- `GET /uploads/<file>` → das Original-Bild

### Tests
- `tests/test_hold_filters.py` — 11 Tests (4 neue für `mask_to_polygon`, 1 neu für `mat_zone_frac`)
- `tests/test_wall_scan.py` — 13 Tests: Color-Extraktion, Clustering (3 Farben, Noise, Sortierung), Start/Top (single/double/no-double/single-hold/empty), Lab→Hex

---

## Erste Lab-Beobachtungen (`visual_idea/Wall_Holds_img.png`, 2160×3840)

| Iteration | Routes | Notiz |
|---|---|---|
| eps=14, median Lab | 9 | viele Routen, alle dunkel (#4d2f29 etc.) |
| + chroma-top-50 % | 5 | besser, aber L noch zu niedrig |
| + L-top-50 % von chroma-top-50 % | 4 | erstes brauchbares Orange (#ca653c) |
| + chroma-top-30 % | **6** | aktuell: Blau/Rot/Mauve/Blau/Olive/Orange |

Aktuelle Hex-Werte:
- `#394b6f` (Blau, 10 Holds)
- `#542d24` (Rot/Braun, 9 Holds)
- `#704f5c` (Mauve, 4)
- `#2b3b5d` (Blau, 4)
- `#a08d44` (Olive, 3)
- `#ce663a` (Orange, 3)

Beobachtungen:
- **Blau spaltet sich in zwei Cluster** (3947 vs. 2b3b) — vermutlich Mid-Blau vs. Dark-Blau auf der Wand. Tuning: eps auf 22 erhöhen, oder a/b ohne L gewichten.
- **Yellows fehlen** — das markante Gelb der Wand wird nicht als eigene Route geclustert. Wahrscheinlich weil L sehr hoch, a/b nahe Neutral → einzelne Holds rutschen unter `_MIN_CHROMA=14` durch. Vermutlich auch wegen kleiner Anzahl (< 3).
- **Orange ist klar erkannt** (#ce663a) — Beweis dass die Pipeline korrekt funktioniert, sobald genug saturierte Pixel da sind.

---

## Validierung (TODO — durch User)

### Bild 1: `visual_idea/Wall_Holds_img.png`
- [ ] Browser-Test: Glow-Outlines auf allen sichtbaren Holds?
- [ ] Anzahl Routes plausibel (Erwartung 5–8)?
- [ ] Tap auf gelben Hold → Route lights up?
- [ ] Tap auf blauen Hold → korrekte Route gewählt?
- [ ] Start-Holds (grüner Außenring) sitzen am Wandfuß?
- [ ] Top-Holds (roter Außenring) sitzen oben?
- Notizen:

### Bild 2: (eigene Aufnahme einfügen)
- [ ] …
- Notizen:

### Bild 3: (eigene Aufnahme einfügen)
- [ ] …
- Notizen:

---

## Bekannte Limitationen / Phase-2-Kandidaten

1. **Helle Holds (Gelb, Weiß) rutschen durch das Chroma-Filter.** Lösung: zusätzliches Helligkeits-Cluster (sehr helle Holds = eigene Route).
2. **SAM segmentiert Schatten als eigene Maske.** Diese landen aktuell als `route_id=null` ("noise") im Overlay als graue Outlines. UX-Frage: ausblenden oder dezent anzeigen?
3. **Volume-Holds (große Wandstrukturen)** mit niedriger Chroma werden ggf. ausgesondert oder spalten in Mini-Cluster. Lösung: separater Size-Class-Detektor.
4. **Bottom-Sheet aktuell statisch** — Drag-Sheet, Carousel zwischen Routen, "Edit Route"-Modus mit Pencil sind für Phase 1.5 vorgesehen.
5. **`Start Sending!` CTA ist ein Dummy** — verlinkt noch nichts; Phase 2 soll das Climb-Pipeline an die Route binden.

---

## Output-Dateien
- `output/scan_test.json` — letzte Scan-JSON
- `output/scan_test_overlay.png` — Debug-Visualisierung
