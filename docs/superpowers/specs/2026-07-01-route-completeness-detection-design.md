# Design: Routen-Vollständigkeitserkennung

## Context

Bei der manuellen Browser-Validierung zeigte sich, dass der Scanner Routen mit unsicherer Datenlage (fehlender Start-Tag, Rand-Anschnitt) genauso selbstbewusst präsentiert wie vollständig erkannte Routen (Blau: Start falsch geraten; Rot: kein kohärenter Cluster, aber trotzdem "Holds" geliefert). Der Nutzer hat den Bedarf erkannt: das System muss unterscheiden können, welche Routen tatsächlich **vollständig** im Foto erfasst sind (echtes Start+Top-Tag-Paar zur selben Route, kein Bildrand-Anschnitt) und das dem Nutzer sichtbar machen, statt geratene Daten als sicher auszugeben.

Geklärt mit dem Nutzer (AskUserQuestion, Session 2026-07-01):
- **Vollständigkeits-Definition:** Kombination aus Tag-Paar-Bestätigung UND kein Bildrand-Kontakt (nicht nur eines von beidem)
- **UX bei unvollständig:** Route bleibt antippbar, aber sichtbar markiert (gestrichelter Ring/Warn-Badge), Pencil-Edit-Mode bleibt nutzbar
- **Scope:** Der zugrunde liegende Tag-Attribution-Bug (`nearest_hold_id` ist rein räumlich, ignoriert Routenzugehörigkeit) wird als Teil dieses Designs mit gefixt, da Vollständigkeitserkennung sonst auf fehlerhafter Datenbasis aufbaut
- **Architektur-Ort:** Client-seitig, erst bei Tap berechnet (konsistent mit "Start/Top-Selection lebt im Client") — kein Server-seitiges Vorab-Clustering, keine Vorab-Übersicht vor dem ersten Tap

## Root Cause: Tag-Attribution ist rein räumlich

`detect_tags()` in `src/wall_scan.py` berechnet für jeden erkannten Tag den räumlich nächstgelegenen Hold (`nearest_hold_id`) — unabhängig davon, zu welcher (client-seitig berechneten) Route dieser Hold später gehört. Liegt ein Start-Sticker geometrisch näher an einem Hold einer *anderen* Route (z.B. an einer Kreuzung zweier Routen auf der Wand), wird der Tag fälschlich dieser anderen Route zugeschlagen. `assignStartTopFromTags()` in `viewer/scan_selection.js` filtert Tags dann über `ids.has(t.nearest_hold_id)` — der echte Start-Tag der betroffenen Route taucht nie auf, die Route fällt auf die ungenaue räumliche Fallback-Heuristik `assignStartTopSpatial()` zurück. Das erklärt den beim Feld-Test beobachteten Blau-Start-Bug (siehe `research/session_report_wall_scan_2026-06-30.md`).

## Fix 1 — Server: `nearby_hold_ids` statt `nearest_hold_id`

**Datei:** `src/wall_scan.py`, Funktion `detect_tags()`

Statt nur des Arg-Min-Treffers alle Holds innerhalb des bereits bestehenden Abstands-Gates (`_TAG_HOLD_DIST_FRAC × image_diag`, aktuell nur für den EINEN nächsten Hold geprüft) sammeln, nach Distanz sortiert, auf eine kleine Obergrenze gekappt (z.B. Top 5). Rechnerisch kaum teurer — die Distanzen sind ohnehin schon berechnet, es wird nur mehr als das Minimum behalten.

```python
"tags": [{id, bbox, center, nearby_hold_ids: [id, ...]}, ...]  # sortiert nächster zuerst
```

Schema-Breaking-Change (`nearest_hold_id` → `nearby_hold_ids`), aber laut Docstring ist das Schema aktiv in Entwicklung ("Start/top selection has moved to the client") — kein Kompatibilitäts-Layer nötig, einmalig durchziehen.

**Betroffen:** `assemble_scan_payload()` (Tags werden 1:1 durchgereicht, kein Code-Change nötig dort), `tests/test_wall_scan.py` (Tag-Tests auf neues Feld umstellen), `viewer/scan_tests.html` (Fixtures anpassen).

## Fix 2 — Client: Tag-Matching gegen Kandidatenliste

**Datei:** `viewer/scan_selection.js`, Funktion `assignStartTopFromTags()`

