"""
Pika character sprites, drawn in code (PIL) in the style of the Pika mascot
("MFEC Clay Boy"): chubby clay boy, curly brown hair, white MFEC tee, khaki shorts,
cream sneakers.

Every part is a soft-shaded "clay" blob (top-left key light, darker towards the
silhouette) rendered at 4x and scaled down. No image files needed.

    frames = render_frames(height=150)   # {"idle": PIL.Image RGBA, "blink": ..., ...}
    icon = head_icon(32)
"""
import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# design space (units); the head + hair sit at the top, sneakers touch the bottom
DW, DH = 120, 156
S = 4  # supersampling

# palette (from the Pika mascot clay palette)
SKIN = (242, 179, 130)
EAR_IN = (205, 128, 84)
NOSE = (238, 152, 102)
HAIR = (78, 49, 28)
HAIR_DK = (48, 29, 14)
HAIR_HI = (128, 86, 55)
EYE = (22, 12, 9)
BLUSH = (250, 128, 117)
SHIRT = (249, 248, 245)
SHIRT_DK = (214, 211, 204)
SHORTS = (170, 138, 80)
SHORTS_DK = (128, 99, 54)
SHOE = (236, 213, 156)
SHOE_DK = (200, 174, 120)
WATCH = (41, 36, 31)
BLUE = (37, 99, 235)
SKY = (125, 205, 250)
GLASS = (214, 238, 252)
MOUTH_IN = (110, 38, 33)
TONGUE = (240, 133, 128)
TEETH = (253, 251, 246)
OUTLINE = (66, 44, 30)

HAND_L, HAND_R = (32.5, 121.5), (87.5, 121.5)

POSES = {
    # pose keys: eyes, brows, mouth, blush, hands (left, right), legs (lift L, R),
    # head (tilt deg, dx, dy), extras: dots n, zzz phase, sparkle phase, waves n,
    # magnifier, sweat
    "idle": {},
    "blink": {"eyes": "closed"},
    "look_l": {"eyes": "left", "head": (3, -0.6, 0)},
    "look_r": {"eyes": "right", "head": (-3, 0.6, 0)},
    "curious": {"eyes": "wide", "brows": "up", "mouth": "smile", "head": (9, 0, 0.5)},
    "walk1": {"legs": (3.5, 0), "hands": ((35, 119), (86, 124)), "head": (-1.5, 0, 0)},
    "walk2": {"legs": (0, 3.5), "hands": ((34, 124), (85, 119)), "head": (1.5, 0, 0)},
    "wave1": {"eyes": "happy", "mouth": "grin", "blush": 0.6, "hands": (None, (101, 80))},
    "wave2": {"eyes": "happy", "mouth": "grin", "blush": 0.6, "hands": (None, (109, 87)),
              "head": (-3, 0, 0)},
    "listen1": {"eyes": "wide", "brows": "up", "mouth": "o", "waves": 1, "head": (4, 0, 0)},
    "listen2": {"eyes": "wide", "brows": "up", "mouth": "o", "waves": 2, "head": (4, 0, 0)},
    "think1": {"eyes": "up", "brows": "think", "mouth": "flat", "hands": (None, (70, 97)),
               "dots": 1, "head": (-3, 0, 0)},
    "think2": {"eyes": "up", "brows": "think", "mouth": "flat", "hands": (None, (70, 97)),
               "dots": 2, "head": (-3, 0, 0)},
    "think3": {"eyes": "up", "brows": "think", "mouth": "flat", "hands": (None, (70, 97)),
               "dots": 3, "head": (-3, 0, 0)},
    "search1": {"eyes": "right", "brows": "up", "mouth": "o", "hands": (None, (92, 96)),
                "magnifier": True, "head": (-3, 0.5, 0)},
    "search2": {"eyes": "right", "brows": "up", "mouth": "smile", "hands": (None, (86, 92)),
                "magnifier": True, "head": (-6, 1, 0)},
    "talk1": {"mouth": "open", "blush": 0.3},
    "talk2": {"mouth": "mid", "blush": 0.3},
    "talk3": {"mouth": "o", "blush": 0.3, "head": (2, 0, 0)},
    "explain1": {"mouth": "open", "brows": "up", "blush": 0.3, "hands": ((21, 108), None),
                 "head": (2, 0, 0)},
    "explain2": {"mouth": "mid", "brows": "up", "blush": 0.3, "hands": ((23, 104), None),
                 "head": (3, 0, 0)},
    "happy1": {"eyes": "happy", "mouth": "grin", "blush": 0.8, "hands": ((17, 81), (103, 81)),
               "sparkle": 0},
    "happy2": {"eyes": "happy", "mouth": "grin", "blush": 0.8, "hands": ((19, 77), (101, 77)),
               "sparkle": 1, "legs": (1.5, 1.5)},
    "sleep1": {"eyes": "sleep", "brows": "relaxed", "mouth": "sleep", "zzz": 0,
               "head": (7, 0, 1.5)},
    "sleep2": {"eyes": "sleep", "brows": "relaxed", "mouth": "sleep", "zzz": 1,
               "head": (7, 0, 2.3)},
    "sad": {"brows": "worried", "mouth": "frown", "sweat": True, "head": (-4, 0, 1)},
    "surprised": {"eyes": "wide", "brows": "up", "mouth": "o", "hands": ((25, 107), (95, 107))},
    "drag": {"eyes": "wide", "brows": "worried", "mouth": "o", "hands": ((18, 84), (102, 84)),
             "legs": (3, 0.5), "sweat": True},
}


