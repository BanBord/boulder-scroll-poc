"""Compositing for the "Maschinenblick" reading video (1080x1920, 30 fps).

Every layer is drawn at SS-times resolution and downsampled once at the end,
so strokes and dots come out anti-aliased at their fractional widths.
Positions and sizes given to the public helpers are output pixels (1080x1920)
unless the name says otherwise.

Colour rule: signal orange ORANGE means "contact" and nothing else.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SS = 2                      # supersampling factor
W, H = 1080, 1920
BG = (18, 18, 18)           # #121212
OFF = (242, 239, 233)       # #F2EFE9
ORANGE = (255, 90, 31)      # #FF5A1F: contact only
LIMB_ORDER = ["left_hand", "right_hand", "left_foot", "right_foot"]
LIMB_CODE = {"left_hand": "LH", "right_hand": "RH", "left_foot": "LF", "right_foot": "RF"}

# Layout (output px, all multiples of 4)
MARGIN = 40
PANEL_TOP = 1560
ROW_TOP = [1592, 1624, 1656, 1688]
ROW_H = 24
TL_X0, TL_X1 = 128, 1040
CURVE_BANDS = {"arm": (1736, 1776), "leg": (1784, 1824), "com": (1832, 1872)}
CURVE_OPACITY = {"arm": 0.90, "leg": 0.60, "com": 0.35}

DOT_GRID = 24               # background dot grid spacing
HALFTONE_CELL = 7
INTRO_S = 1.0               # holds draw in during the first second
INTRO_SPAN_S = 0.8          # appearance times spread over this part of the intro
DRAW_IN_S = 0.2
FILL_FADE_FRAMES = 3

FONT_PATHS = ["/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"]
COCO_BONES = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
              (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


def load_font(px: float) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=round(px * SS))
        except OSError:
            continue
    raise RuntimeError("no monospace font found (tried %s)" % ", ".join(FONT_PATHS))


# ---------------------------------------------------------------- primitives

def new_canvas() -> np.ndarray:
    canvas = np.empty((H * SS, W * SS, 3), np.float32)
    canvas[:] = BG
    return canvas


def blend(canvas: np.ndarray, x0: int, y0: int, alpha: np.ndarray,
          color: Sequence[int], opacity: float = 1.0) -> None:
    """Composite a 0..1 alpha patch whose top-left corner is at SS pixel (x0, y0)."""
    if opacity <= 0:
        return
    ph, pw = alpha.shape
    ch, cw = canvas.shape[:2]
    xa, ya = max(0, x0), max(0, y0)
    xb, yb = min(cw, x0 + pw), min(ch, y0 + ph)
    if xa >= xb or ya >= yb:
        return
    a = alpha[ya - y0:yb - y0, xa - x0:xb - x0] * np.float32(opacity)
    region = canvas[ya:yb, xa:xb]
    region += (np.asarray(color, np.float32) - region) * a[..., None]


def _local_bounds(pts_ss: np.ndarray, pad: int) -> Tuple[int, int, int, int]:
    x0 = int(math.floor(pts_ss[:, 0].min())) - pad
    y0 = int(math.floor(pts_ss[:, 1].min())) - pad
    x1 = int(math.ceil(pts_ss[:, 0].max())) + pad
    y1 = int(math.ceil(pts_ss[:, 1].max())) + pad
    return x0, y0, x1, y1


def _to_fixed(pts_ss: np.ndarray, x0: int, y0: int) -> np.ndarray:
    return np.round((pts_ss - np.array([x0, y0])) * 16).astype(np.int32)


def polyline(canvas, pts, width: float, color, opacity: float = 1.0, closed: bool = False) -> None:
    """Anti-aliased stroke through output-px points; width in output px (fractional ok)."""
    p = np.asarray(pts, np.float64).reshape(-1, 2) * SS
    if len(p) < 2:
        return
    pad = int(width * SS) + 4
    x0, y0, x1, y1 = _local_bounds(p, pad)
    local = np.zeros((y1 - y0, x1 - x0), np.uint8)
    thick = max(1, int(round(width * SS)))
    cv2.polylines(local, [_to_fixed(p, x0, y0)], closed, 255, thick, cv2.LINE_AA, 4)
    blend(canvas, x0, y0, local.astype(np.float32) / 255.0, color, opacity)


def fill_polygon(canvas, pts, color, opacity: float = 1.0) -> None:
    p = np.asarray(pts, np.float64).reshape(-1, 2) * SS
    if len(p) < 3:
        return
    x0, y0, x1, y1 = _local_bounds(p, 2)
    local = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(local, [_to_fixed(p, x0, y0)], 255, cv2.LINE_AA, 4)
    blend(canvas, x0, y0, local.astype(np.float32) / 255.0, color, opacity)


def disc(canvas, cx: float, cy: float, radius: float, color, opacity: float = 1.0) -> None:
    p = np.array([[cx, cy]], np.float64) * SS
    r = max(radius * SS, 0.5)
    pad = int(r) + 3
    x0, y0, x1, y1 = _local_bounds(p, pad)
    local = np.zeros((y1 - y0, x1 - x0), np.uint8)
    center = _to_fixed(p, x0, y0)[0]
    cv2.circle(local, (int(center[0]), int(center[1])), int(round(r * 16)), 255, -1, cv2.LINE_AA, 4)
    blend(canvas, x0, y0, local.astype(np.float32) / 255.0, color, opacity)


def rect(canvas, x0: float, y0: float, x1: float, y1: float, color, opacity: float = 1.0) -> None:
    fill_polygon(canvas, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], color, opacity)


def text(canvas, x: float, y: float, s: str, font: ImageFont.FreeTypeFont,
         color, opacity: float = 1.0) -> Tuple[float, float, float, float]:
    """Draw monospace text with its ink top-left at output px (x, y). Returns its output-px box."""
    l, t, r, b = font.getbbox(s)
    img = Image.new("L", (r - l + 2, b - t + 2), 0)
    ImageDraw.Draw(img).text((1 - l, 1 - t), s, font=font, fill=255)
    alpha = np.asarray(img, np.float32) / 255.0
    ox, oy = int(round(x * SS)) - 1, int(round(y * SS)) - 1
    blend(canvas, ox, oy, alpha, color, opacity)
    return x, y, x + (r - l) / SS, y + (b - t) / SS


def text_size(font: ImageFont.FreeTypeFont, s: str) -> Tuple[float, float]:
    l, t, r, b = font.getbbox(s)
    return (r - l) / SS, (b - t) / SS


# ---------------------------------------------------------------- data

@dataclass
class HoldGeom:
    id: int
    index: int                    # rank top-to-bottom among all holds, 1-based
    color: Optional[str]
    score: Optional[float]
    route: bool
    polys: List[np.ndarray]       # outline polygons, output px
    bbox: Tuple[float, float, float, float]   # x0, y0, x1, y1 output px
    appear_t: float               # seconds; intro draw-in time


@dataclass
class ReadingData:
    fps: float
    n_frames: int
    holds: List[HoldGeom]
    intervals: List[dict]         # limb, hold_id, f_start, f_end, t_start, t_end
    keypoints: np.ndarray         # (N, 17, 3): x, y, conf in output px
    com: np.ndarray               # (N, 2), NaN where unknown
    balance: np.ndarray           # (N, 3): arm, leg, com; NaN where unknown
    person: np.ndarray            # (N, H, W) uint8, 1x
    aligned: np.ndarray           # (N, H, W, 3) uint8 RGB, 1x, stabilised frames
    show_scores: bool
    route_total: int
    holds_total: int
    halftone_r: Tuple[float, float] = (0.5, 3.0)


def contact_state(intervals: List[dict], f: int, hold_id: int):
    """(active intervals, visited flag) for one hold at frame f."""
    active = [iv for iv in intervals if iv["hold_id"] == hold_id and iv["f_start"] <= f <= iv["f_end"]]
    visited = any(iv["hold_id"] == hold_id and iv["f_end"] < f for iv in intervals)
    return active, visited


# ---------------------------------------------------------------- renderer

class ReadingRenderer:
    def __init__(self, data: ReadingData):
        self.d = data
        self.font20 = load_font(20)
        self.font22 = load_font(22)
        self.font16 = load_font(16)
        self.label_h = text_size(self.font20, "H00")[1]
        self.balance_scale = {}
        for k, col in enumerate(["arm", "leg", "com"]):
            vals = np.abs(data.balance[:, k])
            vals = vals[np.isfinite(vals)]
            self.balance_scale[col] = max(float(np.percentile(vals, 98)) if vals.size else 1.0, 1.0)
        self.base = self._build_base()
        self.panel_hold_conflict = any(h.bbox[3] > PANEL_TOP for h in data.holds)
        self._pad_cache = {}

    # static layers: background and dot grid
    def _build_base(self) -> np.ndarray:
        canvas = new_canvas()
        dots = np.zeros((H * SS, W * SS), np.uint8)
        r = SS  # 2 px dot = radius 1 px at output scale
        for y in range(DOT_GRID // 2, H, DOT_GRID):
            for x in range(DOT_GRID // 2, W, DOT_GRID):
                cv2.circle(dots, (x * SS, y * SS), r, 255, -1, cv2.LINE_AA)
        blend(canvas, 0, 0, dots.astype(np.float32) / 255.0, OFF, 0.06)
        return canvas

    def render(self, f: int) -> np.ndarray:
        d = self.d
        t = f / d.fps
        canvas = self.base.copy()
        person = np.asarray(d.person[f])
        self._halftone(canvas, f, person)
        self._holds(canvas, f, t)
        self._skeleton(canvas, f)
        self._com(canvas, f)
        self._labels(canvas, f, t)
        self._readout(canvas, f, t)
        self._panel(canvas, f, t, person)
        out = cv2.resize(canvas, (W, H), interpolation=cv2.INTER_AREA)
        return np.clip(out + 0.5, 0, 255).astype(np.uint8)

    # --- climber as halftone raster
    def _halftone(self, canvas, f: int, person: np.ndarray) -> None:
        cell = HALFTONE_CELL
        gh, gw = H // cell, W // cell
        inside = person[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell).mean(axis=(1, 3)) > 0.5
        if not inside.any():
            return
        frame = np.asarray(self.d.aligned[f])
        lum = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32)
        lum_cell = lum[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell).mean(axis=(1, 3))
        r_lo, r_hi = self.d.halftone_r
        radius = r_lo + (r_hi - r_lo) * lum_cell / 255.0
        ii, jj = np.nonzero(inside)
        rS = radius[ii, jj] * SS
        cy = (ii * cell + cell // 2) * SS
        cx = (jj * cell + cell // 2) * SS
        span = int(math.ceil(r_hi * SS)) + 1
        alpha = np.zeros((H * SS, W * SS), np.float32)
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                dist = math.hypot(dx, dy)
                a = np.clip(rS - dist + 0.5, 0.0, 1.0).astype(np.float32)
                keep = a > 0
                if not keep.any():
                    continue
                yy, xx = cy[keep] + dy, cx[keep] + dx
                alpha[yy, xx] = np.maximum(alpha[yy, xx], a[keep])
        blend(canvas, 0, 0, alpha, OFF, 1.0)

    # --- holds
    def _holds(self, canvas, f: int, t: float) -> None:
        d = self.d
        for h in d.holds:
            if t < h.appear_t:
                continue
            op_in = min(1.0, (t - h.appear_t) / DRAW_IN_S)
            active, visited = contact_state(d.intervals, f, h.id)
            if active:
                k = f - min(iv["f_start"] for iv in active)
                fill = min(1.0, (k + 1) / FILL_FADE_FRAMES)
                for poly in h.polys:
                    fill_polygon(canvas, poly, ORANGE, fill * op_in)
                for poly in h.polys:
                    polyline(canvas, poly, 2.0, ORANGE, op_in, closed=True)
            elif visited:
                for poly in h.polys:
                    polyline(canvas, poly, 2.0, ORANGE, op_in, closed=True)
            elif h.route:
                for poly in h.polys:
                    polyline(canvas, poly, 2.0, OFF, 0.90 * op_in, closed=True)
            else:
                for poly in h.polys:
                    polyline(canvas, poly, 1.5, OFF, 0.28 * op_in, closed=True)

    # --- skeleton with confidence-mapped opacity
    @staticmethod
    def _conf_opacity(c: np.ndarray) -> np.ndarray:
        return np.clip(0.12 + (c - 0.2) / 0.7 * 0.88, 0.12, 1.0)

    def _skeleton(self, canvas, f: int) -> None:
        kp = self.d.keypoints[f]
        if not np.isfinite(kp).all():
            kp = np.nan_to_num(kp)
        op = self._conf_opacity(kp[:, 2])
        for a, b in COCO_BONES:
            if kp[a, 2] <= 0 or kp[b, 2] <= 0:
                continue
            polyline(canvas, [kp[a, :2], kp[b, :2]], 2.0, OFF, float(min(op[a], op[b])))
        for i in range(kp.shape[0]):
            if kp[i, 2] <= 0 and kp[i, 0] == 0 and kp[i, 1] == 0:
                continue
            disc(canvas, kp[i, 0], kp[i, 1], 2.0, OFF, float(op[i]))

    # --- centre of mass
    def _com(self, canvas, f: int) -> None:
        com = self.d.com
        seg = []
        for g in range(f + 1):
            if np.isfinite(com[g]).all():
                seg.append(com[g])
            else:
                if len(seg) >= 2:
                    polyline(canvas, seg, 1.5, OFF, 0.55)
                seg = []
        if len(seg) >= 2:
            polyline(canvas, seg, 1.5, OFF, 0.55)
        if np.isfinite(com[f]).all():
            x, y = com[f]
            polyline(canvas, [[x - 14, y], [x + 14, y]], 1.5, OFF, 1.0)
            polyline(canvas, [[x, y - 14], [x, y + 14]], 1.5, OFF, 1.0)
            text(canvas, x + 20, y - 10, "CoM", self.font20, OFF, 0.70)

    # --- label placement
    def _labels(self, canvas, f: int, t: float) -> None:
        placed = [(MARGIN - 4, MARGIN - 4, MARGIN + 380, MARGIN + 3 * 32 + 4),
                  (0, PANEL_TOP - 4, W, H)]
        items = []
        for h in self.d.holds:
            if t < h.appear_t:
                continue
            active, _ = contact_state(self.d.intervals, f, h.id)
            if not (h.route or active):
                continue
            if active:
                limbs = sorted({iv["limb"] for iv in active}, key=LIMB_ORDER.index)
                elapsed = t - min(iv["t_start"] for iv in active)
                s = "%s %.1fs" % ("+".join(LIMB_CODE[l] for l in limbs), elapsed)
                colour, op = ORANGE, 1.0
            else:
                s = "H%02d" % h.index
                if self.d.show_scores and h.score is not None:
                    s += " %.2f" % h.score
                colour, op = OFF, 0.60
            items.append((h, s, colour, op))
        items.sort(key=lambda it: (it[0].bbox[1] + it[0].bbox[3]) / 2)
        for h, s, colour, op in items:
            w, hh = text_size(self.font20, s)
            x0, y0, x1, y1 = h.bbox
            x = x1 + 8
            if x + w > W - MARGIN:
                x = x0 - 8 - w
            cy = (y0 + y1) / 2 - hh / 2
            y = self._free_slot(cy, x, w, hh, placed)
            placed.append((x - 2, y - 2, x + w + 2, y + hh + 2))
            text(canvas, x, y, s, self.font20, colour, op)

    @staticmethod
    def _free_slot(y: float, x: float, w: float, h: float, placed) -> float:
        def clash(yy):
            for px0, py0, px1, py1 in placed:
                if x < px1 and x + w > px0 and yy < py1 and yy + h > py0:
                    return True
            return False
        if not clash(y):
            return y
        step = h + 4
        for k in range(1, 12):
            for cand in (y + k * step, y - k * step):
                if 0 <= cand <= PANEL_TOP - h - 8 and not clash(cand):
                    return cand
        return y

    # --- readout
    def _readout(self, canvas, f: int, t: float) -> None:
        d = self.d
        n_contacts = sum(1 for iv in d.intervals if iv["f_start"] <= f)
        text(canvas, MARGIN, MARGIN, "T %05.2f s   F %04d" % (t, f), self.font22, OFF, 0.70)
        text(canvas, MARGIN, MARGIN + 32, "HOLDS %d   ROUTE %d" % (d.holds_total, d.route_total),
             self.font22, OFF, 0.70)
        text(canvas, MARGIN, MARGIN + 64, "CONTACTS %02d" % n_contacts, self.font22, OFF, 0.70)

    # --- bottom panel: contact timeline and balance curves
    def _panel(self, canvas, f: int, t: float, person: np.ndarray) -> None:
        d = self.d
        panel_op = 0.92
        if person[PANEL_TOP:].any():
            panel_op = 0.35        # figure enters the panel: let it show through
        rect(canvas, 0, PANEL_TOP, W, H, BG, panel_op)
        polyline(canvas, [[0, PANEL_TOP], [W, PANEL_TOP]], 1.0, OFF, 0.40)
        duration = d.n_frames / d.fps

        def X(tt: float) -> float:
            return TL_X0 + (tt / duration) * (TL_X1 - TL_X0)

        playhead_x = X(t)
        for row, limb in enumerate(LIMB_ORDER):
            top = ROW_TOP[row]
            rect(canvas, TL_X0, top, TL_X1, top + ROW_H, OFF, 0.08)
            for iv in d.intervals:
                if iv["limb"] != limb or iv["t_start"] > t:
                    continue
                rect(canvas, X(iv["t_start"]), top, X(min(iv["t_end"], t)), top + ROW_H, ORANGE, 1.0)
            text(canvas, MARGIN, top + ROW_H / 2 - 8, LIMB_CODE[limb], self.font16, OFF, 0.70)

        for key, (top, bottom) in CURVE_BANDS.items():
            col = ["arm", "leg", "com"].index(key)
            mid = (top + bottom) / 2
            half = (bottom - top) / 2 - 2
            polyline(canvas, [[TL_X0, mid], [TL_X1, mid]], 1.0, OFF, 0.15)
            seg = []
            for g in range(f + 1):
                v = d.balance[g, col]
                if np.isfinite(v):
                    v = float(np.clip(v / self.balance_scale[key], -1.0, 1.0))
                    seg.append([X(g / d.fps), mid - v * half])
                else:
                    if len(seg) >= 2:
                        polyline(canvas, seg, 1.5, OFF, CURVE_OPACITY[key])
                    seg = []
            if len(seg) >= 2:
                polyline(canvas, seg, 1.5, OFF, CURVE_OPACITY[key])
            text(canvas, MARGIN, mid - 8, key.upper(), self.font16, OFF, 0.70)

        polyline(canvas, [[playhead_x, ROW_TOP[0] - 8], [playhead_x, CURVE_BANDS["com"][1]]], 1.0, OFF, 0.90)


def stills_frames(n_frames: int) -> List[int]:
    """Five evenly spread frame indices for the stills (5 %, 27 %, 50 %, 73 %, 95 %)."""
    return [int(round(p * (n_frames - 1))) for p in (0.05, 0.27, 0.50, 0.73, 0.95)]
