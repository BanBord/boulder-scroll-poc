# Session Report — Boulder Scrolling POC
**Datum:** 2026-06-02 (Session 2)  
**Projekt:** Lean Design / Scrolling POC  
**Ziel:** Y-Tracking-Fix, Web App mit Upload-Interface, Skeleton + CoM-Overlay, GitHub-Setup

---

## Was wir gemacht haben

### Ausgangslage
- Bestehende Pipeline aus Session 1: YOLO-Erkennung, EMA-Smoothing, Kalibrierung, H.264-Output
- Zwei offene Probleme: Y-Tracking falsch (Wand scrollt nicht), Web-Viewer-Slider tot
- Neue Anforderungen: Video-Upload-Interface, Feintuning-Controls, Skelett + CoM-Visualisierung

---

### Fix 1 — Y-Tracking wiederhergestellt (`src/pipeline.py`) ✅

**Problem:** `fixed_cy` hielt die Kamera auf einer fixen Höhe. Boulderer driftete beim Hochklettern nach oben aus dem Frame.

**Lösung:** `smooth_cy` verfolgt jetzt die Hüftposition genau wie `smooth_cx`:

```python
# Vorher (falsch):
smooth_cx, _ = smooth_position((hip_x, fixed_cy), (smooth_cx, fixed_cy), alpha=...)

# Nachher (korrekt):
smooth_cx, smooth_cy = smooth_position((hip_x, hip_y), (smooth_cx, smooth_cy), alpha=...)
cropped = crop_fixed(frame, smooth_cx, smooth_cy, ...)
```

`fixed_cy` bleibt als Warm-Start-Wert erhalten, damit kein Sprung am Anfang entsteht.

**Effekt:** Person bleibt vertikal zentriert. Als der Boulderer hochklettert, scrollt die Wand von unten nach oben durch den Frame — das gewünschte „Klettern miterleben"-Erlebnis.

---

### Fix 2 — Web-Viewer-Slider repariert (`viewer/index.html`) ✅

**Problem:** Slider reagierte nicht, da `!vid.duration` auch bei `NaN` `true` zurückgibt — blockierte alle Seeks solange das Video nicht geladen war. Kein Error-Feedback.

**Lösung:**
- Scrubber startet mit `disabled`, wird erst nach `loadedmetadata`-Event aktiviert
- Check `isNaN(vid.duration) || vid.duration === 0` statt nur `!vid.duration`
- `vid.addEventListener('error', ...)` für Diagnose ergänzt

---

### Fix 3 — `serve.py` hinzugefügt ✅

Minimalskript um HTTP-Server auf Port 8080 zu starten und Browser automatisch zu öffnen:

```bash
python3 serve.py   # → öffnet http://localhost:8080/viewer/index.html
```

---

### Schritt 4 — Flask Web App (`app.py`) ✅

Neue vollständige Web App mit Backend:

**Routen:**
- `GET /` → Viewer-HTML
- `POST /render` → Video-Upload + Parameter → startet Pipeline im Background-Thread → gibt `job_id` zurück
- `GET /status/<job_id>` → JSON mit Fortschritt (`progress`, `total`, `status`, `output`)
- `GET /output/<filename>` → serviert gerendertes Video

**Pipeline-Erweiterungen:**
- `progress_callback(frame, total)` — wird alle 10 Frames aufgerufen, Frontend pollt `/status` alle 500ms
- `max_seconds` — rendert nur N Sekunden (für Quick-Preview)

**Port-Konflikt behoben:** macOS AirPlay Receiver belegt Port 5000 → App läuft auf **5001**

```bash
python3 app.py   # → http://localhost:5001
```

---

### Schritt 5 — Erweiterter Viewer mit Controls-Panel (`viewer/index.html`) ✅

Linke Spalte mit:
- **Drag & Drop / Datei-Picker** für beliebige MP4/MOV-Dateien
- **Zoom-Slider** (40–85% Framehöhe)
- **Kamera-Smoothing-Slider** (0.05–0.40)
- **Skeleton-Checkbox** „Skelett + CoM einblenden"
- **Render-Button** mit Fortschrittsbalken
- Automatische Videowiedergabe nach Render-Abschluss

---

### Schritt 6 — Skeleton + CoM-Overlay ✅

**Drei neue/erweiterte Komponenten:**

**`src/detector.py` — `detect_all()`:**  
Einmaliger YOLO-Aufruf pro Frame der alle Daten zurückgibt: Hüftmittelpunkt, 17 Keypoints (x/y), Konfidenz-Array, CoM.

**`src/reframer.py` — `transform_keypoints()`:**  
Transformiert YOLO-Keypoints von Source-Frame-Koordinaten in Output-Frame-Koordinaten:
```python
out_x = (source_x - crop_x1) * (out_w / crop_w)
out_y = (source_y - crop_y1) * (out_h / crop_h)
```

**`src/overlay.py` — `draw_skeleton()`:**
- COCO-Skeleton-Linien (15 Edges: Arme, Beine, Torso, Kopf)
- Joint-Dots (17 Keypoints, Konfidenz ≥ 0.2)
- CoM-Punkt: großer grüner Kreis (`#59ff7a`)
- CoM-Trail: letzten 40 Frames als Schweif mit Fade-Effekt
- Fallback: Wenn keine Keypoints erkannt → nur CoM-Dot am Hüftpunkt
- Blend: 82% Overlay-Opacity über Originalbild

**CLI-Flag:**
```bash
python3 run.py --skeleton
```

---

### Schritt 7 — GitHub-Setup ✅

```
Repo: https://github.com/BanBord/boulder-scroll-poc (privat)
Branch: main
```