# ─── drawing helpers (design units -> supersampled pixels) ────────
def _p(x, y):
    return x * S, y * S


def _mask():
    m = Image.new("L", (DW * S, DH * S), 0)
    return m, ImageDraw.Draw(m)


def _ell(d, cx, cy, rx, ry, fill=255):
    d.ellipse([(cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S], fill=fill)


def _rrect(d, x0, y0, x1, y1, r, fill=255):
    d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill)


def _stroke(d, pts, width, fill=255):
    d.line([_p(x, y) for x, y in pts], fill=fill, width=max(1, int(width * S)), joint="curve")
    for x, y in (pts[0], pts[-1]):
        _ell(d, x, y, width / 2, width / 2, fill)


def _bezier(p0, p1, p2, n=18):
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))
    return out


class _Painter:
    def __init__(self):
        self.img = Image.new("RGBA", (DW * S, DH * S), (0, 0, 0, 0))

    def _paste(self, rgb, alpha, box):
        layer = Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8))
        base = self.img.crop(box)
        self.img.paste(Image.alpha_composite(base, layer), box)

    def clay(self, mask, color, light=(0.32, 0.22), gain=0.40, edge=0.28, sheen=0.10, clip=None):
        """Soft clay shading: bright near the key light, darker towards the silhouette."""
        if clip is not None:
            mask = ImageChops.multiply(mask, clip)
        box = mask.getbbox()
        if not box:
            return
        crop = mask.crop(box)
        m = np.asarray(crop, dtype=np.float32) / 255.0
        h, w = m.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.hypot((xx - light[0] * w) / w, (yy - light[1] * h) / h)
        f = 1.10 - gain * d
        r = max(2.0, 0.12 * min(w, h))
        blur = np.asarray(crop.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255.0
        f *= 1.0 - edge * np.clip((1.0 - blur) * 2.0, 0, 1)
        spec = sheen * np.exp(-(d / 0.16) ** 2) * 255.0
        rgb = np.clip(np.array(color, dtype=np.float32)[None, None, :] * f[..., None] + spec[..., None], 0, 255)
        self._paste(rgb, m * 255.0, box)

    def flat(self, mask, color, alpha=1.0, clip=None):
        if clip is not None:
            mask = ImageChops.multiply(mask, clip)
        box = mask.getbbox()
        if not box:
            return
        m = np.asarray(mask.crop(box), dtype=np.float32) * alpha
        rgb = np.empty(m.shape + (3,), dtype=np.float32)
        rgb[...] = color
        self._paste(rgb, m, box)


# ─── body parts ───────────────────────────────────────────────────
def _legs(pt, lift):
    for side, (sx, up) in enumerate(((49, lift[0]), (71, lift[1]))):
        # shin
        m, d = _mask()
        _rrect(d, sx - 4.2, 129, sx + 4.2, 145 - up, 3.5)
        pt.clay(m, SKIN, gain=0.30, edge=0.2)
        # sneaker: sole + upper + tongue
        dx = -1.5 if side == 0 else 1.5
        cy = 147.5 - up
        m, d = _mask()
        _ell(d, sx + dx, cy + 2.6, 11.2, 4.2)
        pt.clay(m, SHOE_DK, gain=0.25, edge=0.2)
        m, d = _mask()
        _ell(d, sx + dx, cy, 10.2, 5.6)
        pt.clay(m, SHOE, light=(0.35, 0.2), gain=0.30, edge=0.22, sheen=0.12)
        m, d = _mask()
        _stroke(d, [(sx + dx - 3.5, cy - 2.4), (sx + dx + 3.5, cy - 2.4)], 1.0)
        _stroke(d, [(sx + dx - 3.0, cy - 0.4), (sx + dx + 3.0, cy - 0.4)], 1.0)
        pt.flat(m, SHOE_DK, 0.8)


def _shorts(pt):
    m, d = _mask()
    _rrect(d, 38.5, 114, 81.5, 128, 6)
    _rrect(d, 38, 118, 59.4, 133.5, 4.5)
    _rrect(d, 60.6, 118, 82, 133.5, 4.5)
    pt.clay(m, SHORTS, gain=0.32, edge=0.25)
    m, d = _mask()
    _rrect(d, 38, 129.5, 59.4, 133.5, 2.5)
    _rrect(d, 60.6, 129.5, 82, 133.5, 2.5)
    pt.clay(m, SHORTS, light=(0.3, 0.1), gain=0.45, edge=0.35)
    m, d = _mask()
    _stroke(d, [(60, 124), (60, 133)], 0.9)
    pt.flat(m, SHORTS_DK, 0.6)


def _torso(pt):
    m, d = _mask()
    _rrect(d, 37, 89, 83, 125, 14)
    pt.clay(m, SHIRT, light=(0.33, 0.18), gain=0.22, edge=0.22, sheen=0.06)
    # crew-neck collar + neck
    m, d = _mask()
    _ell(d, 60, 90.5, 9.5, 4.2)
    pt.clay(m, SHIRT_DK, gain=0.2, edge=0.3)
    m, d = _mask()
    _ell(d, 60, 89.5, 7.6, 3.2)
    pt.clay(m, (222, 156, 108), gain=0.2, edge=0.3)
    # Pika badge on the chest: blue rounded square with a white lightning bolt
    m, d = _mask()
    _rrect(d, 63, 101, 73, 111, 2.6)
    pt.clay(m, BLUE, light=(0.3, 0.2), gain=0.35, edge=0.15, sheen=0.18)
    m, d = _mask()
    d.polygon([_p(69.2, 102.6), _p(65.4, 106.6), _p(67.9, 106.6), _p(66.6, 109.6),
               _p(70.6, 105.2), _p(68.1, 105.2)], fill=255)
    pt.flat(m, (255, 255, 255))


def _hand(pt, hand):
    m, d = _mask()
    _ell(d, hand[0], hand[1], 5.8, 5.8)
    pt.clay(m, SKIN, gain=0.32, edge=0.22, sheen=0.08)


def _arm(pt, shoulder, hand, watch=False, with_hand=True):
    sx, sy = shoulder
    hx, hy = hand
    m, d = _mask()
    _stroke(d, [(sx, sy + 3), (hx, hy)], 8.4)
    pt.clay(m, SKIN, gain=0.30, edge=0.22)
    if watch:
        t = 0.80
        wx, wy = sx + (hx - sx) * t, sy + 3 + (hy - sy - 3) * t
        ang = math.atan2(hy - sy, hx - sx) + math.pi / 2
        m, d = _mask()
        _stroke(d, [(wx - 4.5 * math.cos(ang), wy - 4.5 * math.sin(ang)),
                    (wx + 4.5 * math.cos(ang), wy + 4.5 * math.sin(ang))], 2.6)
        pt.clay(m, WATCH, gain=0.2, edge=0.1, sheen=0.15)
    if with_hand:
        _hand(pt, hand)
    # short sleeve over the shoulder
    m, d = _mask()
    ang = math.atan2(hy - sy, hx - sx)
    _ell(d, sx + 2.0 * math.cos(ang), sy + 2.0 * math.sin(ang) + 1.5, 6.6, 6.4)
    pt.clay(m, SHIRT, light=(0.35, 0.2), gain=0.30, edge=0.30, sheen=0.03)


def _ears(pt):
    for cx, inner in ((24, 26.5), (96, 93.5)):
        m, d = _mask()
        _ell(d, cx, 66, 8.6, 9.4)
        pt.clay(m, SKIN, gain=0.3, edge=0.25)
        m, d = _mask()
        _ell(d, inner, 66.5, 4.4, 5.2)
        pt.clay(m, EAR_IN, light=(0.7, 0.7), gain=0.3, edge=0.3)


def _head(pt):
    m, d = _mask()
    _ell(d, 60, 58, 36.5, 33)
    _ell(d, 41, 71, 15.5, 15)
    _ell(d, 79, 71, 15.5, 15)
    _ell(d, 60, 79, 24, 12.5)
    pt.clay(m, SKIN, light=(0.36, 0.30), gain=0.30, edge=0.22, sheen=0.07)
    return m


def _hair(pt):
    rnd = random.Random(7)
    m, d = _mask()
    _ell(d, 60, 39, 41.5, 30.5)
    cut, dc = _mask()
    hl = lambda x: 40.0 + 16.0 * ((x - 60) / 38.0) ** 2   # hairline: high middle, low at the sides
    pts = [(x, hl(x)) for x in np.linspace(12, 108, 49)]
    dc.polygon([_p(x, y) for x, y in pts] + [_p(108, DH), _p(12, DH)], fill=255)
    m = ImageChops.subtract(m, cut)
    d = ImageDraw.Draw(m)
    for x in np.arange(27, 95, 8.4):                        # fringe curls
        _ell(d, x, hl(x) - 0.5, 5.3, 5.0)
    for a in np.linspace(math.radians(195), math.radians(345), 13):   # bumpy curly crown
        _ell(d, 60 + 40 * math.cos(a), 39 + 29.5 * math.sin(a), 6.6, 6.2)
    _ell(d, 22.5, 52, 6.0, 7.0)                              # sideburn curls
    _ell(d, 97.5, 52, 6.0, 7.0)
    pt.clay(m, HAIR, light=(0.34, 0.12), gain=0.42, edge=0.30, sheen=0.10)
    # curl texture (tidy rings following the dome), clipped to the hair
    tex_dk, dd = _mask()
    tex_hi, dh = _mask()
    for row, (ry_, n) in enumerate(((0.25, 3), (0.55, 6), (0.85, 8))):
        for i in range(n):
            a = math.radians(200 + (140 / max(1, n - 1)) * i) if n > 1 else math.radians(270)
            cx = 60 + 37 * ry_ * math.cos(a) + rnd.uniform(-1.5, 1.5)
            cy = 42 + 28 * ry_ * math.sin(a) + rnd.uniform(-1.0, 1.0)
            rr = 3.6
            start = rnd.uniform(-30, 30)
            dd.arc([(cx - rr) * S, (cy - rr) * S, (cx + rr) * S, (cy + rr) * S],
                   start, start + 200, fill=255, width=int(1.0 * S))
            _ell(dh, cx - 1.3, cy - 1.5, 1.2, 1.0)
    pt.flat(tex_dk.filter(ImageFilter.GaussianBlur(0.3 * S)), HAIR_DK, 0.55, clip=m)
    pt.flat(tex_hi.filter(ImageFilter.GaussianBlur(0.5 * S)), HAIR_HI, 0.45, clip=m)


def _brows(pt, kind):
    m, d = _mask()
    for sign in (-1, 1):
        cx = 60 + sign * 14.5
        inner, outer = 0.0, 0.0
        if kind == "up":
            inner = outer = -3.0
        elif kind == "worried":
            inner, outer = -3.2, 0.8
        elif kind == "relaxed":
            inner = outer = 1.2
        elif kind == "think" and sign == 1:
            inner, outer = -3.5, -2.5
        p_in = (cx - sign * 7, 52.2 + inner)
        p_out = (cx + sign * 7.5, 53.2 + outer)
        mid = (cx, 50.2 + (inner + outer) / 2)
        _stroke(d, _bezier(p_in, mid, p_out), 2.7)
    pt.clay(m, HAIR, gain=0.2, edge=0.1)


def _eyes(pt, kind):
    for sign in (-1, 1):
        x, y = 60 + sign * 14, 64.5
        if kind in ("open", "wide", "up", "left", "right"):
            rx, ry = (3.9, 5.3) if kind == "wide" else (3.4, 4.7)
            dx, dy = {"up": (0.6, -1.0), "right": (1.4, 0.2), "left": (-1.4, 0.2)}.get(kind, (0, 0))
            m, d = _mask()
            _ell(d, x + dx, y + dy, rx, ry)
            pt.clay(m, EYE, gain=0.2, edge=0.0, sheen=0.05)
            m, d = _mask()
            _ell(d, x + dx - 1.1, y + dy - 1.8, 1.35, 1.35)
            _ell(d, x + dx + 1.2, y + dy + 1.7, 0.6, 0.6)
            pt.flat(m, (255, 255, 255))
        else:
            m, d = _mask()
            if kind == "happy":
                _stroke(d, _bezier((x - 4.2, y + 1.6), (x, y - 4.4), (x + 4.2, y + 1.6)), 2.1)
            elif kind == "sleep":
                _stroke(d, _bezier((x - 4.4, y + 0.5), (x, y + 3.6), (x + 4.4, y + 0.5)), 1.8)
            else:  # closed (blink)
                _stroke(d, _bezier((x - 4.0, y + 0.8), (x, y + 2.6), (x + 4.0, y + 0.8)), 1.7)
            pt.flat(m, EYE)


def _blush(pt, k):
    if k <= 0:
        return
    m, d = _mask()
    _ell(d, 40, 77, 6.2, 4.6)
    _ell(d, 80, 77, 6.2, 4.6)
    pt.flat(m.filter(ImageFilter.GaussianBlur(1.6 * S)), BLUSH, 0.65 * k)


def _nose(pt):
    m, d = _mask()
    _ell(d, 60, 73.5, 6.0, 5.4)
    pt.clay(m, NOSE, light=(0.3, 0.22), gain=0.38, edge=0.18, sheen=0.22)


def _mouth(pt, kind):
    y = 83.5
    m, d = _mask()
    if kind == "smile":
        _stroke(d, _bezier((54.5, y - 0.8), (60, y + 2.8), (65.5, y - 0.8)), 1.6)
        pt.flat(m, HAIR_DK)
    elif kind in ("open", "mid", "o", "sleep"):
        rx, ry = {"open": (4.3, 3.8), "mid": (3.7, 2.3), "o": (2.4, 2.8), "sleep": (1.9, 1.5)}[kind]
        _ell(d, 60, y + 0.8, rx, ry)
        pt.flat(m, MOUTH_IN)
        if kind == "open":
            t, dt = _mask()
            _ell(dt, 60, y + 3.4, 3.0, 1.8)
            pt.flat(t, TONGUE, clip=m)
    elif kind == "grin":
        d.pieslice([52 * S, (y - 8) * S, 68 * S, (y + 7.5) * S], 0, 180, fill=255)
        pt.flat(m, MOUTH_IN)
        t, dt = _mask()
        _rrect(dt, 52, y - 1, 68, y + 1.6, 0.6)
        pt.flat(t, TEETH, clip=m)
        t, dt = _mask()
        _ell(dt, 60, y + 6.4, 4.4, 2.6)
        pt.flat(t, TONGUE, clip=m)
    elif kind == "flat":
        _stroke(d, [(56.5, y + 0.8), (63.8, y + 0.0)], 1.6)
        pt.flat(m, HAIR_DK)
    elif kind == "frown":
        _stroke(d, _bezier((55, y + 2.0), (60, y - 1.4), (65, y + 2.0)), 1.6)
        pt.flat(m, HAIR_DK)


def _sparkle(d, x, y, r):
    d.polygon([_p(x, y - r), _p(x + r * 0.28, y - r * 0.28), _p(x + r, y),
               _p(x + r * 0.28, y + r * 0.28), _p(x, y + r), _p(x - r * 0.28, y + r * 0.28),
               _p(x - r, y), _p(x - r * 0.28, y - r * 0.28)], fill=255)


def _head_extras(pt, pose):
    """Extras that move with the head."""
    n = pose.get("waves", 0)
    if n:
        m, d = _mask()
        for r in (9.5, 14.5)[:n]:
            for cx, a0 in ((24, 150), (96, -30)):
                d.arc([(cx - r) * S, (66 - r) * S, (cx + r) * S, (66 + r) * S],
                      a0, a0 + 60, fill=255, width=int(1.8 * S))
        pt.flat(m, BLUE)
    if pose.get("sweat"):
        m, d = _mask()
        d.polygon([_p(98, 42), _p(95.2, 48), _p(100.8, 48)], fill=255)
        _ell(d, 98, 49, 2.9, 2.9)
        pt.clay(m, SKY, gain=0.3, edge=0.1, sheen=0.4)


def _extras(pt, pose, hands):
    n = pose.get("dots", 0)
    if n:
        m, d = _mask()
        for (x, y, r) in ((92, 18, 1.9), (99, 12, 2.5), (107, 5.5, 3.2))[:n]:
            _ell(d, x, y, r, r)
        pt.clay(m, BLUE, gain=0.3, edge=0.1, sheen=0.25)
    if "zzz" in pose:
        m, d = _mask()
        zs = ((90, 22, 4.5), (98.5, 13, 5.5), (108, 3.5, 6.5))
        if pose["zzz"]:
            zs = ((92, 20, 4.0), (100, 10.5, 6.0), (110, 2.5, 4.8))
        for (x, y, s) in zs:
            _stroke(d, [(x, y), (x + s, y), (x, y + s), (x + s, y + s)], 1.6)
        pt.flat(m, BLUE)
    if "sparkle" in pose:
        m, d = _mask()
        pts = ((13, 30, 4.5), (108, 24, 3.5), (104, 40, 2.4))
        if pose["sparkle"]:
            pts = ((10, 40, 3.0), (16, 24, 2.2), (109, 32, 4.6))
        for (x, y, r) in pts:
            _sparkle(d, x, y, r)
        pt.flat(m, SKY)
    if pose.get("magnifier"):
        hx, hy = hands[1]
        gx, gy, gr = hx + 9.5, hy - 14.5, 8.6
        m, d = _mask()
        _stroke(d, [(hx, hy), (gx - gr * 0.62, gy + gr * 0.62)], 3.0)
        pt.clay(m, (60, 66, 78), gain=0.2, edge=0.1, sheen=0.2)
        m, d = _mask()
        _ell(d, gx, gy, gr, gr)
        pt.clay(m, (58, 70, 92), gain=0.2, edge=0.1, sheen=0.2)
        m, d = _mask()
        _ell(d, gx, gy, gr - 2.3, gr - 2.3)
        pt.clay(m, GLASS, light=(0.3, 0.25), gain=0.25, edge=0.1, sheen=0.5)
        m, d = _mask()   # fingers over the handle
        _ell(d, hx, hy, 5.8, 5.8)
        pt.clay(m, SKIN, gain=0.32, edge=0.22, sheen=0.08)


def _outline(img, px=1.0):
    a = img.getchannel("A").point(lambda v: 255 if v > 90 else 0)
    k = int(px * S) * 2 + 1
    grown = a.filter(ImageFilter.MaxFilter(k))
    base = Image.new("RGBA", img.size, OUTLINE + (0,))
    base.putalpha(grown)
    return Image.alpha_composite(base, img)


def render_pose(name="idle"):
    """One full-resolution (supersampled, design-space) RGBA frame."""
    pose = POSES[name]
    hands = [h or d for h, d in zip(pose.get("hands", (None, None)), (HAND_L, HAND_R))]
    raised = [h[1] < 105 for h in hands]   # hand in front of the face: drawn after the head
    pt = _Painter()
    _legs(pt, pose.get("legs", (0, 0)))
    _shorts(pt)
    _torso(pt)
    _arm(pt, (40.5, 95), hands[0], with_hand=not raised[0])
    _arm(pt, (79.5, 95), hands[1], watch=True, with_hand=not raised[1])
    # head on its own layer so it can tilt / shift
    hd = _Painter()
    _ears(hd)
    _head(hd)
    _hair(hd)
    _brows(hd, pose.get("brows", "normal"))
    _eyes(hd, pose.get("eyes", "open"))
    _blush(hd, pose.get("blush", 0.15))
    _nose(hd)
    _mouth(hd, pose.get("mouth", "smile"))
    _head_extras(hd, pose)
    tilt, dx, dy = pose.get("head", (0, 0, 0))
    layer = hd.img
    if tilt or dx or dy:
        layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(60 * S, 92 * S),
                             translate=(dx * S, dy * S))
    pt.img = Image.alpha_composite(pt.img, layer)
    for hand, up in zip(hands, raised):
        if up:
            _hand(pt, hand)
    _extras(pt, pose, hands)
    return _outline(pt.img)


