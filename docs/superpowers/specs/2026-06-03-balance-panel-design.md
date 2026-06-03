# Balance Panel — Gewichtsverteilung Overlay
**Datum:** 2026-06-03  
**Branch:** weight-distribution

---

## Ziel

Ein emotionales, physikbasiertes Overlay das die Körpergewichtsverteilung eines Boulderkletterers als Balance-Spiel visualisiert. Zielgruppe sind keine Datenanalysten — die Darstellung soll intuitiv fühlbar sein, nicht ablesbar.

---

## Visuelles Design

### Panel-Layout
- **Position:** fix am unteren Rand des Output-Frames (540×960px), immer vollständig sichtbar
- **Höhe:** 220px
- **Hintergrund:** semi-transparentes dunkles Rechteck (opacity ~0.55)

### Drei Elemente

| Element | Radius | Bedeutung | Datenquelle |
|---|---|---|---|
| Arm-Ball | 22px | Horizontaler Schwerpunkt der Arme | Median x der Handgelenke (kp 9, 10) relativ zu CoM |
| Bein-Ball | 28px | Horizontaler Schwerpunkt der Beine | Median x der Knöchel (kp 15, 16) relativ zu CoM |
| CoM-Ball | 38px | Gesamt-Körperschwerpunkt (Anker) | CoM.x relativ zu Bildmitte |

- **Arm-Ball** gleitet auf einer horizontalen Linie (obere Linie im Panel)
- **Bein-Ball** gleitet auf einer zweiten Linie darunter
- **CoM-Ball** sitzt zwischen den Linien und dem unteren Rand, minimal bewegt
- Vertikale Verbindungslinie CoM-Ball → Bein-Linie als visueller Anker

### Farbe
Alle Elemente in der bestehenden Grün-Palette (`#50C832` / BGR `(50,200,50)`), konsistent mit CoM-Dot und Skeleton.

---

## Physik-Modell

### Klassen: `PhysicsState` in `src/balance.py`

Jeder Ball hat: `pos` (aktuell), `vel` (Geschwindigkeit), `target` (Zielposition aus Pose-Daten).

**Update-Regel pro Frame (Spring-Damper):**
```
acc = (target - pos) * stiffness - vel * damping
vel += acc
pos += vel
```

### Drei Zustände

| Zustand | Trigger | stiffness | damping | Beschreibung |
|---|---|---|---|---|
| `STABLE` | CoM-Varianz (30fr) < 8px | 0.08 | 0.85 | Träge, glatte Bewegung |
| `UNSTABLE` | CoM-Varianz ≥ 8px | 0.15 | 0.55 | Reaktiver, spürbar nervös |
| `FALLEN` | CoM-Sprung > 40px/frame **oder** YOLO-conf < 0.15 | 0.0 | 0.98 | Bälle rollen mit letzter Velocity auseinander, frieren nach ~60 Frames ein |

### Varianz-Berechnung
Rolling window der letzten 30 CoM-x-Positionen → Standardabweichung.

---

## Implementierung

### Neue Datei: `src/balance.py`
- `PhysicsState` Klasse
  - `__init__(panel_cx, panel_w)` — initialisiert drei Ballzustände
  - `update(arm_target, leg_target, com_target, com_variance, is_fallen)` → updated Physics pro Frame
  - `get_positions()` → `{arm: (x,y), leg: (x,y), com: (x,y)}`

### Änderung: `src/overlay.py`
- Neue Funktion `draw_balance_panel(frame, positions, panel_y_start)`
  - Zeichnet Hintergrund-Panel, Linien, drei Bälle, Labels

### Änderung: `src/pipeline.py`
- Neuer Parameter `show_balance: bool = False`
- `PhysicsState` Instanz vor dem Loop anlegen
- Pro Frame: Targets aus Keypoints berechnen, `state.update()`, `draw_balance_panel()`
- CoM-Varianz: deque(maxlen=30) der CoM-x-Werte

### Änderung: `app.py`
- `show_balance` aus Form-Submit lesen, an `_run()` und `pipeline.run()` weitergeben

---

## Nicht im POC (bewusst ausgelassen)
- Vertikale Achse der Bälle (nur horizontal im POC)
- Sturz-Animation mit Partikel-Effekten
- Sound
- Konzept 1 (Diamant/Matrix) — separat user-testen, nicht gleichzeitig implementiert
