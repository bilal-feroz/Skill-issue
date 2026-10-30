"""Cinematography: one camera per shot, bound to the timeline with markers.

Each camera = position track + look-at target (which may follow the actor) +
lens track + depth-of-field focus pulled to the target + handheld noise whose
amplitude follows the speed system's lagged `cam_intensity` channel. Early
shots are near locked-off; the camera loses its composure along with him.
"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import bl_util as U
from . import speed as S
from . import timeline as T

V = Vector
E = T.E
CH = S.compute()
FRAMES = list(range(T.FRAME_START, T.FRAME_END + 1))


def ch(name, f):
    return S.value(CH, name, f)


class Shot:
    def __init__(self, cam, ranges, pos, target, lens, fstop=2.8, shake=0.1, roll=None, near=0.02):
        self.cam, self.ranges, self.pos, self.target, self.lens = cam, ranges, pos, target, lens
        self.fstop, self.shake, self.roll, self.near = fstop, shake, roll, near


def track(*keys):
    t = U.Track()
    for k in keys:
        t.key(*k)
    return t


def build(ctx, hero):
    """Define every shot. Positions are in station space (they ride the belt)."""
    W = hero.W
    head = lambda f: hero_point(hero, f, "head", (0, -0.10, 1.56))
    face = lambda f: hero_point(hero, f, "head", (0, -0.13, 1.52))
    chest = lambda f: hero_point(hero, f, "chest", (0, -0.05, 1.22))
    hands = lambda f: (hero_point(hero, f, "hand.L", (0.24, -0.03, 0.74)) + hero_point(hero, f, "hand.R", (-0.24, -0.03, 0.74))) / 2
    const = lambda p: (lambda f, p=V(p): p)
    lerp_t = lambda a, b, f0, f1, ease="smooth": (lambda f: a(f).lerp(b(f), U.ease((f - f0) / (f1 - f0), ease)))
    e = E
    shots = []
    A = shots.append
    A(Shot("CAM_S01_Establish", [(1, 44)], track((1, (-1.55, -1.42, 1.72)), (44, (-1.05, -0.92, 1.56), "smooth")),
           lerp_t(const((0.25, 1.25, 1.05)), head, 1, 44), track((1, 24.0), (44, 27.0)), 4.0, 0.06))
    A(Shot("CAM_S02_Notebook", [(45, 68), (141, 160)],
           track((45, (0.50, 0.88, 1.38)), (68, (0.51, 0.91, 1.35)), (141, (0.49, 0.89, 1.37)), (160, (0.51, 0.93, 1.33))),
           const(W["notebook_page"] + V((0.0, 0.03, 0))), track((45, 40.0), (160, 42.0)), 4.0, 0.05))
    webcam = (0.03, 1.49, 1.10)
    A(Shot("CAM_S03_Webcam", [(69, 92)], track((69, webcam), (92, (0.03, 1.48, 1.10))), face, track((69, 32.0)), 2.8, 0.04))
    A(Shot("CAM_S04_Screen", [(93, 122), (491, 502)],
           track((93, (0.50, 1.05, 1.02)), (122, (0.47, 1.09, 1.01)), (491, (0.50, 1.05, 1.02)), (502, (0.46, 1.10, 1.00))),
           const(W["laptop_screen"]), track((93, 42.0), (122, 46.0), (491, 42.0), (502, 48.0)), 4.0, 0.08))
    A(Shot("CAM_S05_WebcamDoubt", [(123, 140)], track((123, (0.03, 1.49, 1.10)), (140, (0.03, 1.45, 1.11), "smooth")),
           face, track((123, 32.0), (140, 40.0)), 2.8, 0.05))
    A(Shot("CAM_S07_Hands", [(161, 184)], track((161, (-0.37, 1.33, 0.87)), (184, (-0.34, 1.31, 0.86))),
           hands, track((161, 48.0)), 2.2, 0.35))
    A(Shot("CAM_S08_Front", [(185, 214)], track((185, (-0.14, 1.64, 1.17)), (214, (-0.06, 1.56, 1.23))),
           face, track((185, 26.0), (214, 24.0)), 4.0, 0.9))
    A(Shot("CAM_S09_Clock", [(215, 232)], track((215, (-0.30, 0.98, 0.93)), (232, (-0.38, 1.04, 0.88), "in")),
           const(W["clock"] + V((0.02, 0.02, -0.01))), track((215, 40.0), (232, 52.0)), 2.2, 0.8))
    screen_cam = (-0.17, 1.13, 0.98)
    A(Shot("CAM_S10_Tutorial", [(233, 256), (269, 284)],
           track((233, screen_cam), (256, (-0.15, 1.16, 0.97)), (269, (-0.17, 1.13, 0.98)), (284, (-0.15, 1.17, 0.97))),
           const(W["laptop_screen"]), track((233, 40.0), (256, 44.0), (269, 40.0), (284, 44.0)), 5.6, 0.25))
    A(Shot("CAM_S11_Nod", [(257, 268)], track((257, (0.03, 1.46, 1.10))), face, track((257, 36.0)), 2.8, 0.6))
    A(Shot("CAM_S12_Shoulder", [(285, 312)], track((285, (-0.66, 1.24, 1.27)), (312, (-0.63, 1.24, 1.26))),
           const(V((0.14, 1.06, 1.12))), track((285, 32.0)), 4.0, 0.03))
    A(Shot("CAM_S13_Scream", [(313, 330)], track((313, (0.03, 1.50, 1.10)), (318, (0.03, 1.30, 1.13), "expo_out"), (330, (0.03, 1.27, 1.14))),
           face, track((313, 26.0), (318, 40.0), (330, 44.0)), 2.8, 1.6))
    A(Shot("CAM_S14_Build", [(331, 362)], track((331, (-0.78, 1.28, 1.32)), (362, (-0.68, 1.20, 1.26))),
           lerp_t(head, const(W["machine"]), 331, 345), track((331, 26.0)), 4.0, 0.7))
    A(Shot("CAM_S15_Machine", [(363, 386)], track((363, (-0.72, 1.10, 1.02)), (386, (-0.66, 1.16, 0.99))),
           const(W["machine"] + V((0.04, -0.04, -0.03))), track((363, 42.0), (386, 46.0)), 2.8, 0.3))
    A(Shot("CAM_S16_Relax", [(387, 410)], track((387, (0.10, 1.62, 1.42)), (410, (0.10, 1.60, 1.40))),
           lambda f: face(f).lerp(chest(f), 0.35), track((387, 28.0)), 4.0, 0.05))
    A(Shot("CAM_S17_Roadmap", [(411, 434)], track((411, (-0.17, 1.13, 0.98)), (434, (-0.14, 1.18, 0.97), "smooth")),
           const(W["laptop_screen"]), track((411, 40.0)), 5.6, 0.1))
    A(Shot("CAM_S18_Scroll", [(435, 468)], track((435, (0.40, 0.42, 1.35)), (468, (-1.70, -1.58, 2.28), "out")),
           lerp_t(const(W["machine"]), const(V((0.3, -0.2, 0.2))), 435, 468), track((435, 24.0), (468, 18.0)), 8.0, 0.15))
    A(Shot("CAM_S19_Looks", [(469, 490)], track((469, (0.03, 1.49, 1.10))), face, track((469, 30.0)), 2.8, 0.03))
    A(Shot("CAM_S21_Empty", [(503, 516)], track((503, (0.03, 1.46, 1.11))), face, track((503, 40.0)), 2.8, 0.0))
    A(Shot("CAM_S22_Stand", [(517, 538)], track((517, (-1.30, 0.22, 1.22)), (538, (-1.18, 0.10, 1.32))),
           chest, track((517, 26.0)), 4.0, 0.08))
    A(Shot("CAM_S23_Door", [(539, 576)], track((539, (-0.25, -0.95, 1.45)), (552, (1.70, -1.62, 1.52), "smooth"), (576, (1.86, -1.66, 1.56))),
           head, track((539, 30.0), (556, 42.0), (576, 46.0)), 2.8, 0.1))
    A(Shot("CAM_S24_Reveal", [(577, 610)],
           track((577, (1.86, -1.66, 1.56)), (588, (1.90, -1.80, 1.62)), (600, (2.9, -3.1, 2.4), "smooth"), (610, (1.25, -4.3, 2.95), "smooth")),
           lerp_t(head, const(V((1.4, 30.0, 4.5))), 590, 606), track((577, 46.0), (590, 30.0), (610, 22.0)), 5.6, 0.25))
    A(Shot("CAM_S25_Proud", [(611, 632)], track((611, (1.30, 0.48, 1.66)), (632, (1.32, 0.34, 1.64))),
           face, track((611, 38.0), (632, 42.0)), 2.8, 0.1))
    A(Shot("CAM_S26_Display", [(633, 650)], track((633, (3.6, -3.0, 0.90)), (650, (3.6, -3.15, 0.88))),
           const(V((-14.0, 24.0, 10.0))), track((633, 30.0)), 8.0, 0.3))
    A(Shot("CAM_S27_Pullback", [(651, 672)], None, None, track((651, 28.0), (672, 24.0)), 11.0, 0.4))
    A(Shot("CAM_S28_Title", [(673, 720)], track((673, (0, -12.0, -300.0))), const(V((0, 0, -300.0))), track((673, 50.0)), 11.0, 0.0))
    ctx.shots = shots
    # where is "the audience"? the active camera position (for direct looks)
    for s in shots:
        if s.pos is None:
            continue
        for a, b in s.ranges:
            for f in range(a, b + 1):
                hero.cam_pos[f] = V(s.pos(f)) + V((0, ch("belt_distance", f), 0))
    cams = {}
    for s in shots:
        cd = bpy.data.cameras.new(s.cam)
        cd.sensor_width = 36.0
        cd.clip_start = s.near
        cd.clip_end = 6000.0
        cd.dof.use_dof = s.cam not in ("CAM_S28_Title",)
        cd.dof.aperture_fstop = s.fstop
        ob = bpy.data.objects.new(s.cam, cd)
        ob.rotation_mode = 'QUATERNION'
        ctx.cols["Cameras"].objects.link(ob)
        cams[s.cam] = ob
    ctx.cams = cams
    sc = ctx.scene
    for sh in T.SHOTS:
        m = sc.timeline_markers.new(sh["id"], frame=sh["start"])
        m.camera = cams[sh["cam"]]
    sc.camera = cams[T.SHOTS[0]["cam"]]


def hero_point(hero, f, bone, rest_p):
    """Rest-space point carried by a bone, in world space at frame f."""
    i = max(0, min(len(FRAMES) - 1, int(f) - 1))
    D = hero.Ds[i]
    M = hero.mats[i]
    return M @ (D[bone] @ hero.solver.Rinv[bone] @ V(rest_p))


def look_quat(pos, tgt, roll=0.0):
    d = (tgt - pos)
    q = d.to_track_quat('-Z', 'Y')
    if roll:
        q = q @ Quaternion((0, 0, 1), roll)
    return q


def bake(ctx, hero):
    e = E
    for s in ctx.shots:
        ob = ctx.cams[s.cam]
        frames = []
        for a, b in s.ranges:
            frames += list(range(max(1, a - 1), min(720, b + 1) + 1))
        frames = sorted(set(frames))
        locs, quats, lens, focus = [], [], [], []
        prev = None
        for f in frames:
            off = V((0, ch("belt_distance", f), 0))
            if s.cam == "CAM_S27_Pullback":
                pos, tgt, roll = pullback(hero, f)
            else:
                pos = V(s.pos(f)) + off
                tgt = V(s.target(f))
                roll = 0.0
            # targets defined as constants are in station space too
            if s.cam == "CAM_S28_Title":
                pos, tgt = V(s.pos(f)), V(s.target(f))
            elif _is_static_target(s):
                tgt = tgt + off
            # handheld: lagged speed intensity drives amplitude
            amp = s.shake * (0.15 + ch("cam_intensity", f)) * 0.012
            n = V((U.fbm(f * 0.11, 3), U.fbm(f * 0.13, 7), U.fbm(f * 0.09, 11))) * amp * (pos - tgt).length
            q = look_quat(pos, tgt + n, roll + amp * 2.0 * U.noise1(f * 0.07, 5))
            if prev is not None and prev.dot(q) < 0:
                q = Quaternion((-q.w, -q.x, -q.y, -q.z))
            prev = q
            locs.append(tuple(pos))
            quats.append(tuple(q))
            lens.append(s.lens(f))
            focus.append(max(0.05, (tgt - pos).length))
        U.bake_vec(ob, "location", frames, locs)
        U.bake_vec(ob, "rotation_quaternion", frames, quats)
        U.bake(ob.data, "lens", 0, frames, lens)
        U.bake(ob.data, "dof.focus_distance", 0, frames, focus)


def _is_static_target(s):
    # constant targets were authored in station space; actor targets are already world
    return getattr(s.target, "__name__", "") == "<lambda>" and s.target.__code__.co_varnames[:2] == ("f", "p")


def pullback(hero, f):
    """Ballistic exponential pull-back from his desk to 1.3 km above the loops."""
    a, b = E["pullback_start"], E["black"] - 7       # arrive early, then hold on the system
    t = max(0.0, min(1.0, (f - a) / (b - a)))
    k = 3.6
    u = (math.exp(k * t) - 1) / (math.exp(k) - 1)
    off = V((0, ch("belt_distance", f), 0))
    p0 = V((0.05, -0.15, 1.85)) + off
    p1 = V((60.0, -720.0, 1050.0))
    pos = p0.lerp(p1, u) + V((0, 0, 30.0)) * max(0.0, (f - b) / 6.0)
    t0 = V((0.05, 1.15, 0.95)) + off
    t1 = V((75.0, 40.0, 0.0))
    tu = (math.exp(3.5 * t) - 1) / (math.exp(3.5) - 1)
    tgt = t0.lerp(t1, tu)
    return pos, tgt, math.radians(10) * u


def title(ctx):
    """Black card: SKILL ISSUE. / HUMANITY: STILL IN BETA. (typed, cursor blinks)."""
    from .hall import text_object
    from . import materials as M
    col = ctx.cols["Title"]
    e = E
    z = -300.0
    white = M.emission("MAT_TitleWhite", (1, 1, 1, 1), 4.0)
    grey = M.emission("MAT_TitleGrey", (0.75, 0.75, 0.75, 1), 2.2)
    black = M.simple("MAT_TitleBlack", (0, 0, 0, 1), 1.0, **{"Specular IOR Level": 0.0})
    back = U.mesh_object("Title_Backdrop", U.bm_box((60, 0.1, 40), (0, 3.0, z)), col, black, smooth=False)
    t1 = text_object("Title_SkillIssue", col, T.TITLE, 0.82, white, extrude=0.0)
    t1.rotation_euler = (math.pi / 2, 0, 0)
    t1.location = (0, 0, z + 0.25)
    sub_size = 0.25
    t2 = text_object("Title_Subtitle", col, T.SUBTITLE, sub_size, grey, extrude=0.0, bold=False)
    t2.rotation_euler = (math.pi / 2, 0, 0)
    t2.location = (0, 0, z - 0.62)
    import os
    mono = os.path.join(ctx.root, "assets", "fonts", "DejaVuSansMono.woff2")
    try:
        t2.data.font = bpy.data.fonts.load(mono, check_existing=True)
    except Exception:
        pass
    # slam: invisible -> overshoot -> settle
    s0 = e["title_slam"]
    sc = []
    for f in FRAMES:
        if f < s0:
            sc.append((0, 0, 0))
        else:
            k = f - s0
            v = 1.0 + 0.14 * math.exp(-k / 1.8) * math.cos(k * 1.3)
            sc.append((v, v, v))
    U.bake_vec(t1, "scale", FRAMES, sc, 'CONSTANT')
    # subtitle glitches in on the 'beta' blip (E['subtitle']), then a cursor blinks
    s1 = e["subtitle"]
    flick = {s1: 1, s1 + 1: 0, s1 + 2: 1, s1 + 3: 0, s1 + 4: 1}
    sub_sc, sub_x = [], []
    for f in FRAMES:
        on = 0 if f < s1 else flick.get(f, 1)
        sub_sc.append((on, on, on))
        sub_x.append(0.04 * (1 if f in (s1, s1 + 2) else 0))
    U.bake_vec(t2, "scale", FRAMES, sub_sc, 'CONSTANT')
    U.bake_vec(t2, "location", FRAMES, [(x, 0, z - 0.62) for x in sub_x], 'CONSTANT')
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(e["subtitle"] + 10)
    width = t2.dimensions.x
    bpy.context.scene.frame_set(1)
    cursor = U.mesh_object("Title_Cursor", U.bm_box((0.13, 0.02, 0.24), (0, 0, 0)), col, grey, smooth=False)
    cs = []
    for f in FRAMES:
        on = f >= s1 + 5 and (f // 7) % 2 == 0
        cs.append((1, 1, 1) if on else (0, 0, 0))
    cursor.location = (width / 2 + 0.14, -0.01, z - 0.62 + 0.02)
    U.bake_vec(cursor, "scale", FRAMES, cs, 'CONSTANT')