def render_frames(height=150, names=None):
    """{pose name: RGBA image `height` px tall}."""
    width = round(DW * height / DH)
    return {n: render_pose(n).resize((width, height), Image.LANCZOS) for n in (names or POSES)}


def head_icon(size=32, frame=None):
    """Square head-only icon (for the minimised pet / window icons)."""
    img = frame or render_pose("idle")
    box = (12 * S, 4 * S, 108 * S, 100 * S)
    return img.crop(box).resize((size, size), Image.LANCZOS)


def export_assets(out_dir, heights=(110, 150, 200)):
    """Pre-render every pose to PNG (binary alpha, ready for Tk's -transparentcolor) so the
    app itself needs neither Pillow nor numpy."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    big = {n: render_pose(n) for n in POSES}
    for h in heights:
        d = os.path.join(out_dir, str(h))
        os.makedirs(d, exist_ok=True)
        w = round(DW * h / DH)
        for n, im in big.items():
            _binary_alpha(im.resize((w, h), Image.LANCZOS)).save(os.path.join(d, n + ".png"), optimize=True)
    head = head_icon(256, big["idle"])
    _binary_alpha(head.resize((48, 48), Image.LANCZOS)).save(os.path.join(out_dir, "head48.png"), optimize=True)
    head.save(os.path.join(out_dir, "icon.png"))
    head.save(os.path.join(out_dir, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return big


def _binary_alpha(im):
    a = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    rgb = np.asarray(im.convert("RGB")).copy()
    rgb[(rgb[..., 0] <= 1) & (rgb[..., 1] <= 1) & (rgb[..., 2] <= 1)] = 2   # never the key colour
    out = Image.fromarray(rgb).convert("RGBA")
    out.putalpha(a)
    return out


def preview_sheet(frames, out, cols=7, bg=(236, 241, 248, 255)):
    from PIL import ImageFont
    w, h = next(iter(frames.values())).size
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGBA", (w * cols, (h + 22) * rows), bg)
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("segoeui.ttf", 16)
    except OSError:
        font = None
    for i, (name, im) in enumerate(frames.items()):
        x, y = (i % cols) * w, (i // cols) * (h + 22)
        sheet.alpha_composite(im, (x, y))
        d.text((x + w // 2, y + h + 2), name, fill=(30, 58, 138), font=font, anchor="mt")
    sheet.save(out)
    return sheet.size


if __name__ == "__main__":
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    big = export_assets(os.path.join(here, "assets", "pika"))
    frames = {n: im.resize((round(DW * 200 / DH), 200), Image.LANCZOS) for n, im in big.items()}
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "assets", "preview.png")
    print("assets written; preview", out, preview_sheet(frames, out))
