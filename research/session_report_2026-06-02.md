# Session Report — Boulder Scrolling POC
**Datum:** 2026-06-02  
**Projekt:** Lean Design / Scrolling POC  
**Ziel:** Video Reframing von Boulder-Aufnahmen mit Person als fixem Ankerpunkt

---

## Was wir gemacht haben

### Ausgangslage
- Einzelnes Boulder-Video `v5_attempt.mp4` (360×640px, ~55 Sekunden, Portrait)
- Figma-Screens als visuelle Referenz (3 PNGs in `visual_idea/`)
- Ziel: Person immer zentriert, Wand scrollt — "Klettern miterleben"-Gefühl

### Schritt 1 — Grundpipeline (funktioniert ✅)
Aufgebaut mit Python + OpenCV + Ultralytics YOLO:

```
src/detector.py    — YOLO Pose Wrapper
src/reframer.py    — Crop + Smoothing
src/overlay.py     — CoM Dot + Crosshairs
src/pipeline.py    — Hauptloop
run.py             — Einstiegspunkt mit Konfiguration oben
```

**Was funktioniert:**
- YOLO (yolov8n-pose.pt) detectiert die Person stabil in allen Frames
- Exponential Moving Average (EMA) Smoothing verhindert Jitter
- CoM-Berechnung aus gewichteten COCO-Keypoints (Hüfte 30%, Schultern 20%, ...)
- Progress-Bar via tqdm
- Output: `output/scrolling_output.mp4`

### Schritt 2 — Auto-Zoom (funktioniert ✅)
**Problem erkannt:** Output-Frame (540×960) war größer als Quellvideo (360×640) → Person winzig mit schwarzem Rahmen überall.

**Lösung:** Crop-Region kleiner als Output, dann upscale:
- `crop_h = bbox_h / TARGET_FILL`
- `crop_w = crop_h * (out_w / out_h)`
- Region ausschneiden → auf Output-Auflösung hochskalieren

Visuelles Ergebnis: Person füllt ~65% der Framehöhe. Wall sichtbar.

### Schritt 3 — Kalibrierungsbasierte feste Brennweite (funktioniert ✅)
**Problem erkannt:** Dynamischer Zoom aus Schritt 2 pulsiert — YOLO gibt je nach Pose (Arme oben/unten) unterschiedliche bbox_h zurück.

**Lösung:** Zweiphasige Pipeline:
1. **Kalibrierungspass** (60 Sample-Frames): `np.percentile(bbox_heights, 90)` = canonical person height
2. **Hauptpass**: Fixer `crop_h` und `crop_w` für alle Frames — nur Position (cx, cy) wird getracked

Kalibrierungswerte für `v5_attempt.mp4`:
- Canonical person height: **241px**
- Vertical anchor Y: **295px** (Median Hüftposition)
- Fixed crop: **208×370px**

### Schritt 4 — X-Only Centering + Hüftpunkt-Anker (implementiert, visuell noch nicht verifiziert)
**Konzept:** Person soll horizontal zentriert bleiben, Wand scrollt vertikal durch als Person hochklettert.

**Änderungen:**
- `detect_hip_center()`: Nutzt COCO-Keypoints 11+12 (Hüfte L/R) statt bbox-Mitte → stabiler, wird nicht von ausgestreckten Armen beeinflusst
- `calibrate()`: Sammelt jetzt auch Y-Positionen (Hüftpunkt)
- Pipeline: `smooth_cx` wird getracked, `fixed_cy = median hip Y` bleibt fest

### Schritt 5 — Interaktiver Web-Viewer (gebaut, aber nicht funktionsfähig ❌)
`viewer/index.html` mit vertikalem Range-Slider + Video-Scrubbing.

**Was nicht funktioniert:**
- **Codec-Problem**: OpenCV schreibt mit `mp4v` (MPEG-4 Part 2) → wird von Browsern nicht nativ unterstützt. Fix: auf `avc1` (H.264) umgestellt → Datei jetzt 3.9MB statt vorher 9.2MB ✓
- **CORS/file:// Problem**: Browser blockiert lokale Video-Requests wenn HTML via `file://` geöffnet. Fix: Python HTTP-Server auf Port 8080 gestartet
- **Slider liefert keine Interaktion**: Trotz Server und H.264 kein Feedback. Ursache unklar — möglicherweise JavaScript-Problem, Video nicht richtig geladen, oder Browser-spezifisches Issue. **Nicht gelöst.**

---

## Was funktioniert

| Feature | Status |
|---------|--------|
| YOLO Person-Erkennung | ✅ stabil |
| EMA Position-Smoothing | ✅ |
| Kalibrierung (feste Brennweite) | ✅ |
| Hüftpunkt-Tracking | ✅ (implementiert) |
| CoM-Overlay (Dot + Crosshairs) | ✅ |
| H.264 Video-Output | ✅ |
| Web-Viewer HTML | ✅ gebaut |
| Web-Viewer Slider-Interaktion | ❌ nicht funktionsfähig |

