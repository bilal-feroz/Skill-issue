"""Sculpted head and hair for the student (signed-distance 'Clay', meshed with OpenVDB).

Design: an appealing, friendly animated-feature look (the director's call after the caricature
pass): a big round cranium, big eyes set on the head's midline, a short soft lower face with
full cheeks, a small button nose, medium round ears, and a swept quiff over short sides.

Method follows the scenario-blender-sculpting skill: masses first, with stated planes (the
underside of the jaw is a stated plane even on a round face), features blended into ONE
surface so nothing floats. The hair is a thin base plus the quiff volume, blended into one
mass. Messy and Blown shape keys are displacements of that mesh (same topology).

Rest pose, metres, facing -Y, character's left = +X (same frame as character.py).
"""

import math
import os
import sys

import numpy as np
from mathutils import Vector

_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
import bx_sculpt as S  # noqa: E402  (vendored from scenario-labs/skills, MIT)

VOXEL = {"hero": 0.0019, "crowd": 0.010}
CRANIUM_C = (0.0, 0.012, 1.615)
CRANIUM_R = (0.142, 0.156, 0.150)
MOUTH_C = (0.0, -0.140, 1.479)          # character.py places the shape-keyed mouth here
NOSE_TIP = (0.0, -0.168, 1.522)


def _skull():
    """The head's big masses as one field: the face sculpt builds on it, and the hair base is
    this same surface pushed out, so the hair hugs the skull wherever the blends bulge."""
    cran = S.sd_ellipsoid(CRANIUM_C, CRANIUM_R)
    for s in (1, -1):
        cran = cran.clip(S.sd_halfspace((0.134 * s, 0, 0), (s, 0, 0)), 0.045)
    # the face front: one soft plane for the eyes and forehead
    front = S.sd_round_box((0, -0.085, 1.592), (0.100, 0.055, 0.050), 0.045)
    # lower face: short and round, with a stated underside so the chin does not sag
    low = S.sd_ellipsoid((0, -0.058, 1.502), (0.112, 0.092, 0.076))
    low = low.clip(S.sd_halfspace((0, -0.100, 1.428), (0, 0.38, -0.925)), 0.020)
    stump = S.sd_tube([(0, 0.004, 1.425), (0, -0.004, 1.520)], [0.047, 0.047])
    return cran.add(front, 0.040).add(low, 0.080).add(stump, 0.030)


def build_head(name, col, lod, eye_pos, eye_r):
    v = VOXEL[lod]
    clay = S.Clay((-0.190, -0.230, 1.380), (0.190, 0.200, 1.790), v)
    # STYLE: appeal by roundness. A big round cranium, eyes on the head's midline, a short
    # soft lower face with full cheeks, a small button nose. Everything blends wide and soft.
    clay.add(_skull())
    clay.add(S.sd_ellipsoid((0.066, -0.098, 1.521), (0.046, 0.036, 0.040)), blend=0.050, mirror=True)   # full cheeks
    clay.add(S.sd_ellipsoid((0, -0.118, 1.449), (0.030, 0.024, 0.022)), blend=0.030)                     # small round chin
    clay.add(S.sd_ellipsoid((0, -0.122, 1.480), (0.044, 0.030, 0.026)), blend=0.030)                     # mouth mound
    clay.add(S.sd_ellipsoid((0.050, -0.130, 1.629), (0.040, 0.018, 0.014), rot=(0, 0, 6)),
             blend=0.025, mirror=True)                                                                   # soft brow ridges
    # button nose: a short bridge, a round tip, small wings
    clay.add(S.sd_cone((0, -0.136, 1.586), (0, -0.158, 1.532), 0.010, 0.015), blend=0.018)
    clay.add(S.sd_sphere(NOSE_TIP, 0.019), blend=0.012)
    clay.add(S.sd_ellipsoid((0, -0.150, 1.511), (0.016, 0.016, 0.010)), blend=0.010)
    clay.add(S.sd_ellipsoid((0.015, -0.153, 1.512), (0.012, 0.011, 0.010)), blend=0.010, mirror=True)
    clay.sub(S.sd_ellipsoid((0.008, -0.163, 1.5045), (0.0045, 0.0045, 0.0030)), blend=0.003, mirror=True)
    # ears: medium, round, with a bowl
    clay.add(S.sd_ellipsoid((0.136, 0.018, 1.565), (0.016, 0.031, 0.040), rot=(0, 0, -14)), blend=0.012, mirror=True)
    clay.sub(S.sd_ellipsoid((0.147, 0.014, 1.567), (0.007, 0.020, 0.027), rot=(0, 0, -14)), blend=0.006, mirror=True)
    # eye sockets for the big eyes
    ex, ey, ez = eye_pos
    clay.sub(S.sd_sphere((ex, ey, ez), eye_r * 1.04), blend=0.006, mirror=True)
    return clay.to_object(name, collection=col, symmetric=True)


