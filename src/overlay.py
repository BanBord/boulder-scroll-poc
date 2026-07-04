"""Frame overlays: the legacy center-of-mass dot, the skeleton + CoM trail, and
the balance panel drawn on top of the reframed output."""

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

# BGR colours — limb colour coding
_CLR_LH     = (255, 100, 30)    # left  hand/arm  → blue   (RGB #1e64ff)
_CLR_RH     = (30,  140, 255)   # right hand/arm  → orange (RGB #ff8c1e)
_CLR_LF     = (255, 180, 100)   # left  foot/leg  → light blue   (RGB #64b4ff)
_CLR_RF     = (100, 190, 255)   # right foot/leg  → light orange (RGB #ffbe64)
_CLR_BODY   = (200, 200, 200)   # torso / head    → light grey
_COM_CLR    = (89,  255, 122)   # green CoM   (BGR = #59ff7a)
_TRAIL_CLR  = (50,  180,  80)   # darker green trail
_CONF_THRESH = 0.2

# Per-edge colour: index maps to _SKELETON_EDGES list
_EDGE_COLORS = [
    _CLR_BODY,  # (0, 1)  nose → left eye
    _CLR_BODY,  # (0, 2)  nose → right eye
    _CLR_BODY,  # (1, 3)  left eye  → left ear
    _CLR_BODY,  # (2, 4)  right eye → right ear
    _CLR_LH,    # (5, 7)  left shoulder → left elbow
    _CLR_LH,    # (7, 9)  left elbow    → left wrist
    _CLR_RH,    # (6, 8)  right shoulder → right elbow
    _CLR_RH,    # (8,10)  right elbow    → right wrist
    _CLR_BODY,  # (5, 6)  shoulders
    _CLR_BODY,  # (5,11)  left  torso side
    _CLR_BODY,  # (6,12)  right torso side
    _CLR_BODY,  # (11,12) hips
    _CLR_LF,    # (11,13) left hip   → left knee
    _CLR_LF,    # (13,15) left knee  → left ankle
    _CLR_RF,    # (12,14) right hip  → right knee
    _CLR_RF,    # (14,16) right knee → right ankle
]

# Per-joint colour (COCO 17-keypoint order)
_JOINT_COLORS = [
    _CLR_BODY,  # 0  nose
    _CLR_BODY,  # 1  left eye
    _CLR_BODY,  # 2  right eye
    _CLR_BODY,  # 3  left ear
    _CLR_BODY,  # 4  right ear
    _CLR_LH,    # 5  left shoulder
    _CLR_RH,    # 6  right shoulder
    _CLR_LH,    # 7  left elbow
    _CLR_RH,    # 8  right elbow
    _CLR_LH,    # 9  left wrist
    _CLR_RH,    # 10 right wrist
    _CLR_LF,    # 11 left hip
    _CLR_RF,    # 12 right hip
    _CLR_LF,    # 13 left knee
    _CLR_RF,    # 14 right knee
    _CLR_LF,    # 15 left ankle
    _CLR_RF,    # 16 right ankle
]


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

    # Skeleton lines (per-edge colour)
    for edge_idx, (i, j) in enumerate(_SKELETON_EDGES):
        if kp_conf[i] >= _CONF_THRESH and kp_conf[j] >= _CONF_THRESH:
            p1 = (int(keypoints[i, 0]), int(keypoints[i, 1]))
            p2 = (int(keypoints[j, 0]), int(keypoints[j, 1]))
            cv2.line(overlay, p1, p2, _EDGE_COLORS[edge_idx], 2, cv2.LINE_AA)

    # Joint dots (per-joint colour)
    for idx in range(17):
        if kp_conf[idx] >= _CONF_THRESH:
            pt  = (int(keypoints[idx, 0]), int(keypoints[idx, 1]))
            clr = _JOINT_COLORS[idx]
            cv2.circle(overlay, pt, 5, clr,      -1, cv2.LINE_AA)
            cv2.circle(overlay, pt, 5, (0, 0, 0), 1, cv2.LINE_AA)

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


# ── Balance panel ───────────────────────────────────────────────────────────

_PANEL_H    = 220
_BEAM_INSET = 40     # px from frame edge to beam end
_BALL_CLR   = (50, 200, 50)
_BALL_EDGE  = (180, 255, 180)
_BEAM_CLR   = (150, 255, 150)
_LBL_CLR    = (200, 255, 200)


def draw_balance_panel(
    frame: np.ndarray,
    positions: dict,        # from PhysicsState.get_positions()
    blend: float = 0.55,
) -> np.ndarray:
    """
    Draw balance panel in the bottom _PANEL_H pixels of frame.
    Positions are x-coords in output-frame space; panel maps them to panel space.
    """
    out_h, out_w = frame.shape[:2]
    panel_y  = out_h - _PANEL_H
    panel_cx = out_w // 2
    beam_half = out_w // 2 - _BEAM_INSET

    beam_y1 = panel_y + 50    # arm beam y
    beam_y2 = panel_y + 110   # leg beam y
    com_y   = panel_y + 172   # CoM ball centre y

    # Background
    bg = frame.copy()
    cv2.rectangle(bg, (0, panel_y), (out_w, out_h), (8, 8, 8), -1)
    cv2.addWeighted(bg, blend, frame, 1.0 - blend, 0, frame)

    # Beams
    cv2.line(frame, (panel_cx - beam_half, beam_y1),
             (panel_cx + beam_half, beam_y1), _BEAM_CLR, 3, cv2.LINE_AA)
    cv2.line(frame, (panel_cx - beam_half, beam_y2),
             (panel_cx + beam_half, beam_y2), _BEAM_CLR, 3, cv2.LINE_AA)

    # Connector (CoM ball → leg beam)
    com_xi = int(np.clip(positions["com"], panel_cx - beam_half, panel_cx + beam_half))
    cv2.line(frame, (com_xi, beam_y2 + 28), (com_xi, com_y - 38),
             (120, 200, 120), 2, cv2.LINE_AA)

    # Arm ball
    arm_xi = int(np.clip(positions["arm"], panel_cx - beam_half, panel_cx + beam_half))
    cv2.circle(frame, (arm_xi, beam_y1), 20, _BALL_CLR,  -1, cv2.LINE_AA)
    cv2.circle(frame, (arm_xi, beam_y1), 20, _BALL_EDGE,  2, cv2.LINE_AA)

    # Leg ball
    leg_xi = int(np.clip(positions["leg"], panel_cx - beam_half, panel_cx + beam_half))
    cv2.circle(frame, (leg_xi, beam_y2), 26, _BALL_CLR,  -1, cv2.LINE_AA)
    cv2.circle(frame, (leg_xi, beam_y2), 26, _BALL_EDGE,  2, cv2.LINE_AA)

    # CoM ball (fulcrum)
    cv2.circle(frame, (com_xi, com_y), 36, _BALL_CLR,  -1, cv2.LINE_AA)
    cv2.circle(frame, (com_xi, com_y), 36, _BALL_EDGE,  2, cv2.LINE_AA)

    # Labels
    font = cv2.FONT_HERSHEY_SIMPLEX
    def _lbl(text, pt):
        cv2.putText(frame, text, pt, font, 0.38, (0, 0, 0),    3, cv2.LINE_AA)
        cv2.putText(frame, text, pt, font, 0.38, _LBL_CLR,      1, cv2.LINE_AA)

    _lbl("Arm",  (arm_xi - 14, beam_y1 + 5))
    _lbl("Bein", (leg_xi - 18, beam_y2 + 5))
    _lbl("CoM",  (com_xi - 18, com_y   + 5))

    return frame
