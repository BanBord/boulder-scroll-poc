# Aktuelle Methoden zur Skelett- und Pose-Erkennung  

Moderne Pose-Estimation-Frameworks detektieren zuverlässig 2D- bzw. 3D-Schlüsselstellen (Keypoints) am Menschen in Bildern oder Videos. Aktuelle State-of-the-Art-Modelle basieren meist auf Deep-Learning-Architekturen (Convolutional Neural Networks oder Transformer). Beispielsweise bietet das Ultralytics YOLO-Framework (z.B. YOLOv11, Sep 2024) integrierte „Pose“-Modelle, die 17 COCO-Schlüsselstellen (Gelenke) erkennen【1†L81-L90】. YOLOv11 führt hier verbesserte Backbone- und Neck-Architekturen ein und behält dabei hohe Geschwindigkeit und Genauigkeit bei【43†L74-L79】【43†L127-L130】. In Tests erreichen die YOLOv11-Pose-Modelle ähnlich hohe mAP-Werte wie vorherige Versionen (z.B. YOLO26x-pose) und können lokal per GPU bzw. CPU ausgeführt werden. Eine weitere Stärke von Ultralytics ist die integrierte Tracking-Funktion: Mit `model.track()` lassen sich erfasste Skelett-Positionen über die Zeit verfolgen und individuellen IDs zuordnen (z.B. ByteTrack oder BoT-SORT)【69†L418-L421】【71†L134-L142】.  

*Alternativen zu Ultralytics YOLO:* Google bietet etwa **MediaPipe Pose** an, das auf Mobilgeräten und lokal läuft. MediaPipe detektiert 33 Pose-Landmarks im Bild sowie optional 3D-Koordinaten【47†L357-L361】. CMU’s **OpenPose** war eines der ersten Echtzeit-Systeme für Ganzkörper-Pose: Es erkennt multi-person Körper-, Hand-, Gesichts- und Fuß-Keypoints (insgesamt bis zu 135 Punkte)【48†L299-L307】. OpenPose liefert sehr vollständige Skelettdaten, ist aber rechenintensiver. Andere Bibliotheken sind z.B. **AlphaPose** (schnellere PyTorch-Variante), **Detectron2 Keypoint R-CNN** oder Googles **MoveNet**. Alle diese Methoden liefern Koordinaten von Schulter, Ellbogen, Hüfte, Knie etc. – entscheidend ist, die passende Balance zwischen Genauigkeit und Performance (lokal auf CPU/GPU) zu wählen.  

# Tracking in Videos  

Bei Videoanalyse kommt oft zusätzlich Object-Tracking zum Einsatz. Ultralytics YOLO erlaubt beispielsweise, ein trainiertes Pose-Modell auf Videodaten anzuwenden und eine Nachverfolgung (z.B. mit ByteTrack oder BoT-SORT) zu aktivieren【69†L418-L421】【71†L134-L142】. In der Praxis lädt man ein Modell wie `yolo11x-pose.pt` und ruft dann `model.track(source=video.mp4, show=True)` auf. Die Bibliothek verwaltet dabei automatisch eindeutige IDs für erkannte Personen in aufeinanderfolgenden Frames【69†L418-L421】【71†L134-L142】. Ein Beispielcode zeigt, dass Tracking für alle Modelltypen (Detektion, Segmentation, Pose) verfügbar ist:  

```
from ultralytics import YOLO
model = YOLO("yolo11x-pose.pt")         # offizielles Pose-Modell laden
results = model.track("video.mp4", tracker="bytetrack.yaml", show=True)
```  
Diese Pipeline liefert für jede Person im Video zeitlich geordnete Skelettpunkte. So kann man z.B. einen boulderen­de Person ein Leben lang verfolgen.  

# Schwerpunkt- und Gewichtsberechnung  

Aus einem erkannten Skelett allein lässt sich das Körpergewicht einer Person nicht direkt ableiten – dazu fehlen Volumen- oder Dichte­informationen. **Der Schwerpunkt (Körperschwerpunkt, center of gravity)** lässt sich aber näherungsweise aus dem Skelett berechnen, wenn man anthropometrische Modelle nutzt. In der Biomechanik kennt man standardisierte Segmentgewichte (z.B. Dempster 1955): Kopf ~8%, jeder Oberarm ~3–4%, Rumpf ~50% des Gesamtgewichts, usw. Mit einer 3D-Pose kann man dann z.B. jeden Körperabschnitt annehmen und den Gesamt­schwerpunkt als gewichtetes Mittel der Segment-Schwerpunkte bestimmen. Forschende integrieren diese Idee sogar in lernbasierte Methoden: Wei et al. (2025) schlagen vor, anatomische Massenverhältnisse zu verwenden und einen Verlustterm auf den CoG zu legen, um die 3D-Pose-Estimation zu verbessern【13†L25-L34】. 

