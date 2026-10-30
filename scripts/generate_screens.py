#!/usr/bin/env python3
"""SKILL ISSUE: on-screen interface graphics.

Renders the deterministic image sequences that Blender maps onto the laptop,
the external monitor, the notebook page and the stadium display, plus a crowd
texture atlas.  Every frame number comes from ``skill_issue.timeline`` and every
procedural rate from ``skill_issue.speed``; nothing depends on wall-clock time.

    python scripts/generate_screens.py
    python scripts/generate_screens.py --only laptop,monitor --frames 230-320
    python scripts/generate_screens.py --contact out.jpg     # key-frame sheet

Outputs (named by FILM frame number):
    assets/screens/laptop/laptop_####.jpg      1280x800   0001-0720
    assets/screens/monitor/monitor_####.jpg    1600x900   0001-0720
    assets/screens/notebook/notebook_####.png  1024x1024  0001-0232
    assets/screens/display/display_####.jpg    1920x640   0560-0720
    assets/screens/crowd_atlas.png             2048x1280  (4x4 tiles)

System Python 3.11 + Pillow + numpy.  Fonts: assets/fonts/Inter.woff2 and
assets/fonts/DejaVuSansMono.woff2 only.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import re
import sys
import time
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from skill_issue import speed as S  # noqa: E402
from skill_issue import timeline as T  # noqa: E402

E = T.E
SHOT = {sh["id"]: sh for sh in T.SHOTS}
# Derived beats (everything comes from timeline.py; nothing is hard-coded here)
B = dict(
    notifs_out=SHOT["S06"]["end"],            # the three big cards leave by the end of S06
    banner=E["snaps"][1] + 1,                 # 'this lecture is outdated' banner
    code_done=SHOT["S12"]["start"],           # monitor: finished code (shot cut)
    builder_start=SHOT["S14"]["start"],       # laptop: agent builder
    dashboard_start=SHOT["S16"]["start"],     # laptop: calm dashboard
    scrib_start=SHOT["S08"]["start"] + 1,     # notebook: frantic scribbles
    scrib_end=SHOT["S09"]["end"],
    screensaver=E["close_laptop"] + 3,        # monitor: KEEP UP. screensaver
)
FONT_DIR = REPO / "assets" / "fonts"
INTER_PATH = FONT_DIR / "Inter.woff2"
MONO_PATH = FONT_DIR / "DejaVuSansMono.woff2"
OUT_DIR = REPO / "assets" / "screens"
JPEG_Q = 88

SEQUENCES = {
    # name: (first frame, last frame, (w, h), extension)
    "laptop": (T.FRAME_START, T.FRAME_END, (1280, 800), "jpg"),
    "monitor": (T.FRAME_START, T.FRAME_END, (1600, 900), "jpg"),
    "notebook": (T.FRAME_START, B["scrib_end"], (1024, 1024), "png"),   # Blender holds the last frame
    "display": (560, T.FRAME_END, (1920, 640), "jpg"),
}

# =============================================================================
# Shared helpers
# =============================================================================

_CH = None


def CH():
    global _CH
    if _CH is None:
        _CH = S.compute()
    return _CH


def spd(f):
    return S.value(CH(), "speed", f)


def chv(name, f):
    return S.value(CH(), name, f)


def clock_at(f):
    return S.clock_string(chv("clock_minutes", f))


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = clamp(t)
    return t * t * t


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_back(t, k=1.6):
    t = clamp(t) - 1
    return 1 + t * t * ((k + 1) * t + k)


def mix(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def frng(*key):
    """Deterministic RNG from a key (never time based)."""
    h = 1469598103934665603
    for k in key:
        for ch in str(k):
            h = ((h ^ ord(ch)) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
        h = ((h ^ 0x9E) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return random.Random(h)


# Palette (dark UI)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TXT = (236, 239, 245)
TXT2 = (160, 168, 184)
TXT3 = (104, 112, 128)
PANEL = (24, 27, 34)
PANEL2 = (31, 35, 44)
LINE = (44, 49, 61)
BLUE = (76, 141, 255)
BLUE_D = (42, 98, 217)
CYAN = (64, 228, 255)
ORANGE = (255, 118, 44)
RED = (232, 40, 48)
AMBER = (255, 182, 56)
GREEN = (74, 222, 128)
VIOLET = (167, 139, 250)

# ---------------------------------------------------------------- fonts -----
_FONTS = {}


def F(size, weight=400):
    """Inter variable at a given pixel size and weight (100-900)."""
    size = max(6, int(round(size)))
    weight = int(weight)
    key = ("i", size, weight)
    font = _FONTS.get(key)
    if font is None:
        font = ImageFont.truetype(str(INTER_PATH), size)
        font.set_variation_by_axes([float(min(32, max(14, size))), float(weight)])
        _FONTS[key] = font
    return font


def MONO(size):
    size = max(6, int(round(size)))
    key = ("m", size)
    font = _FONTS.get(key)
    if font is None:
        font = ImageFont.truetype(str(MONO_PATH), size)
        _FONTS[key] = font
    return font


def fit(text, max_w, size, weight=700, min_size=8):
    size = int(size)
    while size > min_size and F(size, weight).getlength(text) > max_w:
        size -= 1
    return F(size, weight)


def ellipsize(text, font, max_w):
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return (text.rstrip() + "…") if text else ""


def tracked(draw, xy, text, font, fill, tracking=0.0, anchor="ls"):
    """Draw text with letter spacing (anchor: 'ls' or 'ms' or 'rs')."""
    widths = [font.getlength(c) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    a = "l" + anchor[1]
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill, anchor=a)
        x += w + tracking
    return total


def wrap(text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------- shapes -----
_LUTS = {}


def scale_mask(m, a):
    a = clamp(a, 0, 1)
    if a >= 0.999:
        return m
    q = int(a * 255)
    lut = _LUTS.get(q)
    if lut is None:
        lut = [int(i * q / 255) for i in range(256)]
        _LUTS[q] = lut
    return m.point(lut)


@lru_cache(maxsize=2048)
def rr_mask(w, h, r, ss=4):
    w, h = max(1, int(w)), max(1, int(h))
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1),
                                          radius=max(0, int(r * ss)), fill=255)
    return big.reduce(ss)


@lru_cache(maxsize=1024)
def rr_ring(w, h, r, t, ss=4):
    w, h = max(1, int(w)), max(1, int(h))
    big = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=int(r * ss), fill=255)
    ti = int(round(t * ss))
    d.rounded_rectangle((ti, ti, w * ss - 1 - ti, h * ss - 1 - ti),
                        radius=max(0, int((r - t) * ss)), fill=0)
    return big.reduce(ss)


@lru_cache(maxsize=256)
def circle_mask(d, ss=4):
    d = max(1, int(d))
    big = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(big).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
    return big.reduce(ss)


def ibox(box):
    return tuple(int(round(v)) for v in box)


def fill_rr(img, box, r, color, alpha=1.0):
    x0, y0, x1, y1 = ibox(box)
    if x1 <= x0 or y1 <= y0:
        return
    m = scale_mask(rr_mask(x1 - x0, y1 - y0, r), alpha)
    img.paste(color[:3], (x0, y0, x1, y1), m)


def ring_rr(img, box, r, t, color, alpha=1.0):
    x0, y0, x1, y1 = ibox(box)
    if x1 <= x0 or y1 <= y0:
        return
    m = scale_mask(rr_ring(x1 - x0, y1 - y0, r, t), alpha)
    img.paste(color[:3], (x0, y0, x1, y1), m)


def fill_circle(img, cx, cy, d, color, alpha=1.0):
    d = int(round(d))
    x0, y0 = int(round(cx - d / 2)), int(round(cy - d / 2))
    img.paste(color[:3], (x0, y0, x0 + d, y0 + d), scale_mask(circle_mask(d), alpha))


def fill_rect(img, box, color, alpha=1.0):
    x0, y0, x1, y1 = ibox(box)
    if x1 <= x0 or y1 <= y0:
        return
    if alpha >= 0.999:
        img.paste(color[:3], (x0, y0, x1, y1))
    else:
        img.paste(color[:3], (x0, y0, x1, y1), Image.new("L", (x1 - x0, y1 - y0), int(255 * alpha)))


@lru_cache(maxsize=256)
def _shadow(w, h, r, blur):
    pad = int(blur * 3)
    m = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    m.paste(rr_mask(w, h, r), (pad, pad))
    return m.filter(ImageFilter.GaussianBlur(blur)), pad


def drop_shadow(img, box, r, blur=16, opacity=0.5, dy=8):
    x0, y0, x1, y1 = ibox(box)
    m, pad = _shadow(x1 - x0, y1 - y0, r, blur)
    m = scale_mask(m, opacity)
    img.paste((0, 0, 0), (x0 - pad, y0 - pad + dy, x0 - pad + m.width, y0 - pad + dy + m.height), m)


def vgrad(w, h, c0, c1):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(c0, np.float32) * (1 - t) + np.array(c1, np.float32) * t
    return Image.fromarray(np.broadcast_to(arr, (h, w, 3)).astype(np.uint8))


def paste_grad_rr(img, box, r, c0, c1, alpha=1.0):
    x0, y0, x1, y1 = ibox(box)
    g = vgrad(x1 - x0, y1 - y0, c0, c1)
    img.paste(g, (x0, y0), scale_mask(rr_mask(x1 - x0, y1 - y0, r), alpha))


def aa(img, color, fn, box=None, ss=3, alpha=1.0):
    """Anti-aliased vector drawing: fn(draw, P, ss) draws white on an L mask."""
    if box is None:
        box = (0, 0, img.width, img.height)
    x0, y0, x1, y1 = ibox(box)
    m = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
    d = ImageDraw.Draw(m)

    def P(x, y):
        return ((x - x0) * ss, (y - y0) * ss)

    fn(d, P, ss)
    m = m.reduce(ss)
    img.paste(color[:3], (x0, y0, x1, y1), scale_mask(m, alpha))


def bezier(p0, p1, p2, p3, n=48, t1=1.0):
    pts = []
    for i in range(n + 1):
        t = t1 * i / n
        u = 1 - t
        pts.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return pts


def paste_rgba(img, layer, x, y, opacity=1.0, pop=0.0):
    """Paste an RGBA layer with optional opacity and white 'brightness pop'."""
    if opacity <= 0.003:
        return
    if pop > 0:
        r, g, b, a = layer.split()
        rgb = Image.merge("RGB", (r, g, b))
        rgb = Image.blend(rgb, Image.new("RGB", layer.size, WHITE), pop)
        layer = Image.merge("RGBA", (*rgb.split(), a))
    a = layer.getchannel("A")
    if opacity < 0.999:
        a = scale_mask(a, opacity)
    img.paste(layer.convert("RGB"), (int(round(x)), int(round(y))), a)


def dim(img, k):
    return Image.blend(img, Image.new("RGB", img.size, BLACK), 1 - k)


def gray(img):
    return ImageOps.grayscale(img).convert("RGB")


def hsmear(img, r):
    """Cheap horizontal motion smear."""
    w, h = img.size
    r = max(1, int(r))
    return img.resize((max(1, w // r), h), Image.BOX).resize((w, h), Image.BILINEAR)


def vblur_arr(arr, L):
    """Vertical box blur of length L (numpy, float)."""
    L = int(L)
    if L < 2:
        return arr
    c = np.cumsum(np.pad(arr, ((L, L), (0, 0), (0, 0)), mode="edge"), axis=0, dtype=np.float32)
    out = (c[L + L // 2: L + L // 2 + arr.shape[0]] - c[L // 2: L // 2 + arr.shape[0]]) / L
    return out


def glitch(img, rng, n=6, maxshift=80, hmin=6, hmax=60, split=0):
    arr = np.asarray(img).copy()
    h, w = arr.shape[:2]
    for _ in range(n):
        y0 = rng.randrange(0, h - 1)
        hh = rng.randint(hmin, hmax)
        sh = rng.randint(-maxshift, maxshift)
        arr[y0:y0 + hh] = np.roll(arr[y0:y0 + hh], sh, axis=1)
    if split:
        arr[..., 0] = np.roll(arr[..., 0], split, axis=1)
        arr[..., 2] = np.roll(arr[..., 2], -split, axis=1)
    return Image.fromarray(arr)


# ---------------------------------------------------------------- icons -----
@lru_cache(maxsize=256)
def icon_mask(name, size, ss=4):
    S_ = size * ss
    m = Image.new("L", (S_, S_), 0)
    d = ImageDraw.Draw(m)
    c = S_ / 2

    def star(cx, cy, R, e=2.4, n=120):
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            ca, sa = math.cos(a), math.sin(a)
            pts.append((cx + R * math.copysign(abs(ca) ** e, ca), cy + R * math.copysign(abs(sa) ** e, sa)))
        return pts

    if name == "sparkle":
        d.polygon(star(S_ * 0.42, S_ * 0.56, S_ * 0.40), fill=255)
        d.polygon(star(S_ * 0.80, S_ * 0.20, S_ * 0.17), fill=255)
        d.polygon(star(S_ * 0.82, S_ * 0.82, S_ * 0.10), fill=255)
    elif name == "warn":
        lw = int(S_ * 0.09)
        tri = [(c, S_ * 0.10), (S_ * 0.94, S_ * 0.88), (S_ * 0.06, S_ * 0.88)]
        d.polygon(tri, fill=255)
        d.line(tri + [tri[0]], fill=255, width=lw, joint="curve")
        d.rounded_rectangle((c - S_ * 0.055, S_ * 0.36, c + S_ * 0.055, S_ * 0.64), radius=S_ * 0.05, fill=0)
        d.ellipse((c - S_ * 0.06, S_ * 0.70, c + S_ * 0.06, S_ * 0.82), fill=0)
    elif name == "burst":
        pts = []
        for i in range(24):
            a = 2 * math.pi * i / 24 - math.pi / 2
            R = S_ * (0.47 if i % 2 == 0 else 0.36)
            pts.append((c + R * math.cos(a), c + R * math.sin(a)))
        d.polygon(pts, fill=255)
        d.line([(S_ * 0.32, S_ * 0.52), (S_ * 0.45, S_ * 0.64), (S_ * 0.68, S_ * 0.38)], fill=0,
               width=int(S_ * 0.08), joint="curve")
    elif name == "bell":
        d.chord((S_ * 0.22, S_ * 0.12, S_ * 0.78, S_ * 0.70), 180, 360, fill=255)
        d.polygon([(S_ * 0.22, S_ * 0.41), (S_ * 0.78, S_ * 0.41), (S_ * 0.86, S_ * 0.74), (S_ * 0.14, S_ * 0.74)], fill=255)
        d.rounded_rectangle((S_ * 0.08, S_ * 0.70, S_ * 0.92, S_ * 0.80), radius=S_ * 0.05, fill=255)
        d.ellipse((S_ * 0.40, S_ * 0.78, S_ * 0.60, S_ * 0.94), fill=255)
    elif name == "route":
        lw = int(S_ * 0.09)
        d.line(bezier((S_ * 0.22, S_ * 0.78), (S_ * 0.9, S_ * 0.78), (S_ * 0.1, S_ * 0.25), (S_ * 0.78, S_ * 0.22)),
               fill=255, width=lw, joint="curve")
        d.ellipse((S_ * 0.08, S_ * 0.66, S_ * 0.34, S_ * 0.92), fill=255)
        d.ellipse((S_ * 0.64, S_ * 0.06, S_ * 0.92, S_ * 0.34), fill=255)
        d.ellipse((S_ * 0.73, S_ * 0.15, S_ * 0.83, S_ * 0.25), fill=0)
    elif name == "play":
        d.polygon([(S_ * 0.2, S_ * 0.1), (S_ * 0.9, c), (S_ * 0.2, S_ * 0.9)], fill=255)
    elif name == "ff":
        d.polygon([(S_ * 0.04, S_ * 0.14), (S_ * 0.50, c), (S_ * 0.04, S_ * 0.86)], fill=255)
        d.polygon([(S_ * 0.48, S_ * 0.14), (S_ * 0.96, c), (S_ * 0.48, S_ * 0.86)], fill=255)
    elif name == "pause":
        d.rounded_rectangle((S_ * 0.18, S_ * 0.1, S_ * 0.40, S_ * 0.9), radius=S_ * 0.04, fill=255)
        d.rounded_rectangle((S_ * 0.60, S_ * 0.1, S_ * 0.82, S_ * 0.9), radius=S_ * 0.04, fill=255)
    elif name == "check":
        d.line([(S_ * 0.14, S_ * 0.52), (S_ * 0.40, S_ * 0.78), (S_ * 0.88, S_ * 0.24)], fill=255,
               width=int(S_ * 0.16), joint="curve")
    elif name == "wifi":
        for i, r in enumerate((0.46, 0.31, 0.16)):
            d.arc((c - S_ * r, S_ * 0.82 - S_ * r, c + S_ * r, S_ * 0.82 + S_ * r), 225, 315, fill=255,
                  width=int(S_ * 0.09))
        d.ellipse((c - S_ * 0.07, S_ * 0.74, c + S_ * 0.07, S_ * 0.88), fill=255)
    elif name == "logo":
        d.ellipse((S_ * 0.06, S_ * 0.06, S_ * 0.94, S_ * 0.94), outline=255, width=int(S_ * 0.13))
        d.ellipse((S_ * 0.36, S_ * 0.36, S_ * 0.64, S_ * 0.64), fill=255)
    elif name == "lock":
        d.rounded_rectangle((S_ * 0.18, S_ * 0.44, S_ * 0.82, S_ * 0.92), radius=S_ * 0.08, fill=255)
        d.arc((S_ * 0.30, S_ * 0.12, S_ * 0.70, S_ * 0.62), 180, 360, fill=255, width=int(S_ * 0.1))
        d.line([(S_ * 0.31, S_ * 0.37), (S_ * 0.31, S_ * 0.46)], fill=255, width=int(S_ * 0.1))
        d.line([(S_ * 0.69, S_ * 0.37), (S_ * 0.69, S_ * 0.46)], fill=255, width=int(S_ * 0.1))
    elif name == "paper":
        d.polygon([(S_ * 0.18, S_ * 0.06), (S_ * 0.62, S_ * 0.06), (S_ * 0.84, S_ * 0.28), (S_ * 0.84, S_ * 0.94),
                   (S_ * 0.18, S_ * 0.94)], fill=255)
        for i in range(4):
            y = S_ * (0.42 + i * 0.12)
            d.line([(S_ * 0.30, y), (S_ * 0.72, y)], fill=0, width=int(S_ * 0.05))
    elif name == "bolt":
        d.polygon([(S_ * 0.58, S_ * 0.04), (S_ * 0.16, S_ * 0.56), (S_ * 0.46, S_ * 0.56), (S_ * 0.36, S_ * 0.96),
                   (S_ * 0.84, S_ * 0.40), (S_ * 0.54, S_ * 0.40)], fill=255)
    elif name == "dot":
        d.ellipse((S_ * 0.2, S_ * 0.2, S_ * 0.8, S_ * 0.8), fill=255)
    elif name == "chart":
        for i, hgt in enumerate((0.3, 0.5, 0.42, 0.86)):
            x = S_ * (0.1 + i * 0.22)
            d.rounded_rectangle((x, S_ * (0.94 - hgt), x + S_ * 0.16, S_ * 0.94), radius=S_ * 0.03, fill=255)
    return m.reduce(ss)


def icon(img, name, x, y, size, color, alpha=1.0):
    m = scale_mask(icon_mask(name, int(size)), alpha)
    img.paste(color[:3], (int(x), int(y), int(x) + m.width, int(y) + m.height), m)


# ------------------------------------------------------------ OS chrome -----
@lru_cache(maxsize=8)
def wallpaper(w, h, variant=0):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if variant == 0:
        top, bot = np.array([12, 14, 24], np.float32), np.array([22, 16, 36], np.float32)
        glows = [(0.82 * w, 0.18 * h, 0.65 * w, (50, 90, 210), 0.22), (0.12 * w, 0.95 * h, 0.55 * w, (150, 60, 190), 0.14)]
    else:
        top, bot = np.array([10, 16, 24], np.float32), np.array([14, 22, 34], np.float32)
        glows = [(0.2 * w, 0.1 * h, 0.7 * w, (30, 110, 170), 0.18), (0.9 * w, 0.9 * h, 0.6 * w, (40, 60, 160), 0.14)]
    t = (yy / h)[..., None]
    arr = top * (1 - t) + bot * t
    for cx, cy, r, col, a in glows:
        g = np.clip(1 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r, 0, 1) ** 2 * a
        arr += g[..., None] * np.array(col, np.float32)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def menubar(img, f, sc=1.0, app="Academy", menus=("File", "Edit", "View", "Window", "Help"),
            bell=None, bg=(9, 10, 14), alpha=0.92, accent=BLUE):
    W = img.width
    h = int(30 * sc)
    fill_rect(img, (0, 0, W, h), bg, alpha)
    d = ImageDraw.Draw(img)
    icon(img, "logo", 14 * sc, 7 * sc, 16 * sc, TXT)
    x = 44 * sc
    d.text((x, h / 2), app, font=F(15 * sc, 700), fill=TXT, anchor="lm")
    x += F(15 * sc, 700).getlength(app) + 22 * sc
    for m in menus:
        d.text((x, h / 2), m, font=F(14 * sc, 450), fill=(200, 205, 215), anchor="lm")
        x += F(14 * sc, 450).getlength(m) + 20 * sc
    # right side
    xr = W - 16 * sc
    clk = clock_at(f)
    d.text((xr, h / 2), clk, font=F(15 * sc, 600), fill=TXT, anchor="rm")
    xr -= F(15 * sc, 600).getlength(clk) + 18 * sc
    # battery
    bw, bh = 26 * sc, 12 * sc
    ring_rr(img, (xr - bw, h / 2 - bh / 2, xr, h / 2 + bh / 2), 3 * sc, 1.4 * sc, TXT2)
    fill_rr(img, (xr - bw + 3 * sc, h / 2 - bh / 2 + 3 * sc, xr - bw + 3 * sc + (bw - 6 * sc) * 0.72,
                  h / 2 + bh / 2 - 3 * sc), 1.5 * sc, TXT2)
    xr -= bw + 16 * sc
    icon(img, "wifi", xr - 18 * sc, h / 2 - 9 * sc, 18 * sc, TXT2)
    xr -= 18 * sc + 16 * sc
    if bell is not None:
        icon(img, "bell", xr - 17 * sc, h / 2 - 9 * sc, 17 * sc, TXT)
        if bell > 0:
            label = str(bell) if bell < 100 else "99+"
            fb = F(11 * sc, 800)
            bwid = max(16 * sc, fb.getlength(label) + 9 * sc)
            bx = xr - 6 * sc
            fill_rr(img, (bx - bwid / 2, 3 * sc, bx + bwid / 2, 19 * sc), 8 * sc, RED)
            d.text((bx, 11 * sc), label, font=fb, fill=WHITE, anchor="mm")
    return h


# ------------------------------------------------------------- code text ----
PY_KW = set("def class return async await for in if else elif import from as with while not and or "
            "try except raise yield lambda pass break continue is global finally".split())
PY_CONST = {"None", "True", "False"}
PY_BUILTIN = {"print", "len", "range", "super", "open", "sorted", "enumerate", "min", "max", "sum", "list", "dict"}
TOK_RE = re.compile(r"(#.*$)|(\"(?:[^\"\\]|\\.)*\"?|'(?:[^'\\]|\\.)*'?)|(@\w+)|(\b\d[\d_\.]*\b)|(\b[A-Za-z_]\w*\b)|(\s+)|(.)")
SYN = dict(default=(212, 216, 226), kw=(199, 128, 232), str=(152, 206, 122), com=(110, 119, 136),
           num=(222, 160, 102), fn=(102, 178, 255), cls=(232, 196, 112), self=(236, 112, 124),
           const=(222, 160, 102), deco=(232, 196, 112), builtin=(96, 212, 222))


def code_tokens(line):
    out, prev = [], None
    for m in TOK_RE.finditer(line):
        com, st, deco, num, ident, ws, other = m.groups()
        tok = m.group(0)
        if com:
            kind = "com"
        elif st:
            kind = "str"
        elif deco:
            kind = "deco"
        elif num:
            kind = "num"
        elif ident:
            if ident in PY_KW:
                kind = "kw"
            elif ident in PY_CONST:
                kind = "const"
            elif ident == "self":
                kind = "self"
            elif prev == "def":
                kind = "fn"
            elif prev == "class" or (ident[:1].isupper() and len(ident) > 1):
                kind = "cls"
            elif ident in PY_BUILTIN:
                kind = "builtin"
            else:
                kind = "default"
            prev = ident
        else:
            kind = "default"
        out.append((tok, SYN[kind]))
    return out


def draw_code_line(draw, x, y, line, font, cw, max_chars=None, anchor="ls"):
    n = 0
    for tok, col in code_tokens(line):
        if max_chars is not None and n >= max_chars:
            break
        if max_chars is not None and n + len(tok) > max_chars:
            tok = tok[:max_chars - n]
        if tok.strip():
            draw.text((x + n * cw, y), tok, font=font, fill=col, anchor=anchor)
        n += len(tok)
    return n


def encode_frame(img, ext):
    import io
    buf = io.BytesIO()
    if ext == "png":
        img.convert("RGB").save(buf, "PNG", compress_level=9)
    else:
        img.convert("RGB").save(buf, "JPEG", quality=JPEG_Q, optimize=True, progressive=True)
    return buf.getvalue()


def write_frame(path, data, seen):
    """Write `data` to `path`; byte-identical frames (static holds) become hard links.

    The old file is always unlinked first, so re-rendering one frame never alters
    other frames that were hard-linked to it."""
    import hashlib
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        path.unlink()
    h = hashlib.sha1(data).hexdigest()
    src = seen.get(h)
    if src is not None:
        try:
            os.link(src, path)
            return False
        except OSError:
            pass
    path.write_bytes(data)
    seen[h] = path
    return True


# =============================================================================
# LAPTOP  (1280 x 800)
# =============================================================================
LW, LH = 1280, 800
WIN = (16, 40, 1264, 788)
TAB_Y = (40, 78)
TOOL_Y = (78, 114)
SIDEBAR_X1 = 300
PLAYER = (320, 130, 1244, 650)          # 924 x 520, 16:9
LECTURES = ["What is a neural network?", "Gradient descent", "Backpropagation", "Overfitting",
            "Convolutional nets", "Sequence models", "Attention", "Transformers", "Fine-tuning",
            "Reinforcement learning", "Agents", "What's next?"]
LECT_DUR = ["24:10", "31:42", "38:05", "22:51", "41:13", "35:30", "29:08", "44:56", "33:17", "40:02", "27:45", "12:30"]
TABS = ["Lecture 1 · Intro to ML", "v2.1 release notes", "BREAKING CHANGES", "Migration guide",
        "new_paper.pdf", "Leaderboard", "Framework docs", "v2.2 release notes", "Deprecation notice",
        "Agent tutorial (16x)", "paper_2.pdf", "paper_3.pdf", "v2.3 release notes", "Is my course outdated?"]
MINI_TEXTS = ["v2.1 released", "BREAKING CHANGES", "new paper", "v2.2 released", "deprecated",
              "+0.3% SOTA", "migration guide (1,400 pages)", "v2.3 released", "new framework",
              "your course is outdated", "v3.0 released", "new paper (again)"]
MINI_KIND = {"BREAKING CHANGES": "warn", "deprecated": "warn", "your course is outdated": "warn",
             "new paper": "paper", "new paper (again)": "paper", "migration guide (1,400 pages)": "paper",
             "+0.3% SOTA": "chart"}


def nn_layout(box, layers=(3, 4, 2)):
    x0, y0, x1, y1 = box
    cols = []
    for li, n in enumerate(layers):
        x = x0 + (x1 - x0) * (li / (len(layers) - 1))
        ys = [y0 + (y1 - y0) * ((i + 0.5) / n) for i in range(n)]
        cols.append([(x, y) for y in ys])
    edges = [(a, b) for li in range(len(cols) - 1) for a in cols[li] for b in cols[li + 1]]
    return cols, edges


def course_slide_box():
    px0, py0, px1, py1 = PLAYER
    return (px0 + 420, py0 + 150, px1 - 110, py1 - 130)


@lru_cache(maxsize=1)
def course_base():
    img = wallpaper(LW, LH, 0).copy()
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = WIN
    drop_shadow(img, WIN, 12, blur=20, opacity=0.6, dy=10)
    fill_rr(img, WIN, 12, (18, 20, 25))
    # tab strip + toolbar
    fill_rect(img, (x0 + 1, TAB_Y[0] + 6, x1 - 1, TAB_Y[1]), (13, 14, 18))
    fill_rr(img, (x0, y0, x1, y0 + 24), 12, (13, 14, 18))
    fill_rect(img, (x0 + 1, TOOL_Y[0], x1 - 1, TOOL_Y[1]), (28, 31, 38))
    fill_rect(img, (x0 + 1, TOOL_Y[1] - 1, x1 - 1, TOOL_Y[1]), LINE)
    # window controls (generic)
    for i, c in enumerate(((72, 76, 88), (72, 76, 88), (72, 76, 88))):
        fill_circle(img, x1 - 22 - i * 22, (TAB_Y[0] + TAB_Y[1]) / 2 + 2, 11, c)
    # toolbar: nav + address
    ty = (TOOL_Y[0] + TOOL_Y[1]) / 2
    for i, ch in enumerate(("‹", "›", "↻")):
        d.text((x0 + 26 + i * 30, ty), ch, font=F(22, 500), fill=TXT3, anchor="mm")
    fill_rr(img, (x0 + 110, TOOL_Y[0] + 6, x1 - 120, TOOL_Y[1] - 6), 15, (17, 19, 24))
    icon(img, "lock", x0 + 124, ty - 7, 14, TXT3)
    d.text((x0 + 146, ty), "skillqueue.app/ml-101/lecture-1", font=F(15, 450), fill=TXT2, anchor="lm")
    # content background
    fill_rect(img, (x0 + 1, TOOL_Y[1], x1 - 1, y1 - 12), (18, 20, 25))
    # sidebar
    fill_rect(img, (x0 + 1, TOOL_Y[1], SIDEBAR_X1, y1 - 12), (14, 15, 19))
    fill_rr(img, (x0, y1 - 24, SIDEBAR_X1 + 12, y1), 12, (14, 15, 19))
    fill_rect(img, (SIDEBAR_X1, TOOL_Y[1], SIDEBAR_X1 + 1, y1), LINE)
    tracked(d, (x0 + 22, 146), "COURSE CONTENT", F(12, 700), TXT3, 1.6)
    for i, name in enumerate(LECTURES):
        ry = 162 + i * 44
        if i == 0:
            fill_rr(img, (x0 + 10, ry, SIDEBAR_X1 - 10, ry + 38), 8, (30, 38, 56))
            fill_rr(img, (x0 + 10, ry + 6, x0 + 14, ry + 32), 2, BLUE)
        cc = BLUE if i == 0 else (40, 44, 54)
        fill_circle(img, x0 + 36, ry + 19, 22, cc)
        d.text((x0 + 36, ry + 19), str(i + 1), font=F(11, 700), fill=WHITE if i == 0 else TXT2, anchor="mm")
        fnt = F(14, 600 if i == 0 else 450)
        d.text((x0 + 56, ry + 19), ellipsize(name, fnt, 170), font=fnt, fill=TXT if i == 0 else TXT2, anchor="lm")
        d.text((SIDEBAR_X1 - 20, ry + 19), LECT_DUR[i], font=F(12, 450), fill=TXT3, anchor="rm")
    # player frame + slide
    px0, py0, px1, py1 = PLAYER
    fill_rr(img, PLAYER, 10, (245, 242, 235))
    d.text((px0 + 56, py0 + 74), "What is a neural network?", font=F(44, 750), fill=(24, 27, 36), anchor="ls")
    d.text((px0 + 58, py0 + 112), "Lecture 1 · Foundations", font=F(20, 500), fill=(110, 116, 130), anchor="ls")
    fill_rect(img, (px0 + 58, py0 + 130, px0 + 118, py0 + 134), BLUE)
    bullets = ["Layers of simple units", "Each connection has a weight", "Learning = adjusting weights"]
    for i, b in enumerate(bullets):
        by = py0 + 196 + i * 50
        fill_circle(img, px0 + 66, by - 7, 9, BLUE)
        d.text((px0 + 84, by), b, font=F(22, 500), fill=(52, 57, 70), anchor="ls")
    cols, edges = nn_layout(course_slide_box())

    def draw_edges(dd, P, ss):
        for a, b in edges:
            dd.line([P(*a), P(*b)], fill=255, width=int(1.6 * ss))
    aa(img, (150, 158, 175), draw_edges, box=PLAYER)
    colors = [(76, 141, 255), (124, 92, 246), (34, 197, 140)]
    for li, col in enumerate(cols):
        for (x, y) in col:
            fill_circle(img, x, y, 40, colors[li])
            fill_circle(img, x, y, 22, (255, 255, 255), 0.35)
    labels = ["inputs", "hidden layer", "output"]
    for li, col in enumerate(cols):
        d.text((col[0][0], course_slide_box()[3] + 46), labels[li], font=F(17, 600), fill=(110, 116, 130), anchor="ms")
    # bottom control gradient
    gh = 78
    g = vgrad(px1 - px0, gh, (0, 0, 0), (0, 0, 0))
    gm = Image.fromarray((np.linspace(0, 170, gh)[:, None] * np.ones((1, px1 - px0))).astype(np.uint8))
    img.paste(g, (px0, py1 - gh), gm)
    # under-player info
    d.text((px0, 694), "INTRO TO MACHINE LEARNING · Lecture 1 of 12", font=F(26, 750), fill=TXT, anchor="ls")
    d.text((px0, 728), "Course progress", font=F(15, 500), fill=TXT2, anchor="ls")
    fill_rr(img, (px0 + 128, 718, px0 + 368, 726), 4, (44, 48, 60))
    fill_rr(img, (px0 + 128, 718, px0 + 128 + 240 * 0.03 + 4, 726), 4, BLUE)
    d.text((px0 + 380, 728), "3%", font=F(15, 700), fill=TXT, anchor="ls")
    for i, lab in enumerate(("Notes", "Q&A", "Resources")):
        bx = px1 - (2 - i) * 110
        ring_rr(img, (bx - 100, 708, bx, 738), 8, 1.2, LINE)
        d.text((bx - 50, 723), lab, font=F(14, 600), fill=TXT2, anchor="mm")
    return img


def video_time(f):
    """Seconds into the lecture: real-time playback, then the speed creeps up."""
    t = 72.0
    for k in range(1, f + 1):
        t += playback_rate(k) / T.FPS
    return t


def playback_rate(f):
    if f < E["typing_start"]:
        return 1.0
    s = spd(f)
    return 1.0 if s < 0.33 else 1.25 if s < 0.48 else 1.5 if s < 0.62 else 1.75


def fmt_t(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def draw_tabs(img, n):
    d = ImageDraw.Draw(img)
    x0, x1 = WIN[0] + 10, WIN[2] - 84
    fill_rect(img, (WIN[0] + 1, TAB_Y[0] + 4, x1 + 8, TAB_Y[1]), (13, 14, 18))
    tw = min(240, (x1 - x0) / n)
    for i in range(n):
        tx0 = x0 + i * tw
        active = i == 0
        if active:
            fill_rr(img, (tx0, TAB_Y[0] + 6, tx0 + tw - 2, TAB_Y[1] + 10), 9, (28, 31, 38))
        else:
            if i > 0:
                fill_rect(img, (tx0 - 1, TAB_Y[0] + 16, tx0, TAB_Y[1] - 8), (44, 48, 58))
        col = [BLUE, ORANGE, RED, AMBER, VIOLET, GREEN][i % 6] if i else BLUE
        if tw > 44:
            fill_circle(img, tx0 + 18, (TAB_Y[0] + TAB_Y[1]) / 2 + 2, 12, col)
        if tw > 70:
            fnt = F(13, 500)
            txt = ellipsize(TABS[i % len(TABS)], fnt, tw - 58)
            d.text((tx0 + 32, (TAB_Y[0] + TAB_Y[1]) / 2 + 2), txt, font=fnt, fill=TXT if active else TXT2, anchor="lm")
            d.text((tx0 + tw - 16, (TAB_Y[0] + TAB_Y[1]) / 2 + 2), "×", font=F(14, 400), fill=TXT3, anchor="mm")


# --- big notification cards (frames 90-160) ---------------------------------
CARD_W = 660


@lru_cache(maxsize=16)
def big_toast(text, kind):
    accent = ORANGE if kind == "alert" else BLUE
    f_min = F(38, 780)
    if f_min.getlength(text) <= CARD_W - 130:
        lines = [text]
    elif ". " in text:
        lines = [text.split(". ", 1)[0] + ".", text.split(". ", 1)[1]]
    else:
        lines = wrap(text, F(40, 780), CARD_W - 130)
    h = 74 + 50 * len(lines)
    pad = 40
    im = Image.new("RGBA", (CARD_W + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(CARD_W, h, 18, 16)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.65))
    im.alpha_composite(sh, (pad - spad, pad - spad + 10))
    body = Image.new("RGBA", (CARD_W, h), (30, 34, 44, 255) if kind != "alert" else (44, 30, 28, 255))
    tint = vgrad(CARD_W, h, (36, 41, 53) if kind != "alert" else (58, 34, 28), (26, 29, 38) if kind != "alert" else (38, 26, 25))
    body.paste(tint, (0, 0))
    m = rr_mask(CARD_W, h, 18)
    body.putalpha(m)
    im.alpha_composite(body, (pad, pad))
    d = ImageDraw.Draw(im)
    ring = rr_ring(CARD_W, h, 18, 1.5)
    border = Image.new("RGBA", (CARD_W, h), mix(accent, (255, 255, 255), 0.2) + (0,))
    border.putalpha(scale_mask(ring, 0.55))
    im.alpha_composite(border, (pad, pad))
    # accent strip
    strip = Image.new("RGBA", (6, h - 36), accent + (255,))
    strip.putalpha(rr_mask(6, h - 36, 3))
    im.alpha_composite(strip, (pad + 10, pad + 18))
    # icon tile
    tile = Image.new("RGBA", (64, 64), accent + (255,))
    tile.putalpha(rr_mask(64, 64, 16))
    im.alpha_composite(tile, (pad + 30, pad + 26))
    ic = Image.new("RGBA", (40, 40), (255, 255, 255, 255))
    ic.putalpha(icon_mask("warn" if kind == "alert" else "burst", 40))
    im.alpha_composite(ic, (pad + 42, pad + 37))
    tx = pad + 112
    tracked(d, (tx, pad + 36), "BENCHMARKS" if kind == "alert" else "AI UPDATES", F(15, 700),
            mix(accent, (255, 255, 255), 0.35), 1.8, anchor="ls")
    d.text((pad + CARD_W - 22, pad + 36), "now", font=F(16, 500), fill=(150, 158, 175), anchor="rs")
    for i, ln in enumerate(lines):
        d.text((tx, pad + 92 + 50 * i), ln, font=fit(ln, CARD_W - 132, 42, 780, 36), fill=WHITE, anchor="ls")
    return im, pad, h


def draw_big_notifs(img, f):
    y = 46
    for n in T.NOTIFICATIONS[:3]:
        if f < n["frame"]:
            break
        im, pad, h = big_toast(n["text"], n["kind"])
        age = f - n["frame"]
        t = ease_out((age + 1) / 6)
        out = ease_in((f - (B["notifs_out"] - 3)) / 4) if f >= B["notifs_out"] - 3 else 0.0
        x = LW - 18 - CARD_W + (1 - t) * (CARD_W + 50) + out * (CARD_W + 60)
        pop = 0.55 if age == 0 else 0.25 if age == 1 else 0.0
        paste_rgba(img, im, x - pad, y - pad, opacity=1 - out * 0.5, pop=pop)
        y += h + 12


# --- mini toasts (speed-spawned) --------------------------------------------
MINI_W, MINI_H = 430, 66


@lru_cache(maxsize=32)
def mini_toast(text):
    kind = MINI_KIND.get(text, "release")
    accent = {"warn": AMBER, "paper": VIOLET, "chart": GREEN}.get(kind, BLUE)
    pad = 24
    im = Image.new("RGBA", (MINI_W + 2 * pad, MINI_H + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(MINI_W, MINI_H, 14, 10)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.55))
    im.alpha_composite(sh, (pad - spad, pad - spad + 6))
    body = Image.new("RGBA", (MINI_W, MINI_H), (29, 33, 42, 255))
    body.putalpha(rr_mask(MINI_W, MINI_H, 14))
    im.alpha_composite(body, (pad, pad))
    border = Image.new("RGBA", (MINI_W, MINI_H), (70, 78, 96, 0))
    border.putalpha(rr_ring(MINI_W, MINI_H, 14, 1.2))
    im.alpha_composite(border, (pad, pad))
    tile = Image.new("RGBA", (38, 38), accent + (255,))
    tile.putalpha(rr_mask(38, 38, 10))
    im.alpha_composite(tile, (pad + 14, pad + 14))
    ic = Image.new("RGBA", (24, 24), (255, 255, 255, 255))
    ic.putalpha(icon_mask({"warn": "warn", "paper": "paper", "chart": "chart"}.get(kind, "burst"), 24))
    im.alpha_composite(ic, (pad + 21, pad + 21))
    d = ImageDraw.Draw(im)
    fnt = fit(text, MINI_W - 120, 24, 700, 16)
    d.text((pad + 66, pad + MINI_H / 2 + 1), text, font=fnt, fill=WHITE, anchor="lm")
    d.text((pad + MINI_W - 14, pad + MINI_H / 2 + 1), "now", font=F(14, 500), fill=TXT3, anchor="rm")
    return im, pad


def draw_mini_toasts(img, f, x_right=LW - 18, y_top=44, life_base=26, fmin=0, fmax=9999):
    toasts = [t for t in CH()["events"]["toasts"] if fmin <= t["frame"] <= min(f, fmax)]
    vis = []
    for t in toasts:
        life = int(life_base - 10 * spd(t["frame"]))
        age = f - t["frame"]
        if 0 <= age < life:
            vis.append((t, age, life))
    for t, age, life in vis:
        newer = [u for u in vis if u[0]["frame"] > t["frame"]]
        y = y_top + sum(ease_out((f - u[0]["frame"] + 1) / 5) for u in newer) * (MINI_H + 10)
        text = MINI_TEXTS[t["i"] % len(MINI_TEXTS)]
        im, pad = mini_toast(text)
        slide = ease_out((age + 1) / 5)
        x = x_right - MINI_W + (1 - slide) * (MINI_W + 40)
        fade = 1 - clamp((age - (life - 4)) / 4)
        pop = 0.5 if age == 0 else 0.2 if age == 1 else 0.0
        paste_rgba(img, im, x - pad, y - pad, opacity=fade, pop=pop)


def lap_course(f):
    img = course_base().copy()
    d = ImageDraw.Draw(img)
    s = spd(f)
    act2 = f >= E["typing_start"]
    clutter = clamp((s - 0.2) / 0.52) if act2 else 0.0
    # tabs multiply with speed
    n_tabs = 1 + int(round(clutter * 11)) if act2 else 1
    draw_tabs(img, n_tabs)
    # sidebar 'OUTDATED' tags creep in
    if act2:
        n_tag = int(clutter * 9 + 0.3)
        for i in range(n_tag):
            li = [0, 3, 1, 6, 7, 2, 9, 10, 8][i]
            ry = 162 + li * 44
            fill_rect(img, (SIDEBAR_X1 - 100, ry + 4, SIDEBAR_X1 - 12, ry + 34), (30, 38, 56) if li == 0 else (14, 15, 19))
            fill_rr(img, (SIDEBAR_X1 - 92, ry + 10, SIDEBAR_X1 - 14, ry + 28), 5, (74, 52, 16))
            d.text((SIDEBAR_X1 - 53, ry + 19), "OUTDATED", font=F(10, 800), fill=AMBER, anchor="mm")
    # video signal pulses
    px0, py0, px1, py1 = PLAYER
    cols, edges = nn_layout(course_slide_box())
    vt = video_time(f)
    for ei, (a, b) in enumerate(edges):
        if ei % 3:
            continue
        ph = (vt * 0.45 + ei * 0.137) % 1.0
        x, y = lerp(a[0], b[0], ph), lerp(a[1], b[1], ph)
        fill_circle(img, x, y, 10, BLUE, 0.9 * math.sin(ph * math.pi))
    # controls
    rate = playback_rate(f)
    total = 24 * 60 + 10
    tx0, tx1 = px0 + 20, px1 - 20
    ty = py1 - 46
    fill_rr(img, (tx0, ty - 2, tx1, ty + 3), 3, (255, 255, 255), 0.25)
    fx = tx0 + (tx1 - tx0) * vt / total
    fill_rr(img, (tx0, ty - 2, fx, ty + 3), 3, BLUE)
    fill_circle(img, fx, ty + 0.5, 14, WHITE)
    icon(img, "pause", px0 + 22, py1 - 30, 18, WHITE)
    d.text((px0 + 56, py1 - 21), f"{fmt_t(vt)} / {fmt_t(total)}", font=F(15, 600), fill=WHITE, anchor="lm")
    rl = (f"{rate:g}x")
    hot = rate > 1
    fr = F(15, 800 if hot else 600)
    rw = fr.getlength(rl) + 18
    if hot:
        fill_rr(img, (px1 - 132 - rw, py1 - 33, px1 - 132, py1 - 9), 6, AMBER)
    d.text((px1 - 132 - rw / 2, py1 - 21), rl, font=fr, fill=BLACK if hot else WHITE, anchor="mm")
    d.text((px1 - 92, py1 - 21), "CC", font=F(14, 700), fill=WHITE, anchor="mm")
    ring_rr(img, (px1 - 50, py1 - 30, px1 - 26, py1 - 12), 3, 2, WHITE)
    # 'this course is outdated' banner
    if act2 and f >= B["banner"]:
        a = ease_out((f - B["banner"]) / 5)
        fill_rr(img, (px0 + 16, py0 + 14, px0 + 16 + 560, py0 + 50), 8, (88, 62, 14), a)
        icon(img, "warn", px0 + 28, py0 + 22, 20, AMBER, a)
        d.text((px0 + 58, py0 + 32), "This lecture is 3 weeks old. Parts may be outdated.",
               font=F(16, 650), fill=mix((88, 62, 14), (255, 226, 160), a), anchor="lm")
    # menu bar: unread badge climbs
    unread = 0
    if f >= E["notif1"]:
        unread = sum(1 for n in T.NOTIFICATIONS[:3] if f >= n["frame"])
    if act2:
        unread += sum(1 for t in CH()["events"]["toasts"] if t["frame"] <= f) + int(sum(spd(k) ** 1.6 for k in range(E["typing_start"], f + 1)) * 1.2)
    menubar(img, f, bell=unread)
    if E["notif1"] <= f <= B["notifs_out"]:
        draw_big_notifs(img, f)
    if act2:
        draw_mini_toasts(img, f, fmax=E["tutorial_2x"] - 1)
    return img


# --- tutorial (233-269) ------------------------------------------------------
TUT_STEPS = ["Install the framework", "Create your first agent", "Add memory", "Add tools", "Add a planner",
             "Connect a vector store", "Add evals", "Migrate to v2", "Undo the migration", "Add a second agent",
             "Agents managing agents", "Reflection loop", "Deploy it", "Monitor it", "Scale to 1,000 agents",
             "Rewrite it for v3", "Prompt caching", "Multi-modal input", "Guardrails", "Cost control",
             "Self-improvement", "Replace yourself", "Benchmarks", "Ship it", "Start over (v4)"]
TUT_CODE = [
    "agent = Agent(model=\"latest\")", "agent.add_tool(search)", "memory = Memory(max_items=10_000)",
    "agent.attach(memory)", "plan = planner.make_plan(goal)", "for step in plan:", "    agent.run(step)",
    "result = await agent.ask(question)", "store = VectorStore(dim=1536)", "evals.run(agent, suite=\"all\")",
    "from agentflow import Agent  # v2", "agent = Agent.from_config(\"v3.yaml\")", "team = [Agent() for _ in range(8)]",
    "boss = Agent(role=\"manager\")", "boss.delegate(team)", "agent.reflect(depth=3)", "deploy(agent, replicas=1000)",
    "cache = PromptCache(ttl=3600)", "agent.learn(\"everything\")", "if agent.score > me.score:", "    me.retire()",
]
TUT_CAPS = ["so first we install the framework", "this part is really simple", "now we just wire the planner into memory",
            "don't worry, this changes next week", "pause here if you need to", "okay this is deprecated now but",
            "just copy this from the docs", "and that's basically an agent", "now let's make it scale",
            "you'll want to rewrite this for v3", "trust me on this one", "this used to be a whole job",
            "and boom, it learns by itself", "let's skip the theory", "this is the important part",
            "smash that like button", "okay, faster now", "if it breaks, just upgrade"]


def tut_mult(f):
    if f >= E["tutorial_16x"]:
        return 16
    if f >= E["tutorial_4x"]:
        return 4
    return 2


@lru_cache(maxsize=1)
def tut_phase_table():
    ph, out = 2.2, {}
    for f in range(E["tutorial_2x"], E["notif_better"] + 1):
        out[f] = ph
        if f < E["notif_do_that"]:
            ph += tut_mult(f) * 0.062
    return out


@lru_cache(maxsize=64)
def tut_slide(idx):
    rng = frng("slide", idx)
    img = vgrad(LW, LH, (16, 19, 26), (10, 12, 17))
    d = ImageDraw.Draw(img)
    accent = [BLUE, VIOLET, GREEN, AMBER, CYAN][idx % 5]
    tracked(d, (64, 64), "BUILD AN AI AGENT IN 10 MINUTES  ·  EP. 47", F(16, 700), TXT3, 1.8)
    fill_rect(img, (64, 82, 124, 86), accent)
    d.text((64, 160), f"Step {idx + 1}:", font=F(34, 600), fill=accent, anchor="ls")
    title = TUT_STEPS[idx % len(TUT_STEPS)]
    d.text((64, 226), title, font=fit(title, 1150, 64, 800, 40), fill=WHITE, anchor="ls")
    # code panel
    cx0, cy0, cx1, cy1 = 64, 276, 760, 660
    fill_rr(img, (cx0, cy0, cx1, cy1), 14, (22, 26, 34))
    for i, c in enumerate((RED, AMBER, GREEN)):
        fill_circle(img, cx0 + 24 + i * 20, cy0 + 22, 11, c, 0.7)
    fm = MONO(21)
    cw = fm.getlength("M")
    start = rng.randrange(len(TUT_CODE))
    for i in range(11):
        line = TUT_CODE[(start + i * 3) % len(TUT_CODE)]
        draw_code_line(d, cx0 + 64, cy0 + 72 + i * 30, line, fm, cw)
        d.text((cx0 + 42, cy0 + 72 + i * 30), str(i + 1), font=MONO(16), fill=TXT3, anchor="rs")
    # right side: diagram or bullets
    if idx % 2 == 0:
        boxes = [("INPUT", 840, 300), ("AGENT", 990, 420), ("TOOLS", 840, 540), ("OUTPUT", 1110, 560)]
        for (a, b) in ((0, 1), (2, 1), (1, 3)):
            ax, ay = boxes[a][1] + 70, boxes[a][2] + 30
            bx, by = boxes[b][1] + 70, boxes[b][2] + 30
            aa(img, (90, 100, 120), lambda dd, P, ss, ax=ax, ay=ay, bx=bx, by=by: dd.line([P(ax, ay), P(bx, by)], fill=255, width=3 * ss),
               box=(800, 280, 1260, 640))
        for name, x, y in boxes:
            fill_rr(img, (x, y, x + 140, y + 60), 12, (30, 36, 48))
            ring_rr(img, (x, y, x + 140, y + 60), 12, 2, accent)
            d.text((x + 70, y + 30), name, font=F(20, 750), fill=WHITE, anchor="mm")
    else:
        items = rng.sample(["it's that easy", "no theory needed", "works in v2 (maybe)", "copy-paste friendly",
                            "10 lines of code", "production ready*", "scales infinitely", "beginner friendly"], 4)
        for i, it in enumerate(items):
            y = 330 + i * 74
            fill_circle(img, 818, y - 9, 14, accent)
            d.text((840, y), it, font=F(30, 600), fill=TXT, anchor="ls")
    return img


@lru_cache(maxsize=48)
def caption_img(text):
    fnt = F(32, 650)
    w = int(fnt.getlength(text)) + 44
    im = Image.new("RGBA", (w, 56), (0, 0, 0, 0))
    bg = Image.new("RGBA", (w, 56), (0, 0, 0, 255))
    bg.putalpha(scale_mask(rr_mask(w, 56, 8), 0.78))
    im.alpha_composite(bg)
    ImageDraw.Draw(im).text((w / 2, 29), text, font=fnt, fill=WHITE, anchor="mm")
    return im


@lru_cache(maxsize=8)
def speed_badge(label, hot):
    fnt = F(120, 850)
    tw = fnt.getlength(label)
    w, h = int(tw + 150), 156
    pad = 30
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(w, h, 30, 14)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.7))
    im.alpha_composite(sh, (pad - spad, pad - spad + 6))
    body = Image.new("RGBA", (w, h), (12, 13, 16, 255))
    body.putalpha(scale_mask(rr_mask(w, h, 30), 0.88))
    im.alpha_composite(body, (pad, pad))
    border = Image.new("RGBA", (w, h), (AMBER if hot else (255, 255, 255)) + (0,))
    border.putalpha(scale_mask(rr_ring(w, h, 30, 3), 0.9 if hot else 0.35))
    im.alpha_composite(border, (pad, pad))
    ic = Image.new("RGBA", (64, 64), (AMBER if hot else WHITE) + (255,))
    ic.putalpha(icon_mask("ff", 64))
    im.alpha_composite(ic, (pad + 32, pad + h // 2 - 32))
    ImageDraw.Draw(im).text((pad + 116, pad + h / 2 + 4), label, font=fnt, fill=WHITE, anchor="lm")
    return im, pad


def tut_clean(f):
    ph = tut_phase_table()[min(f, E["notif_better"])]
    idx = int(ph)
    img = tut_slide(idx).copy()
    return img, ph


def tut_overlays(img, f, ph, chaos):
    d = ImageDraw.Draw(img)
    # captions
    cap = TUT_CAPS[int(ph * 2.3) % len(TUT_CAPS)]
    ci = caption_img(cap)
    if chaos > 0:
        ci = hsmear(ci.convert("RGBA"), 6 + 40 * chaos)
    paste_rgba(img, ci, (LW - ci.width) / 2, 690)
    # progress
    prog = clamp(0.22 + (ph - 2.2) * 0.028)
    fill_rect(img, (0, LH - 8, LW, LH), (60, 64, 74))
    fill_rect(img, (0, LH - 8, LW * prog, LH), BLUE)
    left = max(0, int((1 - prog) * 600))
    d.text((LW - 24, LH - 22), f"{fmt_t(left)} left", font=F(18, 600), fill=TXT2, anchor="rs")


def lap_tutorial(f):
    m = tut_mult(f)
    img, ph = tut_clean(f)
    chaos = 0.0
    if m == 4:
        frac = ph % 1.0
        if frac < 0.25 and int(ph) > 0:  # quick cross-fade on each flip
            img = Image.blend(tut_slide(int(ph) - 1), img, 0.35 + frac * 2.6)
    if m == 16:
        chaos = clamp(0.55 + (f - E["tutorial_16x"]) / 14, 0, 1)
        idx = int(ph)
        acc = np.asarray(img, np.float32) * 0.36
        wsum = 0.36
        for k, (wgt, dx) in enumerate(((0.26, -50), (0.2, -110), (0.12, -180), (0.06, -260)), start=1):
            if idx - k < 0:
                break
            sl = np.asarray(tut_slide(idx - k), np.float32)
            acc += np.roll(sl, int(dx * chaos), axis=1) * wgt
            wsum += wgt
        img = Image.fromarray((acc / wsum).clip(0, 255).astype(np.uint8))
        img = Image.blend(img, hsmear(img, 10 + 30 * chaos), 0.55 * chaos)
    tut_overlays(img, f, ph, chaos)
    if m == 16:
        rng = frng("tutglitch", f)
        img = glitch(img, rng, n=int(4 + 8 * chaos), maxshift=int(60 + 140 * chaos), split=int(4 + 8 * chaos))
        d = ImageDraw.Draw(img)
        for _ in range(int(3 + 6 * chaos)):  # caption streaks
            y = rng.randint(640, 760)
            x0 = rng.randint(0, 500)
            fill_rect(img, (x0, y, x0 + rng.randint(300, 900), y + rng.randint(2, 6)), WHITE, rng.uniform(0.3, 0.8))
    # mini toasts keep ticking (sound sync), parked bottom-left, small
    draw_mini_toasts(img, f, x_right=LW - 30, y_top=214, life_base=18, fmin=E["tutorial_2x"])
    # the badge, always crisp
    label = f"{m}x"
    bi, pad = speed_badge(label, m == 16)
    switch = {2: E["tutorial_2x"], 4: E["tutorial_4x"], 16: E["tutorial_16x"]}[m]
    age = f - switch
    sc = 1.0 + 0.32 * (1 - ease_out_back((age + 1) / 5)) if age < 5 else 1.0
    if sc != 1.0:
        bi = bi.resize((int(bi.width * sc), int(bi.height * sc)), Image.BILINEAR)
    bx = LW - 30 - (bi.width - 2 * pad * sc) - pad * sc
    by = 36 - pad * sc - (sc - 1) * 60
    paste_rgba(img, bi, bx, by, pop=0.4 if age == 0 else 0.0)
    return img


# --- hero: AI CAN NOW DO THAT FOR YOU. ----------------------------------------
@lru_cache(maxsize=1)
def hero_bg():
    ph = tut_phase_table()[E["notif_do_that"]]
    img = tut_slide(int(ph)).copy()
    tut_overlays(img, E["notif_do_that"], ph, 0.0)
    img = img.filter(ImageFilter.GaussianBlur(7))
    img = dim(img, 0.32)
    d = ImageDraw.Draw(img)
    fill_circle(img, LW / 2, 640, 70, (0, 0, 0), 0.5)
    icon(img, "pause", LW / 2 - 15, 625, 30, (150, 150, 150))
    return img


@lru_cache(maxsize=1)
def hero_card():
    text = "AI CAN NOW DO THAT FOR YOU."
    w, h = 1100, 232
    pad = 60
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(w, h, 30, 26)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.75))
    im.alpha_composite(sh, (pad - spad, pad - spad + 14))
    body = Image.new("RGBA", (w, h))
    body.paste(vgrad(w, h, (58, 122, 246), (36, 90, 214)), (0, 0))
    body.putalpha(rr_mask(w, h, 30))
    im.alpha_composite(body, (pad, pad))
    border = Image.new("RGBA", (w, h), (170, 205, 255, 0))
    border.putalpha(scale_mask(rr_ring(w, h, 30, 2), 0.7))
    im.alpha_composite(border, (pad, pad))
    d = ImageDraw.Draw(im)
    # header row: friendly sparkle + label + now
    ic = Image.new("RGBA", (46, 46), (255, 255, 255, 255))
    ic.putalpha(icon_mask("sparkle", 46))
    im.alpha_composite(ic, (pad + 40, pad + 24))
    d.text((pad + 98, pad + 48), "Assistant", font=F(24, 650), fill=(225, 236, 255), anchor="lm")
    d.text((pad + w - 40, pad + 48), "now", font=F(22, 500), fill=(200, 218, 255), anchor="rm")
    fnt = fit(text, w - 90, 62, 820, 44)
    d.text((pad + w / 2, pad + 158), text, font=fnt, fill=WHITE, anchor="mm")
    return im, pad


def lap_hero(f):
    img = hero_bg().copy()
    im, pad = hero_card()
    age = f - E["notif_do_that"]
    sc = lerp(0.9, 1.0, ease_out_back((age + 1) / 4, 1.2)) if age < 4 else 1.0
    op = clamp((age + 1) / 2)
    if sc != 1.0:
        im = im.resize((int(im.width * sc), int(im.height * sc)), Image.BILINEAR)
    paste_rgba(img, im, (LW - im.width) / 2, (LH - im.height) / 2 - 10, opacity=op, pop=0.3 if age == 0 else 0.0)
    menubar(img, E["notif_do_that"], bell=None, alpha=0.6)
    return img


# --- takeover: NEW MODEL. BETTER AT EVERYTHING. --------------------------------
@lru_cache(maxsize=1)
def takeover_base():
    yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
    r = np.sqrt(((xx - LW / 2) / LW) ** 2 + ((yy - LH / 2) / LH) ** 2)
    k = np.clip(1 - r * 1.3, 0, 1)[..., None]
    arr = np.array([96, 6, 12], np.float32) * (1 - k) + np.array([200, 18, 28], np.float32) * k
    stripes = (((xx + yy) // 40) % 2 == 0)[..., None] * 6.0
    img = Image.fromarray((arr + stripes).clip(0, 255).astype(np.uint8))
    w, h = 1120, 400
    x0, y0 = (LW - w) // 2, (LH - h) // 2
    drop_shadow(img, (x0, y0, x0 + w, y0 + h), 26, blur=26, opacity=0.6, dy=14)
    paste_grad_rr(img, (x0, y0, x0 + w, y0 + h), 26, (240, 46, 52), (206, 24, 34))
    ring_rr(img, (x0, y0, x0 + w, y0 + h), 26, 3, (255, 190, 190), 0.8)
    d = ImageDraw.Draw(img)
    icon(img, "warn", x0 + 44, y0 + 34, 44, WHITE)
    tracked(d, (x0 + 104, y0 + 68), "SYSTEM ALERT", F(24, 800), (255, 220, 220), 3)
    d.text((x0 + w - 44, y0 + 68), "now", font=F(24, 500), fill=(255, 210, 210), anchor="rs")
    d.text((LW / 2, y0 + 200), "NEW MODEL.", font=F(112, 900), fill=WHITE, anchor="mm")
    t2 = "BETTER AT EVERYTHING."
    d.text((LW / 2, y0 + 316), t2, font=fit(t2, w - 100, 76, 850), fill=WHITE, anchor="mm")
    return img


def lap_takeover(f):
    age = f - E["notif_better"]
    if age == 0:
        return Image.new("RGB", (LW, LH), WHITE)
    img = takeover_base()
    if age == 1:
        return Image.blend(img, Image.new("RGB", (LW, LH), WHITE), 0.6)
    if age <= 6:
        rng = frng("takeover", f)
        k = 1 - (age - 2) / 5
        jx, jy = rng.randint(-40, 40) * k, rng.randint(-16, 16) * k
        out = Image.new("RGB", (LW, LH), (120, 8, 14))
        out.paste(img, (int(jx), int(jy)))
        out = glitch(out, rng, n=int(5 + 8 * k), maxshift=int(140 * k) + 10, split=int(12 * k) + 2)
        if age in (3, 5):
            out = ImageOps.invert(out) if age == 3 else Image.blend(out, Image.new("RGB", out.size, WHITE), 0.25)
        return out
    return img.copy()


# --- agent builder (331-386) -------------------------------------------------
BUILD_NODES = [  # name, type, x, y
    ("YOU", "INPUT", 236, 380),
    ("READ ALL PAPERS", "TOOL", 452, 210),
    ("TUTORIALS @16x", "TOOL", 452, 560),
    ("SUMMARIZE", "LLM", 668, 384),
    ("MEMORY (∞)", "MEMORY", 668, 620),
    ("PLANNER", "PLANNER", 884, 236),
    ("SELF-IMPROVE LOOP", "LOOP", 884, 520),
    ("SKILL TRACKER", "TOOL", 1090, 200),
    ("OUTPUT: ROADMAP", "OUTPUT", 1090, 430),
]
BUILD_EDGES = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (3, 5), (4, 6), (5, 6), (5, 7), (6, 8), (7, 8)]
NODE_W, NODE_H = 172, 78
TYPE_COL = {"INPUT": GREEN, "TOOL": BLUE, "LLM": VIOLET, "MEMORY": (236, 112, 200), "PLANNER": AMBER,
            "LOOP": ORANGE, "OUTPUT": CYAN}


@lru_cache(maxsize=1)
def blueprint_bg():
    img = Image.new("RGB", (LW, LH), (9, 30, 60))
    arr = np.asarray(img).copy()
    arr[:, ::24] = (16, 44, 82)
    arr[::24, :] = (16, 44, 82)
    arr[:, ::120] = (26, 64, 112)
    arr[::120, :] = (26, 64, 112)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    fill_rect(img, (0, 30, LW, 82), (7, 20, 40))
    fill_rect(img, (0, 81, LW, 82), (30, 70, 120))
    icon(img, "bolt", 20, 40, 32, CYAN)
    tw = tracked(d, (64, 67), "AGENT BUILDER", F(26, 800), WHITE, 2.5)
    d.text((64 + tw + 28, 59), "untitled_agent  ·  draft", font=F(16, 500), fill=(120, 160, 210), anchor="lm")
    fill_rect(img, (0, 82, 196, LH), (7, 22, 44))
    fill_rect(img, (196, 82, 197, LH), (30, 70, 120))
    tracked(d, (20, 116), "NODES", F(13, 800), (110, 150, 200), 2)
    for i, t in enumerate(["INPUT", "TOOL", "LLM", "MEMORY", "PLANNER", "LOOP", "OUTPUT"]):
        y = 134 + i * 50
        fill_rr(img, (16, y, 180, y + 40), 8, (14, 38, 70))
        fill_rr(img, (16, y, 22, y + 40), 3, TYPE_COL[t])
        d.text((34, y + 20), {"LLM": "LLM"}.get(t, t.title()), font=F(16, 600), fill=(200, 220, 245), anchor="lm")
    return img


@lru_cache(maxsize=16)
def node_img(i, lit):
    name, typ, _, _ = BUILD_NODES[i]
    col = TYPE_COL[typ]
    pad = 16
    im = Image.new("RGBA", (NODE_W + 2 * pad, NODE_H + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(NODE_W, NODE_H, 12, 8)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.6))
    im.alpha_composite(sh, (pad - spad, pad - spad + 5))
    body = Image.new("RGBA", (NODE_W, NODE_H), (16, 40, 74, 255))
    hdr = Image.new("RGB", (NODE_W, 26), mix(col, (16, 40, 74), 0.45 if lit else 0.7))
    body.paste(hdr, (0, 0))
    body.putalpha(rr_mask(NODE_W, NODE_H, 12))
    im.alpha_composite(body, (pad, pad))
    border = Image.new("RGBA", (NODE_W, NODE_H), (CYAN if lit else (90, 150, 210)) + (0,))
    border.putalpha(scale_mask(rr_ring(NODE_W, NODE_H, 12, 1.8), 0.95 if lit else 0.6))
    im.alpha_composite(border, (pad, pad))
    d = ImageDraw.Draw(im)
    tracked(d, (pad + 12, pad + 18), typ, F(12, 800), WHITE, 1.4)
    led = GREEN if lit else (60, 80, 100)
    d.ellipse((pad + NODE_W - 22, pad + 8, pad + NODE_W - 12, pad + 18), fill=led)
    fnt = fit(name, NODE_W - 30, 19, 750, 12)
    d.text((pad + 12, pad + 54), name, font=fnt, fill=WHITE, anchor="lm")
    for px in (pad, pad + NODE_W):
        d.ellipse((px - 6, pad + 46, px + 6, pad + 58), fill=CYAN, outline=(9, 30, 60), width=2)
    return im, pad


def node_ports(i):
    _, _, x, y = BUILD_NODES[i]
    return (x + NODE_W, y + 52), (x, y + 52)


def edge_curve(a, b, t1=1.0):
    (ox, oy), _ = node_ports(a)
    _, (ix, iy) = node_ports(b)
    dx = max(70, (ix - ox) * 0.5)
    return bezier((ox, oy), (ox + dx, oy), (ix - dx, iy), (ix, iy), n=40, t1=t1)


def lap_builder(f):
    img = blueprint_bg().copy()
    d = ImageDraw.Draw(img)
    parts = E["machine_parts"]
    spawned = [parts[i] if i < len(parts) else E["build_end"] for i in range(len(BUILD_NODES))]
    lit = f >= E["machine_lights"]
    n_built = sum(1 for sf in spawned if f >= sf)
    if n_built == 0:
        ring = (440, 300, 1040, 520)
        for k in range(0, 1200, 24):  # dashed drop zone
            p = k / 1200 * 2 * (600 + 220)
            x0, y0, x1, y1 = ring
            if p < 600:
                pt = (x0 + p, y0)
            elif p < 820:
                pt = (x1, y0 + p - 600)
            elif p < 1420:
                pt = (x1 - (p - 820), y1)
            else:
                pt = (x0, y1 - (p - 1420))
            fill_circle(img, pt[0], pt[1], 4, (90, 150, 210))
        d.text((740, 400), "+  Drop nodes here to build an agent", font=F(26, 600), fill=(150, 190, 235), anchor="mm")
    # wires
    for a, b in BUILD_EDGES:
        t0 = max(spawned[a], spawned[b])
        if f < t0:
            continue
        t = clamp((f - t0 + 1) / 3)
        pts = edge_curve(a, b, ease_out(t))
        aa(img, CYAN, lambda dd, P, ss, pts=pts: dd.line([P(*p) for p in pts], fill=255, width=int(3 * ss), joint="curve"),
           box=(190, 80, LW, LH), alpha=0.85 if lit else 0.6)
    # data packets once the machine is lit
    if lit:
        for ei, (a, b) in enumerate(BUILD_EDGES):
            pts = edge_curve(a, b)
            for k in range(2):
                ph = ((f - E["machine_lights"]) * (0.09 + 0.05 * spd(f)) + ei * 0.31 + k * 0.5) % 1.0
                p = pts[int(ph * (len(pts) - 1))]
                fill_circle(img, p[0], p[1], 12, WHITE)
                fill_circle(img, p[0], p[1], 22, CYAN, 0.35)
    # nodes pop in on the machine_parts beats
    for i, sf in enumerate(spawned):
        if f < sf:
            continue
        age = f - sf
        im, pad = node_img(i, lit)
        sc = [0.55, 1.12, 1.03, 1.0][age] if age < 4 else 1.0
        x, y = BUILD_NODES[i][2], BUILD_NODES[i][3]
        if sc != 1.0:
            im = im.resize((int(im.width * sc), int(im.height * sc)), Image.BILINEAR)
        cx, cy = x + NODE_W / 2, y + NODE_H / 2
        paste_rgba(img, im, cx - im.width / 2, cy - im.height / 2, pop=0.6 if age == 0 else 0.25 if age == 1 else 0)
    # status + deploy button
    if f < E["build_start"]:
        status = "Empty canvas"
    elif f <= E["build_end"]:
        status = f"Building…  {n_built}/{len(BUILD_NODES)} nodes"
    elif f < E["button_press"]:
        status = "Ready to deploy"
    else:
        status = "Deployed"
    d.text((LW - 24, 56), status, font=F(18, 650), fill=CYAN if f >= E["build_start"] else (120, 160, 210), anchor="rm")
    bx0, by0, bx1, by1 = 1030, 700, 1250, 772
    pressed = f >= E["button_press"]
    ready = f > E["build_end"]
    if ready and not pressed:
        glow = 0.35 + 0.35 * (0.5 + 0.5 * math.sin((f - E["machine_lights"]) * 0.9))
        fill_rr(img, (bx0 - 10, by0 - 10, bx1 + 10, by1 + 10), 24, CYAN, glow * 0.5)
    col = (12, 120, 140) if pressed else CYAN if ready else (40, 70, 100)
    off = 4 if pressed else 0
    fill_rr(img, (bx0 + off, by0 + off, bx1 - off, by1 - off), 18, col)
    d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "DEPLOY  ▶", font=F(28, 850),
           fill=(4, 30, 40) if ready else (110, 140, 170), anchor="mm")
    if pressed:
        age = f - E["button_press"]
        a = ease_out((age + 1) / 3)
        fill_rect(img, (0, 290, LW, 520), (2, 12, 22), 0.88 * a)
        fill_rect(img, (0, 290, LW, 293), CYAN, a)
        fill_rect(img, (0, 517, LW, 520), CYAN, a)
        sc = lerp(1.25, 1.0, ease_out((age + 1) / 4))
        fnt = F(int(118 * sc), 850)
        label = "AGENT ONLINE"
        tw = fnt.getlength(label)
        dot = 70 * sc
        total = tw + 36 * sc + dot
        x0 = (LW - total) / 2
        col = mix(WHITE, CYAN, clamp(age / 2))
        d.text((x0, 405), label, font=fnt, fill=col, anchor="lm")
        pulse = 0.5 + 0.5 * math.sin(age * 0.8)
        fill_circle(img, x0 + tw + 36 * sc + dot / 2, 405, dot * 1.6, CYAN, 0.18 + 0.12 * pulse)
        fill_circle(img, x0 + tw + 36 * sc + dot / 2, 405, dot, CYAN)
        if age < 2:
            img = Image.blend(img, Image.new("RGB", img.size, (200, 250, 255)), 0.35 if age == 0 else 0.12)
    menubar(img, f, app="Agent Builder", bell=None, bg=(5, 14, 28))
    return img


# --- calm dashboard (387-410) -------------------------------------------------
@lru_cache(maxsize=1)
def calm_toast():
    text1, text2 = "YOUR PERSONALIZED AI LEARNING", "ROADMAP IS READY."
    w, h = 720, 214
    pad = 40
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(w, h, 20, 18)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.65))
    im.alpha_composite(sh, (pad - spad, pad - spad + 10))
    body = Image.new("RGBA", (w, h))
    body.paste(vgrad(w, h, (30, 40, 56), (22, 29, 41)), (0, 0))
    body.putalpha(rr_mask(w, h, 20))
    im.alpha_composite(body, (pad, pad))
    border = Image.new("RGBA", (w, h), (110, 200, 230, 0))
    border.putalpha(scale_mask(rr_ring(w, h, 20, 1.5), 0.5))
    im.alpha_composite(border, (pad, pad))
    tile = Image.new("RGBA", (64, 64), (40, 170, 200, 255))
    tile.putalpha(rr_mask(64, 64, 16))
    im.alpha_composite(tile, (pad + 26, pad + 28))
    ic = Image.new("RGBA", (40, 40), (255, 255, 255, 255))
    ic.putalpha(icon_mask("route", 40))
    im.alpha_composite(ic, (pad + 38, pad + 40))
    d = ImageDraw.Draw(im)
    tracked(d, (pad + 108, pad + 44), "YOUR AGENT", F(15, 750), (130, 210, 235), 1.8)
    d.text((pad + w - 24, pad + 44), "now", font=F(16, 500), fill=TXT2, anchor="rs")
    fnt = fit(text1, w - 140, 38, 780, 28)
    d.text((pad + 108, pad + 94), text1, font=fnt, fill=WHITE, anchor="ls")
    d.text((pad + 108, pad + 142), text2, font=fnt, fill=WHITE, anchor="ls")
    return im, pad


def open_button_box():
    pad_x = LW - 18 - 720
    return (pad_x + 720 - 24 - 150, 44 + 214 - 24 - 50, pad_x + 720 - 24, 44 + 214 - 24)


def lap_dashboard(f):
    img = Image.new("RGB", (LW, LH), (11, 14, 19))
    d = ImageDraw.Draw(img)
    menubar(img, f, app="Agent", bell=None)
    t = f - B["dashboard_start"]
    fill_circle(img, 48, 66, 14, CYAN, 0.6 + 0.4 * math.sin(f * 0.3))
    tracked(d, (68, 74), "AGENT  ·  ONLINE", F(20, 800), CYAN, 2.4)
    d.text((68, 104), "agent_v8 · learning for you", font=F(16, 500), fill=TXT3, anchor="ls")
    # soft spinner
    cx, cy, R = LW / 2, 352, 64
    a0 = (f * 14) % 360

    def spin(dd, P, ss):
        x0, y0 = P(cx - R, cy - R)
        x1, y1 = P(cx + R, cy + R)
        dd.arc((x0, y0, x1, y1), 0, 360, fill=50, width=int(9 * ss))
        dd.arc((x0, y0, x1, y1), a0, a0 + 100, fill=255, width=int(9 * ss))
    aa(img, CYAN, spin, box=(cx - R - 10, cy - R - 10, cx + R + 10, cy + R + 10))
    d.text((LW / 2, 490), "Learning autonomously…", font=F(52, 720), fill=WHITE, anchor="ms")
    d.text((LW / 2, 530), "Sit back. Your agent is catching up for you.", font=F(22, 450), fill=TXT2, anchor="ms")
    stats = [("PAPERS READ", 1204 + t * 37), ("TUTORIALS WATCHED @16x", 388 + t * 11),
             ("SKILLS FOUND", min(T.ROADMAP_TOTAL, int(T.ROADMAP_TOTAL * clamp((t + 1) / (E["notif_roadmap"] - B["dashboard_start"])) ** 0.8)))]
    for i, (lab, val) in enumerate(stats):
        x0 = 160 + i * 330
        fill_rr(img, (x0, 590, x0 + 300, 710), 16, (20, 25, 33))
        ring_rr(img, (x0, 590, x0 + 300, 710), 16, 1, (40, 48, 62))
        tracked(d, (x0 + 24, 626), lab, F(13, 750), TXT3, 1.5)
        d.text((x0 + 24, 684), f"{val:,}", font=F(44, 780), fill=TXT, anchor="ls")
    if f >= E["notif_roadmap"]:
        im, pad = calm_toast()
        age = f - E["notif_roadmap"]
        tt = ease_out((age + 1) / 6)
        x = LW - 18 - 720 + (1 - tt) * 780
        paste_rgba(img, im, x - pad, 44 - pad, pop=0.4 if age == 0 else 0.15 if age == 1 else 0)
        bx0, by0, bx1, by1 = open_button_box()
        bx0 += (1 - tt) * 780
        bx1 += (1 - tt) * 780
        press = f >= E["roadmap_open"] - 2
        fill_rr(img, (bx0, by0, bx1, by1), 25, (30, 110, 220) if press else BLUE)
        d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "OPEN", font=F(22, 800), fill=WHITE, anchor="mm")
        # the cursor drifts over and clicks
        if f >= E["notif_roadmap"] + 3:
            k = ease_out((f - E["notif_roadmap"] - 3) / 6)
            mx, my = lerp(820, (bx0 + bx1) / 2 + 10, k), lerp(620, (by0 + by1) / 2 + 8, k)
            cur = [(mx, my), (mx, my + 30), (mx + 8, my + 23), (mx + 14, my + 36), (mx + 19, my + 34),
                   (mx + 13, my + 21), (mx + 23, my + 21)]
            aa(img, BLACK, lambda dd, P, ss: dd.polygon([P(*p) for p in cur], fill=255, outline=255, width=int(3 * ss)),
               box=(mx - 6, my - 6, mx + 32, my + 44))
            aa(img, WHITE, lambda dd, P, ss: dd.polygon([P(*p) for p in cur], fill=255),
               box=(mx - 6, my - 6, mx + 32, my + 44))
    return img


# --- roadmap (411-491) --------------------------------------------------------
RM_TOP = 316
RM_ROW = 58


@lru_cache(maxsize=1)
def roadmap_items():
    rng = random.Random(847)
    fixed = ["Linear Algebra", "Prompt Engineering", "Unlearn Prompt Engineering", "Prompt Engineering 2",
             "Agent Framework #47", "The framework that replaced #47", "RAG", "Read 300 papers (this week)",
             "Sleep (optional)", "Fine-tuning", "Evals", "Quantization", "Vibe Architecture", "Diffusion", "MLOps",
             "Agents", "Calculus (again)", "Probability", "Transformers", "Attention (the mechanism)",
             "Attention (yours)", "Embeddings", "Agent Framework #48", "Vector Databases", "Unlearn Vector Databases"]
    topics = ["Linear Algebra", "Prompt Engineering", "RAG", "Fine-tuning", "Evals", "Quantization", "Diffusion",
              "MLOps", "Agents", "Embeddings", "Tokenizers", "Vector Databases", "RLHF", "Distillation",
              "Mixture of Experts", "Context Windows", "Multimodal Models", "Reasoning Models", "Synthetic Data",
              "Inference Optimization", "GPU Kernels", "AI Safety", "Interpretability", "Benchmarks", "Agent Memory",
              "Tool Use", "Long Context", "Small Models", "World Models", "Speech Models", "Model Merging", "Low-rank Adapters",
              "Retrieval", "Guardrails", "Prompt Caching", "Orchestration", "Data Pipelines", "Statistics", "Optimization"]
    pats = ["{t}", "Advanced {t}", "{t} 2", "{t} (new version)", "Unlearn {t}", "{t} for {u}", "Re-learn {t}",
            "{t}, but faster", "{t} in 10 minutes", "Read {k} papers on {t}", "Why {t} is dead", "{t} is back",
            "{t} (deprecated)", "{t} from scratch", "{t} at scale", "Intro to {t} (updated)"]
    items = list(fixed)
    fw = 49
    while len(items) < T.ROADMAP_TOTAL:
        r = rng.random()
        if r < 0.07:
            items.append(f"Agent Framework #{fw}")
            fw += 1
        elif r < 0.11 and not items[-1].startswith("The framework"):
            items.append(f"The framework that replaced #{fw - 1}")
        elif r < 0.13:
            items.append(rng.choice(["Sleep (optional)", "Touch grass (scheduled)", "Vibe Architecture 2",
                                     "Read 300 papers (today)", "Prompt Engineering 3", "Unlearn everything", "Eat (batch)"]))
        else:
            t, u = rng.sample(topics, 2)
            items.append(rng.choice(pats).format(t=t, u=u, k=rng.choice([40, 120, 300, 1000])))
    tags = []
    for i in range(len(items)):
        r = random.Random(i * 31 + 7).random()
        tags.append("NEW" if r < 0.12 else "UPDATED" if r < 0.2 else "DEPRECATED?" if r < 0.25 else
                    f"est. {random.Random(i).choice([6, 12, 20, 40, 80, 120])} h")
    return items, tags


@lru_cache(maxsize=1)
def roadmap_scroll_table():
    """Scroll offset (px) per frame: integrate a velocity that follows the speed channel."""
    a, b = E["scroll_start"], E["notif_obsolete"] - 1
    vis_rows = (LH - RM_TOP) / RM_ROW
    target_top = 772
    raw = {}
    acc = 0.0
    for f in range(a, b + 1):
        ramp = clamp((f - a + 1) / 6)
        acc += (spd(f) ** 2.1) * ramp
        raw[f] = acc
    k = (target_top * RM_ROW) / acc
    table, vel = {}, {}
    prev = 0.0
    for f in range(E["roadmap_open"], b + 2):
        v = raw.get(min(f, b), 0.0) * k if f >= a else 0.0
        table[f] = v
        vel[f] = v - prev
        prev = v
    return table, vel, vis_rows


@lru_cache(maxsize=1)
def roadmap_header():
    img = Image.new("RGB", (LW, RM_TOP), (12, 15, 21))
    d = ImageDraw.Draw(img)
    menubar(img, 1, app="Roadmap", bell=None)  # clock is redrawn per frame
    tracked(d, (60, 78), "YOUR AI LEARNING ROADMAP", F(24, 800), (140, 178, 255), 3.2)
    d.text((LW - 60, 78), "generated for you  ·  847 skills  ·  est. 41,300 h", font=F(17, 500), fill=TXT3, anchor="rs")
    big = F(150, 850)
    d.text((54, 236), "0 / 847", font=big, fill=WHITE, anchor="ls")
    x = 54 + big.getlength("0 / 847") + 34
    d.text((x, 236), "SKILLS MASTERED", font=fit("SKILLS MASTERED", LW - 60 - x, 64, 850), fill=WHITE, anchor="ls")
    fill_rr(img, (60, 268, LW - 140, 286), 9, (34, 40, 52))
    fill_rr(img, (60, 268, 70, 286), 5, (60, 70, 90))
    d.text((LW - 60, 286), "0%", font=F(30, 800), fill=WHITE, anchor="rs")
    fill_rect(img, (0, RM_TOP - 1, LW, RM_TOP), LINE)
    return img


def roadmap_list(scroll, vel):
    """Render the list viewport (LW x LH-RM_TOP) at a given scroll offset."""
    items, tags = roadmap_items()
    h = LH - RM_TOP
    img = Image.new("RGB", (LW, h), (16, 19, 26))
    d = ImageDraw.Draw(img)
    first = int(scroll // RM_ROW)
    off = scroll - first * RM_ROW
    fnum, fname, ftag = F(22, 600), F(28, 600), F(14, 750)
    for k in range(int(h / RM_ROW) + 2):
        i = first + k
        if i >= len(items):
            break
        y = k * RM_ROW - off
        if i % 2 == 0:
            fill_rect(img, (0, y, LW, y + RM_ROW), (19, 23, 31))
        d.text((112, y + RM_ROW / 2), f"{i + 1}.", font=fnum, fill=TXT3, anchor="rm")
        ring_rr(img, (134, y + 15, 162, y + 43), 6, 2.2, (120, 132, 156))
        d.text((184, y + RM_ROW / 2 + 1), items[i], font=fname, fill=TXT, anchor="lm")
        tg = tags[i]
        col = {"NEW": GREEN, "UPDATED": BLUE, "DEPRECATED?": AMBER}.get(tg, TXT3)
        tw = ftag.getlength(tg) + 22
        if tg.startswith("est."):
            d.text((LW - 70, y + RM_ROW / 2), tg, font=F(16, 500), fill=TXT3, anchor="rm")
        else:
            fill_rr(img, (LW - 70 - tw, y + 17, LW - 70, y + 41), 6, mix(col, (16, 19, 26), 0.75))
            d.text((LW - 70 - tw / 2, y + RM_ROW / 2), tg, font=ftag, fill=col, anchor="mm")
    if vel > 6:
        sharp = np.asarray(img, np.float32)
        arr = vblur_arr(sharp, min(vel * 0.8, 150))
        k = clamp((vel - 6) / 120) * 0.7
        img = Image.fromarray((sharp * (1 - k) + arr * k).clip(0, 255).astype(np.uint8))
    # scrollbar (tiny thumb)
    total_h = len(items) * RM_ROW
    track = (LW - 26, 10, LW - 18, h - 10)
    fill_rr(img, track, 4, (34, 40, 52))
    th = max(7, (track[3] - track[1]) * h / total_h)
    ty = track[1] + (track[3] - track[1] - th) * clamp(scroll / (total_h - h))
    fill_rr(img, (track[0] - 1, ty, track[2] + 1, ty + th), 4, (190, 200, 220))
    return img, ty


def lap_roadmap(f, freeze=False):
    table, vel, _ = roadmap_scroll_table()
    ff = min(f, E["notif_obsolete"] - 1)
    sc = table.get(ff, 0.0)
    v = 0.0 if freeze else vel.get(ff, 0.0)
    img = Image.new("RGB", (LW, LH))
    img.paste(roadmap_header(), (0, 0))
    menubar(img, f, app="Roadmap", bell=None)
    lst, ty = roadmap_list(sc, v)
    img.paste(lst, (0, RM_TOP))
    if not freeze and f >= E["scroll_start"]:
        items, _ = roadmap_items()
        cur = int(sc // RM_ROW) + 1
        lab = f"#{cur} / {len(items)}"
        fnt = F(20, 800)
        w = fnt.getlength(lab) + 28
        y = RM_TOP + ty - 8
        fill_rr(img, (LW - 40 - w, y, LW - 40, y + 34), 17, (40, 48, 64))
        ImageDraw.Draw(img).text((LW - 40 - w / 2, y + 17), lab, font=fnt, fill=WHITE, anchor="mm")
    return img


# --- ROADMAP OBSOLETE (492-518) ----------------------------------------------
@lru_cache(maxsize=1)
def obsolete_base():
    img = lap_roadmap(E["notif_obsolete"] - 1, freeze=True)
    return dim(gray(img), 0.42)


@lru_cache(maxsize=1)
def stamp_img():
    txt = "OBSOLETE"
    fnt = F(150, 900)
    w = int(fnt.getlength(txt)) + 120
    h = 230
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((8, 8, w - 8, h - 8), radius=22, outline=255, width=14)
    d.text((w / 2, h / 2 + 6), txt, font=fnt, fill=255, anchor="mm")
    rng = np.random.default_rng(492)
    noise = rng.random((h // 3 + 1, w // 3 + 1))
    noise = np.kron(noise, np.ones((3, 3)))[:h, :w]
    arr = np.asarray(m, np.float32) * (0.55 + 0.45 * (noise > 0.22))
    m = Image.fromarray(arr.astype(np.uint8)).rotate(14, expand=True, resample=Image.BICUBIC)
    im = Image.new("RGBA", m.size, (226, 48, 52, 0))
    im.putalpha(m)
    return im


@lru_cache(maxsize=1)
def obsolete_card():
    w, h = 940, 268
    pad = 50
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sm, spad = _shadow(w, h, 26, 24)
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, 0.8))
    im.alpha_composite(sh, (pad - spad, pad - spad + 14))
    body = Image.new("RGBA", (w, h))
    body.paste(vgrad(w, h, (238, 44, 50), (196, 22, 32)), (0, 0))
    body.putalpha(rr_mask(w, h, 26))
    im.alpha_composite(body, (pad, pad))
    border = Image.new("RGBA", (w, h), (255, 200, 200, 0))
    border.putalpha(scale_mask(rr_ring(w, h, 26, 2.5), 0.8))
    im.alpha_composite(border, (pad, pad))
    d = ImageDraw.Draw(im)
    ic = Image.new("RGBA", (34, 34), (255, 255, 255, 255))
    ic.putalpha(icon_mask("warn", 34))
    im.alpha_composite(ic, (pad + 36, pad + 26))
    tracked(d, (pad + 82, pad + 53), "RELEASE ALERT", F(19, 800), (255, 222, 222), 2.4)
    d.text((pad + w - 36, pad + 53), "now", font=F(19, 500), fill=(255, 215, 215), anchor="rs")
    d.text((pad + w / 2, pad + 134), "NEW RELEASE.", font=F(76, 900), fill=WHITE, anchor="mm")
    t2 = "ROADMAP OBSOLETE."
    d.text((pad + w / 2, pad + 214), t2, font=fit(t2, w - 80, 70, 850), fill=WHITE, anchor="mm")
    return im, pad


def lap_obsolete(f):
    img = obsolete_base().copy()
    age = f - E["notif_obsolete"]
    st = stamp_img()
    sa = age - 2
    if sa >= 0:
        sc = lerp(1.5, 1.0, ease_in((sa + 1) / 3)) if sa < 3 else 1.0
        s2 = st.resize((int(st.width * sc), int(st.height * sc)), Image.BILINEAR) if sc != 1.0 else st
        paste_rgba(img, s2, 640 - s2.width / 2, 190 - s2.height / 2, opacity=0.92 * clamp((sa + 1) / 2))
    im, pad = obsolete_card()
    sc = lerp(0.88, 1.0, ease_out_back((age + 1) / 4, 1.3)) if age < 4 else 1.0
    if sc != 1.0:
        im = im.resize((int(im.width * sc), int(im.height * sc)), Image.BILINEAR)
    paste_rgba(img, im, (LW - im.width) / 2, 520 - im.height / 2, opacity=clamp((age + 1) / 2),
               pop=0.35 if age == 0 else 0.0)
    menubar(img, f, app="Roadmap", bell=None, alpha=0.7)
    return img


def laptop_frame(f):
    if f >= E["close_laptop"]:
        return Image.new("RGB", (LW, LH), BLACK)
    if f < E["tutorial_2x"]:
        return lap_course(f)
    if f < E["notif_do_that"]:
        return lap_tutorial(f)
    if f < E["notif_better"]:
        return lap_hero(f)
    if f < B["builder_start"]:
        return lap_takeover(f)
    if f < B["dashboard_start"]:
        return lap_builder(f)
    if f < E["roadmap_open"]:
        return lap_dashboard(f)
    if f < E["notif_obsolete"]:
        return lap_roadmap(f)
    return lap_obsolete(f)


# =============================================================================
# MONITOR  (1600 x 900)  -- his work
# =============================================================================
MW, MH = 1600, 900
MSC = 1.07
MMENU = int(30 * MSC)

PAPER_TEXT = {
    "abstract": ("Neural networks are function approximators built from many small, simple units. "
                 "Each unit computes a weighted sum of its inputs and passes the result through a "
                 "non-linearity. Stacked in layers, these units can learn surprisingly rich mappings "
                 "from examples alone. This note introduces the core ideas slowly, with one small "
                 "diagram and no hurry at all."),
    "intro": ("Learning, for a neural network, means adjusting its weights so that its outputs move "
              "closer to the answers we want. We measure how wrong it is with a loss function and "
              "nudge every weight a little in the direction that reduces that loss. Repeated many "
              "times, these small corrections add up. The important thing is to take your time: "
              "the fundamentals change slowly, and they will still be here tomorrow. In the next "
              "section we build the simplest possible network by hand."),
}


def draw_window(img, box, title, r=12, body=(26, 28, 34), bar=(20, 22, 27), sc=1.0):
    x0, y0, x1, y1 = box
    drop_shadow(img, box, r, blur=18, opacity=0.55, dy=8)
    fill_rr(img, box, r, body)
    bh = int(36 * sc)
    fill_rr(img, (x0, y0, x1, y0 + bh + r), r, bar)
    fill_rect(img, (x0, y0 + bh, x1, y0 + bh + r + 1), body)
    fill_rect(img, (x0, y0 + bh, x1, y0 + bh + 1), (40, 44, 54))
    for i in range(3):
        fill_circle(img, x0 + 20 + i * 20, y0 + bh / 2, 11 * sc, (70, 74, 86))
    ImageDraw.Draw(img).text(((x0 + x1) / 2, y0 + bh / 2), title, font=F(15 * sc, 600), fill=TXT2, anchor="mm")
    return y0 + bh


@lru_cache(maxsize=1)
def mon_reader_base():
    img = wallpaper(MW, MH, 1).copy()
    d = ImageDraw.Draw(img)
    win = (24, 50, 1010, 884)
    top = draw_window(img, win, "gentle_intro_nn.pdf — Reader")
    fill_rect(img, (25, top + 1, 1009, top + 40), (30, 32, 38))
    d.text((48, top + 20), "Page 1 / 14", font=F(14, 500), fill=TXT2, anchor="lm")
    d.text((986, top + 20), "110%", font=F(14, 500), fill=TXT2, anchor="rm")
    fill_rect(img, (25, top + 40, 1009, 872), (46, 48, 54))
    px0, py0, px1 = 107, top + 64, 927
    page = Image.new("RGB", (px1 - px0, 872 - py0), (246, 243, 236))
    pd = ImageDraw.Draw(page)
    W = page.width
    ink, ink2 = (30, 32, 40), (92, 96, 108)
    pd.text((W / 2, 64), "A Gentle Introduction to Neural Networks", font=F(31, 760), fill=ink, anchor="ms")
    pd.text((W / 2, 98), "A. Learner¹  ·  B. Patient²", font=F(16, 500), fill=ink2, anchor="ms")
    pd.text((W / 2, 120), "¹Department of Trying Hard   ²Institute of Eventually", font=F(13, 450), fill=ink2, anchor="ms")
    pd.text((90, 168), "Abstract", font=F(16, 750), fill=ink, anchor="ls")
    y = 192
    for ln in wrap(PAPER_TEXT["abstract"], F(14, 450), W - 180):
        pd.text((90, y), ln, font=F(14, 450), fill=(60, 64, 74), anchor="ls")
        y += 21
    # figure
    fy0 = y + 18
    pd.rectangle((90, fy0, W - 90, fy0 + 230), outline=(214, 210, 200), width=1)
    cols, edges = nn_layout((230, fy0 + 30, W - 230, fy0 + 200), (4, 5, 3))

    def de(dd, P, ss):
        for a, b in edges:
            dd.line([P(*a), P(*b)], fill=255, width=int(1.2 * ss))
    aa(page, (150, 152, 160), de, box=(90, fy0, W - 90, fy0 + 230))
    for li, col in enumerate(cols):
        for (cx, cy) in col:
            fill_circle(page, cx, cy, 24, [(70, 110, 200), (120, 90, 200), (40, 160, 120)][li])
    pd.text((W / 2, fy0 + 256), "Figure 1. A small feed-forward network. Information flows left to right.",
            font=F(13, 450), fill=ink2, anchor="ms")
    y = fy0 + 302
    pd.text((90, y), "1   Introduction", font=F(19, 750), fill=ink, anchor="ls")
    y += 30
    hl = "The important thing is to take your time"
    for ln in wrap(PAPER_TEXT["intro"], F(14, 450), W - 180):
        if "take your time" in ln or "important thing" in ln:
            i0 = ln.find("The important") if "The important" in ln else 0
            seg = ln[i0:]
            x = 90 + F(14, 450).getlength(ln[:i0])
            pd.rectangle((x - 2, y - 15, x + F(14, 450).getlength(seg) + 2, y + 5), fill=(255, 236, 140))
        pd.text((90, y), ln, font=F(14, 450), fill=(60, 64, 74), anchor="ls")
        y += 21
    _ = hl
    img.paste(page, (px0, py0))
    # notebook window
    nb = (1034, 50, 1576, 560)
    top = draw_window(img, nb, "learn_ai.ipynb", body=(24, 26, 32))
    for i, lab in enumerate(("+", "✂", "▶", "■", "↻")):
        d.text((1060 + i * 34, top + 22), lab, font=F(17, 500), fill=TXT3, anchor="mm")
    fill_rect(img, (1035, top + 42, 1575, top + 43), LINE)
    cy0 = top + 70
    d.text((1054, cy0 + 18), "[1]:", font=MONO(15), fill=(110, 150, 220), anchor="lm")
    fill_rr(img, (1100, cy0, 1556, cy0 + 112), 6, (32, 35, 43))
    fill_rr(img, (1100, cy0, 1104, cy0 + 112), 2, BLUE)
    fm = MONO(17)
    cw = fm.getlength("M")
    for i, ln in enumerate(["# Day 1", "import numpy as np", 'goal = "learn AI"']):
        draw_code_line(d, 1118, cy0 + 26 + i * 30, ln, fm, cw, anchor="lm")
    d.text((1054, cy0 + 160), "[ ]:", font=MONO(15), fill=TXT3, anchor="lm")
    fill_rr(img, (1100, cy0 + 142, 1556, cy0 + 180), 6, (32, 35, 43))
    # today widget
    wb = (1034, 590, 1576, 884)
    drop_shadow(img, wb, 16, blur=18, opacity=0.5)
    fill_rr(img, wb, 16, (24, 27, 34))
    tracked(d, (1064, 638), "TODAY'S GOAL", F(15, 800), (130, 170, 235), 2.2)
    ring_rr(img, (1064, 680, 1112, 728), 10, 3, (140, 150, 170))
    d.text((1136, 704), "Learn AI.", font=F(52, 780), fill=WHITE, anchor="lm")
    d.text((1064, 790), "Day 1 · plenty of time", font=F(19, 500), fill=TXT2, anchor="ls")
    d.text((1064, 830), "Next: take it slow.", font=F(19, 500), fill=TXT3, anchor="ls")
    return img


def mon_reader(f):
    img = mon_reader_base().copy()
    menubar(img, f, sc=MSC, app="Reader")
    if (f // 12) % 2 == 0:  # notebook cursor blink
        fill_rect(img, (1114, 50 + 36 + 70 + 150, 1116, 50 + 36 + 70 + 172), TXT)
    return img


# --- code corpus --------------------------------------------------------------
CODE_COMMENTS = ["TODO: understand this", "works, don't touch", "v2 API changed again", "deprecated since yesterday",
                 "copied from tutorial (16x)", "why does this work", "FIXME before next release (tomorrow)",
                 "temporary (permanent)", "new framework, same bugs", "read the migration guide later",
                 "it was faster in v1", "trust the process"]
CODE_DOCS = ["Learns AI so I don't have to.", "Reads everything. Remembers some of it.", "Do not run after 2 AM.",
             "Faster than me. Not hard.", "Updated for agentflow 0.1 (already old).", "Catches up. Hopefully."]


def _code_block(k, rng):
    kind = k % 6
    name = rng.choice(["read_papers", "watch_tutorial", "summarize", "update_skills", "check_releases", "migrate",
                       "retry", "plan_week", "rank_topics", "sync_memory", "fetch_changelog", "reflect", "benchmark"])
    c = rng.choice(CODE_COMMENTS)
    if kind == 0:
        return [f"    async def {name}_v{k}(self, topic, n={rng.choice([10, 50, 300])}):",
                f'        """{rng.choice(CODE_DOCS)}"""',
                "        items = await self.search(topic, limit=n)",
                "        for item in items:",
                "            if item.version > self.version:",
                f"                await self.migrate(item)  # {c}",
                "            self.memory.add(topic, await self.summarize(item))",
                "        return len(items)", ""]
    if kind == 1:
        return ["    @tool", f"    def {name}_{k}(self, query: str) -> list:",
                f"        # {c}",
                f"        results = self.client.query(query, top_k={rng.choice([5, 8, 16, 64])})",
                "        return [r for r in results if r.score > 0.7]", ""]
    if kind == 2:
        return [f"    def {name}_config_{k}(self):",
                "        return {",
                f'            "model": "latest-{rng.randint(2, 9)}.{rng.randint(0, 9)}",',
                f'            "temperature": {rng.choice([0.0, 0.2, 0.7])},',
                f'            "max_retries": {rng.choice([3, 5, 10, 99])},',
                f'            "speed": {rng.choice([2.0, 4.0, 16.0])},  # {c}',
                "        }", ""]
    if kind == 3:
        return [f"    async def safe_{name}_{k}(self, *args):",
                "        for attempt in range(self.max_retries):",
                "            try:",
                f"                return await self.{name}(*args)",
                "            except DeprecationError as e:",
                f"                log.warning(\"retry %d: %s\", attempt, e)  # {c}",
                "                await self.upgrade_everything()",
                "        raise CaughtUpError(\"never\")", ""]
    if kind == 4:
        return [f"class {rng.choice(['Skill', 'Topic', 'Paper', 'Release', 'Roadmap'])}Tracker{k}:",
                f'    """{rng.choice(CODE_DOCS)}"""',
                "",
                "    def __init__(self, items=None):",
                "        self.items = items or []",
                f"        self.version = {rng.randint(1, 48)}",
                "", ]
    return [f"    # --- {c} " + "-" * rng.randint(8, 30),
            f"    def is_caught_up_{k}(self) -> bool:",
            f"        return self.score >= self.latest_sota()  # {rng.choice(CODE_COMMENTS)}", ""]


@lru_cache(maxsize=1)
def code_corpus():
    lines = ['"""agent.py: an agent that learns AI for me."""', "import asyncio", "import logging",
             "from agentflow import Agent, Tool, Memory  # was: agentkit", "from agentflow.errors import DeprecationError",
             "", "log = logging.getLogger(\"agent\")", "", "",
             "class LearningAgent(Agent):", '    """Learns AI so I don\'t have to."""', "",
             '    def __init__(self, model="latest", speed=16.0):', "        super().__init__(model=model)",
             "        self.memory = Memory(max_items=10_000)", "        self.speed = speed  # 16x",
             "        self.skills, self.version = [], 1", ""]
    rng = random.Random(4812)
    k = 1
    while len(lines) < 600:
        lines += _code_block(k, rng)
        k += 1
    return lines


