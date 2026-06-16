# Abweichungs-Linie im Video — Design

**Datum:** 2026-06-16
**Branch:** `two-climber`
**Ziel:** Visualisiert die bereits existierende "Wackeln"-Kennzahl (`com_lateral_jitter`) direkt im Video als eine gestrichelte Ideallinie (Mittelwert der eigenen CoM-X-Position) plus eine Verbindungslinie, die die aktuelle seitliche Abweichung zeigt.

## Kontext

Die Kennzahlen-Leiste (`docs/superpowers/specs/2026-06-16-com-metrics-design.md`) zeigt "Wackeln" nur als Zahl. Nutzer-Feedback: das soll auch räumlich im Video sichtbar werden — eine Ideallinie (eigener Mittelwert der seitlichen Position) und die Abweichung davon.

## Entscheidungen aus dem Brainstorming

| Frage | Entscheidung |
|---|---|
| Visualisierungs-Ort | Im Video eingebrannt (Pipeline-Render-Zeit), nicht als separates Chart |
| Ideallinie-Definition | Mittelwert der eigenen CoM-X-Position (identisch zur Basis von `com_lateral_jitter`) |
| Mittelwert-Strategie | Leichter Vorab-Durchlauf (nur Pose-Erkennung, kein Schreiben), dann normaler Render-Durchlauf mit bekanntem Mittelwert |

## Was bleibt unverändert

- `_com_lateral_jitter()` in `src/compare.py` — unverändert, bleibt die numerische Kennzahl in der Leiste
- CoM-Punkt + Trail (`draw_skeleton()`) — unverändert
- `app.py`s `/render`-Endpoint — neuer Parameter ist optional mit Default `False`, kein Effekt auf bestehende Aufrufer

## Was sich ändert

### 1. `estimate_mean_com_x()` (`src/pipeline.py`)

Neue Funktion, leichter Vorab-Durchlauf über das ganze Video (nur Pose-Erkennung, kein `VideoWriter`, kein Overlay-Zeichnen). Sammelt CoM-X (Source-Pixel) pro Frame, gibt den Mittelwert zurück. Nutzt den vom Aufrufer übergebenen `Detector`, um das YOLO-Modell nicht doppelt zu laden.

```python
def estimate_mean_com_x(input_path: str, detector) -> float | None:
    """
    Run pose detection once over the whole video (no drawing/writing) to get
    the mean horizontal CoM position in source pixels — used as the reference
    'ideal line' x for the deviation overlay in the main render pass.
    """
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    xs = []
    for _ in range(total):
        ok, frame = cap.read()
        if not ok:
            break
        _, _, _, com_src = detector.detect_all(frame)
        if com_src is not None:
            xs.append(com_src[0])
    cap.release()
    if not xs:
        return None
    return sum(xs) / len(xs)
```

### 2. `run()` bekommt `show_deviation` (`src/pipeline.py`)

Neuer optionaler Parameter `show_deviation: bool = False`. Wenn gesetzt: vor der Hauptverarbeitung (direkt nach `detector = Detector()`, vor der Kalibrierung) wird `estimate_mean_com_x()` aufgerufen, Ergebnis in `mean_com_x` gespeichert (kann `None` sein, wenn keine Erkennung gelang — dann wird einfach nichts gezeichnet, kein Crash).

Im Hauptloop, innerhalb des bestehenden `if show_skeleton:`-Blocks, direkt nach der `com_out`-Berechnung:

```python
            if show_deviation and mean_com_x is not None:
                ideal_x_out = to_out(mean_com_x, smooth_cy)[0]
                draw_deviation(cropped, com_out, ideal_x_out)
```

Voraussetzung: `show_deviation=True` wirkt nur, wenn auch `show_skeleton=True` ist (gleiche Bedingung wie für den CoM-Punkt selbst) — kein separater Pfad nötig.

### 3. `draw_deviation()` (`src/overlay.py`)

Neue Zeichenfunktion neben `draw_com()`/`draw_skeleton()`:

```python
_IDEAL_LINE_CLR = (180, 180, 180)  # light grey, dashed reference line
_DEVIATION_CLR  = (255, 255, 255)  # white connector


def draw_deviation(frame: np.ndarray, com_out, ideal_x: float) -> np.ndarray:
    """Dashed vertical reference line at the climber's mean lateral position,
    plus a short connector from the current CoM to that line."""
    if com_out is None:
        return frame
    h, w = frame.shape[:2]
    ix = int(round(ideal_x))

    dash_len, gap_len = 10, 8
    y = 0
    while y < h:
        y2 = min(y + dash_len, h)
        cv2.line(frame, (ix, y), (ix, y2), _IDEAL_LINE_CLR, 1, cv2.LINE_AA)
        y += dash_len + gap_len

    cx, cy = int(round(com_out[0])), int(round(com_out[1]))
    cv2.line(frame, (cx, cy), (ix, cy), _DEVIATION_CLR, 1, cv2.LINE_AA)
    return frame
```

### 4. Verdrahtung (`src/compare.py`)

`_run_player()`'s `pipeline_run()`-Aufruf bekommt `show_deviation=True` zusätzlich zu den bestehenden Parametern.

## Nicht im Scope

- Farbcodierung der Abweichungsstärke (z.B. rot bei großer Abweichung)
- Gleiche Visualisierung für andere Körperteile (Arme/Füße)
- Anpassung von `run.py`/`app.py`'s `/render`-Endpoint-Default (bleibt `False`)

## Erfolgskriterium

Im Video erscheint eine gestrichelte graue vertikale Linie bei der mittleren seitlichen Position des Kletterers, sowie eine weiße Verbindungslinie vom CoM-Punkt zu dieser Linie. Bewegt sich der Kletterer seitlich weg vom eigenen Durchschnitt, wird die Verbindungslinie länger — visualisiert direkt das, was die "Wackeln"-Zahl in der Kennzahlen-Leiste ausdrückt.