def build_hair(name, col, lod, seed=11):
    """Pompadour: a big swept quiff over the forehead, short combed sides, a low nape."""
    v = VOXEL[lod]
    clay = S.Clay((-0.185, -0.245, 1.425), (0.185, 0.225, 1.860), v)
    sk = _skull()
    base = S.Prim(lambda x, y, z, f=sk.fn: f(x, y, z) - 0.007, sk.lo - 0.01, sk.hi + 0.01)   # skull + 7 mm
    # forehead hairline (the quiff covers it), cut on the FRONT half only: one tilted plane
    # across the whole head would also shave the back of the skull (a garrison cap)
    brow_zone = S.sd_halfspace((0, -0.080, 1.690), (0, 0.62, 0.785)).clip(
        S.sd_halfspace((0, -0.035, 0), (0, 1, 0)), 0.040)
    base = base.cut(brow_zone, 0.012)
    base = base.clip(S.sd_halfspace((0, 0.070, 1.452), (0, 0.32, -0.947)), 0.012)      # nape, low on the skull
    for s in (1, -1):                                                                 # short over the ears
        base = base.clip(S.sd_halfspace((0.112 * s, -0.01, 1.575), (0.55 * s, -0.25, -0.80)), 0.010)
    clay.add(base)
    # the quiff: rises off the crown, rolls forward over the forehead, sweeps to his right
    # the pompadour: one big rounded wave, highest over the front, rolling forward and
    # sweeping to his right; a second, smaller wave behind it
    quiff = [(0.045, -0.010, 1.735), (0.030, -0.070, 1.772), (0.002, -0.118, 1.778),
             (-0.032, -0.152, 1.752), (-0.060, -0.165, 1.715), (-0.078, -0.150, 1.688)]
    clay.add(S.sd_tube(quiff, [0.058, 0.068, 0.066, 0.052, 0.032, 0.012]), blend=0.034)
    front = [(0.060, -0.090, 1.700), (0.030, -0.140, 1.712), (-0.010, -0.168, 1.700)]     # overhang on the forehead
    clay.add(S.sd_tube(front, [0.034, 0.036, 0.020]), blend=0.030)
    lobe = [(0.090, 0.030, 1.708), (0.088, -0.040, 1.738), (0.070, -0.110, 1.728), (0.050, -0.145, 1.700)]
    clay.add(S.sd_tube(lobe, [0.030, 0.038, 0.030, 0.012]), blend=0.028)
    side = [(-0.088, 0.010, 1.708), (-0.095, -0.060, 1.722), (-0.090, -0.118, 1.700)]
    clay.add(S.sd_tube(side, [0.026, 0.030, 0.012]), blend=0.024)
    # combed clumps over the sides and back: soft raised ridges (the skill's "thin base,
    # clumps make the volume"), never cut grooves, which read as seams on a cap
    bc, br = Vector(CRANIUM_C) + Vector((0, 0.002, 0.003)), Vector((0.148, 0.162, 0.156))

    def on_base(az, el, lift=-0.002):
        a, e = math.radians(az), math.radians(el)
        d = Vector((math.cos(e) * math.sin(a), -math.cos(e) * math.cos(a), math.sin(e)))
        p = bc + Vector((d.x * br.x, d.y * br.y, d.z * br.z))
        return tuple(p + d * lift)

    for s in (1, -1):
        for el in (28, 40, 52):
            pts = [on_base(s * az, el - 0.10 * (az - 70)) for az in (70, 100, 130, 158)]
            clay.add(S.sd_tube(pts, [0.006, 0.009, 0.009, 0.006]), blend=0.012)
    ob = clay.to_object(name, collection=col, symmetric=False)
    # shape keys: Messy (strands lift and flare) and Blown (swept back by the scream)
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    rel = co - np.array(CRANIUM_C)
    d_ell = np.linalg.norm(rel / np.array(CRANIUM_R), axis=1)
    # how far a vertex stands off the scalp, saturating so the big quiff never spikes
    raw = np.clip((d_ell - 1.06) * 0.16, 0.0, None)
    cap = 0.014
    above = cap * (1.0 - np.exp(-raw / cap))
    nrm = rel / np.maximum(np.linalg.norm(rel, axis=1, keepdims=True), 1e-9)
    rs = np.random.default_rng(seed)
    ph = rs.uniform(0, 6.28, 3)
    jitter = np.stack([np.sin(co[:, 0] * 70 + ph[0]), np.sin(co[:, 1] * 64 + ph[1]), np.sin(co[:, 2] * 75 + ph[2])], 1)
    messy = co + nrm * above[:, None] * 0.9 + jitter * above[:, None] * 0.8 + np.array([0, 0, 0.6]) * above[:, None]
    blown = co + np.array([0, 1.0, 0.25]) * above[:, None] * 2.0
    ob.shape_key_add(name="Basis", from_mix=False)
    for kname, arr in (("Messy", messy), ("Blown", blown)):
        kb = ob.shape_key_add(name=kname, from_mix=False)
        kb.data.foreach_set("co", arr.astype(np.float32).ravel())
        kb.value = 0.0
    return ob