@lru_cache(maxsize=1)
def code_final():
    tail = ['    async def learn(self, subject, until="caught_up"):',
            "        while not self.is_caught_up(subject):",
            "            news = await self.check_releases(subject)",
            "            if news.breaking:",
            "                self.skills.clear()  # start over",
            "            await self.read_papers(subject, n=300)",
            "            await self.watch_tutorial(subject, speed=16.0)",
            "            self.version += 1",
            "        return self.skills", "", "",
            "def main():",
            '    agent = LearningAgent(model="latest", speed=16.0)',
            '    agent.add_tool(Tool("read_everything", read_everything))',
            '    agent.add_tool(Tool("never_sleep", never_sleep))',
            '    asyncio.run(agent.learn("AI", until="caught_up"))', "", "",
            'if __name__ == "__main__":',
            "    main()  # please work"]
    corp = code_corpus()
    head = corp[200:200 + 40 - len(tail)]
    return head + tail


VERSIONS = ["agent.py", "agent_v2.py", "agent_v3.py", "agent_v4_fixed.py", "agent_v5.py", "agent_v6_new_api.py",
            "agent_v7_final.py", "agent_v7_final_FINAL.py"]


def draw_editor_tabs(img, box, names, active, big=False):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    fill_rect(img, box, (17, 18, 22))
    fnt = F(22 if big else 14, 750 if big else 500)
    x = x0
    n = len(names)
    widths = []
    for i, nm in enumerate(names):
        w = fnt.getlength(nm) + (90 if big else 52)
        widths.append(w)
    total = sum(widths)
    avail = x1 - x0
    shrink = min(1.0, avail / total) if total else 1.0
    for i, nm in enumerate(names):
        w = widths[i] * (1.0 if i == active else shrink if shrink < 1 else 1.0)
        if i != active and shrink < 1:
            w = max(28, (avail - widths[active]) / max(1, n - 1))
        is_act = i == active
        fill_rect(img, (x, y0, x + w - 1, y1), (30, 32, 39) if is_act else (21, 22, 27))
        if is_act:
            fill_rect(img, (x, y0, x + w - 1, y0 + 3), BLUE)
        icon(img, "dot", x + 10, (y0 + y1) / 2 - 7, 14, (250, 204, 80) if is_act else (120, 110, 70))
        if w > 50:
            txt = ellipsize(nm, fnt, w - (64 if big else 40))
            d.text((x + 30, (y0 + y1) / 2), txt, font=fnt, fill=WHITE if is_act else TXT3, anchor="lm")
        x += w
        if x > x1:
            break


