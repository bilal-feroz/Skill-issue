"""The bedroom: a lived-in student room that is secretly a stage set.

Interior: x in [-2, 2], y in [-1.8, 1.8], z in [0, 2.6]; desk on the +Y wall
(the direction of travel and of the finish line), door on the +X wall.
Walls are separate "flats" hinged at their outer bottom edge so they can
fall outward in Act IV. Their backs show plywood and stage bracing.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import bl_util as U
from . import timeline as T
from . import materials as M

ROOM = dict(x0=-2.0, x1=2.0, y0=-1.8, y1=1.8, h=2.6, t=0.08)
DESK = dict(x0=-0.62, x1=1.02, y0=1.08, y1=1.80, top=0.75)
DOOR = dict(y0=-1.25, y1=-0.40, h=2.05)
WINDOW = dict(x0=-0.45, x1=0.85, z0=1.10, z1=2.05)

SCREEN_DIR = None   # set by build(): absolute path to assets/screens


class Room:
    pass


def _uv_box_face(ob, axis_idx, sign):
    """Planar UVs for faces pointing along an axis (screen surfaces)."""
    me = ob.data
    uv = me.uv_layers.new(name="UVMap") if not me.uv_layers else me.uv_layers[0]
    xs = [v.co for v in me.vertices]
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = (0, 0)
    return uv


def _plane(name, col, w, h, mat, loc=(0, 0, 0), rot=(0, 0, 0)):
    """XY plane w x h with clean 0..1 UVs, centred on origin."""
    me = bpy.data.meshes.new(name)
    verts = [(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)]
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    for li, c in zip(range(4), [(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[li].uv = c
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = rot
    col.objects.link(ob)
    if mat:
        me.materials.append(mat)
    return ob


def _wall_slab(w, h, t, holes=()):
    """Wall in local coords: x in [-w/2, w/2], y in [0, t], z in [0, h] with rectangular holes."""
    bm = bmesh.new()
    xs = sorted({-w / 2, w / 2, *[v for hx0, hx1, hz0, hz1 in holes for v in (hx0, hx1)]})
    zs = sorted({0.0, h, *[v for hx0, hx1, hz0, hz1 in holes for v in (hz0, hz1)]})
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            cx, cz = (xs[i] + xs[i + 1]) / 2, (zs[j] + zs[j + 1]) / 2
            if any(hx0 <= cx <= hx1 and hz0 <= cz <= hz1 for hx0, hx1, hz0, hz1 in holes):
                continue
            b = U.bm_box((xs[i + 1] - xs[i], t, zs[j + 1] - zs[j]), (cx, t / 2, cz))
            me = bpy.data.meshes.new("_t")
            b.to_mesh(me)
            b.free()
            bm.from_mesh(me)
            bpy.data.meshes.remove(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    return bm


def build(col_env, col_props, col_screens, screen_dir, seed=4242):
    rng = random.Random(seed)
    R = Room()
    R.objects = {}
    m_wall = M.wall_paint("MAT_WallPaint", (0.42, 0.44, 0.47, 1))
    m_ply = M.wood("MAT_Plywood", (0.45, 0.33, 0.2, 1), (0.32, 0.22, 0.12, 1), 6.0, 0.7)
    m_batten = M.wood("MAT_Batten", (0.38, 0.26, 0.14, 1), (0.25, 0.16, 0.08, 1), 4.0, 0.7)
    m_trim = M.simple("MAT_Trim", (0.65, 0.64, 0.6, 1), 0.5)
    m_floor = M.floor_planks()
    m_wood = M.wood()
    m_steel = M.metal("MAT_SteelDark", (0.15, 0.15, 0.16, 1), 0.4)
    m_black = M.simple("MAT_BlackPlastic", (0.015, 0.015, 0.017, 1), 0.35)
    m_alu = M.metal("MAT_Aluminium", (0.55, 0.56, 0.58, 1), 0.3)
    m_fabric_bed = M.fabric("MAT_Duvet", (0.10, 0.17, 0.25, 1), 160, 0.9, 0.7, 0.3)
    m_sheet = M.fabric("MAT_Sheet", (0.55, 0.55, 0.52, 1), 160, 0.9, 0.5, 0.3)
    m_rug = M.fabric("MAT_Rug", (0.10, 0.11, 0.13, 1), 80, 1.0, 0.4, 0.3)

    # ---- floor platform (also the conveyor station) -------------------------
    fl = U.mesh_object("Room_Floor", U.bm_box((4.2, 3.8, 0.04), (0, 0, -0.02)), col_env, m_floor, smooth=False)
    base = U.mesh_object("Station_Base", U.bm_box((4.3, 3.9, 0.16), (0, 0, -0.12)), col_env, m_steel, smooth=False)
    U.add_bevel(base, 0.01, 2)
    R.floor = fl

    # ---- walls (flats). origin = hinge at the outer bottom edge -------------
    h, t = ROOM["h"], ROOM["t"]
    R.walls = {}

    def flat(name, w, holes, origin, rot_z, fall_axis, fall_sign):
        bm = _wall_slab(w, h, t, holes)
        ob = U.mesh_object(name, bm, col_env, [m_wall, m_ply], smooth=False)
        # outward-facing faces (local +y side) get the plywood back material
        for p in ob.data.polygons:
            if p.normal.y > 0.5:
                p.material_index = 1
        # stage bracing on the back: two diagonal battens + a horizontal rail
        braces = []
        for a, b in (((-w / 2 + 0.2, t, 0.1), (-0.1, t, h - 0.3)), ((w / 2 - 0.2, t, 0.1), (0.1, t, h - 0.3))):
            braces.append(U.bm_capsule(Vector(a) + Vector((0, 0.03, 0)), Vector(b) + Vector((0, 0.03, 0)), 0.025, 0.025, 6, 1))
        braces.append(U.bm_box((w - 0.2, 0.05, 0.08), (0, t + 0.03, h * 0.55)))
        br = U.mesh_object(name + "_Bracing", U.bm_join(*braces), col_env, m_batten, smooth=False)
        br.parent = ob
        ob.location = origin
        ob.rotation_euler = (0, 0, rot_z)
        R.walls[name] = dict(ob=ob, axis=fall_axis, sign=fall_sign)
        return ob

    W, D_ = ROOM["x1"] - ROOM["x0"] + 2 * t, ROOM["y1"] - ROOM["y0"]
    wx0, wx1 = WINDOW["x0"], WINDOW["x1"]
    # front wall (+Y) with the window. local x = world x, local +y = world +y
    wf = flat("Wall_Front", W, [(wx0, wx1, WINDOW["z0"], WINDOW["z1"])], (0, ROOM["y1"], 0), 0.0, 'X', -1)
    # back wall (-Y), rotated 180 so local +y points to -Y
    wb = flat("Wall_Back", W, [], (0, ROOM["y0"], 0), math.pi, 'X', -1)
    # left wall (-X): local +y -> -X  (rot +90)
    wl = flat("Wall_Left", D_, [], (ROOM["x0"], 0, 0), math.pi / 2, 'X', -1)
    # right wall (+X) with the door: local +y -> +X (rot -90); local x -> -world y
    dy0, dy1 = DOOR["y0"], DOOR["y1"]
    wr = flat("Wall_Right", D_, [(-dy1, -dy0, 0.0, DOOR["h"])], (ROOM["x1"], 0, 0), -math.pi / 2, 'X', -1)
    # skirting boards
    for name, size, c in (("Skirt_Front", (4.0, 0.015, 0.09), (0, 1.79, 0.045)),
                          ("Skirt_Back", (4.0, 0.015, 0.09), (0, -1.79, 0.045)),
                          ("Skirt_Left", (0.015, 3.6, 0.09), (-1.99, 0, 0.045))):
        sk = U.mesh_object(name, U.bm_box(size, c), col_env, m_trim, smooth=False)
    # ceiling flat (flies up in Act IV)
    ceil = U.mesh_object("Ceiling", U.bm_box((4.3, 3.9, 0.06), (0, 0, 0.03)), col_env, M.wall_paint("MAT_Ceiling", (0.5, 0.5, 0.5, 1)), smooth=False)
    ceil.location = (0, 0, h)
    R.ceiling = ceil

    # ---- window: frame, mullion, sill, roller blind, fake city light-box ----
    win_col = col_env
    ww, wh = wx1 - wx0, WINDOW["z1"] - WINDOW["z0"]
    wcx, wcz = (wx0 + wx1) / 2, (WINDOW["z0"] + WINDOW["z1"]) / 2
    frame_parts = [U.bm_box((ww + 0.08, 0.06, 0.05), (wcx, 0.03, WINDOW["z0"] - 0.025)),
                   U.bm_box((ww + 0.08, 0.06, 0.05), (wcx, 0.03, WINDOW["z1"] + 0.025)),
                   U.bm_box((0.05, 0.06, wh), (wx0 - 0.025, 0.03, wcz)),
                   U.bm_box((0.05, 0.06, wh), (wx1 + 0.025, 0.03, wcz)),
                   U.bm_box((0.035, 0.04, wh), (wcx, 0.04, wcz)),
                   U.bm_box((ww, 0.035, 0.035), (wcx, 0.04, wcz + 0.1)),
                   U.bm_box((ww + 0.2, 0.16, 0.035), (wcx, -0.05, WINDOW["z0"] - 0.06))]
    wframe = U.mesh_object("Window_Frame", U.bm_join(*frame_parts), win_col, m_trim, smooth=False)
    wframe.parent = wf
    wframe.location = (0, 0, 0)
    city = _plane("Window_CityLightbox", win_col, ww + 0.1, wh + 0.1, M.city_window(),
                  (wcx, 0.35, wcz), (math.pi / 2, 0, 0))
    city.parent = wf
    R.city = city
    blind = U.mesh_object("Window_Blind", U.bm_box((ww - 0.02, 0.012, 0.32), (wcx, 0.02, WINDOW["z1"] - 0.16)), win_col,
                          M.fabric("MAT_Blind", (0.5, 0.45, 0.36, 1), 100, 0.8, 0.2, 0.2), smooth=False)
    blind.parent = wf
    roll = U.mesh_object("Window_BlindRoll", U.bm_cylinder(0.03, ww + 0.04, 16, (0, 0, 0)), win_col, m_trim)
    roll.rotation_euler = (0, math.pi / 2, 0)
    roll.location = (wcx, 0.0, WINDOW["z1"] + 0.0)
    roll.parent = wf

    # ---- door on the right wall (part of the flat) -------------------------
    dcy = (dy0 + dy1) / 2
    door = U.mesh_object("Door", U.bm_rounded_box((dy1 - dy0 - 0.02, 0.045, DOOR["h"] - 0.03), 0.004, 1, (0, 0, 0)),
                         col_env, M.simple("MAT_DoorPaint", (0.55, 0.53, 0.48, 1), 0.45), smooth=False)
    # door panels (raised)
    door.location = (-dcy, t / 2, DOOR["h"] / 2 + 0.01)
    door.parent = wr
    for pz in (0.55, 1.45):
        pnl = U.mesh_object("Door_Panel", U.bm_box((0.6, 0.012, 0.62), (0, -0.026, pz - DOOR["h"] / 2)), col_env,
                            M.simple("MAT_DoorPaint", (0.55, 0.53, 0.48, 1), 0.45), smooth=False)
        pnl.parent = door
    knob_parts = [U.bm_cylinder(0.025, 0.012, 16, (0, 0, 0)),
                  U.bm_capsule((0, 0, 0.0), (-0.1, 0, 0.0), 0.011, 0.011, 8, 2)]
    handle = U.mesh_object("Door_Handle", U.bm_join(*knob_parts), col_env, m_alu)
    handle.rotation_euler = (math.pi / 2, 0, 0)
    handle.location = (dcy + 0.33, -0.04, 1.0 - DOOR["h"] / 2)  # local to door
    handle.parent = door
    handle.location = (0.33, -0.045, 1.0 - DOOR["h"] / 2 - 0.01)
    R.door, R.door_handle = door, handle
    trim = [U.bm_box((0.07, 0.03, DOOR["h"] + 0.05), (-dy1 - 0.035, -0.012, DOOR["h"] / 2)),
            U.bm_box((0.07, 0.03, DOOR["h"] + 0.05), (-dy0 + 0.035, -0.012, DOOR["h"] / 2)),
            U.bm_box((dy1 - dy0 + 0.14, 0.03, 0.07), (-dcy, -0.012, DOOR["h"] + 0.035))]
    dtrim = U.mesh_object("Door_Trim", U.bm_join(*trim), col_env, m_trim, smooth=False)
    dtrim.parent = wr

    # ---- desk ---------------------------------------------------------------
    d = DESK
    dw, dd = d["x1"] - d["x0"], d["y1"] - d["y0"]
    dcx, dcy_ = (d["x0"] + d["x1"]) / 2, (d["y0"] + d["y1"]) / 2
    desk_parts = [U.bm_rounded_box((dw, dd, 0.035), 0.008, 2, (dcx, dcy_, d["top"] - 0.0175))]
    desk = U.mesh_object("Desk_Top", desk_parts[0], col_props, M.wood("MAT_DeskWood", (0.42, 0.25, 0.12, 1), (0.25, 0.13, 0.06, 1), 2.5, 0.38))
    legs = []
    for lx in (d["x0"] + 0.04, d["x1"] - 0.04):
        for ly in (d["y0"] + 0.05, d["y1"] - 0.05):
            legs.append(U.bm_box((0.035, 0.035, d["top"] - 0.035), (lx, ly, (d["top"] - 0.035) / 2)))
    legs.append(U.bm_box((dw - 0.1, 0.02, 0.06), (dcx, d["y1"] - 0.05, 0.62)))
    U.mesh_object("Desk_Legs", U.bm_join(*legs), col_props, m_steel, smooth=False)
    drawer = U.mesh_object("Desk_Drawers", U.bm_rounded_box((0.40, 0.6, 0.55), 0.01, 2, (d["x0"] + 0.25, dcy_ + 0.02, 0.30)),
                           col_props, M.simple("MAT_DrawerWhite", (0.6, 0.6, 0.58, 1), 0.4), smooth=False)
    R.desk = desk
    top = d["top"]

    # ---- laptop (lid hinged at the back edge) ---------------------------------
    lap_c = Vector((0.02, 1.30, top))
    lap = U.empty("Laptop", col_props, lap_c, size=0.1)
    lap.rotation_euler = (0, 0, math.radians(3))
    lb = U.mesh_object("Laptop_Base", U.bm_rounded_box((0.34, 0.235, 0.016), 0.006, 2, (0, 0, 0.008)), col_props, m_alu)
    lb.parent = lap
    kb = _plane("Laptop_Keyboard", col_props, 0.29, 0.11, _keyboard_material(screen_dir), (0, 0.03, 0.0165))
    kb.parent = lap
    tp = _plane("Laptop_Trackpad", col_props, 0.10, 0.06, M.simple("MAT_Trackpad", (0.35, 0.36, 0.38, 1), 0.25), (0, -0.07, 0.0163))
    tp.parent = lap
    hinge = U.empty("Laptop_Hinge", col_props, (0, 0.115, 0.016), size=0.05)
    hinge.parent = lap
    lid = U.mesh_object("Laptop_Lid", U.bm_rounded_box((0.34, 0.010, 0.225), 0.005, 2, (0, 0.005, 0.1125)), col_props, m_alu)
    lid.parent = hinge
    lscr = _plane("Laptop_Screen", col_screens, 0.315, 0.197,
                  M.image_emission("MAT_LaptopScreen", f"{screen_dir}/laptop/laptop_0001.jpg", 1.0,
                                   sequence=dict(first=1, count=720)),
                  (0, -0.0006, 0.115), (math.pi / 2, 0, 0))
    lscr.parent = hinge
    bezel = _plane("Laptop_Bezel", col_props, 0.33, 0.215, m_black, (0, -0.0004, 0.1125), (math.pi / 2, 0, 0))
    bezel.parent = hinge
    hinge.rotation_euler = (math.radians(-18), 0, 0)    # open, tilted back
    R.laptop, R.laptop_hinge, R.laptop_screen = lap, hinge, lscr

    # ---- monitor ------------------------------------------------------------
    mon = U.empty("Monitor", col_props, (0.55, 1.62, top), size=0.1)
    mon.rotation_euler = (0, 0, math.radians(22))
    st = [U.bm_rounded_box((0.24, 0.17, 0.012), 0.01, 2, (0, 0, 0.006)),
          U.bm_box((0.04, 0.025, 0.30), (0, 0.04, 0.16))]
    U.mesh_object("Monitor_Stand", U.bm_join(*st), col_props, m_black).parent = mon
    panel = U.mesh_object("Monitor_Panel", U.bm_rounded_box((0.64, 0.035, 0.38), 0.008, 2, (0, 0.012, 0.40)), col_props, m_black)
    panel.parent = mon
    mscr = _plane("Monitor_Screen", col_screens, 0.615, 0.346,
                  M.image_emission("MAT_MonitorScreen", f"{screen_dir}/monitor/monitor_0001.jpg", 1.0,
                                   sequence=dict(first=1, count=720)),
                  (0, -0.0062, 0.405), (math.pi / 2, 0, 0))
    mscr.parent = mon
    R.monitor, R.monitor_screen = mon, mscr
    # sticky notes on the bezel: the only 'technical notes' still in his handwriting
    notes_col = [(0.85, 0.75, 0.2, 1), (0.9, 0.45, 0.55, 1), (0.4, 0.8, 0.6, 1)]
    for i, (nx, nz, rz) in enumerate(((-0.30, 0.58, 0.12), (0.28, 0.23, -0.2), (0.31, 0.56, 0.05))):
        n = U.mesh_object(f"StickyNote_{i}", U.bm_box((0.065, 0.002, 0.065), (0, 0, 0)), col_props,
                          M.simple(f"MAT_Sticky{i}", notes_col[i], 0.7), smooth=False)
        n.location = (nx, -0.008, nz)
        n.rotation_euler = (0, rz, 0)
        n.parent = mon

    # ---- desk lamp (the warm key light) -----------------------------------------
    lamp = U.empty("DeskLamp", col_props, (0.95, 1.70, top), size=0.1)
    lamp.rotation_euler = (0, 0, math.radians(-58))
    lp = [U.bm_cylinder(0.075, 0.02, 24, (0, 0, 0.01)),
          U.bm_capsule((0, 0, 0.02), (0, -0.05, 0.36), 0.009, 0.009, 8, 2),
          U.bm_capsule((0, -0.05, 0.36), (0, -0.28, 0.42), 0.009, 0.009, 8, 2),
          U.bm_sphere(0.018, 12, 8, (0, -0.05, 0.36))]
    U.mesh_object("DeskLamp_Arm", U.bm_join(*lp), col_props, M.metal("MAT_LampMetal", (0.08, 0.2, 0.18, 1), 0.35, False)).parent = lamp
    shade = U.bm_cylinder(0.075, 0.12, 28, (0, 0, 0), cap=False, radius2=0.028)
    sh = U.mesh_object("DeskLamp_Shade", shade, col_props, [M.metal("MAT_LampMetal", (0.08, 0.2, 0.18, 1), 0.35, False)])
    sol = sh.modifiers.new("Solidify", 'SOLIDIFY')
    sol.thickness = 0.003
    sh.location = (0, -0.30, 0.40)
    sh.rotation_euler = (math.radians(-30), 0, 0)
    sh.parent = lamp
    bulb = U.mesh_object("DeskLamp_Bulb", U.bm_sphere(0.026, 16, 10), col_props, M.emission("MAT_BulbWarm", (1.0, 0.72, 0.42, 1), 40.0))
    bulb.location = (0, -0.305, 0.37)
    bulb.parent = lamp
    R.lamp, R.lamp_bulb = lamp, bulb

    # ---- notebook, pen, mug, clock ---------------------------------------
    nbk = U.empty("Notebook", col_props, (0.42, 1.21, top), size=0.1)
    nbk.rotation_euler = (0, 0, math.radians(-10))
    cover = U.mesh_object("Notebook_Cover", U.bm_box((0.43, 0.30, 0.006), (0, 0, 0.003)), col_props,
                          M.simple("MAT_NotebookCover", (0.06, 0.08, 0.12, 1), 0.6), smooth=False)
    cover.parent = nbk
    lpage = _plane("Notebook_PageLeft", col_props, 0.205, 0.285, M.paper("MAT_PaperRuled"), (-0.105, 0, 0.0075))
    lpage.parent = nbk
    rpage = _plane("Notebook_PageRight", col_screens, 0.205, 0.285,
                   M.image_emission("MAT_NotebookPage", f"{screen_dir}/notebook/notebook_0001.png", 0.0,
                                    sequence=dict(first=1, count=T.E["scrib_end"]), with_bsdf=False),
                   (0.105, 0, 0.0075))
    rpage.parent = nbk
    _make_page_diffuse(rpage.active_material)
    spiral = []
    for i in range(14):
        spiral.append(U.bm_torus(0.008, 0.0012, 12, 6, (0, 0, 0)))
        bmesh.ops.rotate(spiral[-1], cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'Y'), verts=spiral[-1].verts)
        bmesh.ops.translate(spiral[-1], vec=(0, -0.13 + i * 0.02, 0.008), verts=spiral[-1].verts)
    sp = U.mesh_object("Notebook_Spiral", U.bm_join(*spiral), col_props, m_alu)
    sp.parent = nbk
    R.notebook, R.notebook_page = nbk, rpage
    pen = U.mesh_object("Pen", U.bm_join(U.bm_capsule((0, 0, 0), (0, 0, 0.14), 0.0045, 0.0045, 10, 2),
                                         U.bm_cylinder(0.0025, 0.012, 8, (0, 0, -0.006), radius2=0.0005)),
                        col_props, M.simple("MAT_PenBlue", (0.03, 0.08, 0.35, 1), 0.3))
    R.pen = pen
    mug = _mug("Mug_Hero", col_props, M.simple("MAT_MugHero", (0.72, 0.69, 0.62, 1), 0.22))
    mug.location = (-0.26, 1.16, top)
    mug.rotation_euler = (0, 0, math.pi)          # handle toward his left hand
    R.mug = mug
    R.mug_proto = mug
    clock = U.empty("DigitalClock", col_props, (-0.53, 1.13, top), size=0.05)
    clock.rotation_euler = (0, 0, math.radians(25))
    cb = U.mesh_object("Clock_Body", U.bm_rounded_box((0.16, 0.06, 0.07), 0.012, 3, (0, 0, 0.035)), col_props, m_black)
    cb.rotation_euler = (math.radians(-12), 0, 0)
    cb.parent = clock
    cdisp = _plane("Clock_Display", col_screens, 0.13, 0.05,
                   M.image_emission("MAT_ClockDisplay", f"{screen_dir}/clock/clock_0001.png", 2.0,
                                    sequence=dict(first=1, count=720), with_bsdf=False),
                   (0, -0.031, 0.036), (math.pi / 2 - math.radians(12), 0, 0))
    cdisp.parent = clock
    R.clock = clock

    # ---- chair (office chair on casters) ------------------------------------------
    chair = U.empty("Chair", col_props, (0.05, 0.86, 0), size=0.2)
    m_chair = M.fabric("MAT_ChairFabric", (0.05, 0.05, 0.055, 1), 200, 0.9, 0.3, 0.2)
    seat = U.mesh_object("Chair_Seat", U.bm_rounded_box((0.48, 0.46, 0.08), 0.035, 3, (0, 0, 0.47)), col_props, m_chair)
    seat.parent = chair
    # the student faces +Y, so the backrest sits on the chair's -Y side
    back = U.mesh_object("Chair_Back", U.bm_rounded_box((0.44, 0.07, 0.55), 0.04, 3, (0, -0.24, 0.85)), col_props, m_chair)
    back.rotation_euler = (math.radians(8), 0, 0)
    back.parent = chair
    post = [U.bm_cylinder(0.025, 0.36, 16, (0, 0, 0.25)), U.bm_box((0.04, 0.03, 0.4), (0, -0.22, 0.6))]
    for k in range(5):
        a = 2 * math.pi * k / 5
        post.append(U.bm_capsule((0, 0, 0.08), (math.cos(a) * 0.30, math.sin(a) * 0.30, 0.06), 0.018, 0.015, 8, 1))
        post.append(U.bm_sphere(0.028, 10, 6, (math.cos(a) * 0.30, math.sin(a) * 0.30, 0.028)))
    U.mesh_object("Chair_Base", U.bm_join(*post), col_props, m_steel).parent = chair
    R.chair = chair

    # ---- bed along the left wall ---------------------------------------------------
    bedf = U.mesh_object("Bed_Frame", U.bm_box((0.95, 2.0, 0.30), (-1.50, -0.65, 0.15)), col_props, m_wood, smooth=False)
    U.add_bevel(bedf, 0.015, 2)
    U.mesh_object("Bed_Mattress", U.bm_rounded_box((0.9, 1.95, 0.18), 0.05, 3, (-1.50, -0.65, 0.39)), col_props, m_sheet)
    duvet = U.bm_rounded_box((0.98, 1.35, 0.12), 0.05, 2, (-1.48, -0.95, 0.52))
    bmesh.ops.subdivide_edges(duvet, edges=duvet.edges, cuts=6, use_grid_fill=True)
    for v in duvet.verts:
        v.co.z += 0.045 * U.fbm(v.co.x * 4 + v.co.y * 3, 2) + 0.03 * math.sin(v.co.y * 9 + v.co.x * 3)
        if v.co.z < 0.5:
            v.co.x += 0.03 * U.noise1(v.co.y * 6, 9)
    dv = U.mesh_object("Bed_Duvet", duvet, col_props, m_fabric_bed)
    U.add_subsurf(dv, 1, 2)
    pil = U.mesh_object("Bed_Pillow", U.bm_rounded_box((0.62, 0.36, 0.13), 0.06, 3, (-1.52, 0.12, 0.53)), col_props, m_sheet)
    pil.rotation_euler = (0, 0, math.radians(6))
    U.add_subsurf(pil, 1, 2)

    # ---- bookshelf on the right wall, by the desk -------------------------------
    shelf = U.empty("Bookshelf", col_props, (1.80, 0.90, 0), size=0.2)
    shelf.rotation_euler = (0, 0, math.pi / 2)
    sparts = [U.bm_box((0.8, 0.3, 0.025), (0, 0, z)) for z in (0.02, 0.45, 0.88, 1.31, 1.74)]
    sparts += [U.bm_box((0.025, 0.3, 1.75), (x, 0, 0.875)) for x in (-0.4, 0.4)]
    U.mesh_object("Bookshelf_Frame", U.bm_join(*sparts), col_props, m_wood, smooth=False).parent = shelf
    R.book_material = M.random_color_material("MAT_Books", [
        (0.35, 0.05, 0.04, 1), (0.05, 0.12, 0.25, 1), (0.6, 0.45, 0.1, 1), (0.08, 0.2, 0.12, 1),
        (0.55, 0.55, 0.5, 1), (0.15, 0.15, 0.17, 1), (0.45, 0.2, 0.05, 1), (0.2, 0.08, 0.25, 1)], 0.6)
    for zi, z in enumerate((0.0325, 0.4625, 0.8925, 1.3225)):
        x = -0.37
        while x < 0.33:
            bw = rng.uniform(0.025, 0.05)
            bh = rng.uniform(0.2, 0.33)
            tilt = 0.0 if rng.random() > 0.15 else rng.uniform(0.1, 0.3)
            b = U.mesh_object("Shelf_Book", U.bm_rounded_box((bw, rng.uniform(0.18, 0.24), bh), 0.003, 1, (0, 0, bh / 2)), col_props, R.book_material, smooth=False)
            b.location = (x + bw / 2, 0.0, z)
            b.rotation_euler = (0, tilt, 0)
            b.parent = shelf
            x += bw + (0.05 if tilt else 0.002)
            if rng.random() < 0.06:
                x += 0.12
    # dead plant (it was thriving in September)
    pot = U.mesh_object("Plant_Pot", U.bm_cylinder(0.06, 0.1, 16, (0, 0, 0.05), radius2=0.075), col_props, M.simple("MAT_Terracotta", (0.45, 0.17, 0.08, 1), 0.8))
    pot.location = (0.25, 0.0, 1.7525)
    pot.parent = shelf
    stems = [U.bm_capsule((0, 0, 0.1), (math.cos(a) * 0.09, math.sin(a) * 0.09, 0.02 + 0.06 * (k % 2)), 0.004, 0.003, 6, 1)
             for k, a in enumerate([i * 1.3 for i in range(6)])]
    pl = U.mesh_object("Plant_Wilted", U.bm_join(*stems), col_props, M.simple("MAT_DeadLeaf", (0.18, 0.13, 0.04, 1), 0.8))
    pl.location = (0.25, 0.0, 1.85)
    pl.parent = shelf

    # ---- rug, backpack, pizza box, bin, cables, string lights, posters -------------
    # (no rug: it read as a dark blob in the wide paper-follow shot)
    bp = U.mesh_object("Backpack", U.bm_rounded_box((0.32, 0.2, 0.42), 0.08, 3, (0, 0, 0.21)), col_props,
                       M.fabric("MAT_Backpack", (0.04, 0.06, 0.05, 1), 120, 0.9, 0.5, 0.3))
    bp.location = (-0.95, 1.35, 0)
    bp.rotation_euler = (math.radians(-12), 0, math.radians(30))
    U.add_subsurf(bp, 1, 2)
    pz = U.mesh_object("PizzaBox", U.bm_box((0.36, 0.36, 0.045), (0, 0, 0.0225)), col_props,
                       M.simple("MAT_Cardboard", (0.45, 0.32, 0.18, 1), 0.85), smooth=False)
    pz.location = (-0.95, -1.35, 0)
    pz.rotation_euler = (0, 0, math.radians(17))
    pz2 = pz.copy()
    col_props.objects.link(pz2)
    pz2.location = (-0.93, -1.33, 0.045)
    pz2.rotation_euler = (0, 0, math.radians(-8))
    binb = U.mesh_object("Bin", U.bm_cylinder(0.14, 0.32, 24, (0, 0, 0.16), cap=False, radius2=0.12), col_props, m_steel)
    sol = binb.modifiers.new("Solidify", 'SOLIDIFY')
    sol.thickness = 0.004
    binb.location = (1.25, 1.35, 0)
    crumples = [U.bm_sphere(0.05, 8, 6, (rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), 0.04)) for _ in range(5)]
    for c_ in crumples:
        for v in c_.verts:
            v.co += Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * 0.012
    cr = U.mesh_object("CrumpledPapers", U.bm_join(*crumples), col_props, M.paper(), smooth=False)
    cr.location = (1.25, 1.0, 0)
    for name, pts in (("Cable_Laptop", [(0.18, 1.40, 0.752), (0.30, 1.74, 0.75), (0.34, 1.79, 0.4), (0.6, 1.76, 0.01), (1.0, 1.70, 0.01)]),
                      ("Cable_Monitor", [(0.58, 1.68, 0.76), (0.62, 1.79, 0.6), (0.8, 1.77, 0.02), (1.0, 1.72, 0.01)]),
                      ("Cable_Lamp", [(0.95, 1.76, 0.755), (0.99, 1.79, 0.5), (1.0, 1.76, 0.01), (1.04, 1.70, 0.01)])):
        U.curve_object(name, pts, col_props, bevel=0.0035, mat=m_black)
    strip = U.mesh_object("PowerStrip", U.bm_rounded_box((0.3, 0.06, 0.04), 0.008, 2, (1.05, 1.68, 0.02)), col_props,
                          M.simple("MAT_WhitePlastic", (0.7, 0.7, 0.68, 1), 0.4))
    # fairy lights along the left wall above the bed: warm bokeh for the wide shots
    bulbs = []
    m_fairy = M.emission("MAT_FairyLight", (1.0, 0.55, 0.22, 1), 18.0)
    pts = []
    for i in range(26):
        u = i / 25
        y = -1.6 + u * 2.9
        z = 1.95 - 0.18 * math.sin(u * math.pi * 3) ** 2
        pts.append((-1.96, y, z))
        bulbs.append(U.bm_sphere(0.012, 8, 6, (-1.95, y, z - 0.015)))
    U.curve_object("FairyLights_Wire", pts, col_props, bevel=0.0015, mat=m_black)
    U.mesh_object("FairyLights_Bulbs", U.bm_join(*bulbs), col_props, m_fairy)
    # posters / corkboard with 'technical diagrams'
    _poster(col_props, "Poster_NeuralNet", (-1.955, -0.85, 1.55), (math.pi / 2, 0, math.pi / 2), 0.6, 0.8, "nn")
    _poster(col_props, "Poster_Gradient", (1.955, 0.0, 1.45), (math.pi / 2, 0, -math.pi / 2), 0.5, 0.7, "loss")
    cork = U.mesh_object("Corkboard", U.bm_box((0.7, 0.025, 0.45), (0, 0, 0)), col_props,
                         M.simple("MAT_Cork", (0.42, 0.27, 0.13, 1), 0.9), smooth=False)
    cork.location = (-1.05, 1.785, 1.55)
    pin_papers = []
    for i in range(5):
        p = _plane(f"Cork_Note_{i}", col_props, rng.uniform(0.12, 0.18), rng.uniform(0.12, 0.2), M.paper("MAT_PaperNote", (0.8, 0.78, 0.7, 1)),
                   (-1.30 + i * 0.13, 1.77, 1.55 + rng.uniform(-0.12, 0.12)), (math.pi / 2, 0, rng.uniform(-0.15, 0.15)))
    R.top = top
    return R


def _mug(name, col, mat):
    body = U.bm_cylinder(0.042, 0.10, 28, (0, 0, 0.05), cap=True)
    handle = U.bm_torus(0.028, 0.008, 20, 8, (0, 0, 0))
    bmesh.ops.rotate(handle, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'X'), verts=handle.verts)
    bmesh.ops.translate(handle, vec=(0.048, 0, 0.052), verts=handle.verts)
    ob = U.mesh_object(name, U.bm_join(body, handle), col, mat)
    U.add_bevel(ob, 0.003, 2)
    coffee = U.mesh_object(name + "_Coffee", U.bm_cylinder(0.038, 0.002, 24, (0, 0, 0.088)), col,
                           M.simple("MAT_Coffee", (0.04, 0.018, 0.008, 1), 0.08))
    coffee.parent = ob
    return ob


def _keyboard_material(screen_dir=None):
    m = bpy.data.materials.get("MAT_LaptopKeys")
    if m:
        return m
    import os
    alb = os.path.join(screen_dir or "", "keyboard.png")
    glow = os.path.join(screen_dir or "", "keyboard_glow.png")
    if screen_dir and os.path.exists(alb) and os.path.exists(glow):
        # a real keycap texture with backlit legends: reads as a keyboard in a close-up
        m = bpy.data.materials.new("MAT_LaptopKeys")
        m.use_nodes = True
        nb = M.NB(m.node_tree)
        nb.nodes.clear()
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        ta = nb.n("ShaderNodeTexImage", (-650, 100))
        ta.image = bpy.data.images.load(alb, check_existing=True)
        tg = nb.n("ShaderNodeTexImage", (-650, -200))
        tg.image = bpy.data.images.load(glow, check_existing=True)
        for t in (ta, tg):
            t.interpolation = 'Cubic'
            nb.l(tc.outputs["UV"], t.inputs[0])
        p = nb.n("ShaderNodeBsdfPrincipled", (-200, 0))
        p.inputs["Roughness"].default_value = 0.58          # matte caps: no grazing glare
        p.inputs["Specular IOR Level"].default_value = 0.25
        nb.l(ta.outputs["Color"], p.inputs["Base Color"])
        p.inputs["Emission Color"].default_value = (0.55, 0.75, 1.0, 1)
        sm = nb.n("ShaderNodeMath", (-400, -200), _operation='MULTIPLY')
        sm.inputs[1].default_value = 1.8
        nb.l(tg.outputs["Color"], sm.inputs[0])
        nb.l(sm.outputs[0], p.inputs["Emission Strength"])
        out = nb.n("ShaderNodeOutputMaterial", (100, 0))
        nb.l(p.outputs[0], out.inputs[0])
        return m
    m = bpy.data.materials.new("MAT_LaptopKeys")
    m.use_nodes = True
    nb = M.NB(m.node_tree)
    nb.nodes.clear()
    p = nb.n("ShaderNodeBsdfPrincipled", (0, 0))
    p.inputs["Roughness"].default_value = 0.45
    out = nb.n("ShaderNodeOutputMaterial", (300, 0))
    nb.l(p.outputs[0], out.inputs[0])
    tc = nb.n("ShaderNodeTexCoord", (-900, 0))
    br = nb.n("ShaderNodeTexBrick", (-650, 0), Scale=1.0, Mortar_Size=0.15, Brick_Width=0.067, Row_Height=0.2)
    br.offset = 0.25
    br.inputs["Color1"].default_value = (0.02, 0.02, 0.022, 1)
    br.inputs["Color2"].default_value = (0.025, 0.025, 0.027, 1)
    br.inputs["Mortar"].default_value = (0.4, 0.41, 0.43, 1)
    nb.l(tc.outputs["UV"], br.inputs["Vector"])
    nb.l(br.outputs["Color"], p.inputs["Base Color"])
    b = nb.n("ShaderNodeBump", (-300, -200), Strength=0.4, Distance=0.002)
    nb.l(br.outputs["Fac"], b.inputs["Height"])
    nb.l(b.outputs[0], p.inputs["Normal"])
    return m


def _make_page_diffuse(mat):
    """Notebook page: the handwriting texture is lit like paper, not glowing."""
    nt = mat.node_tree
    tex = next(n for n in nt.nodes if n.type == 'TEX_IMAGE')
    out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
    for n in list(nt.nodes):
        if n.type in ('EMISSION', 'ADD_SHADER', 'BSDF_PRINCIPLED'):
            nt.nodes.remove(n)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    p.inputs["Roughness"].default_value = 0.8
    nt.links.new(tex.outputs["Color"], p.inputs["Base Color"])
    nt.links.new(p.outputs[0], out.inputs[0])


def _poster(col, name, loc, rot, w, h, kind):
    m = bpy.data.materials.get(f"MAT_{name}")
    if m is None:
        m = bpy.data.materials.new(f"MAT_{name}")
        m.use_nodes = True
        nb = M.NB(m.node_tree)
        nb.nodes.clear()
        p = nb.n("ShaderNodeBsdfPrincipled", (300, 0))
        p.inputs["Roughness"].default_value = 0.5
        out = nb.n("ShaderNodeOutputMaterial", (600, 0))
        nb.l(p.outputs[0], out.inputs[0])
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        if kind == "nn":
            # layered dots + lines = a neural-net diagram, deliberately naive
            vor = nb.n("ShaderNodeTexVoronoi", (-600, 0), Scale=6.0, Randomness=0.0)
            nb.l(tc.outputs["UV"], vor.inputs["Vector"])
            dots = nb.n("ShaderNodeMath", (-350, 0), _operation='LESS_THAN')
            dots.inputs[1].default_value = 0.12
            nb.l(vor.outputs["Distance"], dots.inputs[0])
            cm = nb.n("ShaderNodeMix", (0, 0), _data_type='RGBA')
            cm.inputs[6].default_value = (0.02, 0.03, 0.06, 1)
            cm.inputs[7].default_value = (0.2, 0.6, 0.8, 1)
            nb.l(dots.outputs[0], cm.inputs["Factor"])
            nb.l(cm.outputs[2], p.inputs["Base Color"])
        else:
            # a 'loss curve' going down... then up
            sep = nb.n("ShaderNodeSeparateXYZ", (-700, 0))
            nb.l(tc.outputs["UV"], sep.inputs[0])
            curve = nb.n("ShaderNodeFloatCurve", (-500, 0))
            pts = curve.mapping.curves[0].points
            pts[0].location = (0, 0.85)
            pts[1].location = (1, 0.7)
            pts.new(0.55, 0.2)
            curve.mapping.update()
            nb.l(sep.outputs["X"], curve.inputs["Value"])
            diff = nb.n("ShaderNodeMath", (-300, 0), _operation='SUBTRACT')
            nb.l(sep.outputs["Y"], diff.inputs[0])
            nb.l(curve.outputs[0], diff.inputs[1])
            ab = nb.n("ShaderNodeMath", (-150, 0), _operation='ABSOLUTE')
            nb.l(diff.outputs[0], ab.inputs[0])
            ln = nb.n("ShaderNodeMath", (0, 0), _operation='LESS_THAN')
            ln.inputs[1].default_value = 0.02
            nb.l(ab.outputs[0], ln.inputs[0])
            cm = nb.n("ShaderNodeMix", (150, 0), _data_type='RGBA')
            cm.inputs[6].default_value = (0.75, 0.72, 0.65, 1)
            cm.inputs[7].default_value = (0.7, 0.1, 0.05, 1)
            nb.l(ln.outputs[0], cm.inputs["Factor"])
            nb.l(cm.outputs[2], p.inputs["Base Color"])
    return _plane(name, col, w, h, m, loc, rot)
