# Wand und Mensch — Video-Auswertung (Design)

**Stand:** 2026-11-09 · Branch `wand-und-mensch` · Status: Entwurf, von Bruno im Chat freigegeben („passt")

## Absicht

Ein Stativvideo, in dem die Wand und der Mensch gemeinsam gelesen werden: Griffmasken (aus Ron Mandićs Segmentierung) und Skelett (aus diesem Repo) in einem Bild. Ergebnis sind Videos und Standbilder für Brunos Portfolio-Stück „Kraxxl", Framing „Wand lesen".

Warum: Die Doku des Semesters endet bei manuell markierten Griffen. Die Segmentierung schließt diese Lücke, und der vorhandene Kontakt-Check in `src/contact.py` bekommt damit erstmals saubere Masken.

## Ziele

1. **Kontakt-Zeitleiste:** welche Hand und welcher Fuß wann an welchem Griff war.
2. **Schwerpunkt-Bahn:** der Weg des Körperschwerpunkts als Linie über den Griffen.
3. **Gleichgewicht:** die vorhandenen Signale `arm`, `leg`, `com` als ruhige Kurve neben dem Video, ohne Bewertung.
4. **Skelett mit Unsicherheit:** Gelenke werden blasser, wo die Keypoint-Konfidenz niedrig ist.

## Nicht-Ziele

- Belastung oder „Strain" pro Körperteil. Aus monokularem 2D-Video nicht belegbar.
- Griff-Erkennung pro Einzelbild. Die Kamera steht, die Masken eines Standbilds gelten für das ganze Video (nach Stabilisierung).
- Geister-Vergleich zweier Versuche. Es fehlen zwei Videos derselben Route aus derselben Kameraposition.
- Umbau der bestehenden Pipeline, des Flask-Viewers oder der Hold-Erkennung in `src/hold_detector.py`.

## Anti-Ziele

- Werte zeigen, die es nicht gibt. Jede Zahl im Bild stammt aus den Daten (Masken-Score, Keypoint-Konfidenz, gemessene Kontaktdauer).
- Ein Bild, das wie ein Urteil über den Körper gelesen wird (Testbefund: Skelett wurde als Vorgabe verstanden).

## Daten und Grenzen

- **Dieses Repo ist öffentlich** (`BanBord/boulder-scroll-poc`). Rons Repo `ron-mandic/holdseg` ist privat und ohne Lizenz.
- Deshalb: Rons Masken, Fotos und Videos werden **nie** eingecheckt. Sie liegen außerhalb des Repos und werden per Pfad-Argument übergeben. `output/` und `uploads/` sind bereits ignoriert.
- Eingaben: ein Stativvideo, eine COCO-JSON mit Griffmasken für ein Standbild dieses Videos (Felder: RLE-Maske, `color`, `score`), optional eine Routen-JSON.
- Pose: `yolov8n-pose.pt` (lokal vorhanden, ignoriert). Personen-Silhouette: macOS Vision (`VNGeneratePersonSegmentationRequest`), kein Download.

## Bausteine

Neue, kleine Module neben dem Bestand; der Bestand wird wiederverwendet, nicht umgebaut.

| Baustein | Aufgabe | nutzt |
|---|---|---|
| `src/masks_io.py` | COCO-RLE lesen, Masken und Metadaten pro Griff liefern | – |
| `src/stabilize.py` | Videobilder auf das Masken-Standbild ausrichten | OpenCV ECC |
| `src/contact_timeline.py` | pro Bild: Hand/Fuß in Maske; daraus Intervalle mit Mindestdauer 0,5 s | `src/contact.py` |
| `src/com_path.py` | Schwerpunkt pro Bild, geglättet, als Bahn | `detector._calculate_com` |
| `src/render_reading.py` | Compositing aller Ebenen zu Video und Standbildern | `overlay.py` wo passend |
| `tools/read_wall_and_body.py` | CLI: Video + Masken rein, Videos + JSON raus | alle |

Ausgabe-JSON: `contacts[{limb, hold_id, t_start, t_end}]`, `com_path[{f, x, y}]`, `balance` (wie bisher), `keypoint_conf` pro Bild.

## Gestaltung („Maschinenblick")

Richtung aus dem Unslop-Durchgang, von Bruno bestätigt:

- **Charakter:** nüchtern, messend, ein bisschen roh.
- **Grund:** dunkel, Fast-Schwarz `#121212`, helle Linien `#F2EFE9`. (Annahme: Bruno hat auf die Dunkel/Hell-Frage nur „passt" geantwortet; dunkel war die Empfehlung.)
- **Eine kräftige Farbe:** Signalorange `#FF5A1F`, bedeutet immer „Kontakt". Routenfarben der Griffe nur als dünne Umrisslinie.
- **Momente:** (1) Griff füllt sich orange, solange Hand oder Fuß ihn berührt. (2) Kletternde Person als Punktraster-Figur mit Skelett, Gelenke nach Konfidenz abgeblendet.
- **Signatur:** kleines Monospace-Etikett pro Griff mit Kennung und Score; bei Kontakt wechselt es auf Körperteil und Dauer.
- **Schrift:** Monospace für Werte, Barlow Condensed für Großes.
- Kein Leuchten, keine Verläufe, kein Neon. Etiketten nur an Griffen der aktiven Route und an berührten Griffen, sonst wird das Bild unlesbar.

## Qualität

- Reine Logik test-first (pytest): RLE-Dekodierung, Kontakt-Intervalle mit Mindestdauer, Bahn-Glättung.
- Erster Schritt vor jeder Änderung: bestehende Tests laufen lassen (Doku nennt 55 grün, Stand 2026-07-01, heute ungeprüft). Es gibt kein venv; Python-Version festlegen (System ist 3.14, `ultralytics` dafür ungeprüft).
- Rendering wird per Einzelbild-Sichtprüfung abgenommen, nicht per Test.

## Offen, vor Veröffentlichung

- Rons Okay für die Verwendung von Masken und Videos im Portfolio.
- Einverständnis der Person im Video für Fassungen, in denen sie erkennbar ist.
- Entscheidung, ob dieses Repo öffentlich bleibt.
- Quellen der Metaanalyse (u. a. Maschek & Schedl 2025, Wulf 2021) an den Primärquellen prüfen, bevor sie zitiert werden.
