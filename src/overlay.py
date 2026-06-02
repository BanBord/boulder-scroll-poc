import cv2
import numpy as np

# ── Legacy CoM dot (kept for backward compat) ──────────────────────────────
COM_COLOR   = (0, 230, 60)
LINE_COLOR  = (0, 230, 60)
LINE_ALPHA  = 0.45
DOT_RADIUS  = 12
LINE_THICK  = 1
LABEL_TEXT  = "Center of Mass"
LABEL_FONT  = cv2.FONT_HERSHEY_SIMPLEX
LABEL_SCALE = 0.55
LABEL_THICK = 1


def draw_com(frame: np.ndarray, cx: int, cy: int) -> np.ndarray:
    """Draw CoM dot + crosshair lines + label onto frame (in-place)."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.line(overlay, (0, cy), (w, cy), LINE_COLOR, LINE_THICK)
    cv2.line(overlay, (cx, 0), (cx, h), LINE_COLOR, LINE_THICK)
    cv2.addWeighted(overlay, LINE_ALPHA, frame, 1 - LINE_ALPHA, 0, frame)
    cv2.circle(frame, (cx, cy), DOT_RADIUS, COM_COLOR, -1)
    (tw, th), _ = cv2.getTextSize(LABEL_TEXT, LABEL_FONT, LABEL_SCALE, LABEL_THICK)
    tx = (w - tw) // 2
    ty = h - 20
    cv2.rectangle(frame, (tx - 6, ty - th - 6), (tx + tw + 6, ty + 6), (0, 0, 0), -1)
    cv2.putText(frame, LABEL_TEXT, (tx, ty), LABEL_FONT, LABEL_SCALE, COM_COLOR, LABEL_THICK, cv2.LINE_AA)
    return frame


# ── Skeleton overlay ────────────────────────────────────────────────────────

# COCO 17-keypoint skeleton edges (0-indexed)
_SKELETON_EDGES = [
    (0, 1), (0, 2),           # nose → eyes
    (1, 3), (2, 4),           # eyes → ears
    (5, 7), (7, 9),           # left arm
    (6, 8), (8, 10),          # right arm
    (5, 6),                   # shoulders
    (5, 11), (6, 12),         # torso sides
    (11, 12),                 # hips
    (11, 13), (13, 15),       # left leg
    (12, 14), (14, 16),       # right leg
]

# BGR colours
_JOINT_CLR  = (255, 255, 255)   # white joints
_LINE_CLR   = (200, 200, 200)   # light grey lines
_COM_CLR    = (89, 255, 122)    # green CoM   (BGR = #59ff7a)
_TRAIL_CLR  = (50, 180, 80)     # darker green trail
_CONF_THRESH = 0.2


def draw_skeleton(
    frame: np.ndarray,
    keypoints: np.ndarray,               # (17, 2) already in output coords
    kp_conf: np.ndarray,                 # (17,)
    com: "tuple[float,float] | None",
    com_trail: "list | None" = None,     # list of (cx,cy) in output coords
    blend: float = 0.82,                 # overlay opacity
) -> np.ndarray:
    """
    Draw COCO skeleton lines, joint dots, CoM dot and optional trail.
    Blends with alpha so the underlying video stays visible.
    Returns frame (modified in-place).
    """
    overlay = frame.copy()

    if keypoints is None or kp_conf is None:
        # No pose data — draw only CoM dot and trail
        if com_trail and len(com_trail) > 1:
            for k in range(1, len(com_trail)):
                if com_trail[k - 1] is not None and com_trail[k] is not None:
                    a = (int(com_trail[k - 1][0]), int(com_trail[k - 1][1]))
                    b = (int(com_trail[k][0]),     int(com_trail[k][1]))
                    cv2.line(overlay, a, b, _TRAIL_CLR, 2, cv2.LINE_AA)
        if com is not None:
            cx, cy = int(com[0]), int(com[1])
            cv2.circle(overlay, (cx, cy), 12, _COM_CLR, -1,  cv2.LINE_AA)
            cv2.circle(overlay, (cx, cy), 12, (0, 0, 0),  2,  cv2.LINE_AA)
            cv2.circle(overlay, (cx, cy),  4, (0, 0, 0), -1,  cv2.LINE_AA)
        cv2.addWeighted(overlay, blend, frame, 1.0 - blend, 0, frame)
        return frame

    # Skeleton lines
    for i, j in _SKELETON_EDGES:
        if kp_conf[i] >= _CONF_THRESH and kp_conf[j] >= _CONF_THRESH:
            p1 = (int(keypoints[i, 0]), int(keypoints[i, 1]))
            p2 = (int(keypoints[j, 0]), int(keypoints[j, 1]))
            cv2.line(overlay, p1, p2, _LINE_CLR, 2, cv2.LINE_AA)

    # Joint dots
    for idx in range(17):
        if kp_conf[idx] >= _CONF_THRESH:
            pt = (int(keypoints[idx, 0]), int(keypoints[idx, 1]))
            cv2.circle(overlay, pt, 5,  _JOINT_CLR, -1, cv2.LINE_AA)
            cv2.circle(overlay, pt, 5,  (0, 0, 0),   1, cv2.LINE_AA)

    # CoM trail
    if com_trail and len(com_trail) > 1:
        for k in range(1, len(com_trail)):
            if com_trail[k - 1] is not None and com_trail[k] is not None:
                a = (int(com_trail[k - 1][0]), int(com_trail[k - 1][1]))
                b = (int(com_trail[k][0]),     int(com_trail[k][1]))
                # trail fades toward the older end
                age_alpha = k / len(com_trail)
                color = tuple(int(c * age_alpha) for c in _TRAIL_CLR)
                cv2.line(overlay, a, b, color, 2, cv2.LINE_AA)

    # CoM dot
    if com is not None:
        cx, cy = int(com[0]), int(com[1])
        cv2.circle(overlay, (cx, cy), 12, _COM_CLR, -1,  cv2.LINE_AA)
        cv2.circle(overlay, (cx, cy), 12, (0, 0, 0), 2,  cv2.LINE_AA)
        cv2.circle(overlay, (cx, cy),  4, (0, 0, 0), -1, cv2.LINE_AA)

    cv2.addWeighted(overlay, blend, frame, 1.0 - blend, 0, frame)
    return frame