Filter ändert sich von `tags.filter(t => ids.has(t.nearest_hold_id))` zu `tags.filter(t => t.nearby_hold_ids.some(id => ids.has(id)))`. Für die weitere Verarbeitung (welcher Hold bekommt Start/Top zugewiesen) wird pro Tag der erste Kandidat aus `nearby_hold_ids` genommen, der tatsächlich in der Route liegt (`t.nearby_hold_ids.find(id => ids.has(id))`) — das ist der zu `nearest_hold_id` äquivalente Wert, nur route-korrekt statt blind-räumlich.

## Fix 3 — Neue Funktion: `checkRouteCompleteness()`

**Datei:** `viewer/scan_selection.js`, neue Export-Funktion, aufgerufen nach `growRoute()` + `assignStartTop()` bei jedem Tap.

```js
export function checkRouteCompleteness({routeIds, startTop, holds, imageSize, edgeMarginPx = 2}) {
  const reasons = [];
  if (startTop.source !== 'tags' || startTop.startIds.length === 0 || startTop.topId === null) {
    reasons.push('missing_tag_pair');
  }
  const [W, H] = imageSize;
  const byId = new Map(holds.map(h => [h.id, h]));
  for (const id of routeIds) {
    const h = byId.get(id);
    const [x, y, w, hh] = h.bbox;
    if (x <= edgeMarginPx || y <= edgeMarginPx ||
        x + w >= W - edgeMarginPx || y + hh >= H - edgeMarginPx) {
      reasons.push('touches_edge');
      break;
    }
  }
  return {complete: reasons.length === 0, reasons};
}
```

`startTop` ist das Ergebnis von `assignStartTop()` (bereits vorhanden, kein Re-Compute). `reasons` bleibt ein Array (nicht nur ein Bool), damit spätere UI-Iterationen differenzierter reagieren können (z.B. unterschiedliche Warntexte), auch wenn Phase 1 nur den Bool fürs Badge braucht.

## Fix 4 — UI-Anzeige

**Datei:** `viewer/scan.html`

Nach Tap: `checkRouteCompleteness()` aufrufen, Ergebnis am Route-State hängen. Rendering:
- `complete === true`: Außenring wie bisher (durchgezogen)
- `complete === false`: Außenring gestrichelt (Canvas `setLineDash([6,4])` statt durchgezogen) + Textzeile im Bottom-Sheet, z.B. "Route evtl. unvollständig erkannt — Start/Top nicht sicher, oder Route reicht über den Bildrand hinaus"

Pencil-Edit-Mode bleibt unverändert nutzbar — unvollständige Routen sind der Hauptanwendungsfall dafür.

## Tests

- `tests/test_wall_scan.py`: bestehende Tag-Tests auf `nearby_hold_ids` umstellen; neuer Test mit zwei Holds unterschiedlicher Route in Tag-Reichweite, der beweist, dass beide als Kandidaten zurückkommen (nicht nur der räumlich nächste)
- `viewer/scan_tests.html`: neue Fixtures für `checkRouteCompleteness()` — (a) vollständige Route (Tag-Paar + kein Rand-Kontakt), (b) fehlender Top-Tag, (c) Hold am Bildrand trotz vollständigem Tag-Paar
- Bestehende 44 Tests dürfen nicht brechen (`pytest tests/`)

## Verifikation

- `pytest tests/` grün
- `/scan_tests` im Browser: neue Completeness-Fixtures grün
- Browser-Smoke-Test auf `visual_idea/Wall_Holds_img.png`: Blau-Route erneut antippen, prüfen ob Start jetzt korrekt UND ob `complete`-Flag plausibel gesetzt wird (Rot und Gelb sollten weiterhin als unvollständig/fehlerhaft markiert werden, da deren Grundproblem — Region-Growing-Bleed bzw. Chroma-Blindspot — durch dieses Design nicht behoben wird, nur sichtbar gemacht)

## Bekannte Limitationen (bewusst nicht in Scope)

- Rot-Region-Growing-Bleed (`growRoute()` zieht andersfarbige Nachbar-Holds mit rein) — wird durch dieses Design nur sichtbar gemacht (Route landet als "unvollständig"), nicht behoben
- Gelb-Chroma-Blindspot (`_MIN_CHROMA=14` in `src/wall_scan.py`) — ebenfalls nur sichtbar gemacht, nicht behoben
- Kein Server-seitiges Vorab-Clustering — es gibt keine Zusammenfassung "X von Y Routen vollständig" vor dem ersten Tap