Praktisch kann man den Schwerpunkt in der Bildebene auch einfach als Mittelwert der erkannten Gelenk-Punkte approximieren (wobei ungesehene Punkte üblicherweise ignoriert werden). Diese Methode wird z.B. in manchen Pose-Analysen und -Klassifikationen angewandt, indem alle sichtbaren Keypoint-Koordinaten gemittelt werden【13†L25-L34】. Für dynamische Anwendungen (wie Klettern) ist die 3D-Berechnung genauer: Mit einem 3D-Skelett (z.B. via Multi-Kamera-Setup) ermittelt man exakter den Punkt, an dem die Gesamtmasse wirkt. 

【64†embed_image】 *Beispielhafte Visualisierung: Ein 3D-Skelett mit markiertem Körperschwerpunkt (blauer Punkt).* 

# Visualisierung und Auswertung  

Ist das Skelett bzw. der Schwerpunkt ermittelt, kann man diese Informationen visuell darstellen. Typischerweise überlagert man die erkannten Gelenke auf das Bild bzw. Video (z.B. mit Linien zwischen ihnen) und zeichnet den Schwerpunkt als Punkt ein. Viele Bibliotheken (Ultralytics, OpenCV, Matplotlib) erlauben das einfache Plotten dieser Punkte. So lässt sich in jedem Videoframe das Skelett zeichnen und der Schwerpunkt als zusätzlicher Marker visualisieren. Über die Zeit ergibt dies eine Trajektorie des Schwerpunkts. In Trainings- oder Analyse-Notebooks (z.B. auf Google Colab) kann man solche Schritte automatisieren: Pose-Schätzung ➔ Schwerpunkt-Berechnung ➔ Plot. 

# Codebeispiele und praktische Tools  

- **Ultralytics YOLO (Python/CLI):** Offizielles Ultralytics-Paket (`pip install ultralytics`) unterstützt alle aktuellen YOLO-Modelle (YOLOv11 etc.) und Tasks. In der CLI kann man etwa `yolo predict model=yolo11x-pose.pt source=video.mp4` verwenden【71†L134-L142】. Die Python-API (siehe Beispiel weiter oben) ist ebenfalls sehr einfach. Ultralytics bietet ausführliche Dokumentation und Beispiele für Pose-Training und -Inference【46†L389-L392】【57†L106-L113】. So gibt es z.B. ein Roboflow-Blog-Tutorial, das zeigt, wie man YOLOv8-Pose-Modelle mit `ultralytics` trainiert【57†L106-L113】. 

- **Beispiele/Notebooks:** Es existieren zahlreiche Open-Source-Notebooks, die den Workflow demonstrieren. Roboflow etwa bietet ein Colab-Notebook *train-yolov8-keypoint.ipynb*, das den kompletten Ablauf erklärt (Annotationen, Training, Inferenz)【57†L106-L113】. Ebenso gibt es Tutorials auf Medium oder YouTube (z.B. “YOLOv11 Pose Estimation” von CodeAddict【3†L43-L50】). Google Colab und Kaggle haben öffentliche Notebooks für MediaPipe und andere Frameworks. Ein direkter Einstieg kann über vorhandene Datensätze (COCO Pose) und vortrainierte Modelle erfolgen. 

- **Lokaler Einsatz:** Alle genannten Tools (Ultralytics, MediaPipe, OpenPose) sind lokal ausführbar. OpenPose benötigt in der Regel eine CUDA-fähige GPU für Echtzeit, MediaPipe läuft auch auf CPU/Mobilprozessor. YOLOv11-Modelle lassen sich je nach Größe (n, s, m, l, x) auf unterschiedlich schneller Hardware betreiben. Für Offline-Analysen genügt oft CPU, für Echtzeitanwendung GPU. Außerdem kann man Modelle (z.B. mittels ONNX oder TensorRT) für Embedded-Systeme exportieren【46†L389-L392】. 

**Quellen:** Zahlreiche aktuelle Publikationen und Dokumentationen belegen diese Methoden. Beispiele sind die Ultralytics-Dokumentation zu YOLO-Pose【1†L81-L90】【43†L127-L130】, Forschungsarbeiten zur Pose-Estimation【13†L25-L34】 sowie Praxis-Tutorials und Notebooks von Roboflow, Medium etc. Alle Links zu relevanten Beispielen und Code sind oben genannt.