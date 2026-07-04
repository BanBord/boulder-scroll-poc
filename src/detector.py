"""YOLO pose detection wrapper: person bbox, hip centre, and center of mass.

Wraps a single ultralytics YOLO pose model and exposes the specific queries the
pipeline needs (calibration sampling, per-frame hip/CoM), computing CoM as a
mass-weighted average of the confident COCO keypoints.
"""

import cv2
import numpy as np
from ultralytics import YOLO

# COCO keypoint weights for Center of Mass approximation
# Based on approximate body segment mass fractions
_COM_WEIGHTS = {
    11: 0.15, 12: 0.15,  # hips
    5: 0.10,  6: 0.10,   # shoulders
    13: 0.07, 14: 0.07,  # knees
    7: 0.04,  8: 0.04,   # elbows
    0: 0.03,             # nose
    1: 0.01, 2: 0.01,    # eyes
    3: 0.01, 4: 0.01,    # ears
    15: 0.03, 16: 0.03,  # ankles
    9: 0.02,  10: 0.02,  # wrists
}

KEYPOINT_CONFIDENCE_THRESHOLD = 0.3


class Detector:
    def __init__(self, model_name: str = "yolov8n-pose.pt"):
        self.model = YOLO(model_name)

    def calibrate(self, cap, n_samples: int = 60) -> dict:
        """
        Sample n_samples frames evenly, detect person in each.
        Returns dict with 'heights' (bbox_h), 'y_positions' (hip or bbox cy).
        Resets cap to frame 0 when done.
        """
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        indices = [int(i * total / n_samples) for i in range(n_samples)]
        heights, y_positions = [], []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            det = self.detect_bbox_center(frame)
            if det is not None:
                heights.append(det[3])
            hip = self.detect_hip_center(frame)
            if hip is not None:
                y_positions.append(hip[1])
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return {"heights": heights, "y_positions": y_positions}

    def detect_all(self, frame):
        """
        Single YOLO call — returns (hip, keypoints, kp_conf, com).
        - hip:       (cx, cy) source coords, or None
        - keypoints: np.ndarray (17, 2) source coords, or None
        - kp_conf:   np.ndarray (17,), or None
        - com:       (cx, cy) source coords, or None
        """
        results = self.model(frame, verbose=False)
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None, None, None, None

        boxes = results[0].boxes
        best_idx = int(np.argmax(boxes.conf.cpu().numpy()))

        hip = None
        keypoints = None
        kp_conf = None
        com = None

        if results[0].keypoints is not None and len(results[0].keypoints) > best_idx:
            kps  = results[0].keypoints[best_idx]
            xy   = kps.xy.cpu().numpy()[0]    # (17, 2)
            conf = kps.conf.cpu().numpy()[0]  # (17,)
            keypoints = xy
            kp_conf   = conf

            # Hip centre
            lc, rc = conf[11], conf[12]
            if lc >= KEYPOINT_CONFIDENCE_THRESHOLD and rc >= KEYPOINT_CONFIDENCE_THRESHOLD:
                hip = (float((xy[11, 0] + xy[12, 0]) / 2),
                       float((xy[11, 1] + xy[12, 1]) / 2))
            elif lc >= KEYPOINT_CONFIDENCE_THRESHOLD:
                hip = (float(xy[11, 0]), float(xy[11, 1]))
            elif rc >= KEYPOINT_CONFIDENCE_THRESHOLD:
                hip = (float(xy[12, 0]), float(xy[12, 1]))

            com = self._calculate_com(xy, conf)

        if hip is None:
            x1, y1, x2, y2 = boxes.xyxy[best_idx].cpu().numpy()
            hip = (float((x1 + x2) / 2), float((y1 + y2) / 2))

        return hip, keypoints, kp_conf, com

    def detect_hip_center(self, frame):
        """
        Return (cx, cy) of hip midpoint from pose keypoints (COCO 11+12).
        Falls back to bbox center if hips not visible with sufficient confidence.
        Returns None if no person detected.
        """
        results = self.model(frame, verbose=False)
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None

        boxes = results[0].boxes
        confidences = boxes.conf.cpu().numpy()
        best_idx = int(np.argmax(confidences))

        if results[0].keypoints is not None and len(results[0].keypoints) > best_idx:
            kps = results[0].keypoints[best_idx]
            xy   = kps.xy.cpu().numpy()[0]
            conf = kps.conf.cpu().numpy()[0]

            l_conf, r_conf = conf[11], conf[12]
            if l_conf >= KEYPOINT_CONFIDENCE_THRESHOLD and r_conf >= KEYPOINT_CONFIDENCE_THRESHOLD:
                return float((xy[11, 0] + xy[12, 0]) / 2), float((xy[11, 1] + xy[12, 1]) / 2)
            elif l_conf >= KEYPOINT_CONFIDENCE_THRESHOLD:
                return float(xy[11, 0]), float(xy[11, 1])
            elif r_conf >= KEYPOINT_CONFIDENCE_THRESHOLD:
                return float(xy[12, 0]), float(xy[12, 1])

        # Fallback: bbox center
        x1, y1, x2, y2 = boxes.xyxy[best_idx].cpu().numpy()
        return float((x1 + x2) / 2), float((y1 + y2) / 2)

    def detect_bbox_center(self, frame):
        """Return (cx, cy, bbox_w, bbox_h) of best-confidence person, or None."""
        results = self.model(frame, verbose=False)
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None

        boxes = results[0].boxes
        confidences = boxes.conf.cpu().numpy()
        best_idx = int(np.argmax(confidences))
        x1, y1, x2, y2 = boxes.xyxy[best_idx].cpu().numpy()
        return (
            float((x1 + x2) / 2),
            float((y1 + y2) / 2),
            float(x2 - x1),
            float(y2 - y1),
        )

    def detect_with_com(self, frame):
        """Return (bbox_center_xywh, com_position) — bbox is (cx,cy,w,h), com is (cx,cy)."""
        results = self.model(frame, verbose=False)
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return None, None

        boxes = results[0].boxes
        confidences = boxes.conf.cpu().numpy()
        best_idx = int(np.argmax(confidences))

        x1, y1, x2, y2 = boxes.xyxy[best_idx].cpu().numpy()
        bbox = (
            float((x1 + x2) / 2),
            float((y1 + y2) / 2),
            float(x2 - x1),
            float(y2 - y1),
        )

        com = None
        if results[0].keypoints is not None and len(results[0].keypoints) > best_idx:
            kps = results[0].keypoints[best_idx]
            xy = kps.xy.cpu().numpy()[0]
            conf = kps.conf.cpu().numpy()[0]
            com = self._calculate_com(xy, conf)

        return bbox, com

    def _calculate_com(self, xy: np.ndarray, conf: np.ndarray) -> tuple[float, float] | None:
        total_weight = 0.0
        weighted_x = 0.0
        weighted_y = 0.0

        for idx, weight in _COM_WEIGHTS.items():
            if conf[idx] >= KEYPOINT_CONFIDENCE_THRESHOLD:
                weighted_x += xy[idx, 0] * weight
                weighted_y += xy[idx, 1] * weight
                total_weight += weight

        if total_weight < 0.05:
            return None

        return float(weighted_x / total_weight), float(weighted_y / total_weight)