---

## Offene Konzeptfrage: Zwei-Ebenen-Ansatz

Gegen Ende der Session haben wir diskutiert, dass der aktuelle Crop-Ansatz nicht ganz das gewünschte Erlebnis erzeugt. Das eigentliche Ziel:

> **Layer 1 (Personenebene):** Person immer fix in Frame-Mitte, immer gleiche Größe  
> **Layer 2 (Hintergrundebene):** Boulderwand scrollt hinter der Person — von unten nach oben

Der aktuelle Ansatz (Crop + Resize) erzeugt zwar einen ähnlichen Effekt, aber:
- Person ist nicht wirklich "herausgelöst" — es ist nur ein verschobener Ausschnitt
- Bei schnellen Bewegungen oder wenn YOLO die Person nicht erkennt: Sprünge sichtbar
- Kein echter Ebenen-Effekt

**Für einen echten Zwei-Ebenen-Ansatz** wäre nötig:
- Segmentierungsmodell (YOLO-seg oder SAM) um Person vom Hintergrund zu trennen
- Person als eigene Textur/Layer auf festem Canvas
- Hintergrund als scrollende zweite Schicht

---

## Nächste mögliche Schritte

### Kurzfristig (PoC weiterführen)

**1. Web-Viewer reparieren**  
Das Video lädt nicht korrekt. Debug-Schritte:
- Prüfen ob `video.readyState` im Browser-Console > 0 ist
- Prüfen ob `video.error` einen Fehler wirft
- Alternative: OpenCV-basierter Desktop-Viewer mit `cv2.createTrackbar` (kein Browser, garantiert funktionsfähig)
- Alternative: Video als Base64 in HTML einbetten (keine Serverpfad-Probleme)

**2. Visuelles Fine-Tuning**  
- `--fill` Wert testen: `python3 run.py --fill 0.55` für mehr Wandkontext
- Smoothing-Alpha anpassen: `--alpha 0.2` für langsamere Kamera
- Testen mit verschiedenen Boulder-Videos

**3. Echter Zwei-Ebenen-Compositing**
```python
# Grobe Idee:
# 1. Segmentierung
from ultralytics import YOLO
seg_model = YOLO("yolov8n-seg.pt")

# 2. Pro Frame:
#    - Background: originaler Frame mit Person-Bereich geblurrt/ausgefüllt
#    - Person: Maske auf Originalframe angewandt → Person-Cutout
#    - Output: Background scrollt basierend auf Personenposition, Person fix in Mitte
```

**4. Analyse-Layer**  
- CoM-Trajektorie als Linie über Zeit (Pfad der vergangenen N Frames einblenden)
- Statische "Route-Map": alle Frames überlagert als Panorama → zeigt gesamte Kletterroute
- Kinematic-Daten aus Keypoints exportieren (Winkel, Geschwindigkeit)

### Mittelfristig

**Produktive Webapplikation**  
Statt statischer HTML-Seite: React/Next.js App mit:
- Video-Upload
- Echtzeit-Processing-Feedback
- Zwei-Ebenen-Renderer auf `<canvas>`
- Scrub-Interface mit Routen-Visualisierung

---

## Technische Details / Konfiguration

**Aktuell konfigurierbare Parameter** (in `run.py`):

| Parameter | Default | Bedeutung |
|-----------|---------|-----------|
| `SMOOTHING_ALPHA` | 0.1 | Kamera-Reaktivität (0.1=träge, 0.4=reaktiv) |
| `PERSON_FILL_TARGET` | 0.65 | Person füllt 65% der Framehöhe |
| `OUTPUT_WIDTH` | 540 | Ausgabe-Breite px |
| `OUTPUT_HEIGHT` | 960 | Ausgabe-Höhe px (9:16 Format) |
| `SHOW_COM` | False | CoM-Overlay ein/aus |

**CLI-Beispiele:**
```bash
python3 run.py                          # Standard
python3 run.py --fill 0.55             # Mehr Wandkontext sichtbar
python3 run.py --fill 0.80             # Näher herangezoomt
python3 run.py --alpha 0.25            # Reaktivere Kamera
python3 run.py --input anderes_video.mp4 --output output/neu.mp4
```

---

## Verwendete Technologien

- **Python 3.14**
- **Ultralytics YOLOv8** (`yolov8n-pose.pt`) — Person-Detection + Pose Estimation
- **OpenCV** (`cv2`) — Video I/O, Bildverarbeitung
- **NumPy** — Berechnungen
- **tqdm** — Progress Bar
- **HTML/CSS/JavaScript** — Web-Viewer (in Arbeit)
