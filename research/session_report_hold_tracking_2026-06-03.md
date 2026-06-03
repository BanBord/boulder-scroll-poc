# Hold Tracking — Zwischenstand (2026-06-03)

## Status: Auf Eis gelegt

---

## Was wurde implementiert

### Neue Dateien
- `src/hold_detector.py` — Hybride Hold-Erkennung (MobileSAM + HSV-Fallback)
- `src/contact.py` — Keypoint-in-Mask Contact-Detection

### Pipeline-Integration (`src/pipeline.py`)
- Neuer Parameter `track_holds: bool`
- Hold-Detektion läuft einmalig auf Referenzframe (t=1s, leere Wand)
- Per-Frame Contact-Check: Wrist/Ankle-Keypoint liegt in Hold-Maske?
- Output: `<videoname>_timeline.json` mit `{fps, holds[], frames[]}`

### App (`app.py`)
- `track_holds` Parameter wird aus dem Form-Submit durchgereicht

---

## Technischer Stand der Hold-Erkennung

### Ansatz: MobileSAM Automatic Mask Generator + HSV-Fallback
- MobileSAM (`vit_t`, ~40MB) läuft einmal auf leerem Referenzframe
- Alle Segmente werden per HSV-Median auf Grün gefiltert
- HSV-Fallback ergänzt Holds die SAM verpasst hat (IoU-Deduplication)
- Checkpoint: `~/.cache/mobile_sam/mobile_sam.pt` (via HuggingFace Hub)

### Ergebnis auf `v5_short.mov`
- SAM (points_per_side=32): 79 Segmente total → 21 grüne
- HSV-Fallback: 33 Kandidaten → 15 zusätzliche
- **Gesamt: 36 erkannte Holds**
- Problem: ~10-15 False Positives (andere Wand rechts, nicht-Route-Holds)
- Problem: noch nicht alle Route-Holds sicher erkannt

### Offene Punkte
1. **Hold-Selektion fehlt** — interaktives Tool um falsche Holds rauszuklicken
2. **Start- und Top-Hold manuell markieren** — für späteres Frame-Framing nötig
3. **Contact-Detection ungetestet** — Code steht, aber kein End-to-End-Test
4. **Koordinaten-Check** — Holds sind in Source-Frame-Koordinaten; bei starkem Kamera-Pan müsste man transformieren (bei statischer Kamera kein Problem)

---

## Abhängigkeiten
```
mobile-sam  (via: pip install git+https://github.com/ChaoningZhang/MobileSAM.git)
timm        (pip install timm)
huggingface_hub (pip install huggingface_hub)
```

---

## Nächster Schritt (wenn wieder aufgenommen)
Interaktives Klick-Tool bauen (`python3 tools/select_holds.py <video>`) das:
1. Referenzframe mit allen erkannten Holds zeigt
2. Klick auf Hold togglet ihn ein/aus
3. Start- und Top-Hold markierbar
4. Speichert `holds_config.json` neben dem Video