@lru_cache(maxsize=1)
def term_table():
    """Simulate the terminal for frames 161..268: installs, deprecations, chaos."""
    names = ["agentkit", "agentflow", "agentforge", "agentstack", "agentry", "agentverse", "agentcore", "agentloop",
             "agentmesh", "agentsmith-lite"]
    vers = ["0.0.1", "0.1", "0.2.0", "1.0rc1", "0.0.3", "2.0", "0.9b", "3.1", "0.4", "1.0"]
    k = 0
    while len(names) < 40:
        names.append(f"agent-framework-{47 + k}")
        vers.append(f"{47 + k}.0")
        k += 1
    rng = random.Random(161)
    lines = [("~/learn_ai $ pkg add agentkit", TXT)]
    table = {}
    bars = []           # (frame_completed, height)
    pi, prog = 0, 0.0
    for f in range(E["typing_start"], E["notif_do_that"]):
        s = spd(f)
        prog += 0.06 + 0.34 * s ** 1.4
        while prog >= 1.0:
            prog -= 1.0
            lines.append((f"installing {names[pi]} {vers[pi]} … ✓", GREEN))
            bars.append((f, 1.42 ** len(bars)))
            nxt = names[pi + 1]
            lines.append((f"{names[pi]} is deprecated → use {nxt}", AMBER))
            if s > 0.45 and rng.random() < 0.5 + 0.4 * s:
                lines.append((rng.choice(["ERROR: tutorial uses the v1 API", "WARNING: 37 peer dependencies changed",
                                          "ERROR: config format changed (again)", "WARNING: your knowledge is 2 days old",
                                          "ERROR: migration guide not found (1,400 pages)", "WARNING: new paper invalidates step 3"]),
                              RED if rng.random() < 0.5 else AMBER))
            lines.append((f"~/learn_ai $ pkg add {nxt}", TXT))
            pi += 1
        table[f] = (len(lines), prog, pi, len(bars))
    return lines, table, names, vers, bars


