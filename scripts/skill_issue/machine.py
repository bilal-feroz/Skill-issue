"""AGENT-01: the learning machine he builds on his desk.

Nine parts lock into place on the E['machine_parts'] frames. On activation
the core glows, rings spin, cyan data pulses run through glass tubes and the
little displays wake up in sequence. Then he slams the BIG BUTTON and the
printer feeds out the roadmap. Cyan is used only here, so it stays special.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import bl_util as U
from . import materials as M


class Machine:
    pass


def _glass(name="MAT_TubeGlass"):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = M.simple(name, (0.8, 0.95, 1.0, 1), 0.03)
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Alpha"].default_value = 0.18
    p.inputs["Specular IOR Level"].default_value = 1.0
    m.surface_render_method = 'BLENDED'
    m.use_backface_culling = False
    return m


def _cyan(name, strength):
    return M.emission(name, (0.15, 0.85, 1.0, 1), strength)


def _display_material(name, seed):
    """Tiny telemetry display: scrolling bars. 'Power' value is keyed."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nb = M.NB(m.node_tree)
    nb.nodes.clear()
    tc = nb.n("ShaderNodeTexCoord", (-1000, 0))
    mp = nb.n("ShaderNodeMapping", (-800, 0))
    mp.name = "Scroll"
    nb.l(tc.outputs["UV"], mp.inputs[0])
    sep = nb.n("ShaderNodeSeparateXYZ", (-600, 0))
    nb.l(mp.outputs[0], sep.inputs[0])
    rows = nb.n("ShaderNodeMath", (-450, 100), _operation='MULTIPLY')
    rows.inputs[1].default_value = 7.0
    nb.l(sep.outputs["Y"], rows.inputs[0])
    fl = nb.n("ShaderNodeMath", (-300, 100), _operation='FLOOR')
    nb.l(rows.outputs[0], fl.inputs[0])
    wn = nb.n("ShaderNodeTexWhiteNoise", (-150, 100))
    wn.noise_dimensions = '1D'
    add = nb.n("ShaderNodeMath", (-250, 250), _operation='ADD')
    add.inputs[1].default_value = seed
    nb.l(fl.outputs[0], add.inputs[0])
    nb.l(add.outputs[0], wn.inputs["W"])
    bar = nb.n("ShaderNodeMath", (0, 0), _operation='LESS_THAN')
    nb.l(sep.outputs["X"], bar.inputs[0])
    nb.l(wn.outputs["Value"], bar.inputs[1])
    fr = nb.n("ShaderNodeMath", (-300, -100), _operation='FRACT')
    nb.l(rows.outputs[0], fr.inputs[0])
    gap = nb.n("ShaderNodeMath", (-150, -100), _operation='LESS_THAN')
    gap.inputs[1].default_value = 0.7
    nb.l(fr.outputs[0], gap.inputs[0])
    mask = nb.n("ShaderNodeMath", (150, 0), _operation='MULTIPLY')
    nb.l(bar.outputs[0], mask.inputs[0])
    nb.l(gap.outputs[0], mask.inputs[1])
    power = nb.n("ShaderNodeValue", (150, -200))
    power.name = "Power"
    power.outputs[0].default_value = 0.0
    lvl = nb.n("ShaderNodeMath", (300, 0), _operation='MULTIPLY_ADD')
    nb.l(mask.outputs[0], lvl.inputs[0])
    lvl.inputs[1].default_value = 6.0
    lvl.inputs[2].default_value = 0.4
    strength = nb.n("ShaderNodeMath", (450, 0), _operation='MULTIPLY')
    nb.l(lvl.outputs[0], strength.inputs[0])
    nb.l(power.outputs[0], strength.inputs[1])
    em = nb.n("ShaderNodeEmission", (600, 0))
    em.inputs["Color"].default_value = (0.15, 0.85, 1.0, 1)
    nb.l(strength.outputs[0], em.inputs["Strength"])
    out = nb.n("ShaderNodeOutputMaterial", (800, 0))
    nb.l(em.outputs[0], out.inputs[0])
    return m


