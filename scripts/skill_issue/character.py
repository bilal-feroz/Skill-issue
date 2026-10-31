"""The Student: a stylised, rigged character built entirely from code.

Design: oversized head, round glasses, messy dark hair, mustard hoodie with
drawstrings, dark jeans and white sneakers. Expressive eyes, lids, brows and a
shape-keyed mouth carry the acting.

Rig: a real Armature. Every mesh is deformed by an Armature modifier, with
vertex weights assigned analytically in code (no heat weighting), so the hoodie,
sleeves and jeans bend smoothly at the spine, elbows and knees. Face parts that
need their own motion (eyes, lids, brows) are separate objects whose origin
sits on their pivot. Their own rotation is applied first and then the head
bone carries them.

Rest pose: standing, facing -Y, character's left = +X, feet on z = 0.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import bl_util as U
from . import materials as M

SIDES = (("L", 1.0), ("R", -1.0))
FWD = Vector((0, -1, 0))
UP = Vector((0, 0, 1))

# name: (head, tail, parent, roll_align_vector)
_BONES_CENTER = [
    ("root",  (0, 0, 0),         (0, 0, 0.3),        None,    FWD),
    ("hips",  (0, 0, 0.92),      (0, 0, 1.02),       "root",  FWD),
    ("spine", (0, 0, 1.02),      (0, 0, 1.16),       "hips",  FWD),
    ("chest", (0, 0, 1.16),      (0, 0, 1.33),       "spine", FWD),
    ("neck",  (0, -0.005, 1.33), (0, -0.01, 1.42),   "chest", FWD),
    ("head",  (0, -0.01, 1.42),  (0, -0.01, 1.70),   "neck",  FWD),
]
_BONES_SIDE = [  # left side; mirrored for R
    ("clavicle", (0.03, -0.01, 1.29),  (0.175, 0.0, 1.305),  "chest",    FWD),
    ("upperarm", (0.185, 0.0, 1.30),   (0.215, 0.01, 1.03),  "clavicle", FWD),
    ("forearm",  (0.215, 0.01, 1.03),  (0.235, -0.01, 0.795), "upperarm", FWD),
    ("hand",     (0.235, -0.01, 0.795), (0.242, -0.016, 0.693), "forearm", FWD),
    ("thigh",    (0.095, 0.0, 0.93),   (0.10, -0.01, 0.50),  "hips",     FWD),
    ("shin",     (0.10, -0.01, 0.50),  (0.10, 0.01, 0.085),  "thigh",    FWD),
    ("foot",     (0.10, 0.01, 0.085),  (0.10, -0.13, 0.025), "shin",     UP),
]
# finger: (z offset across palm toward thumb side, prox len, dist len, radius)
FINGERS = [("index", 0.031, 0.046, 0.039, 0.0112),
           ("middle", 0.0105, 0.050, 0.041, 0.0117),
           ("ring", -0.0105, 0.047, 0.039, 0.0111),
           ("pinky", -0.030, 0.037, 0.031, 0.0100)]

EYE_R = 0.035
EYE_POS = Vector((0.054, -0.114, 1.585))     # big eyes on the head's midline, set wide
HEAD_C = Vector((0.0, -0.005, 1.565))
HEAD_R = 0.165


def _mirror(v, s):
    return Vector((v[0] * s, v[1], v[2]))


class Character:
    pass


# ---------------------------------------------------------------------------
# Armature
# ---------------------------------------------------------------------------

def _build_armature(name, col):
    arm = bpy.data.armatures.new(f"{name}_Rig")
    arm.display_type = 'STICK'
    ob = bpy.data.objects.new(f"{name}_Rig", arm)
    col.objects.link(ob)
    vl = bpy.context.view_layer
    vl.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.edit_bones

    def add(bname, h, t, parent, roll_vec):
        b = eb.new(bname)
        b.head, b.tail = Vector(h), Vector(t)
        b.align_roll(roll_vec)
        if parent:
            b.parent = eb[parent]
        return b

    for bname, h, t, p, r in _BONES_CENTER:
        add(bname, h, t, p, r)
    for side, s in SIDES:
        for bname, h, t, p, r in _BONES_SIDE:
            parent = p if p in ("chest", "hips") else f"{p}.{side}"
            add(f"{bname}.{side}", _mirror(h, s), _mirror(t, s), parent, r)
        # fingers in the hand's frame
        hb = eb[f"hand.{side}"]
        hy = (hb.tail - hb.head).normalized()
        hz = hb.z_axis.normalized()           # thumb side (forward at rest)
        hx = hb.x_axis.normalized()
        for fname, zoff, l1, l2, _r in FINGERS:
            base = hb.tail + hz * zoff - hx * 0.002 * s
            p = add(f"{fname}1.{side}", base, base + hy * l1, None, hz)
            p.parent = hb
            d = add(f"{fname}2.{side}", base + hy * l1, base + hy * (l1 + l2), None, hz)
            d.parent = p
        # thumb: from the palm base, angled toward thumb side and palm
        palm_n = hx * s
        tb = hb.head + hy * 0.025 + hz * 0.030 + palm_n * 0.008
        td = (hy * 0.75 + hz * 0.55 + palm_n * 0.35).normalized()
        t1 = add(f"thumb1.{side}", tb, tb + td * 0.041, None, palm_n)
        t1.parent = hb
        td2 = (td + hy * 0.25).normalized()
        t2 = add(f"thumb2.{side}", tb + td * 0.041, tb + td * 0.041 + td2 * 0.034, None, palm_n)
        t2.parent = t1
    bpy.ops.object.mode_set(mode='OBJECT')
    rest = {b.name: b.matrix_local.copy() for b in arm.bones}
    for pb in ob.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    return ob, rest


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _tube(path, radius_fn, segs=20, scale_xy=(1.0, 1.0), ring_count=None, twist_ref=None):
    """Smooth tube along a polyline. Returns bmesh and per-ring parameter t."""
    pts = [Vector(p) for p in path]
    # resample path uniformly
    lens = [0.0]
    for a, b in zip(pts, pts[1:]):
        lens.append(lens[-1] + (b - a).length)
    total = lens[-1]
    n = ring_count or max(8, int(total / 0.012))
    samples, ts = [], []
    for i in range(n + 1):
        d = total * i / n
        for j in range(len(pts) - 1):
            if lens[j] <= d <= lens[j + 1] + 1e-9:
                u = (d - lens[j]) / max(1e-9, lens[j + 1] - lens[j])
                samples.append(pts[j].lerp(pts[j + 1], u))
                break
        ts.append(i / n)
    bm = bmesh.new()
    ref = Vector(twist_ref) if twist_ref else Vector((1, 0, 0))
    rings = []
    prev_x = None
    for i, (c, t) in enumerate(zip(samples, ts)):
        if i == 0:
            tan = samples[1] - samples[0]
        elif i == len(samples) - 1:
            tan = samples[-1] - samples[-2]
        else:
            tan = samples[i + 1] - samples[i - 1]
        tan.normalize()
        x = (ref - tan * ref.dot(tan)) if prev_x is None else (prev_x - tan * prev_x.dot(tan))
        if x.length < 1e-6:
            x = tan.orthogonal()
        x.normalize()
        y = tan.cross(x).normalized()
        prev_x = x
        r = radius_fn(t)
        ring = []
        for k in range(segs):
            a = 2 * math.pi * k / segs
            off = x * (math.cos(a) * r * scale_xy[0]) + y * (math.sin(a) * r * scale_xy[1])
            ring.append(bm.verts.new(c + off))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for k in range(segs):
            bm.faces.new([a[k], a[(k + 1) % segs], b[(k + 1) % segs], b[k]])
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        f = bm.faces.new(ring[::-1] if flip else ring)
        bmesh.ops.poke(bm, faces=[f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _seg_param(p, a, b):
    ab = b - a
    return max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))


def _smooth01(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _finalize(ob, rig, weights_fn, subsurf=(1, 2)):
    """Assign vertex groups via weights_fn(co) -> {bone: w}, add Armature mod."""
    me = ob.data
    groups = {}
    for v in me.vertices:
        co = ob.matrix_basis @ v.co
        ws = weights_fn(co)
        tot = sum(ws.values()) or 1.0
        for bname, w in ws.items():
            if w <= 1e-4:
                continue
            g = groups.get(bname)
            if g is None:
                g = ob.vertex_groups.new(name=bname)
                groups[bname] = g
            g.add([v.index], w / tot, 'REPLACE')
    # rest-pose coordinates as an attribute: shaders read this so textures (and
    # the procedural iris) stick to the surface instead of swimming when the
    # armature deforms the mesh
    if "rest_co" not in me.attributes:
        attr = me.attributes.new("rest_co", 'FLOAT_VECTOR', 'POINT')
        attr.data.foreach_set("vector", [c for v in me.vertices for c in v.co])
    mod = ob.modifiers.new("Armature", 'ARMATURE')
    mod.object = rig
    if subsurf and subsurf[1] > 0:
        U.add_subsurf(ob, subsurf[0], subsurf[1])
    return ob


def _parent_keep(ob, rig):
    mw = ob.matrix_basis.copy()      # no parent yet; matrix_world may be stale
    ob.parent = rig
    ob.matrix_parent_inverse = rig.matrix_world.inverted()
    ob.matrix_world = mw


def rigid(bone):
    return lambda co: {bone: 1.0}


# ---------------------------------------------------------------------------
# Body parts
# ---------------------------------------------------------------------------

def _head_mesh(lod):
    segs, rings = (40, 28) if lod == "hero" else (16, 10)
    bm = U.bm_sphere(1.0, segs, rings)
    for v in bm.verts:
        x, y, z = v.co
        # base proportions
        x *= HEAD_R * 0.96
        y *= HEAD_R * 0.98
        z *= HEAD_R * 1.06
        t = max(0.0, -z / (HEAD_R * 1.06))         # 0 at equator .. 1 at chin
        x *= 1.0 - 0.20 * t * t                     # jaw taper (soft, rounded chin)
        if y < 0:                                   # face side
            y *= 1.0 - 0.10 * t
            y -= 0.012 * t * (1.0 - abs(x) / HEAD_R)  # chin forward
        else:
            y *= 1.06                               # rounder skull back
        if z > 0:
            x *= 1.0 + 0.04 * (z / (HEAD_R * 1.06))  # wider cranium
        # cheek bulge
        cheek = math.exp(-(((abs(x) - 0.085) / 0.04) ** 2 + ((z + 0.05) / 0.04) ** 2))
        if y < 0:
            y -= 0.008 * cheek
        # subtle asymmetry: the right side of the face sits a hair lower
        if x < 0:
            z -= 0.002
        v.co = Vector((x, y, z)) + HEAD_C
    return bm


def _eye_socket_shading(bm):
    """Push head verts back slightly around each eye so the eyeballs sit in."""
    for side, s in SIDES:
        c = _mirror(EYE_POS, s)
        for v in bm.verts:
            d = (v.co - c).length
            if d < EYE_R * 1.25 and v.co.y < c.y + 0.01:
                push = (EYE_R * 1.25 - d) * 0.6
                v.co.y += push


def _lid_mesh(r, upper=True, segs=24, rings=8):
    """Spherical cap shell (hemisphere) with the rim on the equator; pole +Z (upper)."""
    bm = bmesh.new()
    sgn = 1.0 if upper else -1.0
    rows = []
    for i in range(rings + 1):
        pol = (math.pi / 2) * i / rings            # 0 at pole .. pi/2 at rim
        row = []
        for k in range(segs):
            a = 2 * math.pi * k / segs
            row.append(bm.verts.new((r * math.sin(pol) * math.cos(a),
                                     r * math.sin(pol) * math.sin(a),
                                     sgn * r * math.cos(pol))))
        rows.append(row)
    for i, (a, b) in enumerate(zip(rows, rows[1:])):
        for k in range(segs):
            f = bm.faces.new([a[k], a[(k + 1) % segs], b[(k + 1) % segs], b[k]])
            f.material_index = 1 if i == rings - 1 else 0
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _mouth_shapes():
    """Return dict shape_name -> list of (upper_y, teeth_y, lower_y) per column.

    Coordinates in a 2D mouth plane: x in [-1, 1] maps to width, y up.
    """
    n = 17
    xs = [-1 + 2 * i / (n - 1) for i in range(n)]
    W = 0.038

    def shape(width=1.0, up_curve=0.0, lo_curve=0.0, open_=0.0, corner=0.0, skew=0.0, teeth=0.3):
        cols = []
        for x in xs:
            xx = x * width
            e = 1 - x * x
            corner_lift = corner * x * x
            sk = skew * x
            u = up_curve * e + corner_lift + sk + 0.0013
            lo = lo_curve * e + corner_lift + sk - 0.0013 - open_ * (e ** 0.7)
            show = max(0.0, min(1.0, (u - lo - 0.004) / 0.012))   # teeth only when open
            tth = u - (u - lo) * teeth * show
            cols.append((xx * W, u, tth, lo))
        return cols

    return n, {
        "Basis":  shape(1.0, 0.000, 0.000, 0.0, 0.002),
        "Smile":  shape(1.12, -0.004, -0.006, 0.0, 0.012),
        "Grin":   shape(1.15, -0.002, -0.010, 0.020, 0.012, teeth=0.45),
        "Weak":   shape(0.92, 0.001, 0.0005, 0.0, 0.003, skew=0.0025),
        "Frown":  shape(0.95, 0.003, 0.004, 0.0, -0.008),
        "Scream": shape(0.78, 0.016, 0.000, 0.036, -0.002, teeth=0.18),   # fits the short chin
        "O":      shape(0.45, 0.010, 0.002, 0.016, 0.0, teeth=0.0),
        "Flat":   shape(0.85, 0.0, 0.0, 0.0, 0.0),
        "Proud":  shape(1.05, -0.002, -0.004, 0.0, 0.008, skew=0.004),
    }


def _mouth_object(name, col, head_ob, mats):
    """Mouth = a grid between upper lip, teeth edge and lower lip.

    Several interior rows let the open shapes hug the curved face after
    projection onto the head surface (done once per shape key, in rest space).
    """
    n, shapes = _mouth_shapes()
    from .head_sculpt import MOUTH_C
    center = Vector(MOUTH_C)
    inner_rows = 6
    R = 2 + inner_rows                      # upper, teeth, inner..., lower

    def rows_for(cols):
        out = []
        for (x, u, tth, lo) in cols:
            col_ = [(x, u), (x, tth)]
            for k in range(1, inner_rows):
                col_.append((x, tth + (lo - tth) * k / inner_rows))
            col_.append((x, lo))
            out.append(col_)
        return out                          # [column][row] -> (x, z)

    bm = bmesh.new()
    base = rows_for(shapes["Basis"])
    grid = [[bm.verts.new((x, 0, z)) for (x, z) in column] for column in base]
    for i in range(n - 1):
        for r in range(R - 1):
            f = bm.faces.new([grid[i][r], grid[i + 1][r], grid[i + 1][r + 1], grid[i][r + 1]])
            f.material_index = 1 if r == 0 else 2
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    for m in mats:
        me.materials.append(m)
    ob.location = center
    hm = head_ob.data
    bvh = BVHTree.FromPolygons([v.co.copy() for v in hm.vertices],
                               [tuple(p.vertices) for p in hm.polygons])

    def project(x, z):
        p = Vector((center.x + x, HEAD_C.y, center.z + z))
        hit, nrm, _, _ = bvh.ray_cast(p, Vector((0, -1, 0)))
        if hit is None:
            hit, nrm, _, _ = bvh.find_nearest(p)
        return hit + nrm * 0.0022 - center

    ob.shape_key_add(name="Basis", from_mix=False)
    for sname, cols in shapes.items():
        kb = ob.data.shape_keys.key_blocks["Basis"] if sname == "Basis" else ob.shape_key_add(name=sname, from_mix=False)
        rr = rows_for(cols)
        for i in range(n):
            for r in range(R):
                kb.data[i * R + r].co = project(*rr[i][r])
        kb.value = 0.0          # Blender 5 creates new keys at 1.0
    return ob


def _brow_object(name, col, side, s, mat):
    # soft arched brows: the face's main acting tool
    c = _mirror(Vector((0.054, -0.149, 1.641)), s)
    pts = [Vector((-0.026 * s, 0.006, -0.003)), Vector((-0.008 * s, 0.000, 0.004)),
           Vector((0.013 * s, 0.002, 0.005)), Vector((0.031 * s, 0.013, -0.002))]
    radii = [0.0085, 0.0095, 0.0085, 0.0055]
    bm = bmesh.new()
    rings = []
    segs = 10
    samples = []
    for i in range(len(pts) - 1):
        for k in range(6):
            u = k / 6
            samples.append((pts[i].lerp(pts[i + 1], u), radii[i] + (radii[i + 1] - radii[i]) * u))
    samples.append((pts[-1], radii[-1]))
    for j, (p, r) in enumerate(samples):
        tan = (samples[min(j + 1, len(samples) - 1)][0] - samples[max(j - 1, 0)][0]).normalized()
        x = Vector((0, -1, 0))
        x = (x - tan * x.dot(tan)).normalized()
        y = tan.cross(x).normalized()
        ring = []
        for k in range(segs):
            a = 2 * math.pi * k / segs
            ring.append(bm.verts.new(p + x * math.cos(a) * r * 0.42 + y * math.sin(a) * r))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for k in range(segs):
            bm.faces.new([a[k], a[(k + 1) % segs], b[(k + 1) % segs], b[k]])
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        f = bm.faces.new(ring[::-1] if flip else ring)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = U.mesh_object(name, bm, col, mat)
    ob.location = c
    return ob


def _hair_object(name, col, mat, lod, seed=11):
    """Mop of soft clumps over a full cap, with Messy / Blown shape keys.

    The neat, messy and blown variants are built with identical topology,
    so they become shape keys of one mesh.
    """
    rng = random.Random(seed)
    segs, rings = (40, 22) if lod == "hero" else (16, 10)

    def cap():
        bm = U.bm_sphere(1.0, segs, rings)
        kill = []
        for v in bm.verts:
            x, y, z = v.co
            line = -0.10 + 0.55 * max(0.0, -y) - 0.25 * max(0.0, y)
            if abs(x) > 0.8 and y < 0.3:
                line -= 0.18                       # sideburns over the ears
            if z < line:
                kill.append(v)
            v.co = Vector((x * HEAD_R * 1.06, y * HEAD_R * 1.07, z * HEAD_R * 1.14)) + HEAD_C + Vector((0, 0.008, 0.012))
        bmesh.ops.delete(bm, geom=kill, context='VERTS')
        return bm

    clumps = []
    n = 34 if lod == "hero" else 12
    for i in range(n):
        if i < n * 0.4:          # fringe: swept to the character's right, over the forehead
            az = rng.uniform(-0.9, 0.9)
            el = rng.uniform(0.62, 0.95)
            flow = Vector((-0.55, -0.55, -0.6))
        elif i < n * 0.7:        # sides: flow down and back
            az = rng.choice((-1, 1)) * rng.uniform(1.0, 2.0)
            el = rng.uniform(0.2, 0.75)
            flow = Vector((0, 0.5, -0.8))
        else:                    # crown: flow back, a cowlick that refuses
            az = rng.uniform(-math.pi, math.pi)
            el = rng.uniform(0.85, 1.35)
            flow = Vector((0, 0.8, 0.1))
        nrm = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        base = HEAD_C + Vector((nrm.x * HEAD_R * 1.04, nrm.y * HEAD_R * 1.05, nrm.z * HEAD_R * 1.12))
        tang = (flow - nrm * flow.dot(nrm)).normalized()
        length = rng.uniform(0.045, 0.075)
        radius = rng.uniform(0.026, 0.038)
        clumps.append((base, nrm, tang, length, radius, rng.uniform(-1, 1), rng.uniform(-1, 1)))

    def build(variant):
        bms = [cap()]
        for base, nrm, tang, length, radius, j1, j2 in clumps:
            if variant == "neat":
                d = (tang * 0.95 + nrm * 0.16).normalized()
            elif variant == "messy":
                side = tang.cross(nrm).normalized()
                d = (tang * 0.7 + nrm * (0.45 + 0.2 * j1) + side * 0.35 * j2).normalized()
            else:  # blown back by the scream
                d = (Vector((0, 1.0, 0.25)) * 0.8 + nrm * 0.4).normalized()
            L = length * (1.15 if variant == "messy" else 1.0)
            bms.append(U.bm_capsule(base - nrm * 0.006, base + d * L, radius, radius * 0.38,
                                    segs=10 if lod == "hero" else 6, rings=3))
        return U.bm_join(*bms)

    ob = U.mesh_object(name, build("neat"), col, mat)
    ob.shape_key_add(name="Basis", from_mix=False)
    for kname, variant in (("Messy", "messy"), ("Blown", "blown")):
        kb = ob.shape_key_add(name=kname, from_mix=False)
        bm = build(variant)
        bm.verts.ensure_lookup_table()
        for i, v in enumerate(bm.verts):
            kb.data[i].co = v.co
        bm.free()
        kb.value = 0.0
    return ob


def _glasses(name, col, mat_frame, mat_lens, lod):
    parts = []
    lens_parts = []
    for side, s in SIDES:
        c = _mirror(EYE_POS, s) + Vector((0, -0.048, 0.003))
        rim = U.bm_torus(0.044, 0.0042, 36 if lod == "hero" else 16, 8, (0, 0, 0))
        bmesh.ops.rotate(rim, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, 'X'), verts=rim.verts)
        bmesh.ops.scale(rim, vec=(1.05, 1, 0.95), verts=rim.verts)
        bmesh.ops.rotate(rim, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(-8 * s), 3, 'Z'), verts=rim.verts)
        bmesh.ops.translate(rim, vec=c, verts=rim.verts)
        parts.append(rim)
        # temple arm back to the ear
        a0 = c + Vector((0.046 * s, 0.006, 0.004))
        a1 = Vector((0.158 * s, 0.03, 1.585))
        a2 = Vector((0.160 * s, 0.075, 1.555))
        parts.append(U.bm_capsule(a0, a1, 0.0032, 0.003, 8, 2))
        parts.append(U.bm_capsule(a1, a2, 0.003, 0.003, 8, 2))
        if lod == "hero":
            lens = U.bm_cylinder(0.043, 0.0015, 32, (0, 0, 0))
            bmesh.ops.rotate(lens, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, 'X'), verts=lens.verts)
            bmesh.ops.scale(lens, vec=(1.05, 1, 0.95), verts=lens.verts)
            bmesh.ops.rotate(lens, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(-8 * s), 3, 'Z'), verts=lens.verts)
            bmesh.ops.translate(lens, vec=c, verts=lens.verts)
            lens_parts.append(lens)
    bl = _mirror(EYE_POS, 1) + Vector((0, -0.048, 0.007))
    br = _mirror(EYE_POS, -1) + Vector((0, -0.048, 0.007))
    parts.append(U.bm_capsule(bl - Vector((0.04, 0, -0.006)), br + Vector((0.04, 0, 0.006)), 0.0035, 0.0035, 8, 2))
    fr = U.mesh_object(f"{name}_GlassesFrame", U.bm_join(*parts), col, mat_frame)
    lens_ob = U.mesh_object(f"{name}_GlassesLens", U.bm_join(*lens_parts), col, mat_lens) if lens_parts else None
    return fr, lens_ob


def _hand_geometry(rest_hand, side, s, lod):
    """Palm + wrist stub in world rest space (fingers are separate)."""
    hy = rest_hand.to_3x3() @ Vector((0, 1, 0))
    hx = rest_hand.to_3x3() @ Vector((1, 0, 0))
    hz = rest_hand.to_3x3() @ Vector((0, 0, 1))
    origin = rest_hand.translation
    # canonical palm in (palm_normal X, along Y, thumb Z) with x mirrored for R
    basis = Matrix((hx * s, hy, hz)).transposed()   # columns: X_c, Y, Z
    bm = U.bm_rounded_box((0.030, 0.100, 0.090), 0.014, 3 if lod == "hero" else 1, (0.0, 0.052, -0.001))
    # taper palm toward the wrist and cup it slightly
    for v in bm.verts:
        y = v.co.y
        k = 0.82 + 0.18 * max(0.0, min(1.0, y / 0.09))
        v.co.z *= k
        v.co.x += 0.004 * (v.co.z / 0.04) ** 2
    wrist = U.bm_capsule((0, -0.03, 0), (0, 0.012, 0), 0.022, 0.024, 12, 3)
    for v in wrist.verts:
        v.co.z *= 1.25
    bm = U.bm_join(bm, wrist)
    mat = Matrix.Translation(origin) @ basis.to_4x4()
    bmesh.ops.transform(bm, matrix=mat, verts=bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def build_character(name, col, lod="hero"):
    """Build the student. lod='hero' (full detail) or 'crowd' (lightweight)."""
    ch = Character()
    ch.name = name
    ch.lod = lod
    rig, rest = _build_armature(name, col)
    ch.rig, ch.rest = rig, rest
    mat_skin = M.skin()
    mat_hoodie = M.hoodie()
    mat_denim = M.denim()
    mat_hair = M.hair()
    mat_eye = M.eye()
    mat_shoe = M.simple("MAT_Sneaker", (0.82, 0.80, 0.76, 1), 0.55)
    mat_sole = M.simple("MAT_SneakerSole", (0.30, 0.16, 0.08, 1), 0.7)
    mat_frame = M.simple("MAT_GlassesFrame", (0.025, 0.018, 0.015, 1), 0.25)
    mat_lens = M.glass_lens()
    mat_string = M.simple("MAT_Drawstring", (0.85, 0.83, 0.78, 1), 0.8)
    mat_lidrim = M.simple("MAT_LidRim", (0.05, 0.025, 0.02, 1), 0.6)
    mat_bag = _eyebag_material()
    mouth_mats = M.mouth()
    sub_hero = (1, 2) if lod == "hero" else (0, 0)
    parts = {}

    # ---- head: one sculpted surface (Clay SDF), nose and ears blended in -----
    from . import head_sculpt as HS
    head = HS.build_head(f"{name}_Head", col, lod, EYE_POS, EYE_R)
    head.data.materials.append(mat_skin)
    parts["head"] = head

    # ---- eyes, lids, brows (separate objects, own pivots) ---------------
    ch.eyes, ch.lids, ch.lowlids, ch.brows = {}, {}, {}, {}
    for side, s in SIDES:
        c = _mirror(EYE_POS, s)
        er = EYE_R * (1.0 if side == "L" else 0.975)    # subtle asymmetry
        e = U.mesh_object(f"{name}_Eye.{side}", U.bm_sphere(er, 64 if lod == "hero" else 12, 32 if lod == "hero" else 8), col, mat_eye)
        e.location = c
        ch.eyes[side] = e
        lid = U.mesh_object(f"{name}_Lid.{side}", _lid_mesh(er * 1.13, True, 48 if lod == "hero" else 16, 14 if lod == "hero" else 6), col, [mat_skin, mat_lidrim])
        if lod == "hero":                       # heavy upper lid: a thick shelf
            sol = lid.modifiers.new("Thickness", 'SOLIDIFY')
            sol.thickness = 0.0035
            sol.offset = 1.0
        lid.location = c
        lid.rotation_euler = (math.radians(-40), 0, 0)
        ch.lids[side] = lid
        low = U.mesh_object(f"{name}_LowLid.{side}", _lid_mesh(er * 1.07, False, 48 if lod == "hero" else 16, 14 if lod == "hero" else 6), col, [mat_bag, mat_lidrim])
        low.location = c
        low.rotation_euler = (math.radians(55), 0, 0)
        ch.lowlids[side] = low
        brow = _brow_object(f"{name}_Brow.{side}", col, side, s, mat_hair)
        ch.brows[side] = brow
    ch.mouth = _mouth_object(f"{name}_Mouth", col, head, mouth_mats)
    ch.hair = HS.build_hair(f"{name}_Hair", col, lod)
    ch.hair.data.materials.append(mat_hair)
    # (no glasses: the director's reference design keeps the eyes free)
    head_parts = [head, ch.mouth, ch.hair]
    head_parts += list(ch.eyes.values()) + list(ch.lids.values()) + list(ch.lowlids.values()) + list(ch.brows.values())
    for ob in head_parts:
        # the sculpted head and hair are already dense: no subdivision on top
        _finalize(ob, rig, rigid("head"), subsurf=None)

    # ---- neck ---------------------------------------------------------
    # a tapered tube with real rings (a one-span cylinder subdivides into a striped barrel),
    # leaning slightly forward into the head
    neck_bm = _tube([(0, 0.002, 1.290), (0, -0.004, 1.370), (0, -0.016, 1.455)],
                    lambda t: 0.066 - 0.010 * t, segs=40 if lod == "hero" else 12,
                    scale_xy=(1.0, 0.92), ring_count=16 if lod == "hero" else 4)
    neck = U.mesh_object(f"{name}_Neck", neck_bm, col, mat_skin)
    _finalize(neck, rig, lambda co: {"chest": 1.0 - _smooth01((co.z - 1.30) / 0.08),
                                     "neck": _smooth01((co.z - 1.30) / 0.08) * (1 - _smooth01((co.z - 1.43) / 0.03)),
                                     "head": _smooth01((co.z - 1.43) / 0.03)}, subsurf=sub_hero)

    # ---- hoodie torso -------------------------------------------------
    prof = [(0.855, 0.180, 0.125), (0.875, 0.196, 0.136), (0.95, 0.200, 0.138), (1.02, 0.194, 0.132),
            (1.10, 0.198, 0.132), (1.18, 0.210, 0.138), (1.25, 0.212, 0.136), (1.29, 0.200, 0.128),
            (1.325, 0.160, 0.112), (1.35, 0.095, 0.085), (1.365, 0.075, 0.072)]
    segs = 56 if lod == "hero" else 14
    if lod == "hero":                      # resample the profile finely (smooth silhouette)
        fine = []
        for (z0, a0, b0), (z1, a1, b1) in zip(prof, prof[1:]):
            for k in range(4):
                t = k / 4
                fine.append((z0 + (z1 - z0) * t, a0 + (a1 - a0) * t, b0 + (b1 - b0) * t))
        fine.append(prof[-1])
        prof = fine
    bm = bmesh.new()
    rings = []
    for z, rx, ry in prof:
        ring = []
        for k in range(segs):
            a = 2 * math.pi * k / segs
            x, y = math.cos(a) * rx, math.sin(a) * ry
            # flatter back, fuller front; slight fabric wobble
            if y > 0:
                y *= 0.92
            wob = 1.0 + 0.012 * math.sin(a * 5 + z * 40) if lod == "hero" else 1.0
            ring.append(bm.verts.new((x * wob, y * wob - 0.004, z)))
        rings.append(ring)
    for a_, b_ in zip(rings, rings[1:]):
        for k in range(segs):
            bm.faces.new([a_[k], a_[(k + 1) % segs], b_[(k + 1) % segs], b_[k]])
    bm.faces.new(rings[0][::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    torso = U.mesh_object(f"{name}_Hoodie", bm, col, mat_hoodie)

    def torso_w(co):
        z = co.z
        wh = 1 - _smooth01((z - 0.96) / 0.10)
        wc = _smooth01((z - 1.12) / 0.12)
        ws = max(0.0, 1 - wh - wc)
        w = {"hips": wh, "spine": ws, "chest": wc}
        if z > 1.33:
            w = {"chest": 0.6, "neck": 0.4}
        return w
    _finalize(torso, rig, torso_w, subsurf=sub_hero)
    parts["hoodie"] = torso
    # hood bunched behind the neck, hem band, kangaroo pocket, drawstrings
    hood = U.bm_torus(0.105, 0.046, 56 if lod == "hero" else 12, 18 if lod == "hero" else 6, (0, 0, 0), arc=math.radians(250))
    bmesh.ops.rotate(hood, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(-35), 3, 'Z'), verts=hood.verts)
    bmesh.ops.scale(hood, vec=(1.0, 0.95, 0.75), verts=hood.verts)
    bmesh.ops.rotate(hood, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(-12), 3, 'X'), verts=hood.verts)
    bmesh.ops.translate(hood, vec=(0, 0.035, 1.345), verts=hood.verts)
    hood_ob = U.mesh_object(f"{name}_Hood", hood, col, mat_hoodie)
    _finalize(hood_ob, rig, lambda co: {"chest": 0.7, "neck": 0.3}, subsurf=sub_hero)
    # ribbed crew collar: hides the base of the neck (a long bare neck reads as a peg)
    collar = U.bm_torus(0.071, 0.011, 48 if lod == "hero" else 12, 10 if lod == "hero" else 4, (0, 0, 0))
    bmesh.ops.scale(collar, vec=(1.0, 0.93, 0.85), verts=collar.verts)
    bmesh.ops.rotate(collar, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(-8), 3, 'X'), verts=collar.verts)
    bmesh.ops.translate(collar, vec=(0, -0.004, 1.378), verts=collar.verts)
    collar_ob = U.mesh_object(f"{name}_Collar", collar, col, mat_hoodie)
    _finalize(collar_ob, rig, lambda co: {"chest": 0.65, "neck": 0.35}, subsurf=sub_hero)
    hem = U.bm_torus(1.0, 0.016, segs, 6, (0, 0, 0))
    bmesh.ops.scale(hem, vec=(0.184, 0.128, 1.0), verts=hem.verts)
    for v in hem.verts:
        v.co.z = v.co.z * 1.0
    bmesh.ops.translate(hem, vec=(0, -0.004, 0.865), verts=hem.verts)
    hem_ob = U.mesh_object(f"{name}_HoodieHem", hem, col, mat_hoodie)
    _finalize(hem_ob, rig, rigid("hips"), subsurf=sub_hero)
    if lod == "hero":
        pocket = U.bm_rounded_box((0.21, 0.018, 0.11), 0.008, 2, (0, -0.135, 0.955))
        for v in pocket.verts:
            v.co.y -= 0.0 if v.co.y > -0.135 else 0.0
            v.co.y += 0.25 * (v.co.x ** 2)          # follow belly curvature
        pk = U.mesh_object(f"{name}_Pocket", pocket, col, mat_hoodie)
        _finalize(pk, rig, lambda co: {"hips": 0.6, "spine": 0.4}, subsurf=(1, 1))
        for side, s in SIDES:
            p0 = Vector((0.034 * s, -0.112, 1.33))
            p1 = Vector((0.040 * s, -0.150, 1.20))
            p2 = Vector((0.036 * s, -0.152, 1.13))
            st = U.bm_join(U.bm_capsule(p0, p1, 0.0045, 0.0045, 8, 2), U.bm_capsule(p1, p2, 0.0045, 0.0055, 8, 2))
            so = U.mesh_object(f"{name}_Drawstring.{side}", st, col, mat_string)
            _finalize(so, rig, rigid("chest"), subsurf=None)

    # ---- sleeves (deform at elbow) --------------------------------------
    for side, s in SIDES:
        sh = rest[f"upperarm.{side}"].translation
        el = rest[f"forearm.{side}"].translation
        wr = rest[f"hand.{side}"].translation
        wr_ext = wr + (wr - el).normalized() * 0.012
        path = [sh.lerp(rest[f"clavicle.{side}"].translation, 0.4) + Vector((0, 0, -0.02)), sh + Vector((0, 0, -0.01)), el, wr_ext]
        L1 = (el - sh).length
        L2 = (wr_ext - el).length

        def rfn(t, L1=L1, L2=L2):
            d = t * (L1 + L2)
            if d < L1:
                r = 0.066 - 0.012 * (d / L1)
            else:
                u = (d - L1) / L2
                r = 0.054 - 0.006 * u
                if u > 0.62:                        # bunching near the cuff
                    r *= 1.0 + 0.10 * math.sin((u - 0.62) * 48) * (1 - u)
                if u > 0.9:
                    r = 0.043
            return r
        sb = _tube(path, rfn, segs=36 if lod == "hero" else 10, twist_ref=(0, -1, 0),
                   ring_count=110 if lod == "hero" else None)
        sl = U.mesh_object(f"{name}_Sleeve.{side}", sb, col, mat_hoodie)

        def sw(co, sh=sh, el=el, wr=wr, side=side):
            t1 = _seg_param(co, sh, el)
            t2 = _seg_param(co, el, wr)
            d1 = (sh.lerp(el, t1) - co).length
            d2 = (el.lerp(wr, t2) - co).length
            if d1 < d2 or t2 <= 0.0:
                fa = _smooth01((t1 - 0.82) / 0.36)
                ch_w = 1 - _smooth01(t1 / 0.18)
                return {f"upperarm.{side}": (1 - fa) * (1 - ch_w), f"forearm.{side}": fa,
                        f"clavicle.{side}": ch_w * 0.8, "chest": ch_w * 0.2}
            fa = 1 - _smooth01((0.14 - t2) / 0.28) * 0.5 if t2 < 0.14 else 1.0
            h = _smooth01((t2 - 0.96) / 0.08)
            return {f"upperarm.{side}": 1 - fa, f"forearm.{side}": fa * (1 - h), f"hand.{side}": fa * h * 0.5}
        _finalize(sl, rig, sw, subsurf=sub_hero)
        parts[f"sleeve.{side}"] = sl

    # ---- hands + fingers ------------------------------------------------
    for side, s in SIDES:
        hbm = _hand_geometry(rest[f"hand.{side}"], side, s, lod)
        hand = U.mesh_object(f"{name}_Hand.{side}", hbm, col, mat_skin)
        _finalize(hand, rig, rigid(f"hand.{side}"), subsurf=sub_hero if lod == "hero" else None)
        parts[f"hand.{side}"] = hand
        digit_bms = []
        digit_bones = []
        for fname, _z, l1, l2, r in FINGERS + [("thumb", 0, 0.041, 0.034, 0.0132)]:
            for seg, rr in ((1, r), (2, r * 0.9)):
                bname = f"{fname}{seg}.{side}"
                bm_ = rest[bname]
                head_p = bm_.translation
                length = (l1 if seg == 1 else l2)
                tail_p = head_p + bm_.to_3x3() @ Vector((0, length, 0))
                end_r = rr * 0.92
                cap = U.bm_capsule(head_p, tail_p - (tail_p - head_p).normalized() * (0.002 if seg == 1 else 0.0),
                                   rr, end_r, 10 if lod == "hero" else 6, 3 if lod == "hero" else 1)
                digit_bms.append((cap, bname))
        if lod == "hero":
            for cap, bname in digit_bms:
                f_ob = U.mesh_object(f"{name}_Digit_{bname}", cap, col, mat_skin)
                _finalize(f_ob, rig, rigid(bname), subsurf=(1, 2))
        else:
            # crowd: fuse fingers into a mitten shape weighted to the hand
            mit = U.bm_join(*[c for c, _ in digit_bms])
            f_ob = U.mesh_object(f"{name}_Fingers.{side}", mit, col, mat_skin)
            _finalize(f_ob, rig, rigid(f"hand.{side}"), subsurf=None)

    # ---- legs: jeans + sneakers ---------------------------------------
    for side, s in SIDES:
        hp = rest[f"thigh.{side}"].translation
        kn = rest[f"shin.{side}"].translation
        an = rest[f"foot.{side}"].translation
        path = [hp + Vector((0, 0, 0.03)), kn, an + Vector((0, 0, -0.01))]
        L1 = (kn - hp).length

        def lr(t, L1=L1):
            d = t * (L1 + 0.45)
            if d < L1:
                return 0.090 - 0.030 * (d / L1)
            u = (d - L1) / 0.45
            return 0.060 - 0.004 * u + (0.01 * math.sin(u * 30) * u if u > 0.7 else 0)
        jb = _tube(path, lr, segs=32 if lod == "hero" else 10, twist_ref=(0, -1, 0),
                   ring_count=120 if lod == "hero" else None)
        jeans = U.mesh_object(f"{name}_Jeans.{side}", jb, col, mat_denim)

        def jw(co, hp=hp, kn=kn, an=an, side=side):
            t1 = _seg_param(co, hp, kn)
            t2 = _seg_param(co, kn, an)
            d1 = (hp.lerp(kn, t1) - co).length
            d2 = (kn.lerp(an, t2) - co).length
            if d1 < d2 or t2 <= 0:
                sh_w = _smooth01((t1 - 0.86) / 0.28)
                hip_w = 1 - _smooth01(t1 / 0.12)
                return {"hips": hip_w * 0.6, f"thigh.{side}": (1 - sh_w) * (1 - hip_w * 0.6), f"shin.{side}": sh_w}
            sh_w = 1 - (_smooth01((0.14 - t2) / 0.28) * 0.5 if t2 < 0.14 else 0.0)
            return {f"thigh.{side}": 1 - sh_w, f"shin.{side}": sh_w}
        _finalize(jeans, rig, jw, subsurf=sub_hero)
        parts[f"jeans.{side}"] = jeans
        # sneaker
        sk = U.bm_rounded_box((0.104, 0.27, 0.085), 0.035, 3 if lod == "hero" else 1, (0.10 * s, -0.045, 0.048))
        for v in sk.verts:
            if v.co.y < -0.10:                       # toe box lower & rounder
                v.co.z = 0.012 + (v.co.z - 0.012) * (1 - 0.35 * (-(v.co.y + 0.10) / 0.08))
        shoe = U.mesh_object(f"{name}_Sneaker.{side}", sk, col, mat_shoe)
        _finalize(shoe, rig, rigid(f"foot.{side}"), subsurf=sub_hero if lod == "hero" else None)
        sole = U.bm_rounded_box((0.100, 0.262, 0.022), 0.01, 2 if lod == "hero" else 1, (0.10 * s, -0.045, 0.011))
        so = U.mesh_object(f"{name}_Sole.{side}", sole, col, mat_sole)
        _finalize(so, rig, rigid(f"foot.{side}"), subsurf=None)
    # pelvis block under the hoodie (keeps the hip joint closed when sitting)
    pel = U.bm_rounded_box((0.27, 0.19, 0.17), 0.07, 3 if lod == "hero" else 1, (0, 0.005, 0.90))
    pelvis = U.mesh_object(f"{name}_Pelvis", pel, col, mat_denim)
    _finalize(pelvis, rig, rigid("hips"), subsurf=sub_hero)

    # parent everything to the rig object so the rig places the character
    for ob in col.objects:
        if ob is not rig and ob.parent is None:
            _parent_keep(ob, rig)
    ch.parts = parts
    ch.bag_material = mat_bag
    return ch


def _eyebag_material():
    """Lower-lid skin that darkens with the 'Stress' value (driven later)."""
    m = bpy.data.materials.get("MAT_EyeBag")
    if m:
        return m
    m = bpy.data.materials.new("MAT_EyeBag")
    m.use_nodes = True
    nb = M.NB(m.node_tree)
    nb.nodes.clear()
    p = nb.n("ShaderNodeBsdfPrincipled", (0, 0))
    p.inputs["Roughness"].default_value = 0.5
    p.inputs["Subsurface Weight"].default_value = 0.2
    p.inputs["Subsurface Scale"].default_value = 0.02
    out = nb.n("ShaderNodeOutputMaterial", (300, 0))
    nb.l(p.outputs[0], out.inputs[0])
    v = nb.n("ShaderNodeValue", (-500, 0))
    v.name = "Stress"
    v.outputs[0].default_value = 0.0
    mix = nb.n("ShaderNodeMix", (-250, 0), _data_type='RGBA')
    mix.inputs[6].default_value = (0.60, 0.38, 0.28, 1)
    mix.inputs[7].default_value = (0.26, 0.15, 0.17, 1)
    nb.l(v.outputs[0], mix.inputs["Factor"])
    nb.l(mix.outputs[2], p.inputs["Base Color"])
    return m
