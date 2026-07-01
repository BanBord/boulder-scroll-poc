```
# Climbrr — Video-Analyse & Material-3-Sheets

Funktionsdokumentation des Kern-Screens `AnalyseScreen` (`app/screens-analyse.jsx`).
Sie beschreibt, **wie** die Analyse interaktiv funktioniert — als Grundlage für Umsetzung & Handoff.

---

## 1. Grundprinzip: Das Video *ist* die Analyse

Es gibt keinen separaten „Daten-Screen". Das aufgenommene Video läuft vollflächig im Hintergrund, und **alle** Analyse-Elemente liegen als Overlay darüber. Statt ein Video abzuspielen, **reist man die Strecke entlang** und liest dabei die Bewegungs-Parameter ab.

```
┌─────────────────────────────┐
│ ‹  ● Start  0.0s     [vs Tom▾]│  ← Top-Bar
│                          ╎T  │
│        (Live-Video)      ╎O  │  ← Strecken-Rail (rechts)
│        + Parameter-      ╎P  │
│          Overlay         ╎│  │
│                          ╎S  │
│  ┌───────────────────────┐  │
│  │ Schwerpunkt   …pfad   │  │  ← Parameter-Readout
│  │ Du 71 ───────│ Tom 92 │  │
│  └───────────────────────┘  │
│  [Schwerpunkt][Tritt…][Arm…]│  ← Parameter-Chips
└─────────────────────────────┘
```

Drei Eingaben steuern denselben Wert — den **Fortschritt** `progress` (0 = Start, 1 = Top):

| Geste | Wirkung |
|---|---|
| **Ziehen** auf dem Video (hoch/runter) | scrubbt die Strecke (delta-basiert → Scroll-Gefühl) |
| **Scrollen** / Mausrad | dito, feiner |
| **Ziehen auf der Strecken-Rail** (rechts) | springt absolut an die Position der Route |

`progress` ist die *einzige* Wahrheit: Video-Frame, Schwerpunkt-Punkt, Parameter-Linien, der aktive Moment in der Top-Bar und der Playhead auf der Rail werden alle daraus abgeleitet.

> **Video-Mapping:** `progress` 0→1 wird auf den Kletter-Ausschnitt des Clips abgebildet (`T0 = 0.42`, `T1 = 0.93`). Beim Scrubben wird `video.currentTime` gesetzt — es wird nicht „abgespielt", sondern gesucht (`seek`).

---

## 2. Die Strecken-Rail (Strecke)

Rechts am Bildrand, eine vertikale Mini-Karte der Route — **TOP oben, START unten**.

- Polylinie aus den kuratierten Route-Holds (`FEED_ROUTE` → `FEED_HOLDS`), in die Rail-Box normalisiert.
- **Hold-Pips** entlang der Linie färben sich, sobald `progress` sie passiert.
- **Schlüsselmoment-Knoten** (Crux = pink, Wackler = cyan) liegen an ihrer Position.
- Ein **Playhead** markiert die aktuelle Position; der zurückgelegte Teil der Linie ist im Akzent eingefärbt.
- Die Rail ist selbst ein Scrubber: Ziehen setzt `progress` **absolut** (oben = 1, unten = 0).
- Ein gestrichelter Pfeil-Hinweis (links der Rail) lädt zur ersten Interaktion ein und verschwindet danach (`touched`).

---

## 3. Parameter-Overlay

Pro ausgewähltem Parameter wird eine eigene Visualisierung direkt aufs Video gelegt. Mittelpunkt ist immer der **Schwerpunkt (Center of Mass)**, der sich mit `progress` an der Kletternden hochbewegt.

| Parameter | Metrik (Datenquelle) | Visualisierung im Video |
|---|---|---|
| **Schwerpunkt** | Effizienz | Schwerpunkt-Punkt + horizontale Höhen-Linie |
| **Trittfestigkeit** | Fußarbeit | Punkt + zwei Fuß-Marker (LF hellblau, RF hell­orange) nach unten |
| **Arm & Schulter** | Reichweite | Punkt + zwei Hand-Marker (LH blau, RH orange) nach oben |
| **Kraft** | Kraft | Punkt mit pulsierendem Kraft-Ring |
| **Flüssigkeit** | Stabilität | „Spur" — Schweif des Schwerpunkt-Pfads über die Zeit |

Die Farbcodierung der Gliedmaßen (LH/RH/LF/RF) ist überall in der App identisch.

### Parameter wechseln
Die **Chip-Leiste** unten (horizontal scrollbar) schaltet sofort um — ein Tap, kein Menü. Der aktive Chip ist im Parameter-Farbton hervorgehoben. Alternativ öffnet ein zweites M3-Sheet („Was liest du im Video?") dieselbe Auswahl mit Beschreibung.

### Readout-Karte
Über den Chips zeigt eine Karte den **gewählten Parameter als Balken**: dein Wert (lime) gegen den Vergleichswert (weißer Marker) — bei „Nur ich" gegen den **Hallen-Schnitt (Halle Ø)**.

---

## 4. Vergleich durch Halten (Hold-to-Compare)

Im Normalzustand sieht man **nur die eigene** Linie/den eigenen Punkt — bewusst aufgeräumt.

- **Gedrückt halten** (auf dem Video *oder* der Rail) blendet die **Geister-Spur der ausgewählten Person** ein: deren Parameter-Linie (weiß gestrichelt) + ein weißer Schwerpunkt-Punkt mit Namens-Tag (z. B. „Tom").
- Unten erscheint der aktive Indikator **„● Vergleich mit Tom"**.
- **Loslassen** blendet den Vergleich wieder aus.
- Ein einmaliger Hinweis **„☟ Zum Vergleich … gedrückt halten"** erklärt die Geste und verschwindet, sobald sie zum ersten Mal genutzt wurde (`comparedOnce`).

Im Solo-Modus („Nur ich") gibt es keinen Geist — dort vergleicht der Balken still gegen den Hallen-Schnitt.

State dahinter: `holding` (Finger unten?), gesetzt in `onDown` / `startHold`, zurückgesetzt im globalen `pointerup`/`touchend`-Listener — egal wo losgelassen wird.

---

## 5. Material-3 Bottom-Sheets

Auswahl passiert **im Kontext**, als modales M3-Sheet von unten — nie als eigener Screen. (Der frühere stand-alone „Debrief-Menü"-Screen leitet nur noch auf die Analyse um.)

**Anatomie** (`M3Sheet`):
- **Scrim** — abgedunkelter Hintergrund, Tap schließt (`onClose`).
- **Container** — von unten eingefahren (`cbSheetUp`, `cubic-bezier(.2,.8,.2,1)`), oben abgerundet (28 px), max. 76 % Höhe, scrollbar.
- **Drag-Handle** — die kleine Griffleiste oben.
- **Titel** + **Zeilen** (`M3Row`).

**Zeile** (`M3Row`): führendes Element (Avatar / Farbpunkt) · Titel + Untertitel · optionaler Status-Chip · **Radio-Auswahlkreis** rechts (gefüllt = aktiv). Ausgewählte Zeile ist lime hinterlegt.

### Zwei Sheets

**„Mit wem vergleichen?"** (Teilnehmer-Pill in der Top-Bar)
- **Nur ich** — Solo-Analyse gegen den Hallen-Schnitt.
- Trenner „Jam-Teilnehmer", dann alle anderen Kletternden mit Status-Chip:
  - **BETA** = Referenz-Begehung (Tom), außer Konkurrenz
  - **SEND** = getoppt · **PROJ** = noch Projekt
- Auswahl schließt das Sheet und setzt die Vergleichsperson.

**„Was liest du im Video?"** (alternativ zur Chip-Leiste)
- Alle fünf Parameter mit Farbpunkt + Beschreibung, Radio-Auswahl.

---

## 6. Zustände (State) im Überblick

| State | Zweck |
|---|---|
| `progress` | Position auf der Strecke (0–1) — steuert alles |
| `param` | aktiver Parameter (`com` / `feet` / `arms` / `power` / `flow`) |
| `partnerId` | Vergleichsperson, oder `'solo'` |
| `holding` | hält der Finger gerade → Vergleich sichtbar |
| `sheet` | offenes M3-Sheet (`'who'` / `'param'` / `null`) |
| `touched` / `comparedOnce` | steuern die einmaligen Gesten-Hinweise |

`param` und `partnerId` werden zusätzlich in `window.__cbSel` gespiegelt, damit die Auswahl **über Screen-Wechsel hinweg erhalten** bleibt.

---

## 7. Designprinzipien (warum es so gebaut ist)

1. **Eine Geste, ein Wert.** Ziehen, Scrollen und Rail steuern alle `progress` — kein getrennter Play-Button, keine Scrubber-Leiste, die man treffen muss.
2. **Hände frei vom Detail.** Standard zeigt nur die eigenen Daten; der Vergleich ist ein bewusster, temporärer „Blick" per Halten — kein Dauer-Clutter.
3. **Auswahl im Kontext.** M3-Sheets statt Unter-Screens: man verliert das Video nie aus dem Blick.
4. **Konsistente Sprache.** Top / Send / Projekt / Beta und die Gliedmaßen-Farben sind überall in der App gleich — die Beta ist immer Referenz, nie ein Rang.


```
