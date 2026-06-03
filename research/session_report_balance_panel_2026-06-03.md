# Balance Panel — Session Report (2026-06-03)

## Status: Implementiert, bereit zum Testen

---

## Kontext & Designentscheidung

Ziel: Gewichtsverteilung des Kletterers emotional erfahrbar machen — nicht als Datenanalyse, sondern als intuitives visuelles Spiel.

Zwei Konzepte wurden evaluiert:
1. **Trapez/Matrix**: Diamant auf dem Körper, zwei Punkte wandern auf Achsen (links/rechts, oben/unten)
2. **Balance-Spiel**: Bälle auf Balken als physikalisches System

**Entscheidung: Konzept 2 (Balance-Spiel)** — stärker emotional, spricht Nicht-Daten-Nutzer an.

---

## Was wurde implementiert

### Neue Dateien
- **`src/balance.py`** — `PhysicsState`-Klasse
  - Spring-Damper-Physik: `vel = vel * decay + (target - pos) * stiffness`
  - 3 Zustände: `stable` (träge), `unstable` (reaktiv), `fallen` (Bälle rollen aus)
  - Varianz-Fenster (30 Frames) für Instabilitätserkennung
- **`tests/test_balance.py`** — 4 Unit Tests, alle grün

### Geänderte Dateien
- **`src/overlay.py`** — neue `draw_balance_panel()` Funktion
  - Arm-Ball (r=20), Bein-Ball (r=26), CoM-Ball (r=36) als Anker
  - Semi-transparentes Panel, fix am unteren Frame-Rand
- **`src/pipeline.py`** — `show_balance` Parameter + Integration
  - Target-Berechnung aus YOLO-Keypoints (`_balance_targets()`)
  - Sturzerkennung: CoM-Sprung > 40px/Frame oder YOLO-Confidence < 0.15
- **`app.py`** — Form-Parameter `balance` durchgereicht

---

## Physik-Parameter

| Zustand | Trigger | Stiffness | Decay |
|---|---|---|---|
| `stable` | CoM-Varianz < 8px | 0.08 | 0.85 |
| `unstable` | CoM-Varianz ≥ 8px | 0.15 | 0.55 |
| `fallen` | CoM-Sprung > 40px od. conf < 0.15 | 0.00 | 0.97 |

---

## Test-Output

Pipeline lief auf `v5_short.mov` (10s, 299 Frames):
- Output: `/tmp/balance_test.mp4`
- Größe: 1.3 MB
- 4/4 Unit Tests grün

---

## Offene Fragen / nächste Schritte

1. **Visuelles Tuning** — Physik-Parameter nach subjektivem Eindruck anpassen (Dämpfung, Amplituden)
2. **Sturzmoment** — "Auseinander rollen" visuell prüfen ob es funktioniert
3. **Panel-Position** — ggf. höher setzen wenn Kletterer unten im Frame ist
4. **Konzept 1 (Diamant)** — für User-Test später implementieren

---

## Commit-History dieser Session

```
7ba16bc Wire show_balance param through app
5acc5d6 Fix panel_half to use _BEAM_INSET constant from overlay
8fee3db Integrate balance panel into pipeline (show_balance param)
6686cfe Add _balance_targets() helper to pipeline
(Task 2 overlay commit)
ea09dfa Add PhysicsState for balance panel
e75a0cd Add balance panel implementation plan
546b59f Add balance panel design spec
```