`.gitignore` schließt aus: `*.mp4`, `*.mov`, `*.pt`, `output/`, `uploads/`, `.DS_Store`, `.superpowers/`

Feature-Workflow:
```bash
git checkout -b feature/<name>   # neuer Branch
gh pr create                      # Pull Request öffnen
```

---

## Aktueller Stand

| Komponente | Status |
|---|---|
| Y-Tracking (Wand scrollt) | ✅ funktioniert |
| Web-Viewer Slider | ✅ funktioniert |
| Flask Web App (Upload + Render) | ✅ funktioniert |
| Progress-Anzeige | ✅ funktioniert |
| Skeleton + CoM-Overlay | ✅ funktioniert |
| CoM-Trajektorien-Schweif | ✅ funktioniert |
| GitHub / main-Branch | ✅ eingerichtet |
| Two-Layer-Compositing | ❌ noch nicht |
| Hold-Tracking | ❌ noch nicht |
| Gewichtsverteilung Extremitäten | ❌ noch nicht |

---

## Konfigurierbare Parameter (aktuell)

| Parameter | Default | CLI | Web-Slider |
|---|---|---|---|
| `SMOOTHING_ALPHA` | 0.10 | `--alpha` | ✅ |
| `PERSON_FILL_TARGET` | 0.65 | `--fill` | ✅ |
| `SHOW_SKELETON` | False | `--skeleton` | ✅ Checkbox |
| `max_seconds` | None (full) | — | — (noch nicht im UI) |
| `OUTPUT_WIDTH/HEIGHT` | 540×960 | `--width/height` | — |

---

## Roadmap / Nächste Schritte

### Kurzfristig

**1. Quick-Preview im Web-Interface**  
Slider „Vorschau: X Sekunden" → rendert nur N Sekunden für schnelles Parameter-Testen. Backend-Support (`max_seconds`) ist bereits implementiert, fehlt nur der UI-Slider.

**2. Skeleton-Styling**  
Links/rechts farbkodieren: LH=Blau, RH=Orange, LF=Hellblau, RF=Hellorange. Macht Bewegungsanalyse lesbarer.

**3. Mehrere Videos in der Sidebar**  
Aktuell nur ein Video gleichzeitig. Sidebar mit Video-Liste und `+`-Button für weitere Videos.

---

### Mittelfristig — Analyse-Layer

#### Hold-Tracking + Contact-Timeline

Größtes Feature. Vollständiger Plan:

**Phase 1 — Hold-Detection (einmalig pro Video)**  
- SAM (Segment Anything Model) auf Referenz-Frame
- Holds filtern nach Farbe, Größe, Position
- Hold-IDs + Polygone in `holds.json` speichern

```json
{ "holds": [
    { "id": 1, "center": [210, 340], "color": "#e03a3a", "polygon": [...] }
]}
```

**Phase 2 — Kontakt-Erkennung (frame-by-frame)**  
- YOLO-Keypoints: Handgelenke (9/10) + Knöchel (15/16)
- Proximity-Check: Keypoint innerhalb Hold-Maske = Kontakt
- Hysterese gegen Flackern
- Output: `contacts.json` pro Frame

**Phase 3 — Keyframe-Extraktion**  
- Keyframe = Kontakt-Status ändert sich (Hold gegriffen/losgelassen)
- Cluster <5 Frames auseinander zusammenfassen

**Phase 4 — Timeline UI**  
Vier Spuren (LH / RH / LF / RF) mit Farb-Sprache:

| Extremität | Farbe |
|---|---|
| Linke Hand | Blau `#4a9eff` |
| Rechte Hand | Orange `#ff7a3a` |
| Linker Fuß | Hellblau `#a0cfff` |
| Rechter Fuß | Hellorange `#ffb07a` |

- Kontakt-Blöcke klickbar → Video springt zu Keyframe
- Lücken = kein Kontakt (Umgreifen, Fallen)

---

#### Gewichtsverteilung Extremitäten

Approximiertes biomechanisches Modell:
- Basis: CoM-Position relativ zu den aktiven Kontaktpunkten
- Inverse Distanz-Gewichtung: je näher CoM an Kontaktpunkt, desto mehr Gewicht
- Live-Update während Video läuft

UI: Körper-Silhouette (konsistent mit Skeleton-Overlay) mit Prozentzahlen an vier Extremitäten.

---

#### Two-Layer-Compositing (YOLO-Seg + Hintergrund-Scroll)

Saubererer Ansatz als Crop-Fenster:
1. Person per `yolov8n-seg.pt` segmentieren → Alpha-Maske pro Frame
2. Person-Layer: immer zentriert, immer gleiche Größe
3. Hintergrund-Layer: scrollt basierend auf Personenposition
4. Compositing: Person über Hintergrund legen

Vorteil: keine schwarzen Ränder bei Randpositionen, echter Ebenen-Effekt, kein Jitter bei YOLO-Aussetzern.

---

## Verwendete Technologien

- **Python 3.14** · **Flask 3.x** · **Ultralytics YOLOv8** (`yolov8n-pose.pt`) · **OpenCV** · **NumPy** · **tqdm**
- **HTML/CSS/JavaScript** — Viewer + Web App
- **GitHub** — Versionskontrolle (`BanBord/boulder-scroll-poc`, privat)

## Starten

```bash
# Web App (empfohlen)
python3 app.py          # → http://localhost:5001

# CLI
python3 run.py          # Standard-Render
python3 run.py --skeleton   # mit Skeleton + CoM

# Standalone Viewer (ohne Flask)
python3 serve.py        # → http://localhost:8080/viewer/index.html
```
