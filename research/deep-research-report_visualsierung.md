# Analyse und Visualisierung von Kletterbewegungen

Für die Analyse von Kletterbewegungen aus Videodaten (z.B. durch ein YOLO-gestütztes Skelettmodell) können verschiedene biomechanische Kennwerte extrahiert und visualisiert werden. Im Folgenden werden hierfür mehrere Konzepte und konkrete Umsetzungsansätze beschrieben.

## Schwerpunktverlagerung (Körperschwerpunkt)

Der Körperschwerpunkt (engl. **Center of Mass, CoM**) kann aus den Gelenkkoordinaten des Skelettmodells berechnet werden. Typisch wird dafür ein **segmentbasierter Ansatz** genutzt: Jedem Körpersegment (z.B. Kopf, Oberkörper, Arme, Beine) wird ein Masseanteil gemäß anthropometrischer Tabellen (z.B. Zatsiorsky/De Leva) zugewiesen. Der gesamte CoM ergibt sich dann als gewichteter Mittelwert der Segmente. Grafisch kann man ihn etwa als Punkt oder Flugbahn einzeichnen (siehe Bild unten). In der Forschung wird bei 3D-Analysen auch ein Avatar-Modell des Kletterers verwendet – hier führt das Tracking zu einer COM-Trajektorie, die präziser ist als ein einzelner Marker. 

Zur Verbesserung der Genauigkeit ist es üblich, die ermittelten COM-Koordinaten zu filtern. Studien zeigen z.B., dass rohe CoM-Werte aus Pose Estimation („OpenPose“) noch beträchtliches Rauschen enthalten, das sich durch Tiefpass- oder Kalman-Filterung deutlich reduzieren lässt. So verringerte Kalman-Smoothing den Fehler in der horizontalen CoM-Geschwindigkeit etwa von über 0.1 m/s auf ca. 0.04 m/s.

*Abbildung: Beispiel eines durch Pose-Schätzung gewonnenen Skelettmodells (grüne Glieder) über einer Person. Aus solchen 2D-Gelenkpositionen kann u.a. der Schwerpunkt berechnet werden.*

**Visualisierung:** Der Schwerpunkt kann etwa als farbiger Punkt oder Pfad eingezeichnet werden. Man könnte z.B. seine Koordinaten im Bildverlauf als Linie (bzw. Kurve) darstellen oder die momentane Lage als Markierung auf dem Skelett zeigen. Die Geschwindigkeit des CoM oder seine Auslenkung vom vertikalen Aufstiegskurs lassen sich durch Färbung (z.B. Geschwindigkeitshöhen in Farbskala) visualisieren. Algorithmisch berechnet man zunächst für jeden Frame die Joint-Positionen, multipliziert diese mit den Anteilsgewichten und mittelt. Anschließend kann man die Bahn glätten (z.B. Gaussian/Butterworth Filter oder Kalman-Filter). 

**Mögliche Umsetzungsschritte (Pseudocode):**  
- Erfasse 2D-Gelenkkoordinaten (z.B. mit OpenPose nach YOLO-Erkennung).  
- Berechne CoM: z.B. `CoM_x = (Σ m_i * x_i) / Σ m_i`, analog für y (Massen m_i aus Literatur, z.B. [Zatsiorsky et al.]).  
- (Optional) Glätte die CoM-Zeitreihe (Tiefpass-Filter oder Kalman-Filter).  
- Visualisiere den CoM-Verlauf: z.B. Zeichen eines Punkts/Tracks über die Zeit im Bild.  



## Trittfestigkeit (Fußstabilität)

Die Trittfestigkeit (Stability) hängt vor allem von der Fuß- / Standposition ab. In der Biomechanik wird die **Basis der Stützung** („Base of Support, BoS“) betrachtet: Liegt der projizierte Schwerpunkt innerhalb des vom Standpolygon der Füße aufgespannten Bereichs, gilt der Körper als stabil. Folglich kann man aus den Fußgelenkpunkten des Skelets ein Polygon (z.B. die konvexe Hülle der Fußpositionen) bilden und prüfen, ob der CoM-Punkt darin liegt. Fällt der CoM nach vorne oder zur Seite aus dem Stützbereich heraus, deutet das auf mangelnde Trittfestigkeit hin.  

