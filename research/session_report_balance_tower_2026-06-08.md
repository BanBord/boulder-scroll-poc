# Session Report — Balance Tower & CoM Visualisierung
**Datum:** 2026-06-08  
**Branch:** `weight-distribution`  
**Status:** Implementiert, visuell getestet, bereit für Merge

---

## Was wurde gemacht

### Problem der vorherigen Session
Das Balance-Panel (OpenCV, horizontale Balken + Bälle) funktionierte nicht:
- Alle Targets konstant bei `304.0` (Fallback) — Keypoints meist `None`
- Formel `arm_x - com_x` produziert nahe-0-Werte beim Klettern (Arme strecken sich *vertikal*, nicht seitwärts)
- `fallen`-State wurde nie getriggert
- OpenCV-Rendering zu statisch, keine echte Physik

### Neue Architektur

**Daten-Pipeline (`src/pipeline.py`)**
- `_balance_targets()` ersetzt durch `_balance_data()` mit CoM-zentrischen Signalen:
  - `arm = com_x − arm_midpoint` (Wrists 9,10) — wie weit ist der CoM von den Griffen?
  - `leg = com_x − foot_midpoint` (Knöchel 15,16; Knie 13,14 als Fallback) — CoM über den Füßen?
  - `com = com_x − out_w/2` — absolute Position im Bild
- Pipeline schreibt JSON-Sidecar (`*_balance.json`) mit per-Frame-Daten
- Kein OpenCV-Panel mehr im Video — Physik lebt im Browser

**Flask App (`app.py`)**
- Neue Route `/balance/<filename>` dient den JSON-Sidecar aus
- `balance_json_path` wird an Pipeline übergeben
- Job-Status enthält `balance`-Feld nach erfolgreichem Render

**Viewer (`viewer/index.html`)**
- Canvas-Overlay (`position:absolute;inset:0`) über dem Video
- Balance-Toggle (Checkbox) zum Ein/Ausblenden
- **Physics Engine** (vanilla JS, kein p5.js):
  - Zwei Layer: `armLayer` (halfW=90, ballR=14) und `legLayer` (halfW=76, ballR=18)
  - Spring-Damper pro Layer: Ball rollt durch Schwerkraft (`g·sin θ`), Balken kippt durch Drehmoment (`ball_x · cos θ · τ`)
  - Soft data push: YOLO-Daten nudgen den Ball zur Zielposition gegen die Physik
- **Video-Synchronisation**: `video.currentTime` → Frame-Index → Binary Search in JSON → Targets
- Physik läuft unabhängig vom Video bei 60fps (rAF)

### Tower-Struktur (visuell)
```
     [Bein-Ball]          ← rollt auf Achse 2
  ─────────────────       ← Achse 2 (liegt auf Arm-Ball)
     [Arm-Ball]           ← rollt auf Achse 1
  ─────────────────       ← Achse 1 (liegt auf CoM-Ball)
     [CoM-Ball]           ← Basis, bewegt sich mit Körperschwerpunkt
```
Referenz-Inspiration: gestapelte Balance-Steine, physikalisch korrektes Kippverhalten.

### Daten-Qualität (v5_short.mov, 43s)
| Signal | Range | Frames mit Daten |
|--------|-------|-----------------|
| `arm`  | -34..+158 px | 393/449 (87%) |
| `leg`  | -95..+89 px  | 391/393 (99%) — Knie-Fallback |
| `com`  | -110..+429 px | 393/449 (87%) |

`leg` verbesserte sich von ~50% auf 99% durch Knie-Fallback (kp 13,14).

---

## Research: CoM-Visualisierung für Nutzergruppen

Recherche zu wissenschaftlicher Literatur (MDPI Sensors, PMC, ScienceDirect):

### Was die Forschung macht
- **CoM-Trajektorie als Linie** — roter Punkt + Schweif über Zeit (bereits implementiert)
- **Trajektorienlänge als Performance-Indikator** — kürzere CoM-Pfade = effizienter (Eric Hörst, TrainingForClimbing)
- **6 Bewegungsfehler** (MDPI Sensors 2023) die Anfänger von Experten unterscheiden: Arm-Entkopplung, Gewichtsverlagerung, Hüft-Wand-Abstand, Schulterblockierung u.a.
- **Elite-Kletterer**: größere Wanddistanz während dynamischer Phasen, systematische CoM-Oszillationen

### Nutzergruppen-orientierte Visualisierungen
| Zielgruppe | Empfohlene Visualisierung |
|------------|--------------------------|
| Kletterer selbst | Balance-Turm (emotional, intuitiv) — bereits gebaut |
| Trainer | CoM-Pfadlänge + Fehlererkennung, quantitativ |
| Zuschauer/Publikum | CoM-Spur auf der Route, farbkodiert |
| Forschung | Radar-Chart über mehrere Metriken, Zeitreihen |

### Zwei-Kletterer-Vergleich (nächste Phase)
Stärkste Idee: **CoM-Pfad auf der Route** — beide Kletterer hinterlassen eine farbige Linie durch die Route. Kürzere, glattere Linie = effizienter. Sofort lesbar ohne Erklärung.

Technische Herausforderung: **Synchronisation nach Routenfortschritt** statt Zeit (unterschiedliche Geschwindigkeiten).

---

## Offene Punkte / Next Steps

1. **CoM-Werte > Bildbreite** — `com_out` kann > 540px sein wenn CoM außerhalb Crop-Fenster; Clamping einbauen
2. **Zwei-Kletterer-Vergleich** — Pipeline für zwei Videos auf gleicher Route, überlagerte CoM-Pfade
3. **Fortschritt-Alignment** — synchronisieren nach Routenposition (% der Route), nicht nach Zeit
4. **Balance-Turm Physik-Tuning** — Bälle wirken noch etwas träge; `PHY.torque` und `PHY.gravity` eventuell erhöhen
5. **Hold-Tracking** wieder aufnehmen (Branch `claude/amazing-kilby-47a127`) für vollständige Integration

---

## Output-Dateien
- `output/v5_balance_demo.mp4` — finales Demo-Video (540×960, Skeleton + CoM)
- `output/v5_balance_demo_balance.json` — JSON-Sidecar mit Balance-Daten