def draw_terminal(img, box, f):
    x0, y0, x1, y1 = box
    top = draw_window(img, box, "terminal — learn_ai", body=(12, 13, 16), bar=(22, 23, 28))
    d = ImageDraw.Draw(img)
    lines, table, names, vers, _ = term_table()
    n, prog, pi, _ = table[min(f, E["notif_do_that"] - 1)]
    fm = MONO(17)
    lh = 24
    cur = [(f"installing {names[pi]} {vers[pi]} …", TXT)]
    blocks = int(prog * 20)
    bar = "█" * blocks + "░" * (20 - blocks)
    cur.append((f"[{bar}] {int(prog * 100):3d}%", CYAN))
    shown = lines[:n] + cur
    maxl = int((y1 - top - 20) / lh)
    shown = shown[-maxl:]
    for i, (t, col) in enumerate(shown):
        d.text((x0 + 18, top + 22 + i * lh), ellipsize(t, fm, x1 - x0 - 30), font=fm, fill=col, anchor="lm")


def draw_bench(img, box, f):
    x0, y0, x1, y1 = box
    fill_rr(img, box, 12, (20, 22, 28))
    ring_rr(img, box, 12, 1, (40, 44, 54))
    d = ImageDraw.Draw(img)
    tracked(d, (x0 + 22, y0 + 34), "LEADERBOARD", F(14, 800), TXT2, 2)
    d.text((x1 - 22, y0 + 34), "avg score ↑", font=F(14, 500), fill=TXT3, anchor="rs")
    _, table, _, _, bars = term_table()
    nb = table[min(f, E["notif_do_that"] - 1)][3]
    hist = [(None, 1.0 / 1.42 ** k) for k in range(4, 0, -1)] + bars[:nb]
    vis = hist[-8:]
    if not vis:
        return
    last_f = vis[-1][0]
    grow = ease_out((f - last_f + 1) / 5) if last_f is not None else 1.0
    hmax_new = vis[-1][1]
    hmax_old = max(v[1] for v in vis[:-1]) if len(vis) > 1 else hmax_new
    hmax = lerp(hmax_old, hmax_new, grow) * 1.08
    gx0, gx1, gy0, gy1 = x0 + 30, x1 - 26, y0 + 56, y1 - 40
    for k in range(4):
        gy = gy1 - (gy1 - gy0) * k / 3
        fill_rect(img, (gx0, gy, gx1, gy + 1), (36, 40, 50))
    bw = (gx1 - gx0) / len(vis)
    for i, (bf, h) in enumerate(vis):
        newest = i == len(vis) - 1
        hh = (gy1 - gy0) * h / hmax * (grow if newest else 1.0)
        bx = gx0 + i * bw + bw * 0.18
        fill_rr(img, (bx, gy1 - max(3, hh), bx + bw * 0.64, gy1), 4, RED if newest else (70, 110, 190) if i >= len(vis) - 3 else (60, 66, 82))
        lab = "NEW" if newest else f"m{len(hist) - len(vis) + i + 1}"
        d.text((bx + bw * 0.32, gy1 + 20), lab, font=F(13, 800 if newest else 500), fill=RED if newest else TXT3, anchor="mm")