Visualisiert wird dies z.B. durch ein farbliches Markieren der BoS oder der Distanz zwischen CoM und Fußbasis. Alternativ kann man die **Druckverteilung** auf den Füßen abschätzen. Neuere Ansätze (z.B. *PressNet*) trainieren ein neuronales Netz, das aus den Skelettpunkten eine Fußdruckkarte (Heatmap) ermittelt. Ein Beispiel einer solchen berechneten Fußdruckverteilung ist in der Abbildung unten zu sehen – rote Bereiche bedeuten hohen Druck. Daraus lässt sich der **Center of Pressure (CoP)** ermitteln und mit dem CoM vergleichen. Instabilität zeigt sich, wenn CoM weit vom CoP entfernt ist oder nahe am Rand der BoS positioniert ist.

*Abbildung: Beispiel einer Fußdruckkarte (Heatmap) für beide Füße. Hohe Druckzentren (rot) zeigen, wo der Fuß belastet wird. CoM-Projektion sollte innerhalb des Stützpolygons (BoS) liegen, sonst besteht Instabilität.*

**Visualisierung:** Man kann die Fußstabilität durch Einfärben der Stützfläche (z.B. blau=stabil, rot=instabil) anzeigen. Ein Druck-Heatmap-Bild (s.o.) verdeutlicht, wie stark jeder Fuß (z.B. Ferse vs. Ballen) belastet wird. Ein roter Markierungspunkt für den CoM und ein Umriss des Stützpolygons machen sichtbar, ob der CoM in der Basis liegt.

**Mögliche Umsetzung:**  
- Ermitteln der Fußgelenke (z.B. Sprunggelenk-Koordinaten).  
- Erstelle das Konvexpolygon der Fußpunkte (BoS).  
- Prüfe, ob die CoM-Projektion im Polygon liegt (z.B. Punkt-in-Polygon).  
- Alternativ: Schätze Fußdruck (aufwändiger; z.B. durch ML-Modell) und finde CoP (Schwerpunkt der Verteilung).  
- Visualisiere Basis und CoM: z.B. schraffiertes Stützpolygon mit farbigem CoM-Punkt.  



## Flüssigkeit der Bewegung

Unter Bewegungsflüssigkeit versteht man eine ruhige, ruckfreie Koordination der Bewegungen. In der Forschung wurde dazu u.a. der **Weg des Körperschwerpunkts** und die **Jerk-Kurve** (dritte Ableitung der Position, also Änderung der Beschleunigung) untersucht. Ein gängiges Maß ist die **geometrische Entropie** (engl. *Geometric Entropy, GE*) des Schwerpunktpfads: Man berechnet den Linienpfad \(L\) des CoM und den Umfang \(C\) der Umhüllung (z.B. konvexe Hülle) dieses Pfads. Nach Cordier et al. wird dann \(GE = \ln(2L/C)\) definiert. Ein niedrigerer GE-Wert bedeutet einen geradlinigeren, effizienteren Pfad (mehr „fluide“ Bewegung).  

Beispiel: Ein direkter Aufstieg mit minimaler Seitbewegung hat geringe Entropie. **Jerk-Analyse:** Alternativ kann man auch die Glätte der Bewegung über Jerk messen – z.B. mittleres „dimensionless jerk“ oder Log-LDSJ. Je kleiner der Jerk, desto flüssiger. In der Praxis berechnet man hierzu etwa die Zeitreihe der CoM-Beschleunigung und bildet deren Ableitung. Große Peaks im Jerk-Signal deuten auf Rucke hin.

**Visualisierung:** Man kann den GE-Wert oder Jerk-Wert als Zeitreihe oder Balken zeigen. Auch eine farbliche Kodierung der Pfadsegmente (z.B. stabile Phasen grün, ruckartige Phasen rot) im CoM-Trajektplot ist möglich. 

