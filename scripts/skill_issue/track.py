"""Analytic oval conveyor track (pure Python, shared by Blender build + animation).

Straight A runs along +Y through the hero's station at the world origin, then
the track turns right around a semicircle, comes back down straight B and
closes. It's a racetrack with no exit.
"""

import math

H = 180.0          # half length of each straight (m)
RAD = 75.0         # turn radius of the centre line (m)
LANES = 11
LANE_SPACING = 5.5
STATION_SPACING = 4.0
HERO_LANE = 5      # middle lane -> lateral offset 0
HERO_S0 = H        # the hero station sits at the origin at belt distance 0
LENGTH = 4 * H + 2 * math.pi * RAD


def point(s):
    """Centre-line position (x, y) and unit tangent (tx, ty) at arc length s."""
    s = s % LENGTH
    a = 2 * H
    b = a + math.pi * RAD
    c = b + 2 * H
    if s < a:
        return (0.0, -H + s), (0.0, 1.0)
    if s < b:
        th = math.pi - (s - a) / RAD
        return (RAD + RAD * math.cos(th), H + RAD * math.sin(th)), (math.sin(th), -math.cos(th))
    if s < c:
        return (2 * RAD, H - (s - b)), (0.0, -1.0)
    th = -(s - c) / RAD
    return (RAD + RAD * math.cos(th), -H + RAD * math.sin(th)), (math.sin(th), -math.cos(th))


def side(t):
    """Lateral unit vector (toward the inside of the oval for positive offsets)."""
    return (t[1], -t[0])


def lane_point(s, offset):
    (x, y), t = point(s)
    sx, sy = side(t)
    return (x + sx * offset, y + sy * offset), t


def heading(t):
    """Z rotation so that local +Y aligns with tangent t."""
    return math.atan2(-t[0], t[1])


def samples(step_straight=2.0, step_turn=1.0):
    out = []
    s = 0.0
    while s < LENGTH - 1e-6:
        out.append(s)
        (x, y), _ = point(s)
        on_turn = not (abs(x) < 1e-6 or abs(x - 2 * RAD) < 1e-6)
        s += step_turn if on_turn else step_straight
    return out
