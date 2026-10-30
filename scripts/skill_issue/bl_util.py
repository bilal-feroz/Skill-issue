"""Small, reusable bpy helpers: collections, primitives, baking animation."""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

def collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def link(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)
    return obj


def empty(name, col, loc=(0, 0, 0), display="PLAIN_AXES", size=0.2, parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = display
    ob.empty_display_size = size
    ob.location = loc
    col.objects.link(ob)
    if parent:
        ob.parent = parent
    return ob


# ---------------------------------------------------------------------------
# Mesh primitives (bmesh, no operators -> fast and context-free)
# ---------------------------------------------------------------------------

def mesh_object(name, bm, col, mat=None, smooth=True, loc=(0, 0, 0), rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = rot
    col.objects.link(ob)
    if mat is not None:
        mats = mat if isinstance(mat, (list, tuple)) else [mat]
        for m in mats:
            me.materials.append(m)
    return ob


def bm_box(size=(1, 1, 1), center=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return bm


def bm_rounded_box(size=(1, 1, 1), radius=0.05, segments=3, center=(0, 0, 0)):
    bm = bm_box(size, center)
    r = min(radius, min(size) * 0.49)
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=r, segments=segments,
                    affect='EDGES', profile=0.5, clamp_overlap=True)
    return bm


def bm_cylinder(radius=0.5, depth=1.0, segments=24, center=(0, 0, 0), cap=True, radius2=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius if radius2 is None else radius2,
                          depth=depth)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return bm


def bm_sphere(radius=0.5, segs=24, rings=12, center=(0, 0, 0), scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return bm


def bm_capsule(p0, p1, r0, r1=None, segs=16, rings=6):
    """Tapered capsule between two points (two hemispheres + tube)."""
    r1 = r0 if r1 is None else r1
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    length = axis.length
    bm = bmesh.new()
    verts_rings = []
    # profile along local Z from -r0 (cap) to length + r1 (cap)
    profile = []
    for i in range(rings + 1):
        a = -math.pi / 2 + (math.pi / 2) * i / rings
        profile.append((math.sin(a) * r0, math.cos(a) * r0))
    for i in range(rings + 1):
        a = (math.pi / 2) * i / rings
        profile.append((length + math.sin(a) * r1, math.cos(a) * r1))
    for z, r in profile:
        ring = []
        for s in range(segs):
            t = 2 * math.pi * s / segs
            ring.append(bm.verts.new((math.cos(t) * r, math.sin(t) * r, z)))
        verts_rings.append(ring)
    for a, b in zip(verts_rings, verts_rings[1:]):
        for s in range(segs):
            v = [a[s], a[(s + 1) % segs], b[(s + 1) % segs], b[s]]
            if len({x.co.to_tuple(6) for x in v}) >= 3:
                try:
                    bm.faces.new(v)
                except ValueError:
                    pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    rot = Vector((0, 0, 1)).rotation_difference(axis.normalized() if length > 1e-9 else Vector((0, 0, 1)))
    bmesh.ops.transform(bm, matrix=Matrix.Translation(p0) @ rot.to_matrix().to_4x4(), verts=bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def bm_torus(major=0.5, minor=0.1, seg_major=32, seg_minor=12, center=(0, 0, 0), arc=2 * math.pi):
    bm = bmesh.new()
    closed = arc >= 2 * math.pi - 1e-6
    n_maj = seg_major if closed else seg_major + 1
    rings = []
    for i in range(n_maj):
        u = arc * i / seg_major
        cu, su = math.cos(u), math.sin(u)
        ring = []
        for j in range(seg_minor):
            v = 2 * math.pi * j / seg_minor
            r = major + minor * math.cos(v)
            ring.append(bm.verts.new((center[0] + r * cu, center[1] + r * su, center[2] + minor * math.sin(v))))
        rings.append(ring)
    pairs = list(zip(rings, rings[1:])) + ([(rings[-1], rings[0])] if closed else [])
    for a, b in pairs:
        for j in range(seg_minor):
            bm.faces.new([a[j], b[j], b[(j + 1) % seg_minor], a[(j + 1) % seg_minor]])
    return bm


def bm_join(*bms):
    out = bmesh.new()
    for b in bms:
        me = bpy.data.meshes.new("_tmp")
        b.to_mesh(me)
        out.from_mesh(me)
        bpy.data.meshes.remove(me)
        b.free()
    return out


def add_subsurf(ob, levels=1, render=2):
    m = ob.modifiers.new("Subsurf", 'SUBSURF')
    m.levels = levels
    m.render_levels = render
    return m


def add_bevel(ob, width=0.01, segments=2):
    m = ob.modifiers.new("Bevel", 'BEVEL')
    m.width = width
    m.segments = segments
    m.limit_method = 'ANGLE'
    return m


def curve_object(name, points, col, bevel=0.01, mat=None, closed=False, resolution=12,
                 handle='AUTO', fill_caps=True):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.resolution_u = resolution
    cu.bevel_depth = bevel
    cu.bevel_resolution = 3
    cu.use_fill_caps = fill_caps
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(len(points) - 1)
    for bp, p in zip(sp.bezier_points, points):
        bp.co = p
        bp.handle_left_type = handle
        bp.handle_right_type = handle
    sp.use_cyclic_u = closed
    ob = bpy.data.objects.new(name, cu)
    col.objects.link(ob)
    if mat:
        cu.materials.append(mat)
    return ob


# ---------------------------------------------------------------------------
# Animation baking: fast per-frame fcurves via foreach_set
# ---------------------------------------------------------------------------

def _channelbag(id_data):
    from bpy_extras import anim_utils
    ad = id_data.animation_data or id_data.animation_data_create()
    if ad.action is None:
        act = bpy.data.actions.new(f"ACT_{id_data.name}")
        ad.action = act
    act = ad.action
    if ad.action_slot is None:
        slot = act.slots.new(id_type=id_data.id_type, name=id_data.name)
        ad.action_slot = slot
    return anim_utils.action_ensure_channelbag_for_slot(act, ad.action_slot)


def bake(id_data, data_path, index, frames, values, interp='LINEAR'):
    """Write one fcurve with a key on every given frame (replaces existing)."""
    cb = _channelbag(id_data)
    fc = cb.fcurves.find(data_path, index=index)
    if fc is not None:
        cb.fcurves.remove(fc)
    fc = cb.fcurves.new(data_path, index=index)
    n = len(frames)
    fc.keyframe_points.add(n)
    co = [0.0] * (2 * n)
    co[0::2] = [float(f) for f in frames]
    co[1::2] = [float(v) for v in values]
    fc.keyframe_points.foreach_set("co", co)
    ip = {'LINEAR': 1, 'CONSTANT': 0, 'BEZIER': 2}[interp]
    fc.keyframe_points.foreach_set("interpolation", [ip] * n)
    fc.update()
    return fc


def bake_vec(id_data, data_path, frames, vectors, interp='LINEAR'):
    for i in range(len(vectors[0])):
        bake(id_data, data_path, i, frames, [v[i] for v in vectors], interp)


def key_constant(id_data, data_path, index, keys):
    """keys: list of (frame, value) -> CONSTANT interpolation fcurve."""
    keys = sorted(keys)
    bake(id_data, data_path, index, [k[0] for k in keys], [k[1] for k in keys], 'CONSTANT')


# ---------------------------------------------------------------------------
# Keyframe evaluation in Python (pose-to-pose with easing), so procedural
# layers can be added before baking.
# ---------------------------------------------------------------------------

def ease(t, kind="smooth"):
    t = max(0.0, min(1.0, t))
    if kind == "linear":
        return t
    if kind == "smooth":
        return t * t * (3 - 2 * t)
    if kind == "smoother":
        return t * t * t * (t * (t * 6 - 15) + 10)
    if kind == "in":
        return t * t * t
    if kind == "out":
        return 1 - (1 - t) ** 3
    if kind == "out2":
        return 1 - (1 - t) ** 2
    if kind == "expo_out":
        return 1 - 2 ** (-10 * t) if t < 1 else 1.0
    if kind == "back":       # overshoot then settle
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
    if kind == "elastic":
        if t in (0.0, 1.0):
            return t
        return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1
    if kind == "bounce":
        n1, d1 = 7.5625, 2.75
        if t < 1 / d1:
            return n1 * t * t
        if t < 2 / d1:
            t -= 1.5 / d1
            return n1 * t * t + 0.75
        if t < 2.5 / d1:
            t -= 2.25 / d1
            return n1 * t * t + 0.9375
        t -= 2.625 / d1
        return n1 * t * t + 0.984375
    if kind == "step":
        return 1.0 if t >= 1.0 else 0.0
    return t


class Track:
    """Keys: (frame, value, ease_into_this_key). Values may be floats or tuples."""

    def __init__(self, default=0.0):
        self.keys = []
        self.default = default

    def key(self, frame, value, kind="smooth"):
        self.keys.append((frame, value, kind))
        self.keys.sort(key=lambda k: k[0])
        return self

    def __call__(self, f):
        ks = self.keys
        if not ks:
            return self.default
        if f <= ks[0][0]:
            return ks[0][1]
        if f >= ks[-1][0]:
            return ks[-1][1]
        for (f0, v0, _), (f1, v1, kind) in zip(ks, ks[1:]):
            if f0 <= f <= f1:
                t = ease((f - f0) / max(1e-9, f1 - f0), kind)
                if isinstance(v0, (tuple, list, Vector)):
                    return tuple(a + (b - a) * t for a, b in zip(v0, v1))
                return v0 + (v1 - v0) * t
        return ks[-1][1]


def noise1(x, seed=0):
    """Cheap deterministic smooth 1D value noise in [-1, 1]."""
    def h(i):
        n = (i * 374761393 + seed * 668265263) & 0xFFFFFFFF
        n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
        return ((n ^ (n >> 16)) & 0xFFFF) / 32767.5 - 1.0
    i = math.floor(x)
    t = x - i
    t = t * t * (3 - 2 * t)
    return h(i) * (1 - t) + h(i + 1) * t


def fbm(x, seed=0, octaves=3):
    v, a, fr = 0.0, 0.5, 1.0
    for o in range(octaves):
        v += a * noise1(x * fr, seed + o * 17)
        a *= 0.5
        fr *= 2.03
    return v