**Mögliche Umsetzung:**  
- Berechne CoM-Positionen über Zeit.  
- Für einen definierten Zeitraum (z.B. ganze Route) berechne \(L=\sum\) abstand(t_i,t_{i+1}) und Umfang \(C\). Berechne \(H=\ln(2L/C)\).  
- Oder berechne die Jerk-Kurve: \(j(t)=d^3(\text{CoM})/dt^3\). Bestimme z.B. RMS oder Spitzen des Jerk.  
- Visualisiere z.B. *H* als Wert oder färbe CoM-Pfad anhand der lokalen Jerk-Amplitude ein.  



## Arm- und Schulternutzung

Die Effizienz der Arm- und Schulternutzung kann durch Analyse von Gelenkwinkeln und -bewegungen bewertet werden. Typische Kennzahlen sind z.B. **Armkraft-Auslastung** oder **Reach-and-Mount-Technik**. Praktisch lässt sich hier aus den Skelettdaten die *Haltekraft* indirekt abschätzen durch die Verteilung der Bewegung auf Arme vs. Beine: Beispielsweise kann man die Summe der Winkeländerungen oder Geschwindigkeit der Armgelenke ins Verhältnis zu den Bein-Gelenken setzen. Auch die Haltung der Schultern (Winkel zwischen Rumpf und Oberarm) gibt Aufschluss – ein stabiler Rumpf mit stabilen Schultern deutet auf gute Technik hin. 

**Visualisierung:** Farbige Linien entlang der Arme zeigen etwa, wie stark sie bewegt oder belastet werden (z.B. dicke Linien bei hoher Beschleunigung). Oder man plottet den **Winkel der Ellenbogen** über die Zeit, um zu sehen, wie oft die Arme gestreckt bzw. gebeugt waren. 

**Mögliche Umsetzung:**  
- Aus Pose-Daten Ellenbogen- und Schulterwinkel berechnen.  
- Bestimme Kennwerte wie mittlere Winkelgeschwindigkeit der Arme vs. Beine.  
- Eventuell: Zeichne Pfeile oder Balken, die die Armkraft bzw. Zugversuche visuell betonen (z.B. länger bei mehr Bewegung).  

*Hinweis:* Konkrete Modelle zur Kraftabschätzung aus Video (z.B. durch Muskelmodellierung) sind komplex und selten veröffentlicht. Studien betonen jedoch, dass z.B. **Schulterstabilität** und -mobilität für die Bewegungsqualität entscheidend sind.

## Kraftnutzung (Krafteinsatz)

Da direkter Kraftmessung per Kamera schwer möglich ist, verwendet man Näherungsgrößen. Beispielsweise kann man die **Beschleunigung des Körpers** als Indikator heranziehen: Große vertikale Beschleunigungen (Sprünge) oder abrupte Bremsen weisen auf hohen Krafteinsatz hin. Eine andere Möglichkeit ist die Berechnung der **Arbeit gegen die Schwerkraft**, indem man die Änderung der potenziellen Energie (Anstieg des CoM) pro Zeit betrachtet. 

**Visualisierung:** Man kann etwa die momentane Aufwärtsgeschwindigkeit des CoM farblich darstellen (starkes Bergab bremsen = rot, gleichmäßiges Steigen = grün). Oder ein Balkendiagramm der geschätzten Kraft/Arbeit pro Abschnitt. 

**Mögliche Umsetzung:**  
- Berechne vertikale CoM-Velocity und -Beschleunigung. Große Werte markieren.  
- Schätze Leistung: \(P = m \cdot a \cdot v\) (mit angenommenem Körpergewicht \(m\)).  
- Oder markiere in jedem Frame, ob gerade „Kraftakt“ stattfindet (z.B. wenn beide Beine/Arme sich abrupt bewegen).  

*(Spezifische Publikationen zum visuellen Krafteinsatz bei Klettern sind rar; oft dienen Kraftsensoren oder EMG als Referenz.)*

