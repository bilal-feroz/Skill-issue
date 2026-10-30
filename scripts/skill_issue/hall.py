"""Act IV: the industrial conveyor hall.

* Analytic oval track (track.py) -> belt ribbons, side rails, a cyclic
  centre-line curve for Geometry Nodes.
* GN_Crowd: thousands of identical students. Positions along the belts are
  computed in Geometry Nodes from BeltDistance (driven by the speed controller),
  typing arms and nodding heads are driven by CrowdTypingPhase, and every screen
  picks a different AI announcement from an atlas with a per-instance attribute.
* GN_FarLoops: the same system repeated across a grid of distant loops.
* The CAUGHT UP finish gate, the stadium display, columns, gantries.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import bl_util as U
from . import materials as M
from . import track as TR

BELT_TOP = -0.20
STATION_Z = BELT_TOP


class Hall:
    pass


# ---------------------------------------------------------------------------
# Geometry Nodes helper
# ---------------------------------------------------------------------------

class G:
    def __init__(self, name):
        ng = bpy.data.node_groups.get(name)
        if ng:
            bpy.data.node_groups.remove(ng)
        self.ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
        self.nodes, self.links = self.ng.nodes, self.ng.links
        self.inp = self.nodes.new('NodeGroupInput')
        self.out = self.nodes.new('NodeGroupOutput')
        self.ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        self.ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        self.x = 0

    def socket(self, name, stype, default=None, minv=None, maxv=None):
        s = self.ng.interface.new_socket(name, in_out='INPUT', socket_type=stype)
        if default is not None:
            s.default_value = default
        if minv is not None:
            s.min_value = minv
        if maxv is not None:
            s.max_value = maxv
        return self.inp.outputs[name]

    def n(self, type_, **kw):
        node = self.nodes.new(type_)
        self.x += 160
        node.location = (self.x, 0)
        for k, v in kw.items():
            if k.startswith("_"):
                setattr(node, k[1:], v)
            else:
                node.inputs[k].default_value = v
        return node

    def l(self, a, b):
        self.links.new(a, b)

    def math(self, op, a, b=None, c=None):
        node = self.n('ShaderNodeMath', _operation=op)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                node.inputs[i].default_value = v
            else:
                self.l(v, node.inputs[i])
        return node.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        node = self.n('ShaderNodeVectorMath', _operation=op)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (tuple, list, Vector)):
                node.inputs[i].default_value = v
            else:
                self.l(v, node.inputs[i])
        if scale is not None:
            if isinstance(scale, (int, float)):
                node.inputs["Scale"].default_value = scale
            else:
                self.l(scale, node.inputs["Scale"])
        return node.outputs["Value"] if op in ('DOT_PRODUCT', 'LENGTH', 'DISTANCE') else node.outputs["Vector"]


def _track_curve(col):
    cu = bpy.data.curves.new("TrackCenterline", 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('POLY')
    ss = TR.samples(2.0, 1.0)
    sp.points.add(len(ss) - 1)
    for p, s in zip(sp.points, ss):
        (x, y), _ = TR.point(s)
        p.co = (x, y, 0.0, 1.0)
    sp.use_cyclic_u = True
    ob = bpy.data.objects.new("TrackCenterline", cu)
    col.objects.link(ob)
    ob.hide_render = True
    return ob


def _ribbon(name, col, mat, offset, width, z_top, thickness, step=2.0, uv=True):
    """Belt slab along the oval at lateral offset. UV.x = arc length (m)."""
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    ss = TR.samples(step, 1.0) + [TR.LENGTH]
    rows = []
    for s in ss:
        (x, y), t = TR.point(s)
        sx, sy = TR.side(t)
        row = []
        for k, (o, z) in enumerate(((offset - width / 2, z_top - thickness), (offset - width / 2, z_top),
                                     (offset + width / 2, z_top), (offset + width / 2, z_top - thickness))):
            row.append(bm.verts.new((x + sx * o, y + sy * o, z)))
        rows.append((s, row))
    for (s0, r0), (s1, r1) in zip(rows, rows[1:]):
        for k in range(3):
            f = bm.faces.new([r0[k], r1[k], r1[k + 1], r0[k + 1]])
            for loop in f.loops:
                vi = loop.vert
                s_ = s0 if vi in r0 else s1
                kk = (r0.index(vi) if vi in r0 else r1.index(vi))
                loop[uvl].uv = (s_, kk / 3.0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = U.mesh_object(name, bm, col, mat, smooth=False)
    return ob


def _join_objects(name, objs, col):
    bm = bmesh.new()
    mats = []
    for o in objs:
        me = o.data.copy()
        me.transform(o.matrix_world)
        start = len(mats)
        for m in o.data.materials:
            mats.append(m)
        for p in me.polygons:
            p.material_index += start
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    ob = U.mesh_object(name, bm, col, None, smooth=False)
    for m in mats:
        ob.data.materials.append(m)
    return ob


def build_station_assets(col_assets, crowd_ch, crowd_seated_fn):
    """Bake the posed crowd character into instanceable parts + a desk set.

    Station-local frame: origin on the belt surface, the student faces +Y.
    crowd_seated_fn(ch) poses the character (sitting, typing) and returns the
    world matrix that maps the character into station space.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    groups = {"body": [], "head": [], "armL": [], "armR": []}
    tf = crowd_seated_fn(crowd_ch)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    for ob in list(crowd_ch.rig.children_recursive):
        if ob.type != 'MESH':
            continue
        n = ob.name
        if any(k in n for k in ("Head", "Nose", "Ear", "Eye", "Lid", "Brow", "Mouth", "Hair", "Glasses")):
            g = "head"
        elif any(k in n for k in ("Sleeve.L", "Hand.L", "Fingers.L")):
            g = "armL"
        elif any(k in n for k in ("Sleeve.R", "Hand.R", "Fingers.R")):
            g = "armR"
        else:
            g = "body"
        ev = ob.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, depsgraph=dg)
        me.transform(tf @ ob.matrix_world)
        tmp = bpy.data.objects.new("_tmp_" + n, me)
        groups[g].append(tmp)
    out = {}
    for g, objs in groups.items():
        out[g] = _join_objects(f"Crowd_{g}", objs, col_assets)
        for o in objs:
            bpy.data.meshes.remove(o.data)
    return out


