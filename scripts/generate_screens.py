#!/usr/bin/env python3
"""SKILL ISSUE: on-screen interface graphics.

Renders the deterministic image sequences that Blender maps onto the laptop,
the external monitor, the notebook page and the stadium display, plus a crowd
texture atlas.  Every frame number comes from ``skill_issue.timeline`` and every
procedural rate from ``skill_issue.speed``; nothing depends on wall-clock time.

    python scripts/generate_screens.py
    python scripts/generate_screens.py --only laptop,monitor --frames 230-320
    python scripts/generate_screens.py --only paper,keyboard  # static textures only
    python scripts/generate_screens.py --contact out.jpg     # key-frame sheet

Outputs (sequences are named by FILM frame number):
    assets/screens/laptop/laptop_####.jpg      1280x800   0001-0720
    assets/screens/monitor/monitor_####.jpg    1600x900   0001-0720
    assets/screens/notebook/notebook_####.png  1024x1024  0001-E['scrib_end']
    assets/screens/display/display_####.jpg    1920x640   0560-0720
    assets/screens/crowd_atlas.png             2048x1280  (4x4 tiles)
    assets/screens/roadmap_paper_head.png      512x1536   printout start (header + items 001..)
    assets/screens/roadmap_paper_tile.png      512x2048   printout body, tiles vertically
    assets/screens/keyboard.png                2048x780   laptop keyboard albedo
    assets/screens/keyboard_glow.png           2048x780   legends + backlight edge mask (emission)

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
# Every beat comes from timeline.E (never from shot IDs, which change meaning on
# a retime).  Screen phases use the explicit E keys notifs_out, code_done,
# builder_start, dashboard_start, print_start, scrib_start and scrib_end; the
# few derived beats below are offsets from E.
B = dict(
    banner=E["snaps"][1] + 1,                 # 'this lecture is outdated' banner
    reopen=E["yank"] + 5,                     # laptop lid back open: frantic screen until E['black']
    screensaver=E["close_laptop"] + 3,        # monitor: KEEP UP. screensaver
)
FONT_DIR = REPO / "assets" / "fonts"
INTER_PATH = FONT_DIR / "Inter.woff2"
MONO_PATH = FONT_DIR / "DejaVuSansMono.woff2"
OUT_DIR = REPO / "assets" / "screens"
JPEG_Q = 88

DISPLAY_FIRST = 560     # file-range contract with hall.py (sequence first=560); content is E-based
SEQUENCES = {
    # name: (first frame, last frame, (w, h), extension)
    "laptop": (T.FRAME_START, T.FRAME_END, (1280, 800), "jpg"),
    "monitor": (T.FRAME_START, T.FRAME_END, (1600, 900), "jpg"),
    "notebook": (T.FRAME_START, E["scrib_end"], (1024, 1024), "png"),   # Blender holds the last frame
    "display": (DISPLAY_FIRST, T.FRAME_END, (1920, 640), "jpg"),
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
# DESIGN LANGUAGE  (laptop + monitor)
# =============================================================================
# The screens are filmed small and at an angle, so every state has ONE hero
# message with big high-contrast type, a single accent colour and a pushed-back
# (blurred, darkened) UI behind it.  Cards share one radius / shadow / padding
# vocabulary and every entrance is the same eased slide + fade.
INFO, ALERT, AGENT, WARN = BLUE, RED, CYAN, AMBER
R_HERO, R_CARD, R_CHIP = 30, 22, 14
ENTER = 6                                   # frames for every eased slide + fade


def enter_k(age, n=ENTER):
    """Eased 0..1 entrance progress for an element born `age` frames ago."""
    return ease_out((age + 1) / n)


def exit_k(f, end, n=ENTER):
    """Eased 0..1 exit progress for an element that must be gone by frame `end`."""
    return ease_in((f - (end - n)) / n)


def card(w, h, top, bot, accent=None, r=R_CARD, border=0.55, bw=2.0, blur=24, op=0.6, dy=12):
    """RGBA card: gradient body, soft drop shadow, thin accent border. Returns (im, pad)."""
    w, h = int(w), int(h)
    sm, spad = _shadow(w, h, r, blur)
    pad = spad + dy
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", sm.size, (0, 0, 0, 0))
    sh.putalpha(scale_mask(sm, op))
    im.alpha_composite(sh, (pad - spad, pad - spad + dy))
    body = vgrad(w, h, top, bot).convert("RGBA")
    body.putalpha(rr_mask(w, h, r))
    im.alpha_composite(body, (pad, pad))
    if accent is not None and border > 0:
        ring = Image.new("RGBA", (w, h), tuple(accent[:3]) + (0,))
        ring.putalpha(scale_mask(rr_ring(w, h, r, bw), border))
        im.alpha_composite(ring, (pad, pad))
    return im, pad


def icon_layer(name, size, color):
    ic = Image.new("RGBA", (int(size), int(size)), tuple(color[:3]) + (255,))
    ic.putalpha(icon_mask(name, int(size)))
    return ic


def icon_tile(im, x, y, size, accent, name, fg=WHITE):
    t = Image.new("RGBA", (int(size), int(size)), tuple(accent[:3]) + (255,))
    t.putalpha(rr_mask(int(size), int(size), size * 0.26))
    im.alpha_composite(t, (int(x), int(y)))
    s = int(size * 0.6)
    im.alpha_composite(icon_layer(name, s, fg), (int(x + (size - s) / 2), int(y + (size - s) / 2)))


def focus(img, k, blur=10, keep=0.4):
    """Push the UI behind a hero card back (blur + darken); k = 0..1."""
    if k <= 0.004:
        return img
    back = dim(img.filter(ImageFilter.GaussianBlur(blur)), keep)
    return Image.blend(img, back, clamp(k))


def place_c(img, layer, cx, cy, k=1.0, dx=0.0, dy=0.0, scale0=1.0, opacity=1.0, scale=1.0):
    """Paste a symmetric-padded card centred on (cx, cy) with an eased slide + fade + settle."""
    op = opacity * min(1.0, k * 1.3)
    if op <= 0.003:
        return
    sc = lerp(scale0, 1.0, k) * scale
    if abs(sc - 1.0) > 1e-3:
        layer = layer.resize((max(1, round(layer.width * sc)), max(1, round(layer.height * sc))), Image.BICUBIC)
    paste_rgba(img, layer, cx - layer.width / 2 + (1 - k) * dx, cy - layer.height / 2 + (1 - k) * dy, opacity=op)


def fit_lines(lines, max_w, size, weight=820, min_size=16):
    size = int(size)
    while size > min_size and max(F(size, weight).getlength(ln) for ln in lines) > max_w:
        size -= 1
    return F(size, weight)


def draw_cursor(img, x, y, sc=1.7):
    """Classic arrow pointer, tip at (x, y), with a soft shadow."""
    base = [(0, 0), (0, 30), (8, 23), (14, 36), (19, 34), (13, 21), (23, 21)]
    pts = [(x + px * sc, y + py * sc) for px, py in base]
    box = (x - 12, y - 12, x + 26 * sc + 16, y + 38 * sc + 18)
    sh = [(px + 3, py + 5) for px, py in pts]
    aa(img, BLACK, lambda dd, P, ss: dd.polygon([P(*p) for p in sh], fill=255), box=box, alpha=0.35)
    aa(img, BLACK, lambda dd, P, ss: dd.polygon([P(*p) for p in pts], fill=255, outline=255, width=int(3.2 * ss)), box=box)
    aa(img, WHITE, lambda dd, P, ss: dd.polygon([P(*p) for p in pts], fill=255), box=box)


# =============================================================================
# LAPTOP  (1280 x 800)
# =============================================================================
LW, LH = 1280, 800
LSC = 1.2                                   # menu-bar scale on the laptop
LMENU = int(30 * LSC)
WIN = (16, LMENU + 10, 1264, 788)
TAB_Y = (WIN[1], WIN[1] + 40)
TOOL_Y = (TAB_Y[1], TAB_Y[1] + 42)
SIDEBAR_X1 = 318
SB_ROW0, SB_ROWH, SB_ROWS = TOOL_Y[1] + 50, 58, 9
PLAYER = (338, TOOL_Y[1] + 18, 1244, TOOL_Y[1] + 18 + 510)       # 906 x 510, 16:9
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
    return (px0 + 470, py0 + 170, px1 - 90, py1 - 150)


@lru_cache(maxsize=1)
def course_base():
    img = wallpaper(LW, LH, 0).copy()
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = WIN
    drop_shadow(img, WIN, 14, blur=20, opacity=0.6, dy=10)
    fill_rr(img, WIN, 14, (18, 20, 25))
    fill_rr(img, (x0, y0, x1, TAB_Y[1] + 14), 14, (13, 14, 18))
    fill_rect(img, (x0 + 1, TOOL_Y[0], x1 - 1, TOOL_Y[1]), (28, 31, 38))
    fill_rect(img, (x0 + 1, TOOL_Y[1] - 1, x1 - 1, TOOL_Y[1]), LINE)
    for i in range(3):
        fill_circle(img, x1 - 24 - i * 24, (TAB_Y[0] + TAB_Y[1]) / 2 + 2, 12, (72, 76, 88))
    ty = (TOOL_Y[0] + TOOL_Y[1]) / 2
    for i, ch in enumerate(("‹", "›", "↻")):
        d.text((x0 + 28 + i * 32, ty), ch, font=F(26, 500), fill=TXT3, anchor="mm")
    fill_rr(img, (x0 + 118, TOOL_Y[0] + 6, x1 - 130, TOOL_Y[1] - 6), 15, (17, 19, 24))
    icon(img, "lock", x0 + 134, ty - 8, 16, TXT3)
    d.text((x0 + 160, ty), "skillqueue.app/ml-101/lecture-1", font=F(18, 500), fill=TXT2, anchor="lm")
    fill_rect(img, (x0 + 1, TOOL_Y[1], x1 - 1, y1 - 14), (18, 20, 25))
    # sidebar: fewer, bigger rows
    fill_rect(img, (x0 + 1, TOOL_Y[1], SIDEBAR_X1, y1 - 14), (14, 15, 19))
    fill_rr(img, (x0, y1 - 28, SIDEBAR_X1 + 14, y1), 14, (14, 15, 19))
    fill_rect(img, (SIDEBAR_X1, TOOL_Y[1], SIDEBAR_X1 + 1, y1), LINE)
    tracked(d, (x0 + 22, SB_ROW0 - 16), "COURSE CONTENT", F(15, 750), TXT3, 1.8)
    for i in range(SB_ROWS):
        ry = SB_ROW0 + i * SB_ROWH
        cy = ry + SB_ROWH / 2
        if i == 0:
            fill_rr(img, (x0 + 10, ry + 4, SIDEBAR_X1 - 10, ry + SB_ROWH - 4), 10, (30, 38, 56))
            fill_rr(img, (x0 + 10, ry + 12, x0 + 15, ry + SB_ROWH - 12), 2, BLUE)
        fill_circle(img, x0 + 42, cy, 28, BLUE if i == 0 else (40, 44, 54))
        d.text((x0 + 42, cy), str(i + 1), font=F(14, 750), fill=WHITE if i == 0 else TXT2, anchor="mm")
        fnt = F(19, 650 if i == 0 else 500)
        d.text((x0 + 66, cy), ellipsize(LECTURES[i], fnt, 168), font=fnt, fill=TXT if i == 0 else TXT2, anchor="lm")
        d.text((SIDEBAR_X1 - 18, cy), LECT_DUR[i], font=F(15, 500), fill=TXT3, anchor="rm")
    # player frame + slide
    px0, py0, px1, py1 = PLAYER
    fill_rr(img, PLAYER, 12, (245, 242, 235))
    d.text((px0 + 52, py0 + 80), "What is a neural network?", font=F(46, 780), fill=(24, 27, 36), anchor="ls")
    d.text((px0 + 54, py0 + 118), "Lecture 1 · Foundations", font=F(22, 500), fill=(110, 116, 130), anchor="ls")
    fill_rect(img, (px0 + 54, py0 + 136, px0 + 118, py0 + 141), BLUE)
    for i, b in enumerate(["Layers of simple units", "Weighted connections", "Learning = adjusting weights"]):
        by = py0 + 210 + i * 54
        fill_circle(img, px0 + 62, by - 8, 10, BLUE)
        d.text((px0 + 82, by), b, font=F(24, 550), fill=(52, 57, 70), anchor="ls")
    cols, edges = nn_layout(course_slide_box())

    def draw_edges(dd, P, ss):
        for a, b in edges:
            dd.line([P(*a), P(*b)], fill=255, width=int(1.8 * ss))
    aa(img, (150, 158, 175), draw_edges, box=PLAYER)
    colors = [(76, 141, 255), (124, 92, 246), (34, 197, 140)]
    for li, col in enumerate(cols):
        for (x, y) in col:
            fill_circle(img, x, y, 40, colors[li])
            fill_circle(img, x, y, 22, (255, 255, 255), 0.35)
    for li, lab in enumerate(["inputs", "hidden", "output"]):
        d.text((cols[li][0][0], course_slide_box()[3] + 44), lab, font=F(19, 650), fill=(110, 116, 130), anchor="ms")
    # bottom control gradient
    gh = 84
    gm = Image.fromarray((np.linspace(0, 180, gh)[:, None] * np.ones((1, px1 - px0))).astype(np.uint8))
    img.paste((0, 0, 0), (px0, py1 - gh, px1, py1), gm)
    # under-player info
    d.text((px0, 706), "INTRO TO MACHINE LEARNING · Lecture 1 of 12", font=F(28, 780), fill=TXT, anchor="ls")
    d.text((px0, 750), "Course progress", font=F(18, 550), fill=TXT2, anchor="ls")
    fill_rr(img, (px0 + 156, 738, px0 + 420, 748), 5, (44, 48, 60))
    fill_rr(img, (px0 + 156, 738, px0 + 172, 748), 5, BLUE)
    d.text((px0 + 434, 750), "3%", font=F(18, 750), fill=TXT, anchor="ls")
    for i, lab in enumerate(("Notes", "Q&A", "Resources")):
        bx = px1 - (2 - i) * 124
        ring_rr(img, (bx - 112, 726, bx, 762), 10, 1.4, LINE)
        d.text((bx - 56, 744), lab, font=F(17, 650), fill=TXT2, anchor="mm")
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
    x0, x1 = WIN[0] + 12, WIN[2] - 92
    ym = (TAB_Y[0] + TAB_Y[1]) / 2 + 3
    fill_rect(img, (WIN[0] + 1, TAB_Y[0] + 5, x1 + 8, TAB_Y[1]), (13, 14, 18))
    tw = min(260, (x1 - x0) / n)
    for i in range(n):
        tx0 = x0 + i * tw
        if i == 0:
            fill_rr(img, (tx0, TAB_Y[0] + 6, tx0 + tw - 2, TAB_Y[1] + 12), 10, (28, 31, 38))
        else:
            fill_rect(img, (tx0 - 1, TAB_Y[0] + 15, tx0, TAB_Y[1] - 7), (44, 48, 58))
        col = [BLUE, ORANGE, RED, AMBER, VIOLET, GREEN][i % 6] if i else BLUE
        if tw > 40:
            fill_circle(img, tx0 + 19, ym, 14, col)
        if tw > 80:
            fnt = F(15, 550)
            d.text((tx0 + 36, ym), ellipsize(TABS[i % len(TABS)], fnt, tw - 64), font=fnt,
                   fill=TXT if i == 0 else TXT2, anchor="lm")
            d.text((tx0 + tw - 16, ym), "×", font=F(16, 400), fill=TXT3, anchor="mm")


# --- Act I: the three notification cards (notif1 .. notifs_out) --------------
NOTIF_W = 1060
NOTIF_X = (LW - NOTIF_W) // 2
NOTIF_TXT_W = NOTIF_W - 196


def notif_lines(text):
    if ". " in text.rstrip("."):
        a, b = text.split(". ", 1)
        return [a + ".", b]
    return [text]


@lru_cache(maxsize=1)
def notif_font():
    lines = [ln for n in T.NOTIFICATIONS[:3] for ln in notif_lines(n["text"])]
    return fit_lines(lines, NOTIF_TXT_W, 64, 820, 36)


@lru_cache(maxsize=8)
def notif_card(text, kind):
    accent = ALERT if kind == "alert" else INFO
    fnt = notif_font()
    lines = notif_lines(text)
    lh = int(fnt.size * 1.14)
    by0 = 76 + int(fnt.size * 0.73)
    h = by0 + lh * (len(lines) - 1) + 38
    top, bot = ((40, 45, 58), (28, 31, 40)) if kind != "alert" else ((66, 30, 33), (44, 22, 26))
    im, pad = card(NOTIF_W, h, top, bot, accent, r=R_CARD, border=0.75, blur=22, op=0.62, dy=12)
    d = ImageDraw.Draw(im)
    icon_tile(im, pad + 36, pad + 32, 88, accent, "warn" if kind == "alert" else "burst")
    tx = pad + 156
    tracked(d, (tx, pad + 54), "BENCHMARKS" if kind == "alert" else "AI UPDATES", F(19, 800),
            mix(accent, WHITE, 0.4), 2.2)
    d.text((pad + NOTIF_W - 36, pad + 54), "now", font=F(20, 500), fill=(165, 172, 188), anchor="rs")
    for i, ln in enumerate(lines):
        d.text((tx, pad + by0 + i * lh), ln, font=fnt, fill=WHITE, anchor="ls")
    return im, pad, h


def notif_stack(img, f):
    ns = T.NOTIFICATIONS[:3]
    out = exit_k(f, E["notifs_out"])
    y = LMENU + 36
    for j, n in enumerate(ns):
        im, pad, h = notif_card(n["text"], n["kind"])
        if f >= n["frame"]:
            k = enter_k(f - n["frame"])
            older = enter_k(f - ns[j + 1]["frame"]) if j + 1 < len(ns) and f >= ns[j + 1]["frame"] else 0.0
            x = NOTIF_X + (1 - k) * 110 + out * 160
            op = min(1.0, k * 1.3) * (1 - out)
            paste_rgba(img, im, x - pad, y - pad, opacity=op)
            if older > 0:                            # older cards step back (darker, still opaque)
                fill_rr(img, (x, y, x + NOTIF_W, y + h), R_CARD, BLACK, 0.34 * older * op)
        y += h + 18


# --- Act II: speed-spawned toasts (bigger, max four on screen) ----------------
TOAST_W, TOAST_H, TOAST_MAX = 560, 94, 4


@lru_cache(maxsize=32)
def toast_card(text):
    kind = MINI_KIND.get(text, "release")
    accent = WARN if kind == "warn" else INFO
    im, pad = card(TOAST_W, TOAST_H, (38, 42, 54), (29, 32, 41), accent, r=18, border=0.5, bw=1.6,
                   blur=14, op=0.55, dy=8)
    icon_tile(im, pad + 18, pad + 17, 60, accent, {"warn": "warn", "paper": "paper", "chart": "chart"}.get(kind, "burst"))
    d = ImageDraw.Draw(im)
    fnt = fit(text, TOAST_W - 178, 30, 760, 20)
    d.text((pad + 96, pad + TOAST_H / 2 + 1), text, font=fnt, fill=WHITE, anchor="lm")
    d.text((pad + TOAST_W - 20, pad + TOAST_H / 2 + 1), "now", font=F(17, 500), fill=TXT3, anchor="rm")
    return im, pad


def draw_toasts(img, f, x_right=LW - 22, y_top=LMENU + 14, life_base=26, fmin=0, fmax=9999):
    toasts = [t for t in CH()["events"]["toasts"] if fmin <= t["frame"] <= min(f, fmax)]
    vis = []
    for t in toasts:
        life = int(life_base - 8 * spd(t["frame"]))
        age = f - t["frame"]
        if 0 <= age < life:
            vis.append((t, age, life))
    for t, age, life in vis:
        slot = sum(ease_out((f - u[0]["frame"] + 1) / 5) for u in vis if u[0]["frame"] > t["frame"])
        if slot >= TOAST_MAX:
            continue
        im, pad = toast_card(MINI_TEXTS[t["i"] % len(MINI_TEXTS)])
        k = enter_k(age, 5)
        x = x_right - TOAST_W + (1 - k) * TOAST_W * 0.45
        y = y_top + slot * (TOAST_H + 14)
        fade = (1 - smooth((age - (life - 5)) / 5)) * clamp(TOAST_MAX - slot)
        paste_rgba(img, im, x - pad, y - pad, opacity=min(1.0, k * 1.3) * fade)


def lap_course(f):
    img = course_base().copy()
    d = ImageDraw.Draw(img)
    s = spd(f)
    act2 = f >= E["typing_start"]
    clutter = clamp((s - 0.2) / 0.52) if act2 else 0.0
    draw_tabs(img, 1 + int(round(clutter * 11)) if act2 else 1)
    # sidebar 'OUTDATED' tags creep in
    if act2:
        for i in range(int(clutter * 9 + 0.3)):
            li = [0, 3, 1, 6, 7, 2, 8, 5, 4][i]
            cy = SB_ROW0 + li * SB_ROWH + SB_ROWH / 2
            fill_rect(img, (SIDEBAR_X1 - 116, cy - 18, SIDEBAR_X1 - 11, cy + 18), (30, 38, 56) if li == 0 else (14, 15, 19))
            fill_rr(img, (SIDEBAR_X1 - 112, cy - 15, SIDEBAR_X1 - 12, cy + 15), 8, (82, 58, 14))
            d.text((SIDEBAR_X1 - 62, cy), "OUTDATED", font=F(14, 800), fill=AMBER, anchor="mm")
    # video signal pulses
    px0, py0, px1, py1 = PLAYER
    cols, edges = nn_layout(course_slide_box())
    vt = video_time(f)
    for ei, (a, b) in enumerate(edges):
        if ei % 3:
            continue
        ph = (vt * 0.45 + ei * 0.137) % 1.0
        fill_circle(img, lerp(a[0], b[0], ph), lerp(a[1], b[1], ph), 12, BLUE, 0.9 * math.sin(ph * math.pi))
    # player controls
    rate = playback_rate(f)
    total = 24 * 60 + 10
    tx0, tx1, ty = px0 + 22, px1 - 22, py1 - 52
    fill_rr(img, (tx0, ty - 3, tx1, ty + 3), 3, WHITE, 0.25)
    fx = tx0 + (tx1 - tx0) * vt / total
    fill_rr(img, (tx0, ty - 3, fx, ty + 3), 3, BLUE)
    fill_circle(img, fx, ty, 16, WHITE)
    icon(img, "pause", px0 + 24, py1 - 34, 20, WHITE)
    d.text((px0 + 60, py1 - 24), f"{fmt_t(vt)} / {fmt_t(total)}", font=F(18, 650), fill=WHITE, anchor="lm")
    rl, hot = f"{rate:g}x", rate > 1
    fr = F(18, 800 if hot else 650)
    rw = fr.getlength(rl) + 22
    if hot:
        fill_rr(img, (px1 - 140 - rw, py1 - 38, px1 - 140, py1 - 10), 7, AMBER)
    d.text((px1 - 140 - rw / 2, py1 - 24), rl, font=fr, fill=BLACK if hot else WHITE, anchor="mm")
    d.text((px1 - 98, py1 - 24), "CC", font=F(16, 750), fill=WHITE, anchor="mm")
    ring_rr(img, (px1 - 54, py1 - 34, px1 - 26, py1 - 14), 3, 2, WHITE)
    # 'this lecture is outdated' banner slides down
    if act2 and f >= B["banner"]:
        k = enter_k(f - B["banner"])
        by = py0 + 12 - (1 - k) * 40
        fill_rr(img, (px0 + 12, by, px1 - 12, by + 84), 14, (96, 66, 10), k)
        icon(img, "warn", px0 + 36, by + 25, 34, AMBER, k)
        d.text((px0 + 88, by + 43), "This lecture is 3 weeks old. Parts may be outdated.",
               font=F(26, 750), fill=mix((96, 66, 10), (255, 230, 170), k), anchor="lm")
    # Act I notification cards: the UI behind them is pushed back
    in_notifs = E["notif1"] <= f <= E["notifs_out"]
    if in_notifs:
        img = focus(img, 0.75 * enter_k(f - E["notif1"]) * (1 - exit_k(f, E["notifs_out"])), blur=12, keep=0.36)
    unread = sum(1 for n in T.NOTIFICATIONS[:3] if f >= n["frame"])
    if act2:
        unread += sum(1 for t in CH()["events"]["toasts"] if t["frame"] <= f) + \
            int(sum(spd(k) ** 1.6 for k in range(E["typing_start"], f + 1)) * 1.2)
    menubar(img, f, sc=LSC, bell=unread)
    if in_notifs:
        notif_stack(img, f)
    if act2:
        draw_toasts(img, f, fmax=E["tutorial_2x"] - 1)
    return img


# --- tutorial (tutorial_2x .. notif_do_that) ---------------------------------
TUT_STEPS = ["Install the framework", "Create your first agent", "Add memory", "Add tools", "Add a planner",
             "Connect a vector store", "Add evals", "Migrate to v2", "Undo the migration", "Add a second agent",
             "Agents managing agents", "Reflection loop", "Deploy it", "Monitor it", "Scale to 1,000 agents",
             "Rewrite it for v3", "Prompt caching", "Multi-modal input", "Guardrails", "Cost control",
             "Self-improvement", "Replace yourself", "Benchmarks", "Ship it", "Start over (v4)"]
TUT_CODE = [
    "agent = Agent(model=\"latest\")", "agent.add_tool(search)", "memory = Memory(max_items=10_000)",
    "agent.attach(memory)", "plan = planner.make_plan(goal)", "for step in plan:", "    agent.run(step)",
    "result = await agent.ask(q)", "store = VectorStore(dim=1536)", "evals.run(agent, suite=\"all\")",
    "from agentflow import Agent  # v2", "agent = Agent.from_config(\"v3\")", "team = [Agent() for _ in range(8)]",
    "boss = Agent(role=\"manager\")", "boss.delegate(team)", "agent.reflect(depth=3)", "deploy(agent, replicas=1000)",
    "cache = PromptCache(ttl=3600)", "agent.learn(\"everything\")", "if agent.score > me.score:", "    me.retire()",
]
TUT_CAPS = ["so first we install the framework", "this part is really simple", "now we wire the planner into memory",
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


@lru_cache(maxsize=96)
def tut_slide(idx):
    rng = frng("slide", idx)
    img = vgrad(LW, LH, (16, 19, 26), (10, 12, 17))
    d = ImageDraw.Draw(img)
    accent = [BLUE, VIOLET, GREEN, AMBER, CYAN][idx % 5]
    tracked(d, (64, 70), "BUILD AN AI AGENT IN 10 MINUTES · EP. 47", F(20, 750), TXT3, 2.0)
    fill_rect(img, (64, 90, 132, 95), accent)
    d.text((64, 172), f"Step {idx + 1}:", font=F(42, 650), fill=accent, anchor="ls")
    title = TUT_STEPS[idx % len(TUT_STEPS)]
    d.text((64, 250), title, font=fit(title, 780, 76, 820, 44), fill=WHITE, anchor="ls")
    # code panel
    cx0, cy0, cx1, cy1 = 64, 296, 790, 652
    fill_rr(img, (cx0, cy0, cx1, cy1), 16, (22, 26, 34))
    for i, c in enumerate((RED, AMBER, GREEN)):
        fill_circle(img, cx0 + 26 + i * 22, cy0 + 24, 12, c, 0.7)
    fm = MONO(24)
    cw = fm.getlength("M")
    start = rng.randrange(len(TUT_CODE))
    for i in range(8):
        line = TUT_CODE[(start + i * 3) % len(TUT_CODE)]
        y = cy0 + 82 + i * 36
        draw_code_line(d, cx0 + 66, y, line, fm, cw)
        d.text((cx0 + 44, y), str(i + 1), font=MONO(18), fill=TXT3, anchor="rs")
    # right side: diagram or bullets
    if idx % 2 == 0:
        boxes = [("INPUT", 836, 310), ("AGENT", 990, 430), ("TOOLS", 836, 556), ("OUTPUT", 1086, 572)]
        for (a, b) in ((0, 1), (2, 1), (1, 3)):
            ax, ay = boxes[a][1] + 76, boxes[a][2] + 32
            bx, by = boxes[b][1] + 76, boxes[b][2] + 32
            aa(img, (90, 100, 120), lambda dd, P, ss, ax=ax, ay=ay, bx=bx, by=by: dd.line([P(ax, ay), P(bx, by)], fill=255, width=3 * ss),
               box=(800, 290, 1270, 650))
        for name, x, y in boxes:
            fill_rr(img, (x, y, x + 152, y + 64), 14, (30, 36, 48))
            ring_rr(img, (x, y, x + 152, y + 64), 14, 2, accent)
            d.text((x + 76, y + 32), name, font=F(23, 780), fill=WHITE, anchor="mm")
    else:
        items = rng.sample(["it's that easy", "no theory needed", "works in v2 (maybe)", "copy-paste friendly",
                            "10 lines of code", "production ready*", "scales infinitely", "beginner friendly"], 4)
        for i, it in enumerate(items):
            y = 350 + i * 74
            fill_circle(img, 840, y - 10, 16, accent)
            d.text((864, y), it, font=F(30, 650), fill=TXT, anchor="ls")
    return img


@lru_cache(maxsize=48)
def caption_img(text):
    fnt = F(34, 680)
    w = int(fnt.getlength(text)) + 48
    im = Image.new("RGBA", (w, 60), (0, 0, 0, 0))
    bg = Image.new("RGBA", (w, 60), (0, 0, 0, 255))
    bg.putalpha(scale_mask(rr_mask(w, 60, 10), 0.8))
    im.alpha_composite(bg)
    ImageDraw.Draw(im).text((w / 2, 31), text, font=fnt, fill=WHITE, anchor="mm")
    return im


@lru_cache(maxsize=8)
def speed_badge(label, hot):
    fnt = F(124, 860)
    tw = fnt.getlength(label)
    w, h = int(tw + 156), 160
    im, pad = card(w, h, (14, 15, 18), (10, 11, 14), AMBER if hot else WHITE, r=32,
                   border=0.95 if hot else 0.35, bw=3.5, blur=14, op=0.7, dy=6)
    im.alpha_composite(icon_layer("ff", 66, AMBER if hot else WHITE), (pad + 34, pad + h // 2 - 33))
    ImageDraw.Draw(im).text((pad + 120, pad + h / 2 + 4), label, font=fnt, fill=WHITE, anchor="lm")
    return im, pad


def draw_badge(img, label, hot, age):
    """The speed badge, top right, always crisp; a short eased pop when it changes."""
    bi, pad = speed_badge(label, hot)
    sc = 1.0 + 0.3 * (1 - ease_out_back((age + 1) / 5)) if age < 5 else 1.0
    bw, bh = bi.width - 2 * pad, bi.height - 2 * pad
    cx, cy = LW - 30 - bw / 2, 36 + bh / 2
    place_c(img, bi, cx, cy, 1.0, scale=sc)
    return cy + bh / 2


@lru_cache(maxsize=64)
def updates_pill(n):
    label = f"+{n} updates"
    fnt = F(26, 780)
    w, h = int(fnt.getlength(label)) + 92, 58
    im, pad = card(w, h, (44, 34, 14), (34, 26, 10), WARN, r=29, border=0.8, bw=2, blur=10, op=0.6, dy=5)
    im.alpha_composite(icon_layer("bell", 28, WARN), (pad + 24, pad + 15))
    ImageDraw.Draw(im).text((pad + 64, pad + h / 2 + 1), label, font=fnt, fill=(255, 226, 170), anchor="lm")
    return im, pad


def draw_updates(img, f, y_top):
    """Toast ticks during the tutorial collapse into ONE counter pill under the badge."""
    ts = [t["frame"] for t in CH()["events"]["toasts"] if E["tutorial_2x"] <= t["frame"] <= f]
    if not ts:
        return
    first, last = ts[0], ts[-1]
    im, pad = updates_pill(len(ts))
    k = enter_k(f - first)
    pop = 1.0 + 0.1 * (1 - ease_out((f - last + 1) / 4)) if f - last < 4 else 1.0
    w = im.width - 2 * pad
    place_c(img, im, LW - 30 - w / 2, y_top + 18 + im.height / 2 - pad, k, dx=60, scale=pop)


def tut_clean(f):
    ph = tut_phase_table()[min(f, E["notif_better"])]
    return tut_slide(int(ph)).copy(), ph


def tut_overlays(img, f, ph, chaos):
    d = ImageDraw.Draw(img)
    ci = caption_img(TUT_CAPS[int(ph * 2.3) % len(TUT_CAPS)])
    if chaos > 0:
        ci = hsmear(ci.convert("RGBA"), 6 + 40 * chaos)
    paste_rgba(img, ci, (LW - ci.width) / 2, 682)
    prog = clamp(0.22 + (ph - 2.2) * 0.028)
    fill_rect(img, (0, LH - 10, LW, LH), (60, 64, 74))
    fill_rect(img, (0, LH - 10, LW * prog, LH), BLUE)
    d.text((LW - 26, LH - 24), f"{fmt_t(max(0, int((1 - prog) * 600)))} left", font=F(20, 650), fill=TXT2, anchor="rs")


def smear_stack(img, idx, chaos, trail=((0.26, -50), (0.2, -110), (0.12, -180), (0.06, -260))):
    """Previous slides ghost to the left: the deliberate 'falling apart' look at 16x+."""
    acc = np.asarray(img, np.float32) * 0.36
    wsum = 0.36
    for k, (wgt, dx) in enumerate(trail, start=1):
        if idx - k < 0:
            break
        acc += np.roll(np.asarray(tut_slide(idx - k), np.float32), int(dx * chaos), axis=1) * wgt
        wsum += wgt
    img = Image.fromarray((acc / wsum).clip(0, 255).astype(np.uint8))
    return Image.blend(img, hsmear(img, 10 + 30 * chaos), 0.45 * chaos)


def lap_tutorial(f):
    m = tut_mult(f)
    img, ph = tut_clean(f)
    chaos = 0.0
    if m == 4:
        frac = ph % 1.0
        if frac < 0.25 and int(ph) > 0:          # quick cross-fade on each slide flip
            img = Image.blend(tut_slide(int(ph) - 1), img, 0.35 + frac * 2.6)
    if m == 16:
        chaos = clamp(0.45 + (f - E["tutorial_16x"]) / 18, 0, 0.9)
        img = smear_stack(img, int(ph), chaos)
    tut_overlays(img, f, ph, chaos)
    if m == 16:                                   # deliberate glitch (the video falls apart)
        rng = frng("tutglitch", f)
        img = glitch(img, rng, n=int(3 + 4 * chaos), maxshift=int(40 + 80 * chaos), split=int(2 + 4 * chaos))
    switch = {2: E["tutorial_2x"], 4: E["tutorial_4x"], 16: E["tutorial_16x"]}[m]
    y = draw_badge(img, f"{m}x", m == 16, f - switch)
    draw_updates(img, f, y)
    return img


# --- hero: AI CAN NOW DO THAT FOR YOU. (notif_do_that .. notif_better) --------
@lru_cache(maxsize=1)
def hero_sharp():
    ph = tut_phase_table()[E["notif_do_that"]]
    img = tut_slide(int(ph)).copy()
    tut_overlays(img, E["notif_do_that"], ph, 0.0)
    return img


@lru_cache(maxsize=1)
def hero_back():
    img = dim(hero_sharp().filter(ImageFilter.GaussianBlur(10)), 0.3)
    fill_circle(img, LW / 2, 714, 64, BLACK, 0.5)          # the video is paused
    icon(img, "pause", LW / 2 - 14, 700, 28, (150, 150, 150))
    return img


@lru_cache(maxsize=1)
def hero_card():
    w, h = 1140, 384
    im, pad = card(w, h, (64, 130, 252), (36, 92, 216), (196, 220, 255), r=R_HERO, border=0.75, bw=2.5,
                   blur=30, op=0.72, dy=16)
    d = ImageDraw.Draw(im)
    im.alpha_composite(icon_layer("sparkle", 46, WHITE), (pad + 48, pad + 34))
    d.text((pad + 108, pad + 58), "Assistant", font=F(27, 680), fill=(228, 238, 255), anchor="lm")
    d.text((pad + w - 48, pad + 58), "now", font=F(24, 500), fill=(205, 222, 255), anchor="rm")
    lines = ["AI CAN NOW DO", "THAT FOR YOU."]
    fnt = fit_lines(lines, w - 128, 124, 880)
    cap, lh = fnt.size * 0.73, fnt.size * 1.08
    y0 = pad + 112 + (h - 112 - 34 - (cap + lh)) / 2 + cap
    for i, ln in enumerate(lines):
        d.text((pad + w / 2, y0 + i * lh), ln, font=fnt, fill=WHITE, anchor="ms")
    return im, pad


def lap_hero(f):
    k = enter_k(f - E["notif_do_that"])
    img = Image.blend(hero_sharp(), hero_back(), k) if k < 0.999 else hero_back().copy()
    im, _ = hero_card()
    place_c(img, im, LW / 2, LH / 2 - 6, k, dy=44, scale0=0.95)
    return img


# --- takeover: NEW MODEL. BETTER AT EVERYTHING. (notif_better .. builder_start) --
@lru_cache(maxsize=1)
def takeover_base():
    yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
    r = np.sqrt(((xx - LW / 2) / LW) ** 2 + ((yy - LH / 2) / LH) ** 2)
    k = np.clip(1 - r * 1.25, 0, 1)[..., None]
    arr = np.array([110, 8, 16], np.float32) * (1 - k) + np.array([222, 28, 38], np.float32) * k
    stripes = (((xx + yy) // 46) % 2 == 0)[..., None] * 5.0
    img = Image.fromarray((arr + stripes).clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    icon(img, "warn", 64, 54, 58, WHITE)
    tracked(d, (140, 98), "SYSTEM ALERT", F(32, 820), (255, 224, 224), 4)
    d.text((LW - 64, 98), "now", font=F(28, 500), fill=(255, 210, 210), anchor="rs")
    fill_rect(img, (64, 146, LW - 64, 149), (255, 190, 190), 0.6)
    t1, t2 = "NEW MODEL.", "BETTER AT EVERYTHING."
    d.text((LW / 2, 420), t1, font=fit(t1, LW - 120, 210, 900), fill=WHITE, anchor="ms")
    d.text((LW / 2, 590), t2, font=fit(t2, LW - 120, 116, 880), fill=WHITE, anchor="ms")
    d.text((LW / 2, 700), "Your current skills are now legacy.", font=F(30, 600), fill=(255, 205, 205), anchor="ms")
    return img


def lap_takeover(f):
    age = f - E["notif_better"]
    if age == 0:
        return Image.new("RGB", (LW, LH), WHITE)
    img = takeover_base()
    if age == 1:
        return Image.blend(img, Image.new("RGB", (LW, LH), WHITE), 0.6)
    if age <= 4:                                   # deliberate 3-frame glitch entrance, then rock solid
        rng = frng("takeover", f)
        k = 1 - (age - 2) / 3
        jx, jy = rng.randint(-40, 40) * k, rng.randint(-16, 16) * k
        out = Image.new("RGB", (LW, LH), (120, 8, 14))
        out.paste(img, (int(jx), int(jy)))
        out = glitch(out, rng, n=int(5 + 8 * k), maxshift=int(140 * k) + 10, split=int(12 * k) + 2)
        if age == 3:
            out = ImageOps.invert(out)
        return out
    return img.copy()


# --- agent builder (builder_start .. dashboard_start) -------------------------
BUILD_NODES = [  # name, type, column, centre y
    ("YOU", "INPUT", 0, 440),
    ("READ ALL PAPERS", "TOOL", 1, 270),
    ("TUTORIALS @16x", "TOOL", 1, 580),
    ("SUMMARIZE", "LLM", 2, 420),
    ("MEMORY (∞)", "MEMORY", 2, 640),
    ("PLANNER", "PLANNER", 3, 250),
    ("SELF-IMPROVE LOOP", "LOOP", 3, 500),
    ("SKILL TRACKER", "TOOL", 4, 230),
    ("OUTPUT: ROADMAP", "OUTPUT", 4, 450),
]
BUILD_EDGES = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (3, 5), (4, 6), (5, 6), (5, 7), (6, 8), (7, 8)]
NODE_W, NODE_H = 214, 104
COL_X = [36, 282, 528, 774, 1020]
TYPE_COL = {"INPUT": GREEN, "TOOL": BLUE, "LLM": VIOLET, "MEMORY": (236, 112, 200), "PLANNER": AMBER,
            "LOOP": ORANGE, "OUTPUT": CYAN}


def node_xy(i):
    _, _, c, cy = BUILD_NODES[i]
    return COL_X[c], cy - NODE_H / 2


@lru_cache(maxsize=1)
def blueprint_bg():
    img = Image.new("RGB", (LW, LH), (9, 30, 60))
    arr = np.asarray(img).copy()
    arr[:, ::40] = (14, 40, 76)
    arr[::40, :] = (14, 40, 76)
    arr[:, ::200] = (22, 58, 104)
    arr[::200, :] = (22, 58, 104)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    fill_rect(img, (0, LMENU, LW, LMENU + 64), (7, 20, 40))
    fill_rect(img, (0, LMENU + 63, LW, LMENU + 64), (30, 70, 120))
    icon(img, "bolt", 24, LMENU + 14, 36, CYAN)
    tracked(d, (72, LMENU + 44), "AGENT BUILDER", F(30, 820), WHITE, 3)
    return img


@lru_cache(maxsize=24)
def node_img(i, lit):
    name, typ, _, _ = BUILD_NODES[i]
    col = TYPE_COL[typ]
    im, pad = card(NODE_W, NODE_H, (18, 44, 80), (14, 36, 68), CYAN if lit else (100, 160, 220), r=16,
                   border=0.95 if lit else 0.6, bw=2.2, blur=10, op=0.6, dy=6)
    hdr = Image.new("RGBA", (NODE_W, 34), mix(col, (16, 40, 74), 0.35 if lit else 0.6) + (255,))
    m = rr_mask(NODE_W, NODE_H, 16).crop((0, 0, NODE_W, 34))
    hdr.putalpha(m)
    im.alpha_composite(hdr, (pad, pad))
    d = ImageDraw.Draw(im)
    tracked(d, (pad + 16, pad + 24), typ, F(16, 820), WHITE, 1.8)
    d.ellipse((pad + NODE_W - 28, pad + 10, pad + NODE_W - 14, pad + 24), fill=GREEN if lit else (60, 80, 100))
    d.text((pad + 16, pad + 70), name, font=fit(name, NODE_W - 30, 25, 780, 16), fill=WHITE, anchor="lm")
    for px in (pad, pad + NODE_W):
        d.ellipse((px - 8, pad + 62, px + 8, pad + 78), fill=CYAN, outline=(9, 30, 60), width=3)
    return im, pad


def edge_curve(a, b, t1=1.0):
    ax, ay = node_xy(a)
    bx, by = node_xy(b)
    o, i_ = (ax + NODE_W, ay + 70), (bx, by + 70)
    dx = max(70, (i_[0] - o[0]) * 0.5)
    return bezier(o, (o[0] + dx, o[1]), (i_[0] - dx, i_[1]), i_, n=40, t1=t1)


def lap_builder(f):
    img = blueprint_bg().copy()
    d = ImageDraw.Draw(img)
    parts = E["machine_parts"]
    spawned = [parts[i] if i < len(parts) else E["build_end"] for i in range(len(BUILD_NODES))]
    lit = f >= E["machine_lights"]
    n_built = sum(1 for sf in spawned if f >= sf)
    if n_built == 0:
        x0, y0, x1, y1 = 300, 300, 980, 540
        per = 2 * ((x1 - x0) + (y1 - y0))
        for p in range(0, per, 26):                # dashed drop zone
            pt = ((x0 + p, y0) if p < x1 - x0 else (x1, y0 + p - (x1 - x0)) if p < (x1 - x0) + (y1 - y0) else
                  (x1 - (p - (x1 - x0) - (y1 - y0)), y1) if p < 2 * (x1 - x0) + (y1 - y0) else
                  (x0, y1 - (p - 2 * (x1 - x0) - (y1 - y0))))
            fill_circle(img, pt[0], pt[1], 6, (100, 160, 220))
        d.text((640, 432), "+  Drop nodes here to build an agent", font=F(32, 650), fill=(160, 200, 240), anchor="mm")
    for a, b in BUILD_EDGES:                       # wires draw on
        t0 = max(spawned[a], spawned[b])
        if f < t0:
            continue
        pts = edge_curve(a, b, ease_out((f - t0 + 1) / 4))
        aa(img, CYAN, lambda dd, P, ss, pts=pts: dd.line([P(*p) for p in pts], fill=255, width=int(4 * ss), joint="curve"),
           box=(0, LMENU + 64, LW, LH), alpha=0.9 if lit else 0.6)
    if lit:                                         # data packets once the machine is lit
        for ei, (a, b) in enumerate(BUILD_EDGES):
            pts = edge_curve(a, b)
            for k in range(2):
                ph = ((f - E["machine_lights"]) * (0.07 + 0.04 * spd(f)) + ei * 0.31 + k * 0.5) % 1.0
                p = pts[int(ph * (len(pts) - 1))]
                fill_circle(img, p[0], p[1], 26, CYAN, 0.3)
                fill_circle(img, p[0], p[1], 13, WHITE)
    for i, sf in enumerate(spawned):               # nodes pop in on the machine_parts beats
        if f < sf:
            continue
        age = f - sf
        im, _ = node_img(i, lit)
        x, y = node_xy(i)
        place_c(img, im, x + NODE_W / 2, y + NODE_H / 2, enter_k(age, 4), dy=18, scale0=0.8)
    # status chip + deploy button
    if f < E["build_start"]:
        status = "Empty canvas"
    elif f <= E["build_end"]:
        status = f"Building…  {n_built} / {len(BUILD_NODES)} nodes"
    elif f < E["button_press"]:
        status = "Ready to deploy"
    else:
        status = "Deployed"
    fs = F(22, 700)
    sw = fs.getlength(status) + 40
    fill_rr(img, (LW - 24 - sw, LMENU + 14, LW - 24, LMENU + 50), 18, (12, 44, 66))
    d.text((LW - 24 - sw / 2, LMENU + 32), status, font=fs, fill=CYAN if f >= E["build_start"] else (130, 170, 215), anchor="mm")
    bx0, by0, bx1, by1 = 1020, 690, 1244, 770
    pressed = f >= E["button_press"]
    ready = f > E["build_end"]
    if ready and not pressed:
        glow = 0.35 + 0.3 * (0.5 + 0.5 * math.sin((f - E["build_end"]) * 0.5))
        fill_rr(img, (bx0 - 10, by0 - 10, bx1 + 10, by1 + 10), 26, CYAN, glow * 0.5)
    off = 4 if pressed else 0
    fill_rr(img, (bx0 + off, by0 + off, bx1 - off, by1 - off), 20, (12, 120, 140) if pressed else CYAN if ready else (40, 70, 100))
    d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "DEPLOY  ▶", font=F(30, 850),
           fill=(4, 30, 40) if ready else (110, 140, 170), anchor="mm")
    if pressed:                                     # AGENT ONLINE band
        age = f - E["button_press"]
        a = enter_k(age, 4)
        img = focus(img, 0.6 * a)
        d = ImageDraw.Draw(img)
        fill_rect(img, (0, 286, LW, 530), (2, 12, 22), 0.9 * a)
        fill_rect(img, (0, 286, LW, 290), CYAN, a)
        fill_rect(img, (0, 526, LW, 530), CYAN, a)
        label = "AGENT ONLINE"
        fnt = fit(label, LW - 300, 130, 860)
        tw = fnt.getlength(label)
        dot = 76
        x0 = (LW - (tw + 40 + dot)) / 2 + (1 - a) * 40
        d.text((x0, 408), label, font=fnt, fill=mix(BLACK, WHITE, a), anchor="lm")
        cx = x0 + tw + 40 + dot / 2
        fill_circle(img, cx, 408, dot * 1.7, CYAN, (0.16 + 0.1 * (0.5 + 0.5 * math.sin(age * 0.6))) * a)
        fill_circle(img, cx, 408, dot, CYAN, a)
    menubar(img, f, sc=LSC, app="Agent Builder", bell=None, bg=(5, 14, 28))
    return img


# --- calm dashboard + roadmap card (dashboard_start .. roadmap_open) ----------
CALM_W, CALM_H = 1000, 470
CALM_C = (LW / 2, 456)
OPEN_BTN = (CALM_W - 48 - 250, CALM_H - 48 - 84, CALM_W - 48, CALM_H - 48)     # card-local
CLICK = E["roadmap_open"] - 3                  # the cursor clicks OPEN
CURSOR_IN = CLICK - 6                           # ... after drifting in from the corner


@lru_cache(maxsize=1)
def dash_bg():
    img = Image.new("RGB", (LW, LH), (11, 14, 19))
    yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
    g = np.clip(1 - np.sqrt(((xx - LW / 2) / LW) ** 2 + ((yy - 300) / LH) ** 2) * 1.8, 0, 1) ** 2
    arr = np.asarray(img, np.float32) + g[..., None] * np.array([10, 34, 44], np.float32)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def dash_base(f):
    img = dash_bg().copy()
    d = ImageDraw.Draw(img)
    menubar(img, f, sc=LSC, app="Agent", bell=None)
    t = f - E["dashboard_start"]
    fill_circle(img, 58, 92, 18, CYAN, 0.65 + 0.35 * math.sin(f * 0.25))
    tracked(d, (84, 102), "AGENT · ONLINE", F(26, 820), CYAN, 3)
    d.text((84, 136), "agent_v8 · learning for you", font=F(20, 500), fill=TXT3, anchor="ls")
    cx, cy, R = LW / 2, 300, 74
    a0 = (f * 12) % 360

    def spin(dd, P, ss):
        x0, y0 = P(cx - R, cy - R)
        x1, y1 = P(cx + R, cy + R)
        dd.arc((x0, y0, x1, y1), 0, 360, fill=50, width=int(11 * ss))
        dd.arc((x0, y0, x1, y1), a0, a0 + 100, fill=255, width=int(11 * ss))
    aa(img, CYAN, spin, box=(cx - R - 12, cy - R - 12, cx + R + 12, cy + R + 12))
    d.text((LW / 2, 470), "Learning autonomously…", font=F(62, 760), fill=WHITE, anchor="ms")
    d.text((LW / 2, 516), "Sit back. Your agent is catching up for you.", font=F(26, 500), fill=TXT2, anchor="ms")
    found = int(T.ROADMAP_TOTAL * clamp((t + 1) / (E["notif_roadmap"] - E["dashboard_start"])) ** 0.8)
    stats = [("PAPERS READ", 1204 + t * 37), ("TUTORIALS @16x", 388 + t * 11), ("SKILLS FOUND", min(T.ROADMAP_TOTAL, found))]
    for i, (lab, val) in enumerate(stats):
        x0 = 110 + i * 360
        fill_rr(img, (x0, 576, x0 + 340, 724), 20, (20, 25, 33))
        ring_rr(img, (x0, 576, x0 + 340, 724), 20, 1.2, (40, 48, 62))
        tracked(d, (x0 + 28, 618), lab, F(17, 780), TXT3, 1.8)
        d.text((x0 + 28, 694), f"{val:,}", font=F(58, 800), fill=TXT, anchor="ls")
    return img


@lru_cache(maxsize=1)
def calm_card():
    im, pad = card(CALM_W, CALM_H, (32, 42, 58), (22, 29, 41), AGENT, r=R_HERO, border=0.6, bw=2.2,
                   blur=30, op=0.72, dy=16)
    d = ImageDraw.Draw(im)
    icon_tile(im, pad + 48, pad + 42, 76, (34, 170, 204), "route")
    tracked(d, (pad + 144, pad + 90), "YOUR AGENT", F(22, 800), (140, 220, 240), 2.6)
    d.text((pad + CALM_W - 48, pad + 90), "now", font=F(22, 500), fill=TXT2, anchor="rs")
    lines = ["YOUR PERSONALIZED AI", "LEARNING ROADMAP", "IS READY."]
    fnt = fit_lines(lines, CALM_W - 96, 68, 850)
    lh = fnt.size * 1.12
    for i, ln in enumerate(lines):
        d.text((pad + 48, pad + 196 + i * lh), ln, font=fnt, fill=WHITE, anchor="ls")
    d.text((pad + 48, pad + CALM_H - 52), f"{T.ROADMAP_TOTAL} skills · personalized for you", font=F(24, 550),
           fill=TXT2, anchor="ls")
    open_button(im, pad, "idle")
    return im, pad


def open_button(img, ox, state, oy=None):
    """Draw OPEN at card-local OPEN_BTN offset by (ox, oy): idle / hover / pressed."""
    oy = ox if oy is None else oy
    x0, y0, x1, y1 = OPEN_BTN
    inset = 4 if state == "pressed" else 0
    col = {"idle": CYAN, "hover": (150, 240, 255), "pressed": (20, 150, 180)}[state]
    box = (ox + x0 + inset, oy + y0 + inset, ox + x1 - inset, oy + y1 - inset)
    if isinstance(img, Image.Image) and img.mode == "RGBA":
        lay = Image.new("RGBA", (int(box[2] - box[0]), int(box[3] - box[1])), col + (255,))
        lay.putalpha(rr_mask(lay.width, lay.height, 22))
        img.alpha_composite(lay, (int(box[0]), int(box[1])))
    else:
        fill_rr(img, box, 22, col)
    ImageDraw.Draw(img).text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 + 1), "OPEN", font=F(36, 850),
                             fill=(4, 30, 40), anchor="mm")


def lap_dashboard(f):
    img = dash_base(f)
    if f < E["notif_roadmap"]:
        return img
    age = f - E["notif_roadmap"]
    k = enter_k(age)
    img = focus(img, 0.88 * k, blur=12, keep=0.34)
    im, pad = calm_card()
    place_c(img, im, CALM_C[0], CALM_C[1], k, dy=46, scale0=0.95)
    if k < 0.999:
        return img
    ox, oy = CALM_C[0] - CALM_W / 2, CALM_C[1] - CALM_H / 2
    bx0, by0, bx1, by1 = OPEN_BTN
    tip = (ox + (bx0 + bx1) / 2 + 14, oy + (by0 + by1) / 2 + 8)
    if f >= CLICK:
        open_button(img, ox, "pressed", oy)
        r = 14 + 34 * ease_out((f - CLICK + 1) / 3)
        a = 0.85 * (1 - clamp((f - CLICK) / 3))
        if a > 0.01:
            aa(img, WHITE, lambda dd, P, ss: dd.ellipse((*P(tip[0] - r, tip[1] - r), *P(tip[0] + r, tip[1] + r)),
                                                        outline=255, width=int(4 * ss)),
               box=(tip[0] - 60, tip[1] - 60, tip[0] + 60, tip[1] + 60), alpha=a)
    elif f >= CLICK - 1:
        open_button(img, ox, "hover", oy)
    if f >= CURSOR_IN:
        u = smooth((f - CURSOR_IN) / (CLICK - 1 - CURSOR_IN))
        start = (LW - 40, LH + 10)
        mx = lerp(start[0], tip[0], u) + math.sin(u * math.pi) * 40
        my = lerp(start[1], tip[1], u) + (2 if f >= CLICK else 0)
        draw_cursor(img, mx, my)
    return img


# --- roadmap (roadmap_open .. notif_obsolete) ---------------------------------
RM_HEAD = 380
RM_ROW = 72


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
    raw, acc = {}, 0.0
    for f in range(a, b + 1):
        acc += (spd(f) ** 2.1) * clamp((f - a + 1) / 6)
        raw[f] = acc
    k = (760 * RM_ROW) / acc                          # ~760 rows by the time it goes obsolete
    table, vel, prev = {}, {}, 0.0
    for f in range(E["roadmap_open"], b + 2):
        v = raw.get(min(f, b), 0.0) * k if f >= a else 0.0
        table[f], vel[f], prev = v, v - prev, v
    return table, vel


@lru_cache(maxsize=1)
def roadmap_header():
    img = Image.new("RGB", (LW, RM_HEAD), (12, 15, 21))
    d = ImageDraw.Draw(img)
    tracked(d, (56, 62), "YOUR AI LEARNING ROADMAP", F(26, 820), (150, 186, 255), 3.4)
    num, lab = f"0 / {T.ROADMAP_TOTAL}", ("SKILLS", "MASTERED")
    big = F(212, 880)
    nw = big.getlength(num)
    small = fit_lines(list(lab), LW - 56 - 56 - nw - 44, 84, 860, 40)
    d.text((48, 290), num, font=big, fill=WHITE, anchor="ls")
    x = 48 + nw + 44
    d.text((x, 290 - small.size * 1.0), lab[0], font=small, fill=WHITE, anchor="ls")
    d.text((x, 290), lab[1], font=small, fill=WHITE, anchor="ls")
    fill_rr(img, (56, 318, LW - 150, 346), 14, (36, 42, 56))
    fill_rr(img, (56, 318, 72, 346), 8, (70, 80, 100))
    d.text((LW - 56, 346), "0%", font=F(44, 850), fill=WHITE, anchor="rs")
    fill_rect(img, (0, RM_HEAD - 2, LW, RM_HEAD), LINE)
    return img


def roadmap_list(scroll, vel):
    """The list viewport (LW x LH-RM_HEAD) at a given scroll offset, with speed blur."""
    items, tags = roadmap_items()
    h = LH - RM_HEAD
    img = Image.new("RGB", (LW, h), (16, 19, 26))
    d = ImageDraw.Draw(img)
    first = int(scroll // RM_ROW)
    off = scroll - first * RM_ROW
    fnum, fname, ftag = F(24, 650), F(32, 620), F(18, 780)
    for k in range(int(h / RM_ROW) + 2):
        i = first + k
        if i >= len(items):
            break
        y = k * RM_ROW - off
        cy = y + RM_ROW / 2
        if i % 2 == 0:
            fill_rect(img, (0, y, LW, y + RM_ROW), (20, 24, 32))
        d.text((118, cy), f"{i + 1}.", font=fnum, fill=TXT3, anchor="rm")
        ring_rr(img, (138, cy - 17, 172, cy + 17), 8, 2.6, (128, 140, 164))
        d.text((196, cy + 1), ellipsize(items[i], fname, 760), font=fname, fill=TXT, anchor="lm")
        tg = tags[i]
        if tg.startswith("est."):
            d.text((LW - 72, cy), tg, font=F(21, 550), fill=TXT3, anchor="rm")
        else:
            col = {"NEW": GREEN, "UPDATED": BLUE, "DEPRECATED?": AMBER}[tg]
            tw = ftag.getlength(tg) + 26
            fill_rr(img, (LW - 72 - tw, cy - 15, LW - 72, cy + 15), 8, mix(col, (16, 19, 26), 0.75))
            d.text((LW - 72 - tw / 2, cy), tg, font=ftag, fill=col, anchor="mm")
    if vel > 6:
        sharp = np.asarray(img, np.float32)
        blur = vblur_arr(sharp, min(vel * 0.8, 150))
        k = clamp((vel - 6) / 120) * 0.7
        img = Image.fromarray((sharp * (1 - k) + blur * k).clip(0, 255).astype(np.uint8))
    total_h = len(items) * RM_ROW
    track = (LW - 30, 12, LW - 20, h - 12)
    fill_rr(img, track, 5, (34, 40, 52))
    th = max(10, (track[3] - track[1]) * h / total_h)
    ty = track[1] + (track[3] - track[1] - th) * clamp(scroll / (total_h - h))
    fill_rr(img, (track[0] - 1, ty, track[2] + 1, ty + th), 5, (190, 200, 220))
    return img, ty


@lru_cache(maxsize=1)
def print_feed_table():
    """Paper fed per frame (px) from print_start; shared by the monitor and the laptop chip."""
    tab, vel, acc = {}, {}, 0.0
    for f in range(E["print_start"], E["notif_obsolete"] + 1):
        v = 4 + 1250 * spd(f) ** 2.2 if f >= E["print_start"] + 2 else 0.0
        acc += v
        tab[f], vel[f] = acc, v
    return tab, vel


PRINT_ROW = 40
PRINT_ROWS_PAGE = 26
PRINT_PAGE_H = PRINT_ROW * PRINT_ROWS_PAGE


def print_page(f):
    tab, _ = print_feed_table()
    ff = max(E["print_start"], min(f, E["notif_obsolete"] - 1))
    return int(tab.get(ff, 0.0) // PRINT_PAGE_H) + 1


@lru_cache(maxsize=64)
def print_chip(page):
    fnt, fnt2 = F(24, 800), F(24, 650)
    t1, t2 = "PRINTING…", f"page {page} of ∞"
    w = int(fnt.getlength(t1) + fnt2.getlength(t2)) + 104
    im, pad = card(w, 52, (30, 38, 52), (24, 30, 42), AGENT, r=26, border=0.55, bw=1.6, blur=8, op=0.5, dy=4)
    d = ImageDraw.Draw(im)
    im.alpha_composite(icon_layer("paper", 26, AGENT), (pad + 20, pad + 13))
    d.text((pad + 58, pad + 27), t1, font=fnt, fill=WHITE, anchor="lm")
    d.text((pad + 58 + fnt.getlength(t1) + 14, pad + 27), t2, font=fnt2, fill=AGENT, anchor="lm")
    return im, pad


def roadmap_view(f, freeze=False):
    table, vel = roadmap_scroll_table()
    ff = min(f, E["notif_obsolete"] - 1)
    sc = table.get(ff, 0.0)
    img = Image.new("RGB", (LW, LH))
    img.paste(roadmap_header(), (0, 0))
    lst, ty = roadmap_list(sc, 0.0 if freeze else vel.get(ff, 0.0))
    img.paste(lst, (0, RM_HEAD))
    d = ImageDraw.Draw(img)
    if not freeze and f >= E["scroll_start"]:
        lab = f"#{int(sc // RM_ROW) + 1} / {T.ROADMAP_TOTAL}"
        fnt = F(24, 800)
        w = fnt.getlength(lab) + 32
        y = RM_HEAD + ty - 10
        fill_rr(img, (LW - 46 - w, y, LW - 46, y + 40), 20, (44, 52, 70))
        d.text((LW - 46 - w / 2, y + 20), lab, font=fnt, fill=WHITE, anchor="mm")
    if f >= E["print_start"]:
        im, pad = print_chip(print_page(ff))
        w = im.width - 2 * pad
        place_c(img, im, LW - 40 - w / 2, 54, enter_k(f - E["print_start"]), dy=-24)
    return img


@lru_cache(maxsize=1)
def roadmap_from():
    return lap_dashboard(E["roadmap_open"] - 1)


def lap_roadmap(f):
    img = roadmap_view(f)
    age = f - E["roadmap_open"]
    if age < 5:                                      # opens with an eased slide + fade, then holds still
        k = enter_k(age, 5)
        shift = int(round((1 - k) * 30))
        moved = roadmap_from().copy()
        moved.paste(img.crop((0, 0, LW, LH - shift)), (0, shift))
        return Image.blend(roadmap_from(), moved, min(1.0, k * 1.6))
    return img


# --- NEW RELEASE. ROADMAP OBSOLETE. (notif_obsolete .. close_laptop) -----------
OBS_BAND = (372, 790)


@lru_cache(maxsize=1)
def obsolete_back():
    img = dim(gray(roadmap_view(E["notif_obsolete"] - 1, freeze=True)), 0.42)
    yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
    v = np.clip(np.sqrt(((xx - LW / 2) / LW) ** 2 + ((yy - LH / 2) / LH) ** 2) * 1.6 - 0.25, 0, 1)[..., None]
    arr = np.asarray(img, np.float32) * (1 - 0.35 * v) + v * np.array([60, 0, 4], np.float32) * 0.6
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


@lru_cache(maxsize=1)
def stamp_img():
    txt = "OBSOLETE"
    fnt = F(150, 900)
    w = int(fnt.getlength(txt)) + 120
    h = 230
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((8, 8, w - 8, h - 8), radius=24, outline=255, width=16)
    d.text((w / 2, h / 2 + 6), txt, font=fnt, fill=255, anchor="mm")
    rng = np.random.default_rng(492)
    noise = np.kron(rng.random((h // 3 + 1, w // 3 + 1)), np.ones((3, 3)))[:h, :w]
    arr = np.asarray(m, np.float32) * (0.62 + 0.38 * (noise > 0.2))
    m = Image.fromarray(arr.astype(np.uint8)).rotate(9, expand=True, resample=Image.BICUBIC)
    im = Image.new("RGBA", m.size, (238, 56, 60, 0))
    im.putalpha(m)
    return im


@lru_cache(maxsize=1)
def obsolete_band():
    y0, y1 = OBS_BAND
    h = y1 - y0
    band = Image.new("RGBA", (LW, h + 40), (0, 0, 0, 0))
    sh = Image.new("L", (LW, h + 40), 0)
    ImageDraw.Draw(sh).rectangle((0, 20, LW, h + 20), fill=150)
    band.putalpha(sh.filter(ImageFilter.GaussianBlur(14)))
    body = vgrad(LW, h, (236, 40, 48), (188, 18, 28)).convert("RGBA")
    band.alpha_composite(body, (0, 20))
    d = ImageDraw.Draw(band)
    fill = Image.new("RGBA", (LW, 4), (255, 200, 200, 255))
    band.alpha_composite(fill, (0, 20))
    band.alpha_composite(fill, (0, 20 + h - 4))
    band.alpha_composite(icon_layer("warn", 40, WHITE), (60, 20 + 34))
    tracked(d, (116, 20 + 68), "RELEASE ALERT", F(26, 820), (255, 226, 226), 3.4)
    d.text((LW - 60, 20 + 68), "now", font=F(26, 500), fill=(255, 215, 215), anchor="rs")
    t1, t2 = "NEW RELEASE.", "ROADMAP OBSOLETE."
    f1 = fit(t1, LW - 110, 150, 900)
    f2 = fit(t2, LW - 110, 128, 900)
    d.text((LW / 2, 20 + 226), t1, font=f1, fill=WHITE, anchor="ms")
    d.text((LW / 2, 20 + 362), t2, font=f2, fill=WHITE, anchor="ms")
    return band


def obsolete_frame(age):
    img = obsolete_back().copy()
    st = stamp_img()
    a = min(age, 2)                                   # 3-frame entrance, then perfectly still
    sc = [1.45, 1.12, 1.0][a]
    s2 = st.resize((int(st.width * sc), int(st.height * sc)), Image.BICUBIC) if sc != 1.0 else st
    paste_rgba(img, s2, LW / 2 - s2.width / 2, 196 - s2.height / 2, opacity=[0.55, 0.9, 0.95][a])
    band = obsolete_band()
    paste_rgba(img, band, 0, OBS_BAND[0] - 20 + [70, 14, 0][a], opacity=[0.7, 1.0, 1.0][a])
    if a < 2:
        img = Image.blend(img, Image.new("RGB", img.size, WHITE), [0.3, 0.1][a])
    return img


def lap_obsolete(f):
    return obsolete_frame(f - E["notif_obsolete"])


# --- the lid reopens: frantic (yank+5 .. black) --------------------------------
@lru_cache(maxsize=1)
def frantic_banner():
    h = 124
    band = Image.new("RGBA", (LW, h + 30), (0, 0, 0, 0))
    sh = Image.new("L", (LW, h + 30), 0)
    ImageDraw.Draw(sh).rectangle((0, 15, LW, h + 15), fill=170)
    band.putalpha(sh.filter(ImageFilter.GaussianBlur(10)))
    band.alpha_composite(vgrad(LW, h, (236, 40, 48), (190, 18, 28)).convert("RGBA"), (0, 15))
    d = ImageDraw.Draw(band)
    band.alpha_composite(icon_layer("bolt", 52, WHITE), (40, 15 + 36))
    txt = "NEW MODEL RELEASED · 10X FASTER"
    d.text((LW / 2 + 30, 15 + h / 2 + 2), txt, font=fit(txt, LW - 160, 66, 880), fill=WHITE, anchor="mm")
    return band


def lap_frantic(f):
    age = f - B["reopen"]
    ph = 30.0 + age * 1.6
    idx = int(ph)
    img = smear_stack(tut_slide(idx).copy(), idx, 1.0, trail=((0.3, -70), (0.22, -150), (0.14, -240), (0.08, -340)))
    tut_overlays(img, f, ph, 1.0)
    img = glitch(img, frng("frantic", f), n=10, maxshift=180, split=10)     # deliberate: the video can't keep up
    draw_badge(img, "32x", True, age)
    band = frantic_banner()
    k = enter_k(age, 4)
    paste_rgba(img, band, 0, LH - 168 - 15 + (1 - k) * 120, opacity=min(1.0, k * 1.3))
    return img


def laptop_frame(f):
    if E["close_laptop"] <= f < B["reopen"] or f >= E["black"]:
        return Image.new("RGB", (LW, LH), BLACK)
    if f >= B["reopen"]:
        return lap_frantic(f)
    if f < E["tutorial_2x"]:
        return lap_course(f)
    if f < E["notif_do_that"]:
        return lap_tutorial(f)
    if f < E["notif_better"]:
        return lap_hero(f)
    if f < E["builder_start"]:
        return lap_takeover(f)
    if f < E["dashboard_start"]:
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
    tracked(d, (1064, 640), "TODAY'S GOAL", F(20, 820), (130, 170, 235), 2.6)
    ring_rr(img, (1064, 676, 1120, 732), 12, 3.5, (140, 150, 170))
    d.text((1142, 706), "Learn AI.", font=F(76, 800), fill=WHITE, anchor="lm")
    d.text((1064, 800), "Day 1 · plenty of time", font=F(26, 550), fill=TXT2, anchor="ls")
    d.text((1064, 846), "Next: take it slow.", font=F(26, 550), fill=TXT3, anchor="ls")
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
    top = draw_window(img, box, "terminal — learn_ai", body=(12, 13, 16), bar=(22, 23, 28), sc=1.15)
    d = ImageDraw.Draw(img)
    lines, table, names, vers, _ = term_table()
    n, prog, pi, _ = table[min(f, E["notif_do_that"] - 1)]
    fm = MONO(20)
    lh = 29
    blocks = int(prog * 16)
    cur = [(f"installing {names[pi]} {vers[pi]} …", TXT),
           (f"[{'█' * blocks}{'░' * (16 - blocks)}] {int(prog * 100):3d}%", CYAN)]
    shown = (lines[:n] + cur)[-int((y1 - top - 20) / lh):]
    for i, (t, col) in enumerate(shown):
        d.text((x0 + 20, top + 24 + i * lh), ellipsize(t, fm, x1 - x0 - 34), font=fm, fill=col, anchor="lm")


def draw_bench(img, box, f):
    x0, y0, x1, y1 = box
    fill_rr(img, box, 14, (20, 22, 28))
    ring_rr(img, box, 14, 1.2, (40, 44, 54))
    d = ImageDraw.Draw(img)
    tracked(d, (x0 + 24, y0 + 40), "LEADERBOARD", F(19, 820), TXT2, 2.4)
    d.text((x1 - 24, y0 + 40), "score ↑", font=F(19, 550), fill=TXT3, anchor="rs")
    _, table, _, _, bars = term_table()
    nb = table[min(f, E["notif_do_that"] - 1)][3]
    hist = [(None, 1.0 / 1.42 ** k) for k in range(4, 0, -1)] + bars[:nb]
    vis = hist[-7:]
    if not vis:
        return
    last_f = vis[-1][0]
    grow = ease_out((f - last_f + 1) / 5) if last_f is not None else 1.0
    hmax_new = vis[-1][1]
    hmax_old = max(v[1] for v in vis[:-1]) if len(vis) > 1 else hmax_new
    hmax = lerp(hmax_old, hmax_new, grow) * 1.08
    gx0, gx1, gy0, gy1 = x0 + 30, x1 - 26, y0 + 64, y1 - 46
    for k in range(4):
        gy = gy1 - (gy1 - gy0) * k / 3
        fill_rect(img, (gx0, gy, gx1, gy + 1), (36, 40, 50))
    bw = (gx1 - gx0) / len(vis)
    for i, (bf, h) in enumerate(vis):
        newest = i == len(vis) - 1
        hh = (gy1 - gy0) * h / hmax * (grow if newest else 1.0)
        bx = gx0 + i * bw + bw * 0.16
        fill_rr(img, (bx, gy1 - max(4, hh), bx + bw * 0.68, gy1), 5,
                RED if newest else (70, 110, 190) if i >= len(vis) - 3 else (60, 66, 82))
        lab = "NEW" if newest else f"m{len(hist) - len(vis) + i + 1}"
        d.text((bx + bw * 0.34, gy1 + 24), lab, font=F(17, 820 if newest else 550), fill=RED if newest else TXT3, anchor="mm")


@lru_cache(maxsize=16)
def mon_popup(text):
    w, h = 400, 88
    im, pad = card(w, h, (40, 44, 56), (32, 35, 45), WARN, r=18, border=0.6, bw=1.6, blur=14, op=0.6, dy=8)
    icon_tile(im, pad + 16, pad + 16, 56, WARN, "warn", fg=(40, 26, 0))
    ImageDraw.Draw(im).text((pad + 90, pad + h / 2 + 1), text, font=fit(text, w - 110, 28, 760, 18), fill=WHITE, anchor="lm")
    return im, pad


def mon_code(f):
    img = Image.new("RGB", (MW, MH), (14, 15, 19))
    d = ImageDraw.Draw(img)
    corp = code_corpus()
    phase = chv("typing_phase", f)
    nfl = phase * 1.7
    L = int(nfl)
    ver = min(len(VERSIONS) - 1, int(nfl / 11))
    ex0, ex1 = 0, 960
    draw_editor_tabs(img, (ex0, MMENU, ex1, MMENU + 46), VERSIONS[:ver + 1], ver, big=True)
    fm = MONO(20)
    cw = fm.getlength("M")
    lh = 27
    cy0 = MMENU + 64
    vis = int((MH - 36 - cy0) / lh)
    top = max(0, L - vis + 4)
    fill_rect(img, (ex0, cy0 - 10, ex0 + 70, MH - 36), (17, 18, 23))
    for i in range(vis):
        li = top + i
        if li > L:
            break
        y = cy0 + i * lh + lh / 2
        line = corp[li % len(corp)]
        d.text((ex0 + 58, y), str(li + 1), font=MONO(16), fill=TXT3 if li != L else TXT, anchor="rm")
        if li == L:
            fill_rect(img, (ex0 + 70, y - lh / 2, ex1, y + lh / 2), (28, 31, 40))
            n = int((nfl - L) * len(line))
            draw_code_line(d, ex0 + 84, y, line, fm, cw, max_chars=n, anchor="lm")
            fill_rect(img, (ex0 + 84 + n * cw, y - 12, ex0 + 87 + n * cw, y + 12), WHITE)
        else:
            draw_code_line(d, ex0 + 84, y, line, fm, cw, anchor="lm")
    warn = int(chv("stress", f) * 180)
    fill_rect(img, (ex0, MH - 36, ex1, MH), (36, 84, 190))
    d.text((ex0 + 16, MH - 18), f"Ln {L + 1}   ·   ⚠ {warn} warnings", font=F(18, 650), fill=WHITE, anchor="lm")
    d.text((ex1 - 16, MH - 18), "agentflow 0.1 (deprecated)", font=F(18, 650), fill=(255, 222, 165), anchor="rm")
    fill_rect(img, (ex1, MMENU, ex1 + 1, MH), LINE)
    draw_terminal(img, (972, MMENU + 10, 1590, 560), f)
    draw_bench(img, (972, 574, 1590, 890), f)
    # update popups pile up with speed (big, at most four)
    s = spd(f)
    for k in range(min(4, int(max(0, s - 0.5) * 10))):
        r2 = frng("monpopk", k)
        im, pad = mon_popup(r2.choice(["Update available", "New version!", "Restart required",
                                       "Breaking change", "Docs updated"]))
        paste_rgba(img, im, 120 + k * 120 + r2.randint(0, 60) - pad, 170 + k * 130 + r2.randint(0, 40) - pad)
    menubar(img, f, sc=MSC, app="Code")
    return img


@lru_cache(maxsize=1)
def mon_final_code():
    img = Image.new("RGB", (MW, MH), (14, 15, 19))
    d = ImageDraw.Draw(img)
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
    fm = MONO(18)
    cw = fm.getlength("M")
    lh = 21
    cy0 = MMENU + 72
    lines = code_final()[-int((MH - 60 - cy0) / lh):]
    first = 4812 - len(lines) + 1
    fill_rect(img, (0, cy0 - 10, 80, MH - 52), (17, 18, 23))
    for i, ln in enumerate(lines):
        y = cy0 + i * lh + lh / 2
        d.text((68, y), f"{first + i:,}", font=MONO(14), fill=TXT3, anchor="rm")
        draw_code_line(d, 96, y, ln, fm, cw, anchor="lm")
    mx0 = MW - 128
    fill_rect(img, (mx0 - 8, MMENU + 60, MW, MH - 52), (17, 18, 23))
    rng = random.Random(9)
    for y in range(MMENU + 66, MH - 58, 2):
        w = rng.randint(10, 100) if rng.random() > 0.15 else 0
        ind = rng.choice([0, 0, 8, 16, 24])
        col = rng.choice([(70, 80, 100), (90, 70, 110), (60, 100, 80), (110, 100, 70)])
        if w:
            fill_rect(img, (mx0 + ind, y, mx0 + ind + w * 0.8, y + 1), col)
    fill_rect(img, (mx0 - 6, MH - 52 - 30, MW - 4, MH - 54), (120, 140, 180), 0.25)
    fill_rect(img, (0, MH - 52, MW, MH), (36, 84, 190))
    d.text((20, MH - 26), "4,812 lines  ·  9 hours", font=F(30, 820), fill=WHITE, anchor="lm")
    d.text((MW - 20, MH - 26), "Ln 4,812   ·   ✓ all tests passed   ·   saved", font=F(20, 650),
           fill=(225, 235, 255), anchor="rm")
    menubar(img, E["code_done"], sc=MSC, app="Code")
    return img


@lru_cache(maxsize=1)
def mon_final_back():
    return focus(mon_final_code(), 1.0, blur=8, keep=0.45)


@lru_cache(maxsize=1)
def mon_done_card():
    w, h = 1120, 400
    im, pad = card(w, h, (48, 106, 222), (30, 76, 180), (180, 210, 255), r=R_HERO, border=0.75, bw=2.5,
                   blur=30, op=0.72, dy=16)
    d = ImageDraw.Draw(im)
    icon(im, "dot", pad + 52, pad + 44, 26, (250, 204, 80))
    d.text((pad + 92, pad + 58), "agent_v7_final_FINAL.py", font=F(32, 720), fill=(225, 236, 255), anchor="lm")
    d.text((pad + w - 52, pad + 58), "saved", font=F(28, 550), fill=(200, 220, 255), anchor="rm")
    t1 = "4,812 LINES"
    t2 = "9 HOURS"
    f1 = fit_lines([t1], w - 120, 132, 880)
    d.text((pad + 52, pad + 210), t1, font=f1, fill=WHITE, anchor="ls")
    d.text((pad + 52, pad + 320), t2, font=fit_lines([t2], w - 120, 96, 860), fill=WHITE, anchor="ls")
    d.text((pad + w - 52, pad + 320), "✓ ALL TESTS PASSED", font=F(34, 780), fill=(220, 255, 228), anchor="rs")
    return im, pad


def mon_done(f):
    k = enter_k(f - E["code_done"], 5)
    img = Image.blend(mon_final_code(), mon_final_back(), k) if k < 0.999 else mon_final_back().copy()
    im, _ = mon_done_card()
    place_c(img, im, MW / 2, MH / 2 + 12, k, dy=40, scale0=0.95)
    return img


@lru_cache(maxsize=1)
def mon_final():
    return mon_done(E["code_done"] + ENTER)


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
        ImageDraw.Draw(img).text((MW / 2 + rng.randint(-30, 30), MH / 2), "NEW MODEL.", font=F(190, 900),
                                 fill=(255, 210, 210), anchor="mm")
    return img


# --- telemetry (builder_start .. print_start) ---------------------------------
TELEM_LOG = ["compiling skills graph", "ingesting 1,204 papers", "watching tutorials @16x", "summarizing summaries",
             "pruning outdated knowledge", "self-improving (iteration 3)", "allocating memory (∞)",
             "deploying to node 0x2F", "agent online", "learning autonomously", "reading release notes",
             "ranking 847 skills", "drafting roadmap…", "roadmap ready ✓", "opening roadmap", "sending to printer…"]


@lru_cache(maxsize=1)
def telemetry_bg():
    img = Image.new("RGB", (MW, MH), (4, 13, 21))
    arr = np.asarray(img).copy()
    arr[MMENU::48, :] = (8, 26, 38)
    arr[:, ::48] = (8, 26, 38)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    tracked(d, (52, 92), "AGENT TELEMETRY", F(26, 820), CYAN, 3.4)
    d.text((MW - 52, 92), "agent_v8  ·  uplink ok", font=F(22, 550), fill=(100, 160, 180), anchor="rs")
    for x0, y0, x1, y1, lab in ((48, 300, 780, 590, "LOSS"), (820, 300, 1552, 590, "THROUGHPUT"),
                                (48, 620, 780, 876, "LOG"), (820, 620, 1552, 876, "ACTIVATIONS")):
        fill_rr(img, (x0, y0, x1, y1), 16, (6, 22, 34))
        ring_rr(img, (x0, y0, x1, y1), 16, 1.4, (20, 70, 90))
        tracked(d, (x0 + 24, y0 + 38), lab, F(19, 820), (100, 180, 200), 2.4)
    return img


def mon_telemetry(f):
    img = telemetry_bg().copy()
    d = ImageDraw.Draw(img)
    online = f >= E["button_press"]
    t0, t1 = E["idea"], E["button_press"]
    prog = clamp((f - t0) / (t1 - t0))
    if not online:
        dots = "." * (1 + (f // 6) % 3)
        d.text((48, 210), "TRAINING AGENT" + dots, font=F(96, 830), fill=(220, 250, 255), anchor="ls")
        fill_rr(img, (52, 238, 1060, 262), 12, (14, 40, 56))
        fill_rr(img, (52, 238, 52 + 1008 * prog, 262), 12, CYAN)
        d.text((1084, 264), f"{int(prog * 100)}%", font=F(40, 820), fill=CYAN, anchor="ls")
    else:
        age = f - t1
        fnt = F(150, 860)
        x = 48 + (1 - enter_k(age)) * 30
        d.text((x, 248), "ONLINE", font=fnt, fill=CYAN, anchor="ls")
        x += fnt.getlength("ONLINE") + 44
        fill_circle(img, x + 44, 196, 140, CYAN, 0.15 + 0.12 * (0.5 + 0.5 * math.sin(age * 0.4)))
        fill_circle(img, x + 44, 196, 84, CYAN)
        if f >= E["lean_back"]:
            d.text((x + 132, 220), "learning autonomously", font=F(38, 650), fill=(160, 225, 240), anchor="ls")
    # loss curve: drawn while training, then flat and calm
    x0, y0, x1, y1 = 72, 360, 756, 570
    n = 160
    upto = n if online else int(n * prog)
    rng = random.Random(55)
    pts = []
    for i in range(n):
        v = math.exp(-i / 30) * 0.85 + 0.08 + rng.uniform(-0.03, 0.03) * math.exp(-i / 80)
        pts.append((x0 + (x1 - x0) * i / (n - 1), y1 - (y1 - y0) * v))
    if upto > 1:
        aa(img, CYAN, lambda dd, P, ss: dd.line([P(*p) for p in pts[:upto]], fill=255, width=int(4 * ss), joint="curve"),
           box=(60, 350, 770, 580))
        fill_circle(img, pts[upto - 1][0], pts[upto - 1][1], 16, WHITE)
    s = spd(f)
    bx0, by1 = 846, 570
    for i in range(36):
        k = f - 35 + i
        hh = 30 + 170 * clamp(0.25 + 0.75 * spd(k) * (0.6 + 0.4 * frng("tp", k).random()))
        fill_rect(img, (bx0 + i * 19, by1 - hh, bx0 + i * 19 + 12, by1), CYAN if i == 35 else (30, 130, 160))
    d.text((1528, 344), f"{int(4000 + 52000 * s):,} tok/s", font=F(34, 820), fill=CYAN, anchor="rs")
    nlog = int(clamp((f - t0) / (E["print_start"] - t0)) * (len(TELEM_LOG) - 1)) + 1
    for i, ln in enumerate(TELEM_LOG[:nlog][-6:]):
        d.text((72, 690 + i * 31), f"› {ln}", font=MONO(22), fill=(130, 210, 225), anchor="lm")
    for gy in range(5):
        for gx in range(18):
            a = clamp(0.15 + frng("act", gx, gy, f // 2).random() * (0.4 + 0.6 * s))
            fill_rect(img, (848 + gx * 38, 680 + gy * 38, 848 + gx * 38 + 30, 680 + gy * 38 + 30), CYAN, a * 0.8)
    menubar(img, f, sc=MSC, app="Telemetry", bg=(3, 10, 16))
    return img


# --- printing (print_start .. notif_obsolete) ---------------------------------
def paper_strip(off, h, w=700):
    """Printed paper strip, content scrolled by `off` px (content moves down as it feeds)."""
    items, _ = roadmap_items()
    img = Image.new("RGB", (w, h), (244, 243, 238))
    d = ImageDraw.Draw(img)
    fnt = F(24, 600)
    p_top = off - h
    r0 = int(max(0, p_top) // PRINT_ROW)
    r1 = int(off // PRINT_ROW) + 1
    for r in range(r0, r1 + 1):
        y = off - r * PRINT_ROW
        pg, rp = divmod(r, PRINT_ROWS_PAGE)
        if rp < 2:
            if rp == 0:
                for x in range(10, w - 10, 18):
                    d.line((x, y, x + 9, y), fill=(170, 170, 165), width=2)
                d.text((w / 2, y - 24), f"— page {pg + 1} —", font=F(18, 650), fill=(120, 120, 120), anchor="mm")
            continue
        idx = (pg * (PRINT_ROWS_PAGE - 2) + rp - 2) % len(items)
        d.rectangle((40, y - 17, 60, y + 3), outline=(60, 60, 64), width=3)
        d.text((78, y), ellipsize(f"{idx + 1}.  {items[idx]}", fnt, w - 100), font=fnt, fill=(36, 36, 42), anchor="ls")
    return img


def mon_print(f, freeze=False):
    img = Image.new("RGB", (MW, MH), (12, 13, 17))
    d = ImageDraw.Draw(img)
    tab, vel = print_feed_table()
    ff = max(E["print_start"], min(f, E["notif_obsolete"] - 1))
    off = tab.get(ff, 0.0) + 900
    v = 0.0 if freeze else vel.get(ff, 0.0)
    page = print_page(ff)
    d.text((72, 170), "PRINTING", font=F(120, 850), fill=WHITE, anchor="ls")
    d.text((72, 290), "ROADMAP…", font=F(120, 850), fill=WHITE, anchor="ls")
    d.text((76, 380), f"page {page} of ∞", font=F(64, 760), fill=AGENT, anchor="ls")
    d.text((76, 436), f"{T.ROADMAP_TOTAL} skills  ·  toner 12%", font=F(26, 550), fill=TXT3, anchor="ls")
    fill_rr(img, (76, 492, 720, 516), 12, (34, 38, 48))
    seg = (f * 18) % 800 - 160
    if seg + 160 > 0:
        fill_rr(img, (76 + max(0, seg), 492, 76 + min(644, seg + 160), 516), 12, CYAN)
    d.text((76, 584), "Estimated time remaining:", font=F(30, 550), fill=TXT2, anchor="ls")
    d.text((76, 640), "calculating…", font=F(44, 760), fill=WHITE, anchor="ls")
    sx0, sx1, sy = 820, 1540, 120
    fill_rr(img, (sx0 - 20, sy - 40, sx1 + 20, sy + 30), 18, (34, 36, 44))
    fill_rr(img, (sx0, sy - 6, sx1, sy + 10), 6, (6, 6, 8))
    fill_circle(img, sx1 - 10, sy - 24, 14, GREEN)
    strip = paper_strip(off, MH - sy, sx1 - sx0 - 40)
    if v > 6:
        sharp = np.asarray(strip, np.float32)
        bl = vblur_arr(sharp, min(v * 0.8, 160))
        k = clamp((v - 6) / 100) * 0.75
        strip = Image.fromarray((sharp * (1 - k) + bl * k).clip(0, 255).astype(np.uint8))
    img.paste(strip, (sx0 + 20, sy + 4))
    g = Image.fromarray((np.linspace(140, 0, 40)[:, None] * np.ones((1, strip.width))).astype(np.uint8))
    img.paste((0, 0, 0), (sx0 + 20, sy + 4, sx0 + 20 + strip.width, sy + 44), g)
    menubar(img, f, sc=MSC, app="Print")
    if not freeze and f - E["print_start"] < ENTER:      # telemetry dims out as the print view slides in
        k = enter_k(f - E["print_start"])
        base = dim(mon_telemetry(E["print_start"] - 1), (1 - k) ** 2)
        shift = int(round((1 - k) * 30))
        moved = base.copy()
        moved.paste(img.crop((0, 0, MW, MH - shift)), (0, shift))
        img = Image.blend(base, moved, min(1.0, k * 1.6))
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
    if f < E["code_done"]:
        return mon_code(f)
    if f < E["notif_better"]:
        return mon_done(f)
    if f < E["builder_start"]:
        return mon_glitch(f)
    if f < E["print_start"]:
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
    a0, span = E["scrib_start"], E["scrib_end"] - E["scrib_start"] + 1

    def W(s_, e_):
        # sub-windows authored on a 47-frame reference span, rescaled to E['scrib_start']..E['scrib_end']
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
# PRINTED ROADMAP PAPER  (thermal printout for the physical scroll)
# =============================================================================
# head: 512 x 1536, the START of the printout (top edge = first paper out)
# tile: 512 x 2048, the list continued, seamless vertically.  The paper tone and
# ink-density fields are periodic over 2048 px and the head uses the last 1536
# rows of the same field, so head -> tile -> tile ... joins without a seam.
PAPER_W, PAPER_HEAD_H, PAPER_TILE_H = 512, 1536, 2048
PAPER_ROW = 64                                    # 2048 / 64 = 32 rows per tile
PAPER_SS = 3                                      # supersampling for crisp ink edges
PAPER_TONE = np.array([243, 240, 232], np.float32)    # off-white thermal paper
PAPER_INK = np.array([22, 22, 26], np.float32)        # near-black thermal ink
PAPER_MONO = 26                                   # item text size (px)
PAPER_HEAD_ITEMS = ["Linear Algebra", "Probability", "Prompt Engineering", "Unlearn Prompt Eng.",
                    "Calculus (again)", "Python 4 (not out)", "Agent Framework #47", "Framework #48 (new!)",
                    "Read 300 papers", "Transformers", "Attention (paper)", "Attention (yours)",
                    "Sleep (optional)", "RAG", "Why RAG is dead", "RAG is back"]
PAPER_TILE_ROWS = [  # rows of the tile; str = item, ("§", text) = section line
    "Fine-tuning", "Unlearn Fine-tuning", "Agent Framework #112", "Touch grass (sched.)",
    "Evals for your evals", "Vibe Architecture", "Context windows (∞)", "Read 1,000 papers",
    "Prompt Engineering 3", ("§", "MODULE 7: AGENTS (AGAIN)"), "Quantization (4-bit)", "Eat (batch job)",
    "MLOps (new version)", "Reasoning models", "Synthetic data", "Distillation", "Mixture of Experts",
    "Embeddings 2", "Unlearn everything", "GPU kernels", "Interpretability", "Tokenizers (again)",
    ("§", "MODULE 8: EVERYTHING NEW"), "AI Safety", "Agents managing agents", "Benchmarks (new)",
    "World models", "Long context", "Model merging", "Small models", "Re-learn Linear Alg.",
    "Sleep (deprecated)"]


@lru_cache(maxsize=1)
def paper_fields():
    """(tone RGB, ink density) for one 2048-px period."""
    H, W = PAPER_TILE_H, PAPER_W
    rng = np.random.default_rng(51_2048)

    def periodic(gy, gx, amp):
        g = np.tile(rng.normal(0, 1, (gy, gx)).astype(np.float32), (3, 1))
        a = np.asarray(Image.fromarray(g).resize((W, 3 * H), Image.BICUBIC))[H:2 * H]
        return a / (a.std() + 1e-6) * amp

    mottle = periodic(16, 4, 1.8) + periodic(64, 16, 0.9)
    grain = rng.normal(0, 1.1, (H, W)).astype(np.float32)
    tone = PAPER_TONE[None, None, :] + (mottle + grain)[..., None] * np.array([1.0, 1.0, 1.08], np.float32)
    y = np.arange(H, dtype=np.float32)[:, None]
    band = 1 - 0.05 * (0.5 + 0.5 * np.sin(2 * np.pi * y * 8 / H)) - 0.03 * (0.5 + 0.5 * np.sin(2 * np.pi * y * 37 / H + 1.3))
    dens = (0.93 + 0.05 * periodic(32, 8, 1.0)) * band
    for x in (97, 98, 311):                         # faint thermal-head streaks
        dens[:, x] *= 0.78
    return tone, np.clip(dens, 0.6, 1.0)


def paper_compose(mask, y0):
    """Ink an L mask (H x 512) onto paper using field rows y0..y0+H (mod 2048)."""
    tone, dens = paper_fields()
    H = mask.height
    rows = (np.arange(H) + y0) % PAPER_TILE_H
    a = np.asarray(mask, np.float32)[..., None] / 255.0 * dens[rows][..., None]
    out = tone[rows] * (1 - a) + PAPER_INK * a
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def paper_text(d, xy, text, size, anchor="ls", font=None):
    """Thermal-ish mono text: slightly emboldened DejaVu Sans Mono at PAPER_SS scale."""
    S = PAPER_SS
    fnt = font or MONO(size * S)
    d.text((xy[0] * S, xy[1] * S), text, font=fnt, fill=255, anchor=anchor, stroke_width=max(1, int(0.55 * S)),
           stroke_fill=255)


def paper_item(d, y, num, name):
    """One checkbox row whose top edge is at y (1x px)."""
    S = PAPER_SS
    yc = y + PAPER_ROW / 2
    x = 24
    d.rectangle((x * S, (yc - 14) * S, (x + 28) * S, (yc + 14) * S), outline=255, width=int(3.2 * S))
    paper_text(d, (x + 44, yc), f"{num:03d}", PAPER_MONO, "lm")
    nx = x + 44 + 3 * PAPER_MONO * 0.602 + 16
    size = PAPER_MONO
    while size > 20 and MONO(size * S).getlength(name) / S > PAPER_W - 20 - nx:
        size -= 1
    paper_text(d, (nx, yc), name, size, "lm")


def paper_section(d, y, text):
    S = PAPER_SS
    yc = y + PAPER_ROW / 2
    paper_text(d, (PAPER_W / 2, yc), text, 21, "mm")
    tw = MONO(21 * S).getlength(text) / S
    for x0, x1 in ((18, PAPER_W / 2 - tw / 2 - 12), (PAPER_W / 2 + tw / 2 + 12, PAPER_W - 18)):
        if x1 - x0 > 8:
            d.line((x0 * S, yc * S, x1 * S, yc * S), fill=255, width=int(3 * S))


def dashed(d, y, w=3, dash=14, gap=9):
    S = PAPER_SS
    x = 18
    while x < PAPER_W - 18:
        d.line((x * S, y * S, min(PAPER_W - 18, x + dash) * S, y * S), fill=255, width=int(w * S))
        x += dash + gap


def render_paper_head():
    S, W, H = PAPER_SS, PAPER_W, PAPER_HEAD_H
    m = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(m)
    paper_text(d, (W / 2, 70), "*** AGENT v8 · PRINTOUT ***", 20, "ms")
    lines = ["YOUR AI", "LEARNING", "ROADMAP"]
    fnt = fit_lines(lines, W - 44, 110, 900)
    size = fnt.size
    big = F(size * S, 900)
    cap, lh = size * 0.727, size * 1.06
    y = 112 + cap
    for ln in lines:
        d.text((W / 2 * S, y * S), ln, font=big, fill=255, anchor="ms")
        y += lh
    y += 6 - lh + 46
    sub = "847 SKILLS · PERSONALIZED · v1.0"
    sf = fit(sub, W - 40, 30, 760, 14)
    d.text((W / 2 * S, y * S), sub, font=F(sf.size * S, 760), fill=255, anchor="ms")
    y += 26
    for dy in (0, 10):
        d.line((18 * S, (y + dy) * S, (W - 18) * S, (y + dy) * S), fill=255, width=int(3.5 * S))
    y += 52
    for k, v in (("FOR", "YOU"), ("DATE", "TODAY"), ("VALID UNTIL", "TOMORROW"), ("EST. TIME", "41,300 h"),
                 ("MASTERED", "0 / 847")):
        n = 34 - len(k) - len(v)
        paper_text(d, (22, y), f"{k} {'.' * (n - 2)} {v}", 21, "ls")
        y += 34
    y += 4
    dashed(d, y)
    row0 = int(math.ceil((y + 14) / PAPER_ROW)) * PAPER_ROW
    n_rows = (H - row0) // PAPER_ROW
    for i in range(n_rows):
        paper_item(d, row0 + i * PAPER_ROW, i + 1, PAPER_HEAD_ITEMS[i % len(PAPER_HEAD_ITEMS)])
    m = m.reduce(S)
    return paper_compose(m, PAPER_TILE_H - H), n_rows


def render_paper_tile():
    S, W, H = PAPER_SS, PAPER_W, PAPER_TILE_H
    assert len(PAPER_TILE_ROWS) == H // PAPER_ROW
    m = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(m)
    num = 101
    for r, row in enumerate(PAPER_TILE_ROWS):
        if isinstance(row, tuple):
            paper_section(d, r * PAPER_ROW, row[1])
        else:
            paper_item(d, r * PAPER_ROW, num, row)
            num += 1
    return paper_compose(m.reduce(S), 0)


def render_paper_textures():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    head, n = render_paper_head()
    head.save(OUT_DIR / "roadmap_paper_head.png", "PNG", compress_level=9)
    tile = render_paper_tile()
    tile.save(OUT_DIR / "roadmap_paper_tile.png", "PNG", compress_level=9)
    return head, tile


# =============================================================================
# LAPTOP KEYBOARD  (2048 x 780 albedo + emission mask; plane is 0.29 m x 0.11 m)
# =============================================================================
KB_W, KB_H = 2048, 780
KB_SS = 2
KB_U = 128                                        # one key unit in px (15 units across)
KB_FN_H = 0.62                                    # function row height in units
KB_GAP = 0.13                                     # gap between keycaps in units
KB_CAP_TOP, KB_CAP_BOT = (40, 41, 46), (27, 28, 32)
KB_WELL = (9, 9, 11)
KB_LEGEND = (208, 211, 217)
KB_BACKLIGHT = (120, 165, 255)


def kb_layout():
    """[(x, y, w, h, legend)] in 1x px; legend = (kind, *text)."""
    u = KB_U
    L = lambda t: ("letter", t)            # noqa: E731
    Dl = lambda a, b: ("dual", a, b)       # noqa: E731
    wl = lambda t: ("word_l", t)           # noqa: E731
    wr = lambda t: ("word_r", t)           # noqa: E731
    rows = [
        (KB_FN_H, [(1.5, wl("esc"))] + [(1.0, ("fkey", f"F{i}")) for i in range(1, 13)] + [(1.5, wr("del"))]),
        (1.0, [(1, Dl("~", "`")), (1, Dl("!", "1")), (1, Dl("@", "2")), (1, Dl("#", "3")), (1, Dl("$", "4")),
               (1, Dl("%", "5")), (1, Dl("^", "6")), (1, Dl("&", "7")), (1, Dl("*", "8")), (1, Dl("(", "9")),
               (1, Dl(")", "0")), (1, Dl("_", "-")), (1, Dl("+", "=")), (2, wr("backspace"))]),
        (1.0, [(1.5, wl("tab"))] + [(1, L(c)) for c in "QWERTYUIOP"] +
              [(1, Dl("{", "[")), (1, Dl("}", "]")), (1.5, Dl("|", "\\"))]),
        (1.0, [(1.75, wl("caps lock"))] + [(1, L(c)) for c in "ASDFGHJKL"] +
              [(1, Dl(":", ";")), (1, Dl('"', "'")), (2.25, wr("enter"))]),
        (1.0, [(2.25, wl("shift"))] + [(1, L(c)) for c in "ZXCVBNM"] +
              [(1, Dl("<", ",")), (1, Dl(">", ".")), (1, Dl("?", "/")), (2.75, wr("shift"))]),
        (1.0, [(1, wl("fn")), (1, wl("ctrl")), (1, wl("alt")), (1.25, ("glyph", "◆")), (5.5, ("blank",)),
               (1.25, ("glyph", "◆")), (1, wr("alt")), (3, ("arrows",))]),
    ]
    total_h = sum(h for h, _ in rows) * u
    x0, y = (KB_W - 15 * u) / 2, (KB_H - total_h) / 2
    keys = []
    for h, row in rows:
        x = x0
        for w, leg in row:
            if leg[0] == "arrows":                # inverted T, half-height keys
                hh = h * u / 2
                keys.append((x, y + hh, u, hh, ("glyph", "←")))
                keys.append((x + u, y, u, hh, ("glyph", "↑")))
                keys.append((x + u, y + hh, u, hh, ("glyph", "↓")))
                keys.append((x + 2 * u, y + hh, u, hh, ("glyph", "→")))
            else:
                keys.append((x, y, w * u, h * u, leg))
            x += w * u
        y += h * u
    return keys


def render_keyboard():
    S, u = KB_SS, KB_U
    W, H = KB_W * S, KB_H * S
    g = KB_GAP * u
    keys = kb_layout()
    caps = Image.new("L", (W, H), 0)             # keycap footprint
    top_lit = Image.new("L", (W, H), 0)          # top-edge bevel highlight
    low_edge = Image.new("L", (W, H), 0)         # bottom-edge shade
    legends = Image.new("L", (W, H), 0)
    cap_rgb = Image.new("RGB", (W, H), KB_WELL)
    dl = ImageDraw.Draw(legends)
    for (x, y, w, h, leg) in keys:
        half = h < u * 0.7
        ins = g / 2 if not half else g / 3
        bx0, by0, bx1, by1 = (x + ins) * S, (y + ins) * S, (x + w - ins) * S, (y + h - ins) * S
        kw, kh = int(round(bx1 - bx0)), int(round(by1 - by0))
        r = (0.11 if not half else 0.08) * u * S
        m = rr_mask(kw, kh, r, ss=2)
        ox, oy = int(round(bx0)), int(round(by0))
        caps.paste(255, (ox, oy, ox + kw, oy + kh), m)
        cap_rgb.paste(vgrad(kw, kh, KB_CAP_TOP, KB_CAP_BOT), (ox, oy), m)
        ring = rr_ring(kw, kh, r, 2.2 * S, ss=2)
        ramp = np.linspace(1.0, 0.0, kh, dtype=np.float32)[:, None] ** 1.6
        top_lit.paste(Image.fromarray((np.asarray(ring, np.float32) * ramp).astype(np.uint8)), (ox, oy),
                      Image.fromarray((np.asarray(ring, np.float32) * ramp).astype(np.uint8)))
        low = Image.fromarray((np.asarray(ring, np.float32) * ramp[::-1] ** 0.8).astype(np.uint8))
        low_edge.paste(low, (ox, oy), low)
        # legends
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        kind = leg[0]
        pad_x, pad_b = 0.15 * u * S, 0.17 * u * S
        if kind == "letter":
            dl.text((cx, cy + 0.01 * u * S), leg[1], font=F(0.30 * u * S, 520), fill=255, anchor="mm")
        elif kind == "dual":
            f2 = F(0.215 * u * S, 520)
            dl.text((cx, by0 + (by1 - by0) * 0.33), leg[1], font=f2, fill=255, anchor="mm")
            dl.text((cx, by0 + (by1 - by0) * 0.70), leg[2], font=f2, fill=255, anchor="mm")
        elif kind == "word_l":
            dl.text((bx0 + pad_x, by1 - pad_b * (0.75 if half else 1)), leg[1], font=F((0.155 if not half else 0.15) * u * S, 560),
                    fill=255, anchor="ls")
        elif kind == "word_r":
            dl.text((bx1 - pad_x, by1 - pad_b * (0.75 if half else 1)), leg[1], font=F((0.155 if not half else 0.15) * u * S, 560),
                    fill=255, anchor="rs")
        elif kind == "fkey":
            dl.text((cx, cy), leg[1], font=F(0.17 * u * S, 560), fill=255, anchor="mm")
        elif kind == "glyph":
            fnt = MONO(0.21 * u * S) if leg[1] == "◆" else F(0.24 * u * S, 600)
            dl.text((cx, cy), leg[1], font=fnt, fill=255, anchor="mm")
    capf = np.asarray(caps, np.float32) / 255.0
    outside = 1.0 - capf
    # soft cool backlight leaking out from under every keycap
    halo = np.asarray(caps.filter(ImageFilter.GaussianBlur(7 * S)), np.float32) / 255.0
    halo2 = np.asarray(caps.filter(ImageFilter.GaussianBlur(2.5 * S)), np.float32) / 255.0
    glow = np.clip(0.55 * halo + 0.6 * halo2, 0, 1) * outside
    shadow_src = Image.new("L", (W, H), 0)
    shadow_src.paste(caps.crop((0, 0, W, H - 5 * S)), (0, 5 * S))
    shadow = np.asarray(shadow_src.filter(ImageFilter.GaussianBlur(5 * S)), np.float32) / 255.0 * outside
    rng = np.random.default_rng(2048)
    noise = rng.normal(0, 1.0, (H // 2, W // 2)).astype(np.float32)
    noise = np.asarray(Image.fromarray(noise).resize((W, H), Image.BILINEAR))
    rgb = np.asarray(cap_rgb, np.float32)
    rgb = rgb + noise[..., None] * 1.2
    well = rgb * (1 - 0.55 * shadow[..., None]) + glow[..., None] * np.array(KB_BACKLIGHT, np.float32) * 0.38
    rgb = rgb * capf[..., None] + well * outside[..., None]
    hi = np.asarray(top_lit, np.float32)[..., None] / 255.0
    lo = np.asarray(low_edge, np.float32)[..., None] / 255.0
    rgb = rgb * (1 - 0.55 * hi) + np.array([86, 89, 98], np.float32) * 0.55 * hi
    rgb = rgb * (1 - 0.45 * lo)
    leg = np.asarray(legends, np.float32)[..., None] / 255.0
    rgb = rgb * (1 - leg) + np.array(KB_LEGEND, np.float32) * leg
    albedo = Image.fromarray(rgb.clip(0, 255).astype(np.uint8)).resize((KB_W, KB_H), Image.LANCZOS)
    emis = np.maximum(leg[..., 0], np.clip(glow * 0.75, 0, 1))
    glow_img = Image.fromarray((emis * 255).clip(0, 255).astype(np.uint8)).resize((KB_W, KB_H), Image.LANCZOS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    albedo.save(OUT_DIR / "keyboard.png", "PNG", compress_level=9)
    glow_img.save(OUT_DIR / "keyboard_glow.png", "PNG", compress_level=9)
    return albedo, glow_img


# =============================================================================
# Runner
# =============================================================================
RENDERERS = {}
STATICS = {}                       # single images: name -> render function


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
STATICS["atlas"] = render_atlas
STATICS["paper"] = render_paper_textures
STATICS["keyboard"] = render_keyboard


def parse_frames(spec):
    if not spec:
        return None
    a, _, b = spec.partition("-")
    return int(a), int(b or a)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma list of: " + ",".join(list(SEQUENCES) + list(STATICS)))
    ap.add_argument("--frames", default="", help="film frame range a-b (clipped per sequence)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--contact", default="", help="write a key-frame contact sheet to this path and exit")
    args = ap.parse_args(argv)

    if args.contact:
        build_contact_sheet(Path(args.contact))
        return
    only = [s.strip() for s in args.only.split(",") if s.strip()] or list(SEQUENCES) + list(STATICS)
    rng = parse_frames(args.frames)
    tasks = []
    for seq in only:
        if seq not in SEQUENCES:
            continue
        a, b, _, _ = SEQUENCES[seq]
        if rng:
            a, b = max(a, rng[0]), min(b, rng[1])
        tasks += [(seq, f) for f in range(a, b + 1)]
    t0 = time.time()
    for name, fn in STATICS.items():
        if name in only:
            fn()
            print(f"{name} -> written to", OUT_DIR)
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


CONTACT_KEYS = [("laptop", [100, 120, 200, 225, 250, 290, 300, 380, 402, 406, 412, 425, 450, 505, 660]),
                ("monitor", [150, 220, 270, 330, 450])]
CONTACT_TEXTURES = [("roadmap_paper_head.png", 1000), ("roadmap_paper_tile.png", 1000), ("keyboard.png", 560)]


def build_contact_sheet(path, thumb_h=300, width=2460):
    """Key frames (read from disk, rendered on the fly if missing) plus the static textures."""
    items = []
    for seq, frames in CONTACT_KEYS:
        a, b, _, ext = SEQUENCES[seq]
        for f in frames:
            if not a <= f <= b:
                continue
            fp = OUT_DIR / seq / f"{seq}_{f:04d}.{ext}"
            im = Image.open(fp).convert("RGB") if fp.exists() else RENDERERS[seq](f)
            items.append((f"{seq} {f:04d}  ({T.shot_at(f)['id']})", im, thumb_h))
    for name, h in CONTACT_TEXTURES:
        fp = OUT_DIR / name
        if not fp.exists():
            render_paper_textures() if name.startswith("roadmap") else render_keyboard()
        items.append((name, Image.open(fp).convert("RGB"), h))
    pad, lab = 14, 28
    rows, row, x = [], [], pad
    for name, im, h in items:
        w = int(im.width * h / im.height)
        if row and x + w + pad > width:
            rows.append(row)
            row, x = [], pad
        row.append((name, im.resize((w, h), Image.LANCZOS), x))
        x += w + pad
    rows.append(row)
    heights = [max(t.height for _, t, _ in r) for r in rows]
    sheet = Image.new("RGB", (width, pad + sum(h + lab + pad for h in heights)), (40, 42, 46))
    d = ImageDraw.Draw(sheet)
    y = pad
    for r, hgt in zip(rows, heights):
        for name, im, x in r:
            d.text((x, y + 20), name, font=F(19, 650), fill=(230, 232, 236), anchor="ls")
            sheet.paste(im, (x, y + lab))
        y += hgt + lab + pad
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, "JPEG", quality=90)
    print("contact sheet ->", path)


if __name__ == "__main__":
    main()