## Genutzte Klettertechniken

Kletterspezifische Techniken (z.B. *Drop Knee*, *Flaggen*, *High Stepping*) kann man durch Mustererkennung in den Gelenkwinkeln erkennen. Zum Beispiel kennzeichnet ein stark gedrehter Hüftwinkel in Relation zum Stützfuß einen **Drop Knee** (Knie an den Felssockel gedreht), während ein weit erhobenes Bein einen **High Step** andeutet. 

**Beispiel:** Köstermeyer et al. entwickelten ein System zur Fehlererkennung beim Klettern, das z.B. prüft, ob das vordere Knie die Stütze nicht überquert – wird dies missachtet, gilt dies als Fehler beim Erreichen. Ähnliche Ansätze lassen sich nutzen, um positive Technikmomente zu kennzeichnen. 

**Visualisierung:** Man könnte beim Erkennen einer Technik eine farbige Markierung am entsprechenden Gelenk setzen (z.B. blaues Knie bei Drop-Knee) oder einen Text-Overlay mit dem Technik-Namen. 

**Mögliche Umsetzung:**  
- Definiere Kriterien (Regeln) für jede Technik auf Basis von Gelenkwinkeln (z.B. Hüftwinkel > 45° = Drop Knee).  
- Prüfe diese Regeln in jedem Frame.  
- Markiere erkannte Technikphasen in der Visualisierung (z.B. farbiges Knie).  



## Zusammenfassung der Ansätze

Insgesamt lassen sich alle genannten Kennwerte aus den YOLO-basierten 2D-Pose-Daten extrahieren. Nach Berechnung der Gelenkkoordinaten können automatisiert Schwerpunkte, Stabilitätsmaße, Glattheitsmetriken, Winkel und Geschwindigkeiten gewonnen werden. Zur Visualisierung kombinieren wir Linien, Punkte, Farbskalen und Diagramme über das Videobild. Eine mögliche **Proof-of-Concept-Pipeline** könnte so aussehen:

- **Pose-Estimation:** YOLO detektiert Person, OpenPose (oder vergleichbares) liefert 2D-Skelettpunkte.  
- **Körperschwerpunkt:** Berechne CoM aus Gewichten; filtere und zeichne Pfad/Marker (z.B. gelbe Linie).  
- **Fußstabilität:** Erstelle Basis-Polygon aus Fußpunkten; markiere bei Instabilität rot; optional Fußdruck-Heatmap (wie oben).  
- **Bewegungsflüssigkeit:** Berechne Jerk oder Entropie aus CoM-Kurve; zeige Wert über Zeit (Liniendiagramm oder Farbcodierung).  
- **Arme/Schultern:** Berechne Gelenkwinkel und -geschwindigkeiten; markiere Phasen mit starker Armbewegung (z.B. pulsierende Arme) oder stelle Winkeldiagramm nebenher dar.  
- **Krafteinsatz:** Nutze CoM-Beschleunigung zur groben Kraftschätzung; fülle in Frames mit hohem Kräfteeinsatz ein Balkendiagramm oder verändere Farbtönung (z.B. Rot = starkes Abbremsen).  

Die Kombina­tion solcher Visualisierungen macht die komplexen Bewegungsparameter für Trainer und Sportler leicht verständlich. Durch Referenzen auf die Fachliteratur und konfigurierbare Parameter (z.B. Filterfrequenzen) kann das System dabei wissenschaftlich fundiert und flexibel sein.

**Quellen:** Zahlreiche Studien zeigen, wie sich COM-Trajektorien und Stabilitätsmaße aus Pose-Daten berechnen lassen. Für Kletterbewegungen wurden etwa die geometrische Entropie der COM-Bahn und die CoM-Geschwindigkeit als Leistungsindikator eingesetzt. Auch Workflows zur aus Pose-Schätzungen abgeleiteten Dynamik (Fußdruck, CoP) liegen vor. Unsere vorgeschlagenen Methoden stehen damit im Einklang mit aktuellen Forschungsansätzen.