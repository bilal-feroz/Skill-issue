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
    """One shot's camera, authored in shot-relative time t in [0, 1]."""

    def __init__(self, sid, pos, target, lens, fstop=4.0, shake=0.05, near=0.02):
        sh = next(x for x in T.SHOTS if x["id"] == sid)
        self.sid, self.cam = sid, sh["cam"]
        self.a, self.b = sh["start"], sh["end"]
        self.ranges = [(self.a, self.b)]
        self.fstop, self.shake, self.near = fstop, shake, near
        self._pos, self._target, self._lens = pos, target, lens

    def t(self, f):
        return max(0.0, min(1.0, (f - self.a) / max(1, self.b - self.a)))

    def pos(self, f):
        return V(self._pos(self.t(f))) if self._pos else None

    def target(self, f):
        tg = self._target
        if isinstance(tg, U.Track):
            return V(tg(self.t(f)))
        return V(tg(f))

    def lens(self, f):
        return self._lens(self.t(f))


def track(*keys):
    """Keys in shot-relative time: (t, value[, ease])."""
    t = U.Track()
    for k in keys:
        t.key(*k)
    return t


def build(ctx, hero):
    """Define every shot. Positions are in station space (they ride the belt).

    Grammar (scenario-blender-previs-storyboard): one fact per shot, eye height unless a
    stated reason, one consistent screen-insert angle, calm cameras early and kinetic later,
    handheld only where urgency motivates it."""
    W = hero.W
    head = lambda f: hero_point(hero, f, "head", (0, -0.10, 1.56))
    face = lambda f: hero_point(hero, f, "head", (0, -0.13, 1.55))      # eyes-to-nose: room for the quiff
    chest = lambda f: hero_point(hero, f, "chest", (0, -0.05, 1.22))
    const = lambda p: (lambda f, p=V(p): p)
    shots = []
    A = shots.append
    WEB = (0.03, 1.56, 1.22)                 # 'webcam', cheated up to eye level (no chin distortion)
    INS = (-0.17, 1.13, 0.98)                # the laptop screen insert: one consistent angle
    scr = const(W["laptop_screen"])
    kb = W["laptop_M"] @ V((0, 0.03, 0.0165))

    # ACT I: calm, near locked-off
    est = Shot("S01", track((0, (-1.55, -1.42, 1.72)), (1, (-1.05, -0.92, 1.56), "smooth")),
               None, track((0, 24.0), (1, 27.0)), 4.0, 0.03)
    est._target = lambda f, e=est: V((0.25, 1.25, 1.05)).lerp(head(f), U.ease(e.t(f), "smooth"))
    A(est)
    A(Shot("S02", track((0, (0.50, 0.88, 1.38)), (1, (0.51, 0.91, 1.35))), const(W["notebook_page"] + V((0, 0.03, 0))),
           track((0, 40.0)), 4.0, 0.02))
    A(Shot("S03", track((0, WEB), (1, (0.03, 1.55, 1.22))), face, track((0, 30.0)), 2.8, 0.02))
    A(Shot("S04", track((0, INS), (1, (-0.15, 1.17, 0.97))), scr, track((0, 42.0), (1, 44.0)), 5.6, 0.03))
    A(Shot("S05", track((0, WEB), (1, (0.03, 1.50, 1.21), "smooth")), face, track((0, 32.0), (1, 36.0)), 2.8, 0.02))
    A(Shot("S06", track((0, (0.49, 0.89, 1.37)), (1, (0.51, 0.93, 1.33))), const(W["notebook_page"] + V((0, 0.03, 0))),
           track((0, 42.0)), 4.0, 0.03))
    # ACT II: the crescendo
    A(Shot("S07", track((0, W["laptop_M"] @ V((0.20, -0.21, 0.27))), (1, W["laptop_M"] @ V((0.18, -0.19, 0.25)), "smooth")),
           const(W["laptop_M"] @ V((0.0, 0.02, 0.017))), track((0, 62.0), (1, 66.0)), 8.0, 0.06))
    A(Shot("S08", track((0, (0.88, 1.52, 1.52)), (1, (0.80, 1.45, 1.47), "in")), const(V((0.08, 1.02, 1.02))),
           track((0, 26.0)), 5.6, 0.30))
    A(Shot("S08b", track((0, (-0.39, 0.87, 0.87)), (1, (-0.43, 0.94, 0.85), "in")), const(W["clock"] + V((0.0, 0.0, -0.005))),
           track((0, 44.0), (1, 52.0)), 2.8, 0.45))
    A(Shot("S09", track((0, INS), (1, (-0.15, 1.16, 0.97))), scr, track((0, 42.0), (1, 46.0)), 5.6, 0.12))
    A(Shot("S10", track((0, (0.03, 1.52, 1.22))), face, track((0, 34.0)), 2.8, 0.30))
    A(Shot("S11", track((0, INS)), scr, track((0, 44.0)), 5.6, 0.02))          # stillness for the punchline
    # from the notification side: his eyes dart from the code (three-quarter) to the
    # notification (almost to lens), so both looks read
    A(Shot("S12", track((0, (0.62, 1.28, 1.32)), (1, (0.60, 1.27, 1.31))), face, track((0, 38.0)), 4.0, 0.02))
    A(Shot("S13", track((0, INS), (1, (-0.16, 1.15, 0.975))), scr, track((0, 42.0), (1, 48.0)), 5.6, 0.35))
    A(Shot("S14", track((0, (0.03, 1.57, 1.36)), (0.3, (0.03, 1.36, 1.38), "expo_out"), (1, (0.03, 1.33, 1.38))),
           face, track((0, 30.0), (0.3, 44.0), (1, 48.0)), 2.8, 0.9))
    # ACT III: slower, every beat held long enough to read
    bld = Shot("S15", track((0, (-0.88, 1.58, 1.28)), (1, (-0.80, 1.52, 1.22))), None, track((0, 26.0)), 4.0, 0.25)
    bld._target = lambda f, e=bld: head(f).lerp(V(W["machine"]), U.ease(e.t(f) / 0.35, "smooth"))
    A(bld)
    A(Shot("S16", track((0, (-0.64, 1.00, 0.97)), (1, (-0.60, 1.05, 0.95))), const(W["machine"] + V((0.04, -0.04, -0.03))),
           track((0, 42.0), (1, 45.0)), 4.0, 0.10))
    A(Shot("S17", track((0, (0.10, 1.62, 1.42)), (1, (0.10, 1.60, 1.40))), lambda f: face(f).lerp(chest(f), 0.35),
           track((0, 28.0)), 4.0, 0.02))
    A(Shot("S18", track((0, INS), (1, (-0.14, 1.18, 0.97), "smooth")), const(W["laptop_screen"] + V((-0.035, 0.0, 0.025))),
           track((0, 40.0), (1, 44.0)), 5.6, 0.03))
    slot = W["printer_slot"]
    # two facts, two shots: (1) it prints HIS roadmap, header readable as it hangs off the desk;
    # (2) it never stops. Both near locked-off, so nothing smears.
    A(Shot("S19", track((0, (-0.30, 0.62, 1.00)), (1, (-0.31, 0.68, 0.96), "smooth")),
           track((0, tuple(slot + V((0, -0.10, -0.08)))), (1, (-0.40, 1.06, 0.52), "smooth")),
           track((0, 26.0), (1, 28.0)), 8.0, 0.03))
    A(Shot("S19b", track((0, (-1.40, -1.25, 2.10)), (1, (-1.47, -1.34, 2.17), "smooth")), const(V((0.0, 0.25, 0.25))),
           track((0, 22.0)), 11.0, 0.02))
    A(Shot("S20", track((0, WEB)), face, track((0, 30.0)), 2.8, 0.02))
    A(Shot("S21", track((0, (0.40, 0.68, 1.80)), (1, (0.38, 0.74, 1.76))), scr, track((0, 62.0), (1, 66.0)), 4.0, 0.02))
    A(Shot("S22", track((0, (0.03, 1.52, 1.23))), face, track((0, 36.0)), 2.8, 0.0))
    # ACT IV
    A(Shot("S23", track((0, (-1.30, 0.22, 1.22)), (1, (-1.18, 0.10, 1.32))), chest, track((0, 26.0)), 4.0, 0.04))
    A(Shot("S24", track((0, (-0.25, -0.95, 1.45)), (0.35, (1.55, -1.55, 1.52), "smooth"), (0.6, (1.92, -1.37, 1.62), "smooth"),
                        (1, (1.93, -1.41, 1.64))),
           head, track((0, 30.0), (0.45, 34.0), (1, 36.0)), 2.8, 0.06))
    rev = Shot("S25", track((0, (1.93, -1.41, 1.64)), (0.3, (1.92, -1.64, 1.66)), (0.65, (2.9, -3.1, 2.4), "smooth"),
                            (1, (1.25, -4.3, 2.95), "smooth")), None, track((0, 35.0), (0.4, 28.0), (1, 22.0)), 5.6, 0.12)
    rev._target = lambda f, e=rev: head(f).lerp(V((1.4, 30.0, 4.5)), U.ease((e.t(f) - 0.4) / 0.25, "smooth"))
    A(rev)
    A(Shot("S26", track((0, (1.30, 0.48, 1.66)), (1, (1.32, 0.34, 1.64))), face, track((0, 38.0), (1, 42.0)), 2.8, 0.05))
    A(Shot("S27", track((0, (3.6, -3.0, 0.90)), (1, (3.6, -3.15, 0.88))), const(V((-14.0, 24.0, 10.0))),
           track((0, 30.0)), 8.0, 0.2))
    A(Shot("S28", None, const(V((0, 0, 0))), track((0, 28.0), (1, 24.0)), 11.0, 0.25))
    A(Shot("S29", track((0, (0, -12.0, -300.0))), const(V((0, 0, -300.0))), track((0, 50.0)), 11.0, 0.0))
    ctx.shots = shots
    # where is "the audience"? the active camera position (for direct looks)
    for s in shots:
        if s._pos is None:
            continue
        for f in range(s.a, s.b + 1):
            hero.cam_pos[f] = s.pos(f) + V((0, ch("belt_distance", f), 0))
    cams = {}
    for s in shots:
        if s.cam in cams:
            continue
        cd = bpy.data.cameras.new(s.cam)
        cd.sensor_width = 36.0
        cd.clip_start = s.near
        cd.clip_end = 6000.0
        cd.dof.use_dof = s.cam != "CAM_Title"
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
    """Bake every camera: shots sharing a camera write into the same f-curves."""
    per_cam = {}
    for s in ctx.shots:
        rows = per_cam.setdefault(s.cam, {})
        for f in range(max(1, s.a - 1), min(720, s.b + 1) + 1):
            if f in rows and not (s.a <= f <= s.b):
                continue                      # a neighbouring shot owns this frame
            rows[f] = s
    for cam, rows in per_cam.items():
        ob = ctx.cams[cam]
        frames = sorted(rows)
        locs, quats, lens, focus, fst = [], [], [], [], []
        prev = None
        for f in frames:
            s = rows[f]
            off = V((0, ch("belt_distance", f), 0))
            roll = 0.0
            if cam == "CAM_Pullback":
                pos, tgt, roll = pullback(hero, f)
            elif cam == "CAM_Title":
                pos, tgt = s.pos(f), s.target(f)
            else:
                pos = s.pos(f) + off
                tgt = s.target(f)
                if _is_static_target(s):
                    tgt = tgt + off
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
            fst.append(s.fstop)
        U.bake_vec(ob, "location", frames, locs)
        U.bake_vec(ob, "rotation_quaternion", frames, quats)
        U.bake(ob.data, "lens", 0, frames, lens)
        U.bake(ob.data, "dof.focus_distance", 0, frames, focus)
        U.bake(ob.data, "dof.aperture_fstop", 0, frames, fst, 'CONSTANT')


def _is_static_target(s):
    # constant / keyed targets were authored in station space; actor targets are already world
    tg = s._target
    if isinstance(tg, U.Track):
        return True
    return getattr(tg, "__name__", "") == "<lambda>" and tg.__code__.co_varnames[:2] == ("f", "p")


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


def captions(ctx):
    """Whisper caption: an overlay image alpha-composited during the whisper."""
    comp = ctx.scene.compositing_node_group
    if "CaptionAmount" not in comp.nodes:
        return
    a, b = E["whisper_start"] + 1, E["whisper_end"] - 2
    vals = [1.0 if a <= f <= b else 0.0 for f in FRAMES]
    U.bake(comp, 'nodes["CaptionAmount"].outputs[0].default_value', 0, FRAMES, vals, 'CONSTANT')