def build(col, desk_top, origin=(-0.28, 1.53), seed=99):
    rng = random.Random(seed)
    MC = Machine()
    root = U.empty("AgentMachine", col, (origin[0], origin[1], desk_top), size=0.1)
    root.rotation_euler = (0, 0, math.radians(-12))
    MC.root = root
    m_body = M.metal("MAT_MachineBody", (0.06, 0.065, 0.07, 1), 0.35, False)
    m_panel = M.metal("MAT_MachinePanel", (0.42, 0.43, 0.45, 1), 0.3)
    m_rubber = M.simple("MAT_Rubber", (0.02, 0.02, 0.02, 1), 0.8)
    m_glass = _glass()
    m_core = _cyan("MAT_CoreGlow", 0.0)
    m_btn = M.simple("MAT_BigButton", (0.75, 0.06, 0.03, 1), 0.2, **{"Coat Weight": 1.0})
    m_haz = M.hazard_stripes()
    parts = []

    def part(name, bm, mat, final_loc=(0, 0, 0), smooth=True):
        ob = U.mesh_object(f"Agent_{name}", bm, col, mat, smooth=smooth)
        ob.parent = root
        ob.location = final_loc
        parts.append(ob)
        return ob

    # 1 base plate
    base = part("Base", U.bm_rounded_box((0.36, 0.27, 0.035), 0.012, 3, (0, 0, 0.0175)), m_body, smooth=False)
    for x in (-0.15, 0.15):
        for y in (-0.11, 0.11):
            f = U.mesh_object("Agent_Foot", U.bm_cylinder(0.012, 0.006, 12, (x, y, -0.003)), col, m_rubber)
            f.parent = base
    # 2 core: glass dome + glowing brain + rings
    core = part("CoreHousing", U.bm_join(U.bm_cylinder(0.075, 0.03, 32, (0, 0, 0.05)),
                                         U.bm_torus(0.075, 0.006, 32, 8, (0, 0, 0.21))), m_panel, (0.0, 0.03, 0))
    dome = U.mesh_object("Agent_Dome", U.bm_cylinder(0.07, 0.15, 32, (0, 0, 0.135), cap=True), col, m_glass)
    dome.parent = core
    brain = U.mesh_object("Agent_Brain", U.bm_sphere(0.042, 24, 12, (0, 0, 0)), col, m_core)
    for v in brain.data.vertices:
        n = v.co.normalized()
        v.co += n * 0.006 * math.sin(v.co.x * 160) * math.sin(v.co.z * 140)
    brain.location = (0, 0, 0.13)
    brain.parent = core
    rings = []
    for i, r in enumerate((0.058, 0.05)):
        ring = U.mesh_object(f"Agent_Ring{i}", U.bm_torus(r, 0.0025, 40, 6, (0, 0, 0)), col, m_panel)
        ring.location = (0, 0, 0.13)
        ring.rotation_euler = (math.radians(70 + 40 * i), 0, 0)
        ring.parent = core
        rings.append(ring)
    MC.brain, MC.rings, MC.core = brain, rings, core
    # 3 / 4 side modules (left: memory stack, right: 'optimiser')
    sideL = part("ModuleL", U.bm_join(*[U.bm_rounded_box((0.08, 0.10, 0.026), 0.004, 2, (0, 0, 0.05 + 0.03 * k)) for k in range(4)]),
                 m_body, (-0.13, 0.04, 0), smooth=False)
    sideR = part("ModuleR", U.bm_join(U.bm_rounded_box((0.08, 0.10, 0.12), 0.01, 2, (0, 0, 0.095)),
                                      U.bm_cylinder(0.03, 0.012, 24, (0, -0.05, 0.10))), m_body, (0.13, 0.04, 0), smooth=False)
    fan = U.mesh_object("Agent_Fan", U.bm_join(*[U.bm_box((0.05, 0.004, 0.012), (0.0, 0, 0)) for _ in range(1)],
                                               *[_blade(a) for a in range(5)]), col, m_panel)
    fan.location = (0, -0.057, 0.10)
    fan.rotation_euler = (math.pi / 2, 0, 0)
    fan.parent = sideR
    MC.fan = fan
    # 5 glass tubes from core to modules, with pulse beads
    tube_paths = [
        [Vector((-0.13, 0.04, 0.17)), Vector((-0.10, 0.06, 0.25)), Vector((-0.03, 0.05, 0.27)), Vector((0.0, 0.03, 0.22))],
        [Vector((0.13, 0.04, 0.16)), Vector((0.11, 0.07, 0.26)), Vector((0.04, 0.06, 0.28)), Vector((0.0, 0.03, 0.22))],
        [Vector((-0.13, -0.02, 0.06)), Vector((-0.07, -0.10, 0.06)), Vector((0.05, -0.10, 0.06)), Vector((0.13, -0.02, 0.06))],
    ]
    tubes_bm = []
    MC.tube_curves = []
    for k, pts in enumerate(tube_paths):
        tubes_bm.append(_tube_bm(pts, 0.009))
        MC.tube_curves.append(pts)
    tubes = part("Tubes", U.bm_join(*tubes_bm), m_glass)
    MC.beads = []
    m_bead = _cyan("MAT_DataBead", 0.0)
    for k in range(len(tube_paths)):
        for b in range(3):
            bead = U.mesh_object(f"Agent_Bead_{k}_{b}", U.bm_capsule((0, 0, -0.006), (0, 0, 0.006), 0.0045, 0.0045, 8, 2), col, m_bead)
            bead.parent = root
            bead.scale = (0, 0, 0)
            MC.beads.append((bead, k, b / 3.0))
    MC.bead_material = m_bead
    # 6 display panel with two tiny screens + a gauge
    disp = part("DisplayPanel", U.bm_rounded_box((0.17, 0.02, 0.07), 0.006, 2, (0, 0, 0.0)), m_panel, (-0.055, -0.115, 0.075), smooth=False)
    disp.rotation_euler = (math.radians(-20), 0, 0)
    MC.displays = []
    for i, x in enumerate((-0.042, 0.032)):
        mat = _display_material(f"MAT_AgentDisplay{i}", 3.7 * (i + 1))
        sc = U.mesh_object(f"Agent_Screen{i}", U.bm_box((0.062, 0.002, 0.045), (0, 0, 0)), col, mat, smooth=False)
        sc.location = (x, -0.0105, 0.0)
        sc.parent = disp
        _uv_project_xz(sc)
        MC.displays.append(mat)
    # 7 big button box (hazard-striped) + button cap
    bbox = part("ButtonBox", U.bm_rounded_box((0.09, 0.09, 0.05), 0.008, 2, (0, 0, 0.025)), m_haz, (0.125, -0.085, 0.035), smooth=False)
    btn = U.mesh_object("Agent_BigButton", U.bm_join(U.bm_cylinder(0.033, 0.018, 32, (0, 0, 0.009)),
                                                    U.bm_sphere(0.033, 32, 8, (0, 0, 0.012), (1, 1, 0.35))), col, m_btn)
    btn.location = (0, 0, 0.05)
    btn.parent = bbox
    collar = U.mesh_object("Agent_ButtonCollar", U.bm_torus(0.036, 0.005, 32, 8, (0, 0, 0.05)), col, m_panel)
    collar.parent = bbox
    MC.button = btn
    # 8 printer unit with slot and paper roll
    prn = part("Printer", U.bm_rounded_box((0.17, 0.08, 0.05), 0.008, 2, (0, 0, 0.025)), m_body, (-0.06, -0.075, 0.0), smooth=False)
    slot = U.mesh_object("Agent_PrinterSlot", U.bm_box((0.13, 0.01, 0.006), (0, -0.041, 0.03)), col, M.simple("MAT_Slot", (0, 0, 0, 1), 0.9), smooth=False)
    slot.parent = prn
    roll = U.mesh_object("Agent_PaperRoll", U.bm_cylinder(0.022, 0.12, 20, (0, 0, 0)), col, M.paper("MAT_RollPaper", (0.85, 0.83, 0.78, 1)))
    roll.rotation_euler = (0, math.pi / 2, 0)
    roll.location = (0, 0.005, 0.065)
    roll.parent = prn
    MC.printer, MC.roll = prn, roll
    # 9 antenna with a status light
    ant = part("Antenna", U.bm_join(U.bm_capsule((0, 0, 0), (0, 0, 0.13), 0.003, 0.002, 8, 2)), m_panel, (0.15, 0.10, 0.035))
    tip = U.mesh_object("Agent_AntennaTip", U.bm_sphere(0.008, 12, 8, (0, 0, 0.135)), col, _cyan("MAT_AntennaTip", 0.0))
    tip.parent = ant
    MC.antenna_tip = tip.active_material
    MC.parts = parts                     # in assembly order (matches machine_parts)
    MC.final = {p.name: (p.location.copy(), p.rotation_euler.copy()) for p in parts}
    # local cyan glow (turns on with the machine)
    ld = bpy.data.lights.new("Agent_GlowLight", 'POINT')
    ld.energy = 0.0
    ld.color = (0.2, 0.85, 1.0)
    ld.shadow_soft_size = 0.05
    glow = bpy.data.objects.new("Agent_GlowLight", ld)
    col.objects.link(glow)
    glow.parent = core
    glow.location = (0, 0, 0.14)
    MC.glow = glow
    # slot exit point in world space (for the paper scroll), computed at build
    MC.slot_local = Vector((-0.06, -0.075 - 0.045, 0.03))
    return MC


def _blade(i):
    bm = U.bm_box((0.022, 0.003, 0.009), (0.013, 0, 0))
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(2 * math.pi * i / 5, 3, 'Y'), verts=bm.verts)
    return bm


def _tube_bm(pts, r):
    # Catmull-Rom through the points, then a capsule chain
    samples = []
    P = [pts[0]] + pts + [pts[-1]]
    for i in range(1, len(P) - 2):
        for k in range(8):
            t = k / 8
            p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
            samples.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    samples.append(pts[-1])
    bms = [U.bm_capsule(a, b, r, r, 12, 1) for a, b in zip(samples, samples[1:])]
    return U.bm_join(*bms)


def tube_point(pts, t):
    P = [pts[0]] + pts + [pts[-1]]
    n = len(pts) - 1
    t = max(0.0, min(0.9999, t)) * n
    i = int(t) + 1
    u = t - int(t)
    p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u)


def _uv_project_xz(ob):
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    xs = [v.co.x for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((co.x - x0) / (x1 - x0 + 1e-9), (co.z - z0) / (z1 - z0 + 1e-9))