def build_desk_set(col_assets, room_mats):
    """Low-poly desk + chair + monitor + lamp for the crowd (station-local)."""
    m_wood, m_black, m_steel, m_bulb, m_chair = room_mats
    parts = []
    top = 0.75
    parts.append(U.mesh_object("_d1", U.bm_box((1.4, 0.65, 0.035), (0, 0.55, top - 0.0175)), col_assets, m_wood, smooth=False))
    legs = [U.bm_box((0.035, 0.035, top), (x, y, top / 2)) for x in (-0.66, 0.66) for y in (0.27, 0.83)]
    parts.append(U.mesh_object("_d2", U.bm_join(*legs), col_assets, m_steel, smooth=False))
    parts.append(U.mesh_object("_d3", U.bm_join(U.bm_box((0.62, 0.03, 0.37), (0.15, 0.78, top + 0.40)),
                                                 U.bm_box((0.04, 0.03, 0.22), (0.15, 0.80, top + 0.11)),
                                                 U.bm_box((0.22, 0.16, 0.012), (0.15, 0.80, top + 0.006)),
                                                 U.bm_box((0.32, 0.22, 0.015), (0.0, 0.42, top + 0.008))),
                                      col_assets, m_black, smooth=False))
    parts.append(U.mesh_object("_d4", U.bm_join(U.bm_cylinder(0.06, 0.02, 10, (-0.55, 0.75, top + 0.01)),
                                                 U.bm_capsule((-0.55, 0.75, top), (-0.5, 0.6, top + 0.38), 0.008, 0.008, 6, 1),
                                                 U.bm_cylinder(0.065, 0.1, 12, (-0.42, 0.52, top + 0.38), radius2=0.025)),
                                      col_assets, m_steel, smooth=False))
    parts.append(U.mesh_object("_d5", U.bm_sphere(0.03, 8, 6, (-0.42, 0.52, top + 0.33)), col_assets, m_bulb))
    parts.append(U.mesh_object("_d6", U.bm_join(U.bm_rounded_box((0.46, 0.44, 0.07), 0.03, 1, (0, -0.12, 0.47)),
                                                 U.bm_rounded_box((0.42, 0.06, 0.5), 0.03, 1, (0, -0.36, 0.82)),
                                                 U.bm_cylinder(0.025, 0.4, 8, (0, -0.12, 0.22)),
                                                 U.bm_cylinder(0.3, 0.03, 10, (0, -0.12, 0.03))),
                                      col_assets, m_chair, smooth=False))
    parts.append(U.mesh_object("_d7", U.bm_join(*[U.bm_box((0.2, 0.15, 0.04), (0.5, 0.45, top + 0.02 + 0.042 * k)) for k in range(4)]),
                               col_assets, M.random_color_material("MAT_CrowdBooks", [(0.35, 0.05, 0.04, 1), (0.05, 0.12, 0.25, 1), (0.6, 0.45, 0.1, 1), (0.08, 0.2, 0.12, 1)]), smooth=False))
    plate = U.mesh_object("_d8", U.bm_box((1.8, 2.0, 0.08), (0, 0.1, 0.04)), col_assets, m_steel, smooth=False)
    parts.append(plate)
    desk = _join_objects("Crowd_DeskSet", parts, col_assets)
    for p in parts:
        bpy.data.objects.remove(p)
    screen = bpy.data.meshes.new("Crowd_Screen")
    w, h = 0.58, 0.33
    cx, cy, cz = 0.15, 0.7625, top + 0.40
    screen.from_pydata([(cx - w / 2, cy, cz - h / 2), (cx + w / 2, cy, cz - h / 2), (cx + w / 2, cy, cz + h / 2), (cx - w / 2, cy, cz + h / 2)], [], [(0, 1, 2, 3)])
    uv = screen.uv_layers.new(name="UVMap")
    for li, c in zip(range(4), [(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[li].uv = c
    sc = bpy.data.objects.new("Crowd_Screen", screen)
    col_assets.objects.link(sc)
    return desk, sc


def crowd_screen_material(atlas_path):
    """Picks one of 16 atlas tiles per instance via the instancer attribute 'tile'."""
    m = bpy.data.materials.get("MAT_CrowdScreen")
    if m:
        return m
    m = bpy.data.materials.new("MAT_CrowdScreen")
    m.use_nodes = True
    nb = M.NB(m.node_tree)
    nb.nodes.clear()
    attr = nb.n("ShaderNodeAttribute", (-1200, 200))
    attr.attribute_type = 'INSTANCER'
    attr.attribute_name = "tile"
    tc = nb.n("ShaderNodeTexCoord", (-1200, -100))
    col_ = nb.n("ShaderNodeMath", (-1000, 300), _operation='MODULO')
    col_.inputs[1].default_value = 4.0
    nb.l(attr.outputs["Fac"], col_.inputs[0])
    row = nb.n("ShaderNodeMath", (-1000, 150), _operation='DIVIDE')
    row.inputs[1].default_value = 4.0
    nb.l(attr.outputs["Fac"], row.inputs[0])
    rowf = nb.n("ShaderNodeMath", (-850, 150), _operation='FLOOR')
    nb.l(row.outputs[0], rowf.inputs[0])
    rowi = nb.n("ShaderNodeMath", (-700, 150), _operation='SUBTRACT')
    rowi.inputs[0].default_value = 3.0
    nb.l(rowf.outputs[0], rowi.inputs[1])
    sep = nb.n("ShaderNodeSeparateXYZ", (-1000, -100))
    nb.l(tc.outputs["UV"], sep.inputs[0])
    u = nb.n("ShaderNodeMath", (-600, 0), _operation='ADD')
    nb.l(sep.outputs["X"], u.inputs[0])
    nb.l(col_.outputs[0], u.inputs[1])
    u4 = nb.n("ShaderNodeMath", (-450, 0), _operation='DIVIDE')
    u4.inputs[1].default_value = 4.0
    nb.l(u.outputs[0], u4.inputs[0])
    v = nb.n("ShaderNodeMath", (-600, -150), _operation='ADD')
    nb.l(sep.outputs["Y"], v.inputs[0])
    nb.l(rowi.outputs[0], v.inputs[1])
    v4 = nb.n("ShaderNodeMath", (-450, -150), _operation='DIVIDE')
    v4.inputs[1].default_value = 4.0
    nb.l(v.outputs[0], v4.inputs[0])
    cmb = nb.n("ShaderNodeCombineXYZ", (-300, -50))
    nb.l(u4.outputs[0], cmb.inputs[0])
    nb.l(v4.outputs[0], cmb.inputs[1])
    tex = nb.n("ShaderNodeTexImage", (-100, 0))
    tex.image = bpy.data.images.load(atlas_path, check_existing=True)
    tex.extension = 'CLIP'
    nb.l(cmb.outputs[0], tex.inputs[0])
    em = nb.n("ShaderNodeEmission", (200, 0))
    em.inputs["Strength"].default_value = 2.5
    nb.l(tex.outputs["Color"], em.inputs["Color"])
    out = nb.n("ShaderNodeOutputMaterial", (400, 0))
    nb.l(em.outputs[0], out.inputs[0])
    return m


def build_crowd_gn(name, track_ob, station_col, armL, armR, head, screen, lanes, per_lane, spacing,
                   lane_spacing, exclude_hero=True, seed=3):
    """GN tree: stations along the belts, all driven by BeltDistance/TypingPhase."""
    g = G(name)
    i_track = g.socket("Track", 'NodeSocketObject')
    i_belt = g.socket("Belt Distance", 'NodeSocketFloat', 0.0)
    i_phase = g.socket("Typing Phase", 'NodeSocketFloat', 0.0)
    i_lanes = g.socket("Lanes", 'NodeSocketInt', lanes)
    i_per = g.socket("Per Lane", 'NodeSocketInt', per_lane)
    i_sp = g.socket("Spacing", 'NodeSocketFloat', spacing)
    i_lsp = g.socket("Lane Spacing", 'NodeSocketFloat', lane_spacing)
    i_hl = g.socket("Hero Lane", 'NodeSocketInt', TR.HERO_LANE if exclude_hero else -99)
    i_hj = g.socket("Hero Index", 'NodeSocketInt', int(round(TR.HERO_S0 / spacing)))
    i_z = g.socket("Height", 'NodeSocketFloat', STATION_Z)
    i_amp = g.socket("Arm Amplitude", 'NodeSocketFloat', 0.09)

    oi = g.n('GeometryNodeObjectInfo')
    oi.transform_space = 'RELATIVE'
    g.l(i_track, oi.inputs["Object"])
    clen = g.n('GeometryNodeCurveLength')
    g.l(oi.outputs["Geometry"], clen.inputs["Curve"])

    count = g.math('MULTIPLY', i_lanes, i_per)
    pts = g.n('GeometryNodePoints')
    g.l(count, pts.inputs["Count"])
    idx = g.n('GeometryNodeInputIndex').outputs[0]
    lane = g.math('FLOOR', g.math('DIVIDE', idx, i_per))
    j = g.math('FLOORED_MODULO', idx, i_per)
    # arc length: station slot + belt travel + a per-lane stagger
    stagger = g.math('MULTIPLY', lane, spacing * 0.37)
    s_raw = g.math('ADD', g.math('ADD', g.math('MULTIPLY', j, i_sp), i_belt), stagger)
    s = g.math('FLOORED_MODULO', s_raw, clen.outputs["Length"])
    smp = g.n('GeometryNodeSampleCurve')
    smp.mode = 'LENGTH'
    smp.use_all_curves = True
    g.l(oi.outputs["Geometry"], smp.inputs["Curves"])
    g.l(s, smp.inputs["Length"])
    tan = smp.outputs["Tangent"]
    side = g.vmath('NORMALIZE', g.vmath('CROSS_PRODUCT', tan, (0.0, 0.0, 1.0)))
    off = g.math('MULTIPLY', g.math('SUBTRACT', lane, g.math('MULTIPLY', g.math('SUBTRACT', i_lanes, 1), 0.5)), i_lsp)
    pos = g.vmath('ADD', smp.outputs["Position"], g.vmath('SCALE', side, scale=off))
    comb = g.n('ShaderNodeCombineXYZ')
    g.l(i_z, comb.inputs["Z"])
    pos = g.vmath('ADD', pos, comb.outputs[0])
    setp = g.n('GeometryNodeSetPosition')
    g.l(pts.outputs[0], setp.inputs["Geometry"])
    g.l(pos, setp.inputs["Position"])
    # delete the hero's slot (+ the neighbours his falling walls will cover)
    is_lane = g.n('FunctionNodeCompare', _data_type='INT', _operation='EQUAL')
    g.l(lane, is_lane.inputs[0])
    g.l(i_hl, is_lane.inputs[1])
    # arc-length distance (incl. stagger) from the hero's slot at belt distance 0
    ds = g.math('ABSOLUTE', g.math('SUBTRACT', g.math('ADD', g.math('MULTIPLY', j, i_sp), stagger), TR.HERO_S0))
    near = g.math('LESS_THAN', ds, 6.5)
    kill = g.math('MULTIPLY', is_lane.outputs[0], near)
    dele = g.n('GeometryNodeDeleteGeometry')
    dele.domain = 'POINT'
    g.l(setp.outputs[0], dele.inputs["Geometry"])
    g.l(kill, dele.inputs["Selection"])
    # rotation: local +Y follows the belt tangent
    align = g.n('FunctionNodeAlignRotationToVector')
    align.axis = 'Y'
    align.pivot_axis = 'Z'
    g.l(tan, align.inputs["Vector"])
    rnd = g.n('FunctionNodeRandomValue', _data_type='FLOAT')
    rnd.inputs["Seed"].default_value = seed
    g.l(idx, rnd.inputs["ID"])
    rval = rnd.outputs[0]
    # stash per-point values before instancing
    st_r = g.n('GeometryNodeStoreNamedAttribute', _data_type='FLOAT', _domain='POINT')
    st_r.inputs["Name"].default_value = "rnd"
    g.l(dele.outputs[0], st_r.inputs["Geometry"])
    g.l(rval, st_r.inputs["Value"])
    rot_attr = g.n('GeometryNodeStoreNamedAttribute', _data_type='QUATERNION', _domain='POINT')
    rot_attr.inputs["Name"].default_value = "rot"
    g.l(st_r.outputs[0], rot_attr.inputs["Geometry"])
    g.l(align.outputs[0], rot_attr.inputs["Value"])
    points = rot_attr.outputs[0]

    def named(name, dtype):
        na = g.n('GeometryNodeInputNamedAttribute', _data_type=dtype)
        na.inputs["Name"].default_value = name
        return na.outputs[0]

    def instance(obj_or_col, is_col=False):
        if is_col:
            info = g.n('GeometryNodeCollectionInfo')
            info.transform_space = 'ORIGINAL'
            info.inputs["Collection"].default_value = obj_or_col
            info.inputs["Separate Children"].default_value = False
            geo = info.outputs[0]
        else:
            info = g.n('GeometryNodeObjectInfo')
            info.transform_space = 'ORIGINAL'
            info.inputs["Object"].default_value = obj_or_col
            info.inputs["As Instance"].default_value = True
            geo = info.outputs["Geometry"]
        iop = g.n('GeometryNodeInstanceOnPoints')
        g.l(points, iop.inputs["Points"])
        g.l(geo, iop.inputs["Instance"])
        g.l(named("rot", 'QUATERNION'), iop.inputs["Rotation"])
        return iop.outputs[0]

    two_pi = 2 * math.pi
    r = named("rnd", 'FLOAT')
    # static desk set + body
    desk_i = instance(station_col, True)
    # arms: tap around the shoulder (local X), L and R half a cycle apart
    arms = []
    for ob, ph, pivot in ((armL, 0.0, (-0.19, 0.06, 1.04)), (armR, 0.5, (0.19, 0.06, 1.04))):
        inst = instance(ob)
        ang = g.math('MULTIPLY', g.math('SINE', g.math('MULTIPLY', g.math('ADD', g.math('ADD', i_phase, ph), r), two_pi)), i_amp)
        eul = g.n('ShaderNodeCombineXYZ')
        g.l(ang, eul.inputs["X"])
        e2r = g.n('FunctionNodeEulerToRotation')
        g.l(eul.outputs[0], e2r.inputs["Euler"])
        rot = g.n('GeometryNodeRotateInstances')
        g.l(inst, rot.inputs["Instances"])
        g.l(e2r.outputs[0], rot.inputs["Rotation"])
        rot.inputs["Pivot Point"].default_value = pivot
        rot.inputs["Local Space"].default_value = True
        arms.append(rot.outputs[0])
    # head: slow nod + jitter
    hinst = instance(head)
    nod = g.math('MULTIPLY', g.math('SINE', g.math('MULTIPLY', g.math('ADD', g.math('MULTIPLY', i_phase, 0.25), r), two_pi)), 0.06)
    eul = g.n('ShaderNodeCombineXYZ')
    g.l(nod, eul.inputs["X"])
    e2r = g.n('FunctionNodeEulerToRotation')
    g.l(eul.outputs[0], e2r.inputs["Euler"])
    hrot = g.n('GeometryNodeRotateInstances')
    g.l(hinst, hrot.inputs["Instances"])
    g.l(e2r.outputs[0], hrot.inputs["Rotation"])
    hrot.inputs["Pivot Point"].default_value = (0, 0.05, 1.10)
    hrot.inputs["Local Space"].default_value = True
    # screens: per-instance tile index for the announcement atlas
    sinst = instance(screen)
    tile = g.math('FLOOR', g.math('MULTIPLY', r, 15.999))
    st = g.n('GeometryNodeStoreNamedAttribute', _data_type='FLOAT', _domain='INSTANCE')
    st.inputs["Name"].default_value = "tile"
    g.l(sinst, st.inputs["Geometry"])
    g.l(tile, st.inputs["Value"])
    join = g.n('GeometryNodeJoinGeometry')
    for geo in [desk_i] + arms + [hrot.outputs[0], st.outputs[0]]:
        g.l(geo, join.inputs[0])
    g.l(join.outputs[0], g.out.inputs[0])
    return g.ng


def build_far_gn(name, far_station, glow_ob, offsets, lanes=5, per_lane=150):
    """The same loop repeated into the distance as cheap glowing stations."""
    g = G(name)
    i_track = g.socket("Track", 'NodeSocketObject')
    i_belt = g.socket("Belt Distance", 'NodeSocketFloat', 0.0)
    i_gap = g.socket("Finish Gap", 'NodeSocketFloat', 70.0)
    oi = g.n('GeometryNodeObjectInfo')
    oi.transform_space = 'RELATIVE'
    g.l(i_track, oi.inputs["Object"])
    clen = g.n('GeometryNodeCurveLength')
    g.l(oi.outputs["Geometry"], clen.inputs["Curve"])
    total = len(offsets) * lanes * per_lane
    pts = g.n('GeometryNodePoints', Count=total)
    idx = g.n('GeometryNodeInputIndex').outputs[0]
    per_loop = lanes * per_lane
    loop = g.math('FLOOR', g.math('DIVIDE', idx, per_loop))
    within = g.math('FLOORED_MODULO', idx, per_loop)
    lane = g.math('FLOOR', g.math('DIVIDE', within, per_lane))
    j = g.math('FLOORED_MODULO', within, per_lane)
    L = clen.outputs["Length"]
    spacing = g.math('DIVIDE', L, per_lane)
    # each loop runs at its own phase so the field never looks synchronised
    s_raw = g.math('ADD', g.math('ADD', g.math('MULTIPLY', j, spacing), i_belt), g.math('MULTIPLY', loop, 37.0))
    s = g.math('FLOORED_MODULO', s_raw, L)
    smp = g.n('GeometryNodeSampleCurve')
    smp.mode = 'LENGTH'
    smp.use_all_curves = True
    g.l(oi.outputs["Geometry"], smp.inputs["Curves"])
    g.l(s, smp.inputs["Length"])
    side = g.vmath('NORMALIZE', g.vmath('CROSS_PRODUCT', smp.outputs["Tangent"], (0.0, 0.0, 1.0)))
    off = g.math('MULTIPLY', g.math('SUBTRACT', lane, (lanes - 1) / 2), 11.0)
    # loop offset table via index -> sample a mesh line? use a points->offset lookup
    lut = g.n('GeometryNodeMeshLine')
    lut.mode = 'OFFSET'
    lut.inputs["Count"].default_value = len(offsets)
    # build explicit offsets: encode loop grid as (col, row) from the loop index
    cols = int(round(math.sqrt(len(offsets) + 1)))
    pos = g.vmath('ADD', smp.outputs["Position"], g.vmath('SCALE', side, scale=off))
    # grid placement: x = (loop % 5 - 2) * 300 (skip centre), y = (loop // 5 - 2) * 620
    gx = g.n('ShaderNodeMath', _operation='FLOORED_MODULO')
    g.l(loop, gx.inputs[0])
    gx.inputs[1].default_value = 5
    gy = g.math('FLOOR', g.math('DIVIDE', loop, 5))
    ox = g.math('MULTIPLY', g.math('SUBTRACT', gx.outputs[0], 2), 300.0)
    oy = g.math('MULTIPLY', g.math('SUBTRACT', gy, 2), 620.0)
    comb = g.n('ShaderNodeCombineXYZ')
    g.l(ox, comb.inputs["X"])
    g.l(oy, comb.inputs["Y"])
    comb.inputs["Z"].default_value = STATION_Z
    pos = g.vmath('ADD', pos, comb.outputs[0])
    setp = g.n('GeometryNodeSetPosition')
    g.l(pts.outputs[0], setp.inputs["Geometry"])
    g.l(pos, setp.inputs["Position"])
    # drop the centre loop (that's ours, rendered in full detail)
    centre = g.n('FunctionNodeCompare', _data_type='FLOAT', _operation='EQUAL')
    centre.inputs["Epsilon"].default_value = 0.1
    g.l(loop, centre.inputs[0])
    centre.inputs[1].default_value = 12.0
    dele = g.n('GeometryNodeDeleteGeometry')
    dele.domain = 'POINT'
    g.l(setp.outputs[0], dele.inputs["Geometry"])
    g.l(centre.outputs[0], dele.inputs["Selection"])
    align = g.n('FunctionNodeAlignRotationToVector')
    align.axis = 'Y'
    align.pivot_axis = 'Z'
    g.l(smp.outputs["Tangent"], align.inputs["Vector"])
    info = g.n('GeometryNodeObjectInfo')
    info.inputs["Object"].default_value = far_station
    info.inputs["As Instance"].default_value = True
    iop = g.n('GeometryNodeInstanceOnPoints')
    g.l(dele.outputs[0], iop.inputs["Points"])
    g.l(info.outputs["Geometry"], iop.inputs["Instance"])
    g.l(align.outputs[0], iop.inputs["Rotation"])
    # one unreachable finish glow per loop
    gp = g.n('GeometryNodePoints', Count=25)
    gidx = g.n('GeometryNodeInputIndex').outputs[0]
    gs = g.math('FLOORED_MODULO', g.math('ADD', g.math('ADD', g.math('MULTIPLY', gidx, 37.0), i_belt), g.math('ADD', i_gap, TR.HERO_S0)), L)
    gsmp = g.n('GeometryNodeSampleCurve')
    gsmp.mode = 'LENGTH'
    gsmp.use_all_curves = True
    g.l(oi.outputs["Geometry"], gsmp.inputs["Curves"])
    g.l(gs, gsmp.inputs["Length"])
    ggx = g.n('ShaderNodeMath', _operation='FLOORED_MODULO')
    g.l(gidx, ggx.inputs[0])
    ggx.inputs[1].default_value = 5
    ggy = g.math('FLOOR', g.math('DIVIDE', gidx, 5))
    gcomb = g.n('ShaderNodeCombineXYZ')
    g.l(g.math('MULTIPLY', g.math('SUBTRACT', ggx.outputs[0], 2), 300.0), gcomb.inputs["X"])
    g.l(g.math('MULTIPLY', g.math('SUBTRACT', ggy, 2), 620.0), gcomb.inputs["Y"])
    gsp = g.n('GeometryNodeSetPosition')
    g.l(gp.outputs[0], gsp.inputs["Geometry"])
    g.l(g.vmath('ADD', gsmp.outputs["Position"], gcomb.outputs[0]), gsp.inputs["Position"])
    gcentre = g.n('FunctionNodeCompare', _data_type='FLOAT', _operation='EQUAL')
    gcentre.inputs["Epsilon"].default_value = 0.1
    g.l(gidx, gcentre.inputs[0])
    gcentre.inputs[1].default_value = 12.0
    gdel = g.n('GeometryNodeDeleteGeometry')
    gdel.domain = 'POINT'
    g.l(gsp.outputs[0], gdel.inputs["Geometry"])
    g.l(gcentre.outputs[0], gdel.inputs["Selection"])
    galign = g.n('FunctionNodeAlignRotationToVector')
    galign.axis = 'Y'
    galign.pivot_axis = 'Z'
    g.l(gsmp.outputs["Tangent"], galign.inputs["Vector"])
    ginfo = g.n('GeometryNodeObjectInfo')
    ginfo.inputs["Object"].default_value = glow_ob
    ginfo.inputs["As Instance"].default_value = True
    giop = g.n('GeometryNodeInstanceOnPoints')
    g.l(gdel.outputs[0], giop.inputs["Points"])
    g.l(ginfo.outputs["Geometry"], giop.inputs["Instance"])
    g.l(galign.outputs[0], giop.inputs["Rotation"])
    join = g.n('GeometryNodeJoinGeometry')
    g.l(iop.outputs[0], join.inputs[0])
    g.l(giop.outputs[0], join.inputs[0])
    g.l(join.outputs[0], g.out.inputs[0])
    return g.ng


def _load_font():
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "fonts", "Inter.woff2")
    try:
        f = bpy.data.fonts.load(path, check_existing=True)
        return f
    except Exception:
        return None


def text_object(name, col, body, size, mat, extrude=0.0, align='CENTER', bold=True):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = 'CENTER'
    cu.extrude = extrude
    f = _load_font()
    if f:
        cu.font = f
    if bold:
        cu.offset = size * 0.012          # fake weight: thicken outlines
    ob = bpy.data.objects.new(name, cu)
    col.objects.link(ob)
    if mat:
        cu.materials.append(mat)
    return ob


def build(col_hall, col_inst, col_assets, screen_dir, crowd_ch, crowd_seated_fn, room_mats, seed=21):
    rng = random.Random(seed)
    HL = Hall()
    m_conc = M.concrete("MAT_HallFloor", (0.05, 0.05, 0.055, 1))
    m_steel = M.metal("MAT_HallSteel", (0.22, 0.23, 0.25, 1), 0.45)
    m_belt = M.belt()
    m_haz = M.hazard_stripes()
    m_warn = M.emission("MAT_WarningRed", (1.0, 0.08, 0.04, 1), 25.0)
    m_work = M.emission("MAT_WorkLight", (1.0, 0.82, 0.6, 1), 12.0)

    track = _track_curve(col_hall)
    HL.track = track
    floor = U.mesh_object("Hall_Floor", U.bm_box((6000, 6000, 0.2), (75, 0, -1.3)), col_hall, m_conc, smooth=False)
    belts = []
    for k in range(TR.LANES):
        o = (k - (TR.LANES - 1) / 2) * TR.LANE_SPACING
        belts.append(_ribbon(f"Belt_{k:02d}", col_hall, m_belt, o, 4.5, BELT_TOP, 0.12))
        for e in (-1, 1):
            belts.append(_ribbon(f"BeltRail_{k:02d}_{e}", col_hall, m_steel, o + e * 2.32, 0.12, BELT_TOP + 0.12, 0.55, step=4.0))
    HL.belts = belts
    # structural under-frame (one long dark box ribbon under all belts)
    under = _ribbon("Belt_UnderFrame", col_hall, m_steel, 0.0, TR.LANES * TR.LANE_SPACING + 1.0, BELT_TOP - 0.12, 1.0, step=4.0)
    # columns: a big grid, kept off the track
    col_mesh = U.bm_box((2.2, 2.2, 90), (0, 0, 45 - 1.2))
    col_proto = U.mesh_object("Hall_Column", col_mesh, col_assets, m_steel, smooth=False)
    beacon_proto = U.mesh_object("Hall_Beacon", U.bm_sphere(0.35, 10, 6, (0, -1.15, 9)), col_assets, m_warn)
    beacon_proto.parent = col_proto
    for gx in range(-8, 13):
        for gy in range(-14, 15):
            x, y = gx * 36.0 - 30.0, gy * 40.0 + 20.0
            # distance from the track centre-line
            if -40 < x < 190 and -265 < y < 265:
                inside = (40 < x < 110 and -170 < y < 170)
                if not inside:
                    continue
            o = bpy.data.objects.new("Hall_Column_Inst", None)
            o.instance_type = 'COLLECTION'
            col_hall.objects.link(o)
            o.location = (x, y, 0)
            o.instance_collection = _proto_collection(col_assets, "PROTO_Column", [col_proto, beacon_proto])
    # gantries over our straight, with work lights
    gantry_parts = []
    for y in range(-60, 160, 24):
        gantry_parts.append(U.bm_box((70, 1.2, 1.6), (0, y, 22.0)))
        for x in (-34, 34):
            gantry_parts.append(U.bm_box((1.2, 1.2, 23.5), (x, y, 10.5)))
    U.mesh_object("Hall_Gantries", U.bm_join(*gantry_parts), col_hall, m_steel, smooth=False)
    lamps = []
    for y in range(-60, 160, 24):
        for x in (-22, -11, 0, 11, 22):
            lamps.append(U.bm_box((2.4, 0.5, 0.15), (x, y, 21.1)))
    U.mesh_object("Hall_WorkLights", U.bm_join(*lamps), col_hall, m_work, smooth=False)

    # ---- crowd assets + GN ----------------------------------------------------
    parts = build_station_assets(col_assets, crowd_ch, crowd_seated_fn)
    desk, screen = build_desk_set(col_assets, room_mats)
    screen.data.materials.append(crowd_screen_material(f"{screen_dir}/crowd_atlas.png"))
    station_col = _proto_collection(col_assets, "PROTO_Station", [desk, parts["body"]])
    emitter = U.mesh_object("GN_Crowd", bmesh.new(), col_inst, None)
    mod = emitter.modifiers.new("Crowd", 'NODES')
    ng = build_crowd_gn("GN_CrowdStations", track, station_col, parts["armL"], parts["armR"], parts["head"], screen,
                        TR.LANES, int(TR.LENGTH // TR.STATION_SPACING), TR.STATION_SPACING, TR.LANE_SPACING)
    mod.node_group = ng
    _set_input(mod, "Track", track)
    HL.crowd_mod = mod
    HL.crowd_parts = parts

    # ---- far loops: glowing dots ------------------------------------------------
    far = U.mesh_object("Far_Station", U.bm_join(U.bm_box((1.6, 1.0, 0.8), (0, 0.4, 0.4))), col_assets,
                        M.simple("MAT_FarDesk", (0.03, 0.03, 0.035, 1), 0.6), smooth=False)
    lamp_dot = U.mesh_object("Far_Lamp", U.bm_box((0.35, 0.35, 0.35), (-0.5, 0.6, 1.2)), col_assets,
                             M.emission("MAT_FarLamp", (1.0, 0.6, 0.3, 1), 60.0), smooth=False)
    scr_dot = U.mesh_object("Far_Screen", U.bm_box((0.7, 0.1, 0.4), (0.2, 0.8, 1.2)), col_assets,
                            M.emission("MAT_FarScreen", (0.3, 0.55, 1.0, 1), 40.0), smooth=False)
    far_ob = _join_objects("Far_StationJoined", [far, lamp_dot, scr_dot], col_assets)
    for o in (far, lamp_dot, scr_dot):
        bpy.data.objects.remove(o)
    fglow = U.mesh_object("Far_FinishGlow", U.bm_box((60, 1.0, 14), (0, 0, 8)), col_assets,
                          M.emission("MAT_FarFinish", (1.0, 0.85, 0.6, 1), 30.0), smooth=False)
    far_em = U.mesh_object("GN_FarLoops", bmesh.new(), col_inst, None)
    fmod = far_em.modifiers.new("FarLoops", 'NODES')
    fmod.node_group = build_far_gn("GN_FarLoopField", far_ob, fglow, list(range(25)))
    _set_input(fmod, "Track", track)
    HL.far_mod = fmod
    # simplified belts for the far loops: dark ribbons via linked duplicates of one mesh
    far_belt = _ribbon("Far_BeltProto", col_assets, M.simple("MAT_FarBelt", (0.02, 0.02, 0.022, 1), 0.7), 0.0, 55.0, BELT_TOP, 0.1, step=6.0)
    for k in range(25):
        if k == 12:
            continue
        gx, gy = k % 5, k // 5
        o = bpy.data.objects.new("Far_Belt", far_belt.data)
        col_hall.objects.link(o)
        o.location = ((gx - 2) * 300.0, (gy - 2) * 620.0, 0)

    # ---- finish gate: CAUGHT UP ---------------------------------------------------
    gate = U.empty("FinishGate", col_hall, (0, 70, 0), size=3)
    m_gate_glow = M.emission("MAT_FinishGlow", (1.0, 0.86, 0.62, 1), 9.0)
    m_gate_frame = M.metal("MAT_GateFrame", (0.25, 0.25, 0.27, 1), 0.4)
    w = TR.LANES * TR.LANE_SPACING + 6
    frame_parts = [U.bm_box((2.0, 2.0, 14.5), (x, 0, 7.25 - 1.2)) for x in (-w / 2, w / 2)]
    frame_parts.append(U.bm_box((w + 2, 2.0, 4.0), (0, 0, 13.3)))
    U.mesh_object("FinishGate_Frame", U.bm_join(*frame_parts), col_hall, m_gate_frame, smooth=False).parent = gate
    band = U.mesh_object("FinishGate_Band", U.bm_box((w - 1.5, 0.4, 0.6), (0, -1.05, 11.05)), col_hall, m_gate_glow, smooth=False)
    band.parent = gate
    # glowing edge strips on the pylons and beam: the line itself, not a wall
    strips = [U.bm_box((0.35, 0.35, 12.0), (x, -1.05, 5.0)) for x in (-w / 2 + 1.1, w / 2 - 1.1)]
    U.mesh_object("FinishGate_Strips", U.bm_join(*strips), col_hall, m_gate_glow, smooth=False).parent = gate
    # a big sign on its own black panel above the gate, readable from far down the track
    panel = U.mesh_object("FinishGate_SignPanel", U.bm_box((40.0, 0.6, 7.0), (0, 0, 20.0)), col_hall,
                          M.simple("MAT_SignPanel", (0.01, 0.01, 0.012, 1), 0.6), smooth=False)
    panel.parent = gate
    posts = [U.bm_box((0.8, 0.8, 4.0), (x, 0, 16.5)) for x in (-15, 15)]
    U.mesh_object("FinishGate_SignPosts", U.bm_join(*posts), col_hall, m_gate_frame, smooth=False).parent = gate
    sign = text_object("FinishGate_Sign", col_hall, "CAUGHT UP", 6.2, M.emission("MAT_FinishSign", (1.0, 0.88, 0.66, 1), 3.2), extrude=0.1)
    sign.rotation_euler = (math.pi / 2, 0, 0)          # readable from the runners' side (-Y)
    sign.location = (0, -0.45, 20.0)
    sign.parent = gate
    # checkered finish strip across the belts
    chk = M.simple("MAT_Checker", (1, 1, 1, 1), 0.4)
    nt = chk.node_tree
    ct = nt.nodes.new("ShaderNodeTexChecker")
    ct.inputs["Scale"].default_value = 1.0
    ct.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1)
    ct.inputs["Color2"].default_value = (0.01, 0.01, 0.01, 1)
    tcn = nt.nodes.new("ShaderNodeTexCoord")
    mpn = nt.nodes.new("ShaderNodeMapping")
    mpn.inputs["Scale"].default_value = (0.8, 0.8, 0.8)
    nt.links.new(tcn.outputs["Object"], mpn.inputs[0])
    nt.links.new(mpn.outputs[0], ct.inputs["Vector"])
    nt.links.new(ct.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    nt.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 1.6
    nt.links.new(ct.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Emission Color"])
    strip = U.mesh_object("FinishGate_Checker", U.bm_box((w - 2, 2.5, 0.05), (0, 0, BELT_TOP + 0.03)), col_hall, chk, smooth=False)
    strip.parent = gate
    ld = bpy.data.lights.new("FinishGate_Light", 'AREA')
    ld.shape = 'RECTANGLE'
    ld.size, ld.size_y = w, 14.0
    ld.energy = 0.0
    ld.color = (1.0, 0.86, 0.65)
    gl = bpy.data.objects.new("FinishGate_Light", ld)
    col_hall.objects.link(gl)
    gl.location = (0, -2.5, 9.0)
    gl.rotation_euler = (math.pi / 2, 0, 0)    # light faces -Y (back down the track)
    gl.parent = gate
    HL.gate, HL.gate_light = gate, gl

    # ---- stadium display hanging over the track ------------------------------------------
    disp = U.empty("StadiumDisplay", col_hall, (-15.0, 24.0, 10.5), size=2)
    housing = U.mesh_object("StadiumDisplay_Housing", U.bm_box((17.0, 1.2, 6.0), (0, 0.6, 0)), col_hall, m_steel, smooth=False)
    housing.parent = disp
    from .room import _plane
    dscr = _plane("StadiumDisplay_Screen", col_hall, 16.2, 5.4,
                  M.image_emission("MAT_StadiumDisplay", f"{screen_dir}/display/display_0560.jpg", 3.0,
                                   sequence=dict(first=560, count=161), with_bsdf=False),
                  (0, -0.02, 0), (math.pi / 2, 0, 0))
    dscr.parent = disp
    for x in (-7, 7):
        cab = U.mesh_object("StadiumDisplay_Cable", U.bm_cylinder(0.06, 4.0, 6, (x, 0.6, 5.0)), col_hall, m_steel)
        cab.parent = disp
    disp.rotation_euler = (math.radians(-12), 0, math.radians(-14))
    HL.display = disp
    return HL


def _proto_collection(parent, name, objs):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        parent.children.link(c)
    for o in objs:
        if o.name not in c.objects:
            for uc in list(o.users_collection):
                uc.objects.unlink(o)
            c.objects.link(o)
    return c


def _set_input(mod, name, value):
    ng = mod.node_group
    for item in ng.interface.items_tree:
        if getattr(item, "in_out", None) == 'INPUT' and item.name == name:
            getattr(mod.properties.inputs, item.identifier).value = value   # Blender 5.x API
            return item.identifier
    raise KeyError(name)


def input_id(mod, name):
    for item in mod.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == 'INPUT' and item.name == name:
            return item.identifier
    raise KeyError(name)