def mon_code(f):
    img = Image.new("RGB", (MW, MH), (14, 15, 19))
    d = ImageDraw.Draw(img)
    corp = code_corpus()
    phase = chv("typing_phase", f)
    nfl = phase * 1.7
    L = int(nfl)
    ver = min(len(VERSIONS) - 1, int(nfl / 11))
    # editor
    ex0, ex1 = 0, 960
    draw_editor_tabs(img, (ex0, MMENU, ex1, MMENU + 40), VERSIONS[:ver + 1], ver)
    fill_rect(img, (ex0, MMENU + 40, ex1, MMENU + 66), (24, 25, 31))
    d.text((ex0 + 16, MMENU + 53), f"learn_ai  ›  {VERSIONS[ver]}  ›  LearningAgent", font=F(13, 500), fill=TXT3, anchor="lm")
    fm = MONO(17)
    cw = fm.getlength("M")
    lh = 22
    cy0 = MMENU + 78
    vis = int((MH - 30 - cy0) / lh)
    top = max(0, L - vis + 4)
    fill_rect(img, (ex0, cy0 - 8, ex0 + 62, MH - 30), (17, 18, 23))
    for i in range(vis):
        li = top + i
        if li > L:
            break
        y = cy0 + i * lh + lh / 2
        line = corp[li % len(corp)]
        d.text((ex0 + 50, y), str(li + 1), font=MONO(14), fill=TXT3 if li != L else TXT, anchor="rm")
        if li == L:
            fill_rect(img, (ex0 + 62, y - lh / 2, ex1, y + lh / 2), (28, 31, 40))
            n = int((nfl - L) * len(line))
            draw_code_line(d, ex0 + 76, y, line, fm, cw, max_chars=n, anchor="lm")
            fill_rect(img, (ex0 + 76 + n * cw, y - 10, ex0 + 78 + n * cw, y + 10), WHITE)
        else:
            draw_code_line(d, ex0 + 76, y, line, fm, cw, anchor="lm")
    warn = int(chv("stress", f) * 180)
    fill_rect(img, (ex0, MH - 30, ex1, MH), (36, 84, 190))
    d.text((ex0 + 14, MH - 15), f"Ln {L + 1}, Col {int((nfl - L) * 40) + 1}   ·   Python   ·   ⚠ {warn}", font=F(14, 600), fill=WHITE, anchor="lm")
    d.text((ex1 - 14, MH - 15), "agentflow 0.1  (deprecated)", font=F(14, 600), fill=(255, 220, 160), anchor="rm")
    fill_rect(img, (ex1, MMENU, ex1 + 1, MH), LINE)
    draw_terminal(img, (972, MMENU + 10, 1590, 560), f)
    draw_bench(img, (972, 574, 1590, 890), f)
    # chaos: update popups pile up with speed
    s = spd(f)
    rng = frng("monpop", f // 3)
    for k in range(int(max(0, s - 0.5) * 10)):
        r2 = frng("monpopk", k)
        bx = 140 + r2.randint(0, 520)
        by = 160 + r2.randint(0, 520)
        fill_rr(img, (bx, by, bx + 300, by + 64), 10, (36, 40, 52))
        ring_rr(img, (bx, by, bx + 300, by + 64), 10, 1, (80, 90, 110))
        icon(img, "warn", bx + 14, by + 20, 24, AMBER)
        d.text((bx + 50, by + 32), r2.choice(["Update available", "New version!", "Restart required",
                                              "Breaking change", "Docs updated"]), font=F(18, 700), fill=WHITE, anchor="lm")
    _ = rng
    menubar(img, f, sc=MSC, app="Code")
    return img


@lru_cache(maxsize=1)
def mon_final():
    img = Image.new("RGB", (MW, MH), (14, 15, 19))
    d = ImageDraw.Draw(img)
    # older versions as small dim tabs, then the big active tab
    fnt = F(26, 800)
    label = "agent_v7_final_FINAL.py"
    tw = fnt.getlength(label) + 96
    fill_rect(img, (0, MMENU, MW, MMENU + 60), (17, 18, 22))
    old = VERSIONS[:-1]
    ow = 150
    for i, nm in enumerate(old):
        x = i * ow
        fill_rect(img, (x, MMENU + 8, x + ow - 2, MMENU + 60), (22, 23, 28))
        icon(img, "dot", x + 10, MMENU + 27, 12, (120, 110, 70))
        d.text((x + 28, MMENU + 34), ellipsize(nm, F(14, 500), ow - 40), font=F(14, 500), fill=TXT3, anchor="lm")
    tx = len(old) * ow + 6
    fill_rect(img, (tx, MMENU, tx + tw, MMENU + 60), (30, 32, 39))
    fill_rect(img, (tx, MMENU, tx + tw, MMENU + 4), BLUE)
    icon(img, "dot", tx + 18, MMENU + 21, 18, (250, 204, 80))
    d.text((tx + 48, MMENU + 31), label, font=fnt, fill=WHITE, anchor="lm")
    d.text((tx + tw - 24, MMENU + 31), "×", font=F(22, 400), fill=TXT3, anchor="mm")
    fm = MONO(16)
    cw = fm.getlength("M")
    lh = 18.4
    cy0 = MMENU + 70
    lines = code_final()
    first = 4812 - len(lines) + 1
    fill_rect(img, (0, cy0 - 10, 76, MH - 52), (17, 18, 23))
    for i, ln in enumerate(lines):
        y = cy0 + i * lh + lh / 2
        d.text((64, y), f"{first + i:,}", font=MONO(14), fill=TXT3, anchor="rm")
        draw_code_line(d, 92, y, ln, fm, cw, anchor="lm")
    # minimap of a very long file
    mx0, mx1 = MW - 128, MW - 16
    fill_rect(img, (mx0 - 8, MMENU + 60, MW, MH - 52), (17, 18, 23))
    rng = random.Random(9)
    for y in range(MMENU + 66, MH - 58, 2):
        w = rng.randint(10, 100) if rng.random() > 0.15 else 0
        ind = rng.choice([0, 0, 8, 16, 24])
        col = rng.choice([(70, 80, 100), (90, 70, 110), (60, 100, 80), (110, 100, 70)])
        if w:
            fill_rect(img, (mx0 + ind, y, mx0 + ind + w * 0.8, y + 1), col)
    fill_rect(img, (mx0 - 6, MH - 52 - 30, MW - 4, MH - 54), (120, 140, 180), 0.25)
    # status bar
    fill_rect(img, (0, MH - 52, MW, MH), (36, 84, 190))
    d.text((20, MH - 26), "4,812 lines  ·  9 hours", font=F(30, 820), fill=WHITE, anchor="lm")
    d.text((MW - 20, MH - 26), "Ln 4,812, Col 1   ·   Python   ·   ✓ all tests passed   ·   saved",
           font=F(17, 600), fill=(225, 235, 255), anchor="rm")
    menubar(img, E["notif_do_that"], sc=MSC, app="Code")
    return img


def mon_glitch(f):
    base = mon_final()
    age = f - E["notif_better"]
    rng = frng("monglitch", f)
    tint = [0.85, 0.5, 0.75, 0.35, 0.65, 0.3, 0.55, 0.25, 0.45, 0.3, 0.5, 0.25, 0.4, 0.3, 0.45, 0.3, 0.4, 0.35][min(age, 17)]
    img = Image.blend(base, Image.new("RGB", base.size, (200, 10, 20)), tint)
    if age < 2:
        img = Image.blend(img, Image.new("RGB", base.size, WHITE), 0.5 if age == 0 else 0.2)
    img = glitch(img, rng, n=6 + rng.randint(0, 8), maxshift=40 + rng.randint(0, 140), hmin=4, hmax=50,
                 split=rng.randint(3, 14))
    arr = np.asarray(img).copy()
    arr[::3] = (arr[::3] * 0.7).astype(np.uint8)
    img = Image.fromarray(arr)
    if age % 4 in (1, 2):
        d = ImageDraw.Draw(img)
        d.text((MW / 2 + rng.randint(-30, 30), MH / 2), "NEW MODEL.", font=F(170, 900), fill=(255, 210, 210), anchor="mm")
    return img


# --- telemetry (331-410) ------------------------------------------------------
def mon_telemetry(f):
    img = Image.new("RGB", (MW, MH), (4, 13, 21))
    arr = np.asarray(img).copy()
    arr[MMENU::40, :] = (8, 26, 38)
    arr[:, ::40] = (8, 26, 38)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    online = f >= E["button_press"]
    tracked(d, (48, 84), "AGENT TELEMETRY", F(22, 800), CYAN, 3)
    d.text((MW - 48, 84), "agent_v8  ·  node 0x2F  ·  uplink ok", font=F(17, 500), fill=(90, 150, 170), anchor="rs")
    t0, t1 = E["idea"], E["button_press"]
    prog = clamp((f - t0) / (t1 - t0))
    if not online:
        dots = "." * (1 + (f // 4) % 3)
        d.text((48, 196), "TRAINING AGENT" + dots, font=F(84, 820), fill=(220, 250, 255), anchor="ls")
        fill_rr(img, (48, 222, 1000, 240), 9, (14, 40, 56))
        fill_rr(img, (48, 222, 48 + 952 * prog, 240), 9, CYAN)
        d.text((1020, 240), f"{int(prog * 100)}%", font=F(30, 800), fill=CYAN, anchor="ls")
    else:
        age = f - t1
        sc = lerp(1.2, 1.0, ease_out((age + 1) / 4))
        fnt = F(int(130 * sc), 850)
        d.text((48, 222), "ONLINE", font=fnt, fill=CYAN, anchor="ls")
        x = 48 + fnt.getlength("ONLINE") + 40
        pulse = 0.5 + 0.5 * math.sin(age * 0.5)
        fill_circle(img, x + 40, 176, 130, CYAN, 0.15 + 0.15 * pulse)
        fill_circle(img, x + 40, 176, 76, CYAN)
        if f >= E["lean_back"]:
            d.text((x + 120, 196), "learning autonomously", font=F(30, 600), fill=(150, 220, 235), anchor="ls")
    # panels
    panels = [(48, 290, 780, 590, "LOSS"), (820, 290, 1552, 590, "THROUGHPUT  tok/s"), (48, 620, 780, 870, "LOG"),
              (820, 620, 1552, 870, "ACTIVATIONS")]
    for x0, y0, x1, y1, lab in panels:
        fill_rr(img, (x0, y0, x1, y1), 12, (6, 22, 34))
        ring_rr(img, (x0, y0, x1, y1), 12, 1.2, (20, 70, 90))
        tracked(d, (x0 + 20, y0 + 30), lab, F(14, 800), (90, 170, 190), 2)
    # loss curve: drawn progressively while training, then flat and calm
    x0, y0, x1, y1 = 68, 330, 760, 570
    n = 160
    upto = int(n * clamp((f - t0) / (t1 - t0) * 1.0 + (0.0 if not online else 1.0)))
    rng = random.Random(55)
    pts = []
    for i in range(n):
        v = math.exp(-i / 30) * 0.85 + 0.08 + rng.uniform(-0.03, 0.03) * math.exp(-i / 80)
        pts.append((x0 + (x1 - x0) * i / (n - 1), y1 - (y1 - y0) * v))
    if upto > 1:
        aa(img, CYAN, lambda dd, P, ss: dd.line([P(*p) for p in pts[:upto]], fill=255, width=int(3 * ss), joint="curve"),
           box=(60, 320, 770, 580))
        fill_circle(img, pts[upto - 1][0], pts[upto - 1][1], 12, WHITE)
    # throughput bars (scrolling)
    s = spd(f)
    bx0, by1 = 840, 570
    for i in range(48):
        k = f - 47 + i
        r = frng("tp", k).random()
        hh = 30 + 190 * clamp(0.25 + 0.75 * spd(k) * (0.6 + 0.4 * r))
        fill_rect(img, (bx0 + i * 14.6, by1 - hh, bx0 + i * 14.6 + 9, by1), CYAN if i == 47 else (30, 130, 160))
    d.text((1532, 330), f"{int(4000 + 52000 * s):,}", font=F(26, 800), fill=CYAN, anchor="rs")
    # log
    log_lines = ["compiling skills graph", "ingesting 1,204 papers", "watching tutorials @16x", "summarizing summaries",
                 "pruning outdated knowledge", "self-improving (iteration 3)", "allocating memory (∞)",
                 "deploying to node 0x2F", "agent online", "learning autonomously", "reading release notes",
                 "ranking 847 skills", "drafting roadmap…"]
    nlog = int(clamp((f - t0) / (E["notif_roadmap"] - t0)) * (len(log_lines) - 1)) + 1
    for i, ln in enumerate(log_lines[:nlog][-8:]):
        d.text((68, 668 + i * 25), f"[{clock_at(f)}]  {ln}", font=MONO(15), fill=(120, 200, 215), anchor="lm")
    # activations grid
    for gy in range(6):
        for gx in range(24):
            r = frng("act", gx, gy, f // 2).random()
            a = clamp(0.15 + r * (0.4 + 0.6 * s))
            fill_rect(img, (842 + gx * 29, 664 + gy * 32, 842 + gx * 29 + 22, 664 + gy * 32 + 24), CYAN, a * 0.8)
    menubar(img, f, sc=MSC, app="Telemetry", bg=(3, 10, 16))
    return img


# --- printing (411-491) -------------------------------------------------------
PRINT_ROW = 34
PRINT_ROWS_PAGE = 29
PRINT_PAGE_H = PRINT_ROW * PRINT_ROWS_PAGE


@lru_cache(maxsize=1)
def print_feed_table():
    tab, vel, acc = {}, {}, 0.0
    for f in range(E["roadmap_open"], E["notif_obsolete"] + 1):
        v = 4 + 1250 * spd(f) ** 2.2 if f >= E["roadmap_open"] + 2 else 0.0
        acc += v
        tab[f], vel[f] = acc, v
    return tab, vel


def paper_strip(off, h, w=700):
    """Printed paper strip, content scrolled by `off` px (content moves down as it feeds)."""
    items, _ = roadmap_items()
    img = Image.new("RGB", (w, h), (244, 243, 238))
    d = ImageDraw.Draw(img)
    fnt = F(19, 550)
    # paper coordinate p = off - y : content printed earlier is lower on screen
    p_top, p_bot = off - h, off
    r0 = int(max(0, p_top) // PRINT_ROW)
    r1 = int(p_bot // PRINT_ROW) + 1
    for r in range(r0, r1 + 1):
        y = off - r * PRINT_ROW
        pg, rp = divmod(r, PRINT_ROWS_PAGE)
        if rp < 2:
            if rp == 0:
                for x in range(10, w - 10, 18):
                    d.line((x, y, x + 9, y), fill=(170, 170, 165), width=2)
                d.text((w / 2, y - 22), f"— page {pg + 1} —", font=F(15, 600), fill=(120, 120, 120), anchor="mm")
            continue
        idx = pg * (PRINT_ROWS_PAGE - 2) + rp - 2
        if idx >= len(items):
            idx %= len(items)
        d.rectangle((40, y - 13, 56, y + 3), outline=(60, 60, 64), width=2)
        d.text((72, y), f"{idx + 1}.  {items[idx]}", font=fnt, fill=(40, 40, 46), anchor="ls")
    return img


def mon_print(f, freeze=False):
    img = Image.new("RGB", (MW, MH), (12, 13, 17))
    d = ImageDraw.Draw(img)
    tab, vel = print_feed_table()
    ff = min(f, E["notif_obsolete"] - 1)
    off = tab.get(ff, 0.0) + 900
    v = 0.0 if freeze else vel.get(ff, 0.0)
    page = int((off - 900) // PRINT_PAGE_H) + 1
    dots = "…"
    d.text((80, 150), "PRINTING ROADMAP" + dots, font=fit("PRINTING ROADMAP" + dots, 680, 76, 820), fill=WHITE, anchor="ls")
    d.text((84, 214), f"page {page} of ∞", font=F(46, 700), fill=CYAN, anchor="ls")
    d.text((84, 262), f"{T.ROADMAP_TOTAL} skills  ·  sheets used: {page}  ·  toner 12%", font=F(20, 500), fill=TXT3, anchor="ls")
    # printer slot
    sx0, sx1, sy = 820, 1540, 120
    fill_rr(img, (sx0 - 20, sy - 40, sx1 + 20, sy + 30), 18, (34, 36, 44))
    fill_rr(img, (sx0, sy - 6, sx1, sy + 10), 6, (6, 6, 8))
    fill_circle(img, sx1 - 10, sy - 24, 12, GREEN if (f // 3) % 2 else (30, 120, 60))
    strip = paper_strip(off, MH - sy, sx1 - sx0 - 40)
    if v > 6:
        sharp = np.asarray(strip, np.float32)
        bl = vblur_arr(sharp, min(v * 0.8, 160))
        k = clamp((v - 6) / 100) * 0.75
        strip = Image.fromarray((sharp * (1 - k) + bl * k).clip(0, 255).astype(np.uint8))
    img.paste(strip, (sx0 + 20, sy + 4))
    # shade under the slot
    g = Image.fromarray((np.linspace(140, 0, 40)[:, None] * np.ones((1, strip.width))).astype(np.uint8))
    img.paste((0, 0, 0), (sx0 + 20, sy + 4, sx0 + 20 + strip.width, sy + 44), g)
    # spinner + progress on the left
    fill_rr(img, (84, 330, 700, 350), 10, (34, 38, 48))
    seg = (f * 18) % 760 - 160
    fill_rr(img, (84 + max(0, seg), 330, 84 + min(616, seg + 160), 350), 10, CYAN) if seg + 160 > 0 else None
    d.text((84, 400), "Estimated time remaining:", font=F(24, 500), fill=TXT2, anchor="ls")
    d.text((84, 450), "calculating…", font=F(34, 700), fill=WHITE, anchor="ls")
    menubar(img, f, sc=MSC, app="Print")
    return img


@lru_cache(maxsize=1)
def mon_obsolete_base():
    img = dim(gray(mon_print(E["notif_obsolete"] - 1, freeze=True)), 0.4)
    d = ImageDraw.Draw(img)
    fnt = F(190, 900)
    w = fnt.getlength("OBSOLETE") + 120
    x0, y0 = (MW - w) / 2, MH / 2 - 150
    fill_rr(img, (x0, y0, x0 + w, y0 + 300), 30, (20, 20, 22), 0.7)
    ring_rr(img, (x0, y0, x0 + w, y0 + 300), 30, 8, (175, 178, 184))
    d.text((MW / 2, MH / 2 + 8), "OBSOLETE", font=fnt, fill=(190, 193, 198), anchor="mm")
    return img


def mon_screensaver(f):
    img = Image.new("RGB", (MW, MH), (5, 6, 8))
    d = ImageDraw.Draw(img)
    t = f - B["screensaver"]
    cx = MW / 2 + math.sin(t * 0.013) * 260
    cy = MH / 2 + math.sin(t * 0.009 + 1.3) * 140
    fill_circle(img, cx, cy - 150, 44, (40, 52, 72))
    fill_circle(img, cx, cy - 150, 22, (5, 6, 8))
    d.text((cx, cy + 10), "KEEP UP.", font=F(160, 820), fill=(54, 66, 90), anchor="mm")
    d.text((cx, cy + 112), "a friendly reminder from your learning platform", font=F(22, 500), fill=(36, 44, 58), anchor="mm")
    return img


def monitor_frame(f):
    if f < E["typing_start"]:
        return mon_reader(f)
    if f < B["code_done"]:
        return mon_code(f)
    if f < E["notif_better"]:
        return mon_final().copy()
    if f < B["builder_start"]:
        return mon_glitch(f)
    if f < E["roadmap_open"]:
        return mon_telemetry(f)
    if f < E["notif_obsolete"]:
        return mon_print(f)
    if f < B["screensaver"]:
        return mon_obsolete_base().copy()
    if f < B["screensaver"] + 4:  # dip through black into the screensaver
        k = (f - B["screensaver"] + 1) / 5
        if k < 0.5:
            return dim(mon_obsolete_base(), 1 - 2 * k)
        return dim(mon_screensaver(f), (k - 0.5) * 2)
    return mon_screensaver(f)


# =============================================================================
# NOTEBOOK  (1024 x 1024 PNG)  -- procedural single-stroke handwriting
# =============================================================================
NW = 1024
NB_RULE0, NB_RULE_DY, NB_MARGIN = 150, 52, 132
INK = np.array([30, 42, 104], np.float32)


def _L(*pts):
    return ("L", pts)


def _C(*pts):
    return ("C", pts)


def _D(x, y):
    return ("D", ((x, y),))


# Capital letters as pen strokes in cap units (x right, y down, 0 = cap line, 1 = baseline).
# Each glyph: (advance, [stroke, ...]); stroke = [piece, ...]; piece = L(polyline) | C(smooth curve) | D(dot).
GLYPHS = {
    "A": (0.74, [[_L((0.0, 1.0), (0.37, 0.0), (0.74, 1.0))], [_L((0.15, 0.63), (0.6, 0.6))]]),
    "B": (0.60, [[_L((0.0, 0.0), (0.0, 1.0))],
                 [_C((0.0, 0.02), (0.34, 0.0), (0.52, 0.1), (0.5, 0.3), (0.3, 0.46), (0.04, 0.48)),
                  _C((0.04, 0.48), (0.4, 0.5), (0.6, 0.66), (0.56, 0.88), (0.3, 1.0), (0.0, 0.98))]]),
    "C": (0.66, [[_C((0.64, 0.15), (0.45, 0.0), (0.2, 0.04), (0.03, 0.3), (0.03, 0.68), (0.2, 0.96), (0.45, 1.0), (0.66, 0.86))]]),
    "D": (0.68, [[_L((0.0, 0.0), (0.0, 1.0))],
                 [_C((0.0, 0.02), (0.34, 0.02), (0.6, 0.18), (0.68, 0.5), (0.6, 0.82), (0.34, 0.98), (0.0, 0.98))]]),
    "E": (0.58, [[_L((0.58, 0.0), (0.0, 0.02), (0.0, 1.0), (0.6, 0.98))], [_L((0.0, 0.5), (0.46, 0.49))]]),
    "F": (0.56, [[_L((0.56, 0.0), (0.0, 0.02), (0.0, 1.0))], [_L((0.0, 0.5), (0.44, 0.49))]]),
    "G": (0.70, [[_C((0.64, 0.16), (0.45, 0.0), (0.18, 0.05), (0.02, 0.35), (0.04, 0.7), (0.22, 0.97), (0.48, 1.0), (0.68, 0.84)),
                  _L((0.68, 0.84), (0.68, 0.57), (0.42, 0.57))]]),
    "H": (0.68, [[_L((0.0, 0.0), (0.0, 1.0))], [_L((0.68, 0.0), (0.68, 1.0))], [_L((0.0, 0.5), (0.68, 0.49))]]),
    "I": (0.34, [[_L((0.17, 0.0), (0.17, 1.0))], [_L((0.0, 0.0), (0.34, 0.0))], [_L((0.0, 1.0), (0.34, 1.0))]]),
    "J": (0.50, [[_C((0.48, 0.0), (0.47, 0.6), (0.4, 0.92), (0.2, 1.0), (0.02, 0.86))]]),
    "K": (0.62, [[_L((0.0, 0.0), (0.0, 1.0))], [_L((0.6, 0.0), (0.02, 0.56))], [_L((0.17, 0.42), (0.62, 1.0))]]),
    "L": (0.54, [[_L((0.0, 0.0), (0.0, 1.0), (0.55, 0.98))]]),
    "M": (0.84, [[_L((0.0, 1.0), (0.04, 0.0), (0.42, 0.68), (0.8, 0.0), (0.84, 1.0))]]),
    "N": (0.70, [[_L((0.0, 1.0), (0.0, 0.0), (0.7, 1.0), (0.7, 0.0))]]),
    "O": (0.74, [[_C((0.42, 0.0), (0.12, 0.08), (0.0, 0.45), (0.1, 0.86), (0.4, 1.0), (0.68, 0.88), (0.76, 0.5), (0.66, 0.12),
                     (0.44, 0.0), (0.3, 0.04))]]),
    "P": (0.58, [[_L((0.0, 0.0), (0.0, 1.0))],
                 [_C((0.0, 0.02), (0.36, 0.0), (0.58, 0.12), (0.58, 0.34), (0.38, 0.5), (0.02, 0.52))]]),
    "Q": (0.76, [[_C((0.42, 0.0), (0.12, 0.08), (0.0, 0.45), (0.1, 0.86), (0.4, 1.0), (0.68, 0.88), (0.76, 0.5), (0.66, 0.12),
                     (0.44, 0.0), (0.3, 0.04))], [_L((0.46, 0.7), (0.8, 1.06))]]),
    "R": (0.62, [[_L((0.0, 0.0), (0.0, 1.0))],
                 [_C((0.0, 0.02), (0.36, 0.0), (0.58, 0.12), (0.58, 0.32), (0.38, 0.48), (0.04, 0.5)),
                  _L((0.04, 0.5), (0.62, 1.0))]]),
    "S": (0.60, [[_C((0.58, 0.13), (0.42, 0.0), (0.15, 0.02), (0.03, 0.2), (0.12, 0.38), (0.32, 0.47), (0.52, 0.58),
                     (0.6, 0.78), (0.48, 0.96), (0.22, 1.0), (0.0, 0.88))]]),
    "T": (0.70, [[_L((0.0, 0.02), (0.7, 0.0))], [_L((0.35, 0.01), (0.35, 1.0))]]),
    "U": (0.66, [[_C((0.0, 0.0), (0.0, 0.55), (0.06, 0.88), (0.33, 1.0), (0.6, 0.88), (0.66, 0.55), (0.66, 0.0))]]),
    "V": (0.70, [[_L((0.0, 0.0), (0.35, 1.0), (0.7, 0.0))]]),
    "W": (0.96, [[_L((0.0, 0.0), (0.22, 1.0), (0.48, 0.3), (0.74, 1.0), (0.96, 0.0))]]),
    "X": (0.64, [[_L((0.0, 0.0), (0.64, 1.0))], [_L((0.64, 0.0), (0.0, 1.0))]]),
    "Y": (0.66, [[_L((0.0, 0.0), (0.33, 0.5))], [_L((0.66, 0.0), (0.33, 0.5), (0.33, 1.0))]]),
    "Z": (0.62, [[_L((0.0, 0.02), (0.62, 0.0), (0.0, 1.0), (0.64, 0.98))]]),
    "!": (0.14, [[_L((0.07, 0.0), (0.06, 0.7))], [_D(0.06, 0.95)]]),
    "?": (0.56, [[_C((0.0, 0.22), (0.12, 0.04), (0.32, 0.0), (0.52, 0.12), (0.52, 0.3), (0.3, 0.46), (0.27, 0.7))],
                 [_D(0.27, 0.95)]]),
    ".": (0.12, [[_D(0.06, 0.95)]]),
    ",": (0.12, [[_L((0.08, 0.9), (0.02, 1.12))]]),
    "-": (0.40, [[_L((0.02, 0.55), (0.38, 0.53))]]),
}


KERN = {("A", "T"): -0.16, ("T", "A"): -0.16, ("L", "T"): -0.14, ("L", "A"): -0.06, ("F", "A"): -0.12,
        ("P", "A"): -0.08, ("A", "V"): -0.12, ("V", "A"): -0.12, ("T", "E"): -0.04, ("L", "Y"): -0.1, ("A", "Y"): -0.1}


def _catmull(pts, steps=18):
    P = np.array(pts, np.float64)
    if len(P) < 2:
        return P
    P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    t = np.linspace(0, 1, steps, endpoint=False)[:, None]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 +
                          (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2][None])
    return np.vstack(out)


def _piece_pts(kind, pts):
    if kind == "C":
        return _catmull(pts)
    if kind == "D":
        x, y = pts[0]
        a = np.linspace(0.6, 0.6 + 2 * math.pi * 1.25, 26)
        r = 0.028 + 0.012 * np.linspace(1, 0, 26)
        return np.stack([x + r * np.cos(a), y + r * np.sin(a)], 1)
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) * 40))
        t = np.linspace(0, 1, n, endpoint=False)[:, None]
        out.append(np.array([x0, y0]) * (1 - t) + np.array([x1, y1]) * t)
    out.append(np.array([pts[-1]], np.float64))
    return np.vstack(out)


def _resample(pts, step=1.0):
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    L = s[-1]
    if L < 1e-6:
        return pts[:1].repeat(2, 0), 0.0
    n = max(2, int(L / step) + 1)
    u = np.linspace(0, L, n)
    return np.stack([np.interp(u, s, pts[:, 0]), np.interp(u, s, pts[:, 1])], 1), L


def _finish_stroke(pts_px, st, rng, taper_end=0.45, land=6.0, dot=False):
    """Resample, wobble, round corners, and attach pressure (width/alpha) arrays."""
    pts, L = _resample(pts_px, 1.0)
    n = len(pts)
    s = np.linspace(0, L, n)
    wob = st.get("wobble", 0.8)
    for axis in (0, 1):
        disp = np.zeros(n)
        for lam, amp in ((38, 0.5), (90, 0.8), (190, 1.0)):
            disp += amp * np.sin(2 * math.pi * s / lam + rng.uniform(0, 6.28))
        pts[:, axis] += disp * wob / 1.6
    win = int(2 + 3 * st.get("messy", 0.0))
    if n > 2 * win + 2 and not dot:
        k = np.ones(win * 2 + 1) / (win * 2 + 1)
        for axis in (0, 1):
            col = np.pad(pts[:, axis], win, mode="edge")
            sm = np.convolve(col, k, mode="valid")
            pts[win:-win, axis] = sm[win:-win]
    landing = np.clip(s / land, 0, 1) ** 0.6 if not dot else np.ones(n)
    tail = 1 - taper_end * np.clip((s - (L - 14)) / 14, 0, 1) if L > 20 else np.ones(n)
    noise = np.zeros(n)
    for lam in (23, 61):
        noise += np.sin(2 * math.pi * s / lam + rng.uniform(0, 6.28))
    p = landing * tail * (0.9 + 0.05 * noise)
    width = st["width"] * st.get("press", 1.0) * (0.55 + 0.45 * p)
    alpha = np.clip((0.62 + 0.5 * p) * min(1.0, 0.85 + 0.15 * st.get("press", 1.0)), 0, 1)
    skip = np.sin(2 * math.pi * s / 37.0 + rng.uniform(0, 6.28)) > 0.93  # occasional ballpoint skip
    alpha = np.where(skip, alpha * 0.8, alpha)
    alpha = np.round(alpha * 12) / 12  # few distinct levels: smaller PNGs
    return dict(pts=pts, w=width, a=alpha, L=L)


def hand_text(text, st):
    """Lay out `text` in the handwriting font. Returns (strokes, bbox)."""
    rng = random.Random(st["seed"])
    raw = []        # (unit-space dense pts, is_dot)
    x = 0.0
    for ci, ch in enumerate(text):
        if ch == " ":
            x += st.get("space", 0.42) + rng.uniform(-0.04, 0.04)
            continue
        adv, strokes = GLYPHS[ch]
        sj = 1 + rng.uniform(-1, 1) * st.get("sizej", 0.05)
        by = rng.uniform(-1, 1) * st.get("basej", 0.03)
        lr = math.radians(rng.uniform(-1, 1) * st.get("rotj", 2.0))
        cx = adv / 2
        for stroke in strokes:
            pts = np.vstack([_piece_pts(k, p) for k, p in stroke])
            is_dot = all(k == "D" for k, _ in stroke)
            # overshoot / sloppiness on stroke ends for messy writing
            u = pts.copy()
            u[:, 0] = (u[:, 0] - cx) * sj
            u[:, 1] = (u[:, 1] - 1.0) * sj
            ca, sa = math.cos(lr), math.sin(lr)
            u = np.stack([u[:, 0] * ca - u[:, 1] * sa, u[:, 0] * sa + u[:, 1] * ca], 1)
            u[:, 0] += x + cx * sj
            u[:, 1] += 1.0 + by
            raw.append((u, is_dot))
        x += adv * sj + st.get("track", 0.17) + rng.uniform(-1, 1) * st.get("trackj", 0.03)
        if ci + 1 < len(text):
            x += KERN.get((ch, text[ci + 1]), 0.0)
    total = x - st.get("track", 0.17)
    cap = st["cap"]
    if st.get("max_w") and total * cap > st["max_w"]:
        cap = st["max_w"] / total
    rot = math.radians(st.get("rot", 0.0))
    cr, sr = math.cos(rot), math.sin(rot)
    x0, base = st["x0"], st["base"]
    slant = st.get("slant", 0.08)
    out = []
    for u, is_dot in raw:
        X = (u[:, 0] + slant * (1 - u[:, 1])) * cap
        Y = (u[:, 1] - 1) * cap
        P = np.stack([x0 + X * cr - Y * sr, base + X * sr + Y * cr], 1)
        out.append(_finish_stroke(P, st, rng, taper_end=0.5, land=4.0 + 4.0 * st.get("press", 1.0), dot=is_dot))
    allp = np.vstack([s_["pts"] for s_ in out])
    bbox = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    return out, bbox


def hand_mark(points, st, taper=0.8, curve=True):
    rng = random.Random(st["seed"])
    P = _catmull(points, 24) if curve else _piece_pts("L", points)
    return [_finish_stroke(np.asarray(P, np.float64), st, rng, taper_end=taper, land=3.0)]


def scribble_strike(bbox, seed, passes=3, width=4.0):
    x0, y0, x1, y1 = bbox
    rng = random.Random(seed)
    ym = (y0 + y1) / 2
    hh = (y1 - y0)
    pts = [(x0 - 10, ym + rng.uniform(-0.2, 0.1) * hh)]
    for i in range(passes * 2):
        x = x1 + 10 if i % 2 == 0 else x0 - 6
        pts.append((x + rng.uniform(-8, 8), ym + (rng.uniform(-0.35, 0.35)) * hh))
    st = dict(seed=seed, width=width, press=1.2, wobble=1.0, messy=0.6)
    return hand_mark(pts, st, taper=0.6, curve=False)


def scribble_circle(bbox, seed, width=4.0):
    x0, y0, x1, y1 = bbox
    rng = random.Random(seed)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2 + 30, (y1 - y0) / 2 + 24
    a0 = math.radians(200)
    pts = []
    for i in range(30):
        a = a0 + 2 * math.pi * 1.12 * i / 29
        k = 1 + 0.06 * math.sin(i * 0.9 + rng.uniform(0, 1)) + 0.04 * i / 29
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    st = dict(seed=seed, width=width, press=1.15, wobble=1.2, messy=0.5)
    return hand_mark(pts, st, taper=0.7)


@lru_cache(maxsize=1)
def notebook_script():
    """All writing on the page, in order, each with its frame window."""
    R = lambda k: NB_RULE0 + NB_RULE_DY * k  # noqa: E731
    a0, span = B["scrib_start"], B["scrib_end"] - B["scrib_start"] + 1

    def W(s_, e_):
        # sub-windows authored on a 47-frame reference span, rescaled to the real S08-S09 span
        return a0 + round((s_ - 186) / 47 * span), a0 + round((e_ - 186 + 1) / 47 * span) - 1
    jobs = []
    st1 = dict(seed=11, cap=132, x0=170, base=R(3), slant=0.06, width=6.2, press=1.0, wobble=0.7, messy=0.0,
               sizej=0.03, basej=0.02, rotj=1.5, track=0.2, max_w=780)
    s1, b1 = hand_text("LEARN AI.", st1)
    jobs.append((s1, E["write1_start"], E["write1_end"]))
    # confident underline swoosh
    ux0, ux1, uy = b1[0] - 14, b1[2] + 40, R(3) + 30
    ul = hand_mark([(ux0, uy + 4), (ux0 + 0.3 * (ux1 - ux0), uy + 8), (ux0 + 0.65 * (ux1 - ux0), uy + 4),
                    (ux1 - 30, uy - 6), (ux1, uy - 22)],
                   dict(seed=12, width=6.6, press=1.1, wobble=0.6, messy=0.2), taper=0.92)
    jobs.append((ul, E["underline1_start"], E["underline1_end"]))
    st2 = dict(seed=21, cap=96, x0=150, base=R(6), slant=0.30, width=7.2, press=1.3, wobble=1.6, messy=0.8,
               sizej=0.09, basej=0.06, rotj=4.5, track=0.14, trackj=0.05, rot=-2.5, max_w=790)
    s2, _ = hand_text("LEARN AI FASTER.", st2)
    jobs.append((s2, E["write2_start"], E["write2_end"]))
    # frantic tiny scribbles lower on the page (186-232)
    small = dict(width=4.6, press=1.25, wobble=1.3, messy=0.8, sizej=0.1, basej=0.07, rotj=6, track=0.13, trackj=0.05,
                 slant=0.28)
    s3, b3 = hand_text("FASTER!!", dict(small, seed=31, cap=58, x0=560, base=R(8) + 4, rot=-6))
    jobs.append((s3, *W(186, 192)))
    u3 = hand_mark([(b3[0] - 4, b3[3] + 12), (b3[2] + 10, b3[3] + 4)], dict(seed=32, width=4.4, press=1.3, wobble=1, messy=0.6), 0.7, False)
    u3b = hand_mark([(b3[0] + 6, b3[3] + 24), (b3[2] + 16, b3[3] + 15)], dict(seed=33, width=4.2, press=1.3, wobble=1, messy=0.6), 0.7, False)
    jobs.append((u3 + u3b, *W(193, 196)))
    s4, _ = hand_text("SLEEP LATER", dict(small, seed=41, cap=44, x0=168, base=R(9) + 18, rot=3))
    jobs.append((s4, *W(197, 205)))
    s5, b5 = hand_text("WEEKEND", dict(small, seed=51, cap=40, x0=700, base=R(11) - 14, rot=-2))
    jobs.append((s5, *W(206, 210)))
    jobs.append((scribble_strike(b5, 52, passes=3, width=4.4), *W(211, 213)))
    s6, b6 = hand_text("AGENTS??", dict(small, seed=61, cap=60, x0=200, base=R(12) + 30, rot=-4, width=5.0))
    jobs.append((s6, *W(214, 221)))
    jobs.append((scribble_circle(b6, 62, width=4.4), *W(222, 226)))
    s7, b7 = hand_text("BREAK", dict(small, seed=71, cap=38, x0=680, base=R(14) + 6, rot=4))
    jobs.append((s7, *W(227, 229)))
    jobs.append((scribble_strike(b7, 72, passes=2, width=4.6), *W(230, 232)))
    return jobs


def _visible_strokes(strokes, start, end, f):
    """True write-on: strokes drawn in order with pen-lift travel time between them."""
    if f < start:
        return []
    durs, prev_end = [], None
    for s_ in strokes:
        gap = 0.0 if prev_end is None else 0.3 * float(np.hypot(*(s_["pts"][0] - prev_end))) + 14.0
        durs.append((gap, s_["L"]))
        prev_end = s_["pts"][-1]
    total = sum(g + l for g, l in durs)
    t = total * clamp((f - start + 1) / (end - start + 1))
    out = []
    for s_, (g, l) in zip(strokes, durs):
        if t <= g:
            break
        t -= g
        if t >= l:
            out.append((s_, len(s_["pts"])))
            t -= l
        else:
            tau = t / l
            lam = 0.65 * tau + 0.35 * smooth(tau)
            out.append((s_, max(1, int(lam * len(s_["pts"])))))
            break
    return out


@lru_cache(maxsize=1)
def paper_arr():
    rng = np.random.default_rng(1024)
    base = np.array([241, 234, 215], np.float32)

    def mottle(n, amp):
        a = rng.normal(0, 1, (n, n)).astype(np.float32)
        im = Image.fromarray(a).resize((NW, NW), Image.BICUBIC)
        a = np.asarray(im)
        return a / a.std() * amp

    m = mottle(12, 1.6)
    yy, xx = np.mgrid[0:NW, 0:NW].astype(np.float32)
    vign = (((xx - NW / 2) / NW) ** 2 + ((yy - NW / 2) / NW) ** 2) * -14
    arr = base[None, None, :] + (m + vign)[..., None] * np.array([1.0, 1.0, 1.1], np.float32)
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    # specks + fibres (sparse: keeps PNG frames small)
    sp = Image.new("L", (NW, NW), 0)
    d = ImageDraw.Draw(sp)
    r2 = random.Random(77)
    for _ in range(650):
        x, y = r2.uniform(0, NW), r2.uniform(0, NW)
        r = r2.uniform(0.6, 1.4)
        d.ellipse((x - r, y - r, x + r, y + r), fill=int(r2.uniform(15, 45)))
    for _ in range(110):
        x, y = r2.uniform(0, NW), r2.uniform(0, NW)
        a = r2.uniform(0, 6.28)
        L = r2.uniform(6, 26)
        d.line((x, y, x + L * math.cos(a), y + L * math.sin(a) * 0.4), fill=int(r2.uniform(10, 26)), width=1)
    arr = np.asarray(img, np.float32) * (1 - np.asarray(sp, np.float32)[..., None] / 255 * 0.28)
    # rules + margin
    rule = np.array([150, 182, 226], np.float32)
    for k in range(17):
        y = NB_RULE0 + NB_RULE_DY * k
        if y > NW - 20:
            break
        for dy, a in ((-1, 0.25), (0, 0.62), (1, 0.55), (2, 0.15)):
            arr[y + dy] = arr[y + dy] * (1 - a) + rule * a
    red = np.array([226, 116, 118], np.float32)
    for x in (NB_MARGIN, NB_MARGIN + 1, NB_MARGIN + 2):
        a = 0.65 if x == NB_MARGIN + 1 else 0.35
        arr[:, x] = arr[:, x] * (1 - a) + red * a
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    dd = ImageDraw.Draw(img)
    dd.text((NW - 250, 104), "DATE", font=F(15, 600), fill=(140, 160, 196), anchor="ls")
    dd.line((NW - 200, 104, NW - 60, 104), fill=(150, 170, 206), width=2)
    return np.asarray(img, np.float32)


def notebook_frame(f, ss=3):
    mask = Image.new("L", (NW * ss, NW * ss), 0)
    d = ImageDraw.Draw(mask)
    for strokes, a, b in notebook_script():
        for s_, n in _visible_strokes(strokes, a, b, f):
            P = s_["pts"][:n] * ss
            R = s_["w"][:n] * ss / 2
            A = (s_["a"][:n] * 255).astype(int)
            for (x, y), r, al in zip(P, R, A):
                d.ellipse((x - r, y - r, x + r, y + r), fill=int(al))
    m = np.asarray(mask.reduce(ss), np.float32)[..., None] / 255.0
    arr = paper_arr() * (1 - m) + INK * m
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


# =============================================================================
# DISPLAY  (1920 x 640)  -- stadium LED jumbotron
# =============================================================================
DW, DH, PITCH = 1920, 640, 8               # pitch 8 = one LED per JPEG block: crisp grid, small files
GW, GH = DW // PITCH, DH // PITCH          # 240 x 80 LEDs
VW, VH = 1536, 512                          # content canvas (box-filtered down to the LED grid)
VS = VW / GW                                # canvas px per LED
LED_AMBER = (255, 170, 40)
LED_WHITE = (255, 236, 210)
LED_RED = (255, 44, 28)


@lru_cache(maxsize=1)
def led_dot():
    yy, xx = np.mgrid[0:PITCH, 0:PITCH].astype(np.float32)
    c = (PITCH - 1) / 2
    d = np.sqrt((xx - c) ** 2 + (yy - c) ** 2)
    hard = np.clip(1.55 - d / (PITCH * 0.34), 0, 1) ** 1.2
    soft = np.exp(-(d / (PITCH * 0.3)) ** 2)
    tile = 0.5 * hard + 0.5 * soft
    return np.tile(tile, (GH, GW)).astype(np.float32)


def led_compose(content, f, brightness=1.0):
    """content: RGB image VW x VH -> LED panel image DW x DH."""
    led = np.asarray(content.resize((GW, GH), Image.BOX), np.float32) / 255.0
    led = np.round(led * 24) / 24 * brightness           # finite LED drive levels
    rows = 0.94 + 0.06 * (np.arange(GH) % 2)[:, None, None]
    band = 1 + 0.05 * np.exp(-(((np.arange(GH) - (f * 3.1) % (GH + 40) + 20) / 9.0) ** 2))[:, None, None]
    led = led * rows * band
    up = np.repeat(np.repeat(led, PITCH, 0), PITCH, 1)
    out = (up * 1.35 + 0.006) * led_dot()[..., None]
    bloom = Image.fromarray((led.clip(0, 1) * 255).astype(np.uint8)).resize((DW // 8, DH // 8), Image.BILINEAR)
    bloom = np.asarray(bloom.filter(ImageFilter.GaussianBlur(2.2)).resize((DW, DH), Image.BILINEAR), np.float32) / 255.0
    out = out + bloom * 0.35
    return Image.fromarray((out.clip(0, 1) * 255).astype(np.uint8))


def disp_counter(f):
    """MODELS RELEASED TODAY counter: starts at 1,204 and ticks faster and faster."""
    n, acc = 1204, 0.0
    for k in range(SEQUENCES["display"][0], f + 1):
        acc += 0.45 + 0.004 * (k - SEQUENCES["display"][0]) + 0.8 * spd(k)
        while acc >= 1:
            acc -= 1
            n += 1
    return n


def disp_idle(f):
    img = Image.new("RGB", (VW, VH), BLACK)
    d = ImageDraw.Draw(img)
    d.text((VW / 2, 228), "KEEP UP.", font=F(300, 900), fill=LED_AMBER, anchor="mm")
    fill_rect(img, (120, 380, VW - 120, 386), LED_AMBER, 0.5)
    d.text((VW / 2, 448), f"MODELS RELEASED TODAY: {disp_counter(f):,}", font=F(68, 800), fill=LED_WHITE, anchor="mm")
    return img


def disp_congrats(f):
    img = Image.new("RGB", (VW, VH), BLACK)
    d = ImageDraw.Draw(img)
    age = f - E["pa_start"]
    # cheap wipe-in
    wipe = clamp((age + 1) / 4)
    rng = random.Random(4242)
    # LED confetti
    for i in range(150):
        x0 = rng.uniform(0, VW)
        sp = rng.uniform(5, 12)
        ph = rng.uniform(0, VH)
        col = rng.choice([LED_AMBER, LED_WHITE, LED_RED, (60, 220, 90), (60, 140, 255), (255, 80, 200)])
        y = (ph + age * sp * VS * 0.9) % (VH + 40) - 20
        x = x0 + math.sin(age * 0.3 + i) * 18
        s_ = rng.choice([2, 2, 3]) * VS
        d.rectangle((x, y, x + s_, y + s_), fill=col)
    # chasing border lights
    per = 2 * (VW + VH)
    for k in range(0, per, 32):
        p = (k + age * 16) % per
        if (k // 32) % 3:
            continue
        if p < VW:
            x, y = p, 4
        elif p < VW + VH:
            x, y = VW - 8, p - VW
        elif p < 2 * VW + VH:
            x, y = VW - (p - VW - VH), VH - 8
        else:
            x, y = 4, VH - (p - 2 * VW - VH)
        d.rectangle((x, y, x + 8, y + 8), fill=LED_AMBER)
    t1 = Image.new("RGB", (VW, VH), BLACK)
    td = ImageDraw.Draw(t1)
    td.text((VW / 2, 196), "CONGRATULATIONS.", font=fit("CONGRATULATIONS.", VW - 120, 190, 900), fill=LED_WHITE, anchor="mm")
    td.text((VW / 2, 382), "YOU ARE NOW AN EXPERT.", font=fit("YOU ARE NOW AN EXPERT.", VW - 200, 110, 850), fill=LED_AMBER, anchor="mm")
    mask = Image.new("L", (VW, VH), 0)
    ImageDraw.Draw(mask).rectangle((0, 0, VW * wipe, VH), fill=255)
    img.paste(t1, (0, 0), ImageChops.multiply(mask, t1.convert("L").point(lambda v: 255 if v > 8 else 0)))
    blink = 1.0 if (age // 6) % 2 == 0 or age > 18 else 0.75
    return img, blink


def disp_final_content():
    img = Image.new("RGB", (VW, VH), BLACK)
    d = ImageDraw.Draw(img)
    top, mid, bot = T.DISPLAY_FINAL
    d.text((VW / 2, 70), top, font=F(74, 850), fill=LED_AMBER, anchor="mm")
    d.text((VW / 2, 262), mid, font=fit(mid, VW - 140, 290, 900), fill=LED_RED, anchor="mm")
    d.text((VW / 2, 452), bot, font=F(64, 800), fill=LED_AMBER, anchor="mm")
    return img


def disp_final(f):
    img = disp_final_content()
    d = ImageDraw.Draw(img)
    age = f - E["display_flip"] - 4
    # warning chevrons scrolling along the top and bottom edges
    for y0 in (0, VH - 18):
        for k in range(-2, VW // 48 + 3):
            x = k * 48 + (age * 6) % 48
            d.polygon([(x, y0), (x + 24, y0), (x + 42, y0 + 18), (x + 18, y0 + 18)], fill=LED_RED if k % 2 else LED_AMBER)
    for x in (60, VW - 60):  # blinking warning triangles beside the top line
        if (age // 4) % 2 == 0:
            d.polygon([(x, 36), (x + 36, 100), (x - 36, 100)], fill=LED_AMBER)
            d.rectangle((x - 4, 56, x + 4, 82), fill=BLACK)
            d.rectangle((x - 4, 88, x + 4, 95), fill=BLACK)
    flash = 1.0 if (age // 3) % 2 == 0 else 0.8
    return img, flash


def disp_flip(f):
    """3-4 frame split-flap / glitch transition into the warning."""
    age = f - E["display_flip"]
    rng = frng("flip", f)
    a, _ = disp_congrats(E["display_flip"] - 1)
    b = disp_final_content()
    cols, rows = 24, 4
    cw, ch = VW // cols, VH // rows
    out = Image.new("RGB", (VW, VH), BLACK)
    d = ImageDraw.Draw(out)
    glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%!?"
    for r in range(rows):
        for c in range(cols):
            k = rng.random()
            done = (c + r * 3) / (cols + rows * 3) < (age + 0.5) / 4.0
            box = (c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)
            if done and k > 0.25:
                out.paste(b.crop(box), box[:2])
            elif k < 0.55:
                g = rng.choice(glyphs)
                d.text((c * cw + cw / 2, r * ch + ch / 2), g, font=F(ch * 0.8, 900),
                       fill=rng.choice([LED_AMBER, LED_RED, LED_WHITE]), anchor="mm")
            else:
                out.paste(a.crop(box), box[:2])
            d.line((c * cw, r * ch + ch / 2, (c + 1) * cw, r * ch + ch / 2), fill=BLACK, width=int(VS * 2))
    out = glitch(out, rng, n=6, maxshift=160, hmin=int(VS * 3), hmax=int(VS * 14), split=int(VS * 2))
    return out


def display_frame(f):
    if f < E["pa_start"]:
        return led_compose(disp_idle(f), f)
    if f < E["display_flip"]:
        img, br = disp_congrats(f)
        return led_compose(img, f, br)
    if f < E["display_flip"] + 4:
        return led_compose(disp_flip(f), f)
    img, br = disp_final(f)
    return led_compose(img, f, br)


# =============================================================================
# CROWD ATLAS  (2048 x 1280, 4 x 4 tiles of 512 x 320)
# =============================================================================
ATLAS = [  # (line1, line2, style, label, icon)
    ("NEW MODEL", "RELEASED", "blue", "UPDATE", "burst"),
    ("v9.0", "BREAKING CHANGES", "amber", "RELEASE NOTES", "warn"),
    ("DEPRECATED", "", "red", "NOTICE", "warn"),
    ("UPGRADE", "REQUIRED", "navy", "SYSTEM", "bolt"),
    ("LEARN THIS", "NOW", "white", "TRENDING", "bolt"),
    ("+0.2%", "SOTA", "blue", "LEADERBOARD", "chart"),
    ("AGENT", "FRAMEWORK 48", "navy", "NEW FRAMEWORK", "burst"),
    ("PAPER OF", "THE HOUR", "white", "RESEARCH", "paper"),
    ("YOU ARE", "BEHIND", "red", "ALERT", "warn"),
    ("NEW", "BENCHMARK", "blue", "EVALS", "chart"),
    ("COURSE", "OUTDATED", "amber", "LEARNING", "warn"),
    ("1,204 NEW", "TOOLS TODAY", "navy", "DIGEST", "burst"),
    ("v10.0", "OUT NOW", "blue", "RELEASE", "burst"),
    ("RETRAIN", "YOURSELF", "white", "CAREER", "sparkle"),
    ("MIGRATE", "NOW", "navy", "ACTION REQUIRED", "bolt"),
    ("NEW", "PARADIGM", "blue", "BREAKING", "sparkle"),
]
ATLAS_STYLE = {
    "blue": ((30, 86, 230), (22, 64, 190), WHITE, (190, 215, 255)),
    "navy": ((10, 20, 48), (6, 12, 32), WHITE, (90, 200, 255)),
    "white": ((246, 248, 252), (226, 232, 242), (10, 26, 64), (40, 100, 230)),
    "red": ((216, 30, 38), (170, 18, 26), WHITE, (255, 210, 210)),
    "amber": ((255, 178, 30), (238, 146, 10), (26, 16, 0), (90, 50, 0)),
}


def atlas_tile(i):
    l1, l2, style, label, ic = ATLAS[i]
    c0, c1, fg, acc = ATLAS_STYLE[style]
    k = 2
    W, H = 512 * k, 320 * k
    img = vgrad(W, H, c0, c1)
    d = ImageDraw.Draw(img)
    # window chrome
    bar = mix(c1, BLACK, 0.25) if style != "white" else (210, 216, 228)
    fill_rect(img, (0, 0, W, 26 * k), bar)
    for j in range(3):
        fill_circle(img, (16 + j * 16) * k, 13 * k, 8 * k, mix(bar, fg, 0.35))
    icon(img, ic, 26 * k, 44 * k, 34 * k, acc)
    tracked(d, (72 * k, 72 * k), label, F(19 * k, 800), acc, 2.2 * k)
    lines = [l for l in (l1, l2) if l]
    if len(lines) == 1:
        d.text((W / 2, 200 * k), lines[0], font=fit(lines[0], W - 60 * k, 104 * k, 900), fill=fg, anchor="mm")
    else:
        f1 = fit(lines[0], W - 64 * k, 100 * k, 900)
        f2 = fit(lines[1], W - 64 * k, 100 * k, 900)
        c1, c2, gap = f1.size * 0.73, f2.size * 0.73, 26 * k
        top = 92 * k + (186 * k - (c1 + gap + c2)) / 2
        d.text((36 * k, top + c1), lines[0], font=f1, fill=fg, anchor="ls")
        d.text((36 * k, top + c1 + gap + c2), lines[1], font=f2, fill=fg, anchor="ls")
    fill_rect(img, (36 * k, 290 * k, 160 * k, 296 * k), acc)
    return img.resize((512, 320), Image.LANCZOS)


def render_atlas():
    atlas = Image.new("RGB", (2048, 1280), BLACK)
    for i in range(16):
        atlas.paste(atlas_tile(i), ((i % 4) * 512, (i // 4) * 320))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    atlas.save(OUT_DIR / "crowd_atlas.png", "PNG", compress_level=9)
    return atlas


# =============================================================================
# Runner
# =============================================================================
RENDERERS = {}


def _render_task(task):
    seq, f = task
    first, last, size, ext = SEQUENCES[seq]
    img = RENDERERS[seq](f)
    assert img.size == size, (seq, f, img.size)
    return seq, f, encode_frame(img, ext)


RENDERERS["laptop"] = laptop_frame
RENDERERS["monitor"] = monitor_frame
RENDERERS["notebook"] = notebook_frame
RENDERERS["display"] = display_frame
RENDERERS["atlas"] = render_atlas


def parse_frames(spec):
    if not spec:
        return None
    a, _, b = spec.partition("-")
    return int(a), int(b or a)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma list of: " + ",".join(list(SEQUENCES) + ["atlas"]))
    ap.add_argument("--frames", default="", help="film frame range a-b (clipped per sequence)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--contact", default="", help="write a key-frame contact sheet to this path and exit")
    args = ap.parse_args(argv)

    if args.contact:
        build_contact_sheet(Path(args.contact))
        return
    only = [s.strip() for s in args.only.split(",") if s.strip()] or list(SEQUENCES) + ["atlas"]
    rng = parse_frames(args.frames)
    tasks = []
    for seq in only:
        if seq == "atlas" or seq not in SEQUENCES:
            continue
        a, b, _, _ = SEQUENCES[seq]
        if rng:
            a, b = max(a, rng[0]), min(b, rng[1])
        tasks += [(seq, f) for f in range(a, b + 1)]
    t0 = time.time()
    if "atlas" in only and "atlas" in RENDERERS:
        RENDERERS["atlas"]()
        print("atlas ->", OUT_DIR / "crowd_atlas.png")
    stats, seen = {}, {}

    def store(seq, f, data):
        ext = SEQUENCES[seq][3]
        new = write_frame(OUT_DIR / seq / f"{seq}_{f:04d}.{ext}", data, seen.setdefault(seq, {}))
        st = stats.setdefault(seq, [0, 0, 0])
        st[0] += 1
        st[1] += len(data)
        st[2] += len(data) if new else 0

    if tasks:
        if args.workers > 1:
            with Pool(args.workers) as pool:
                for seq, f, data in pool.imap(_render_task, tasks, chunksize=6):
                    store(seq, f, data)
        else:
            for t in tasks:
                store(*_render_task(t))
    tot = [0, 0]
    for seq, (n, apparent, unique) in stats.items():
        tot[0] += apparent
        tot[1] += unique
        print(f"{seq:9s} {n:4d} frames  {apparent / 1e6:6.1f} MB apparent  {unique / 1e6:6.1f} MB unique on disk")
    if stats:
        print(f"{'total':9s}             {tot[0] / 1e6:6.1f} MB apparent  {tot[1] / 1e6:6.1f} MB unique on disk")
    print(f"done in {time.time() - t0:.1f} s")


CONTACT_KEYS = [("laptop", [60, 95, 120, 200, 250, 290, 320, 360, 405, 425, 500]),
                ("monitor", [100, 230, 290, 380, 450, 600]),
                ("notebook", [41, 57, 158, 232]),
                ("display", [590, 600, 630, 650])]


def build_contact_sheet(path, thumb_h=250, width=2000):
    """Key frames (read from disk, rendered on the fly if missing) plus the atlas."""
    items = []
    for seq, frames in CONTACT_KEYS:
        a, b, _, ext = SEQUENCES[seq]
        for f in frames:
            if not a <= f <= b:
                continue
            fp = OUT_DIR / seq / f"{seq}_{f:04d}.{ext}"
            im = Image.open(fp).convert("RGB") if fp.exists() else RENDERERS[seq](f)
            items.append((f"{seq} {f:04d}  ({T.shot_at(f)['id']})", im))
    ap = OUT_DIR / "crowd_atlas.png"
    items.append(("crowd_atlas", Image.open(ap).convert("RGB") if ap.exists() else render_atlas()))
    pad, lab = 14, 26
    rows, row, x = [], [], pad
    for name, im in items:
        w = int(im.width * thumb_h / im.height)
        if row and x + w + pad > width:
            rows.append(row)
            row, x = [], pad
        row.append((name, im.resize((w, thumb_h), Image.LANCZOS), x))
        x += w + pad
    rows.append(row)
    sheet = Image.new("RGB", (width, pad + len(rows) * (thumb_h + lab + pad)), (40, 42, 46))
    d = ImageDraw.Draw(sheet)
    for r, row in enumerate(rows):
        y = pad + r * (thumb_h + lab + pad)
        for name, im, x in row:
            d.text((x, y + 18), name, font=F(17, 650), fill=(230, 232, 236), anchor="ls")
            sheet.paste(im, (x, y + lab))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, "JPEG", quality=90)
    print("contact sheet ->", path)


if __name__ == "__main__":
    main()
