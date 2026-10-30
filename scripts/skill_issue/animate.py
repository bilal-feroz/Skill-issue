"""The performance: every animated property in the film is generated here.

Structure
* SPEED_CONTROLLER: an empty whose custom properties carry the speed channels
  per frame (see speed.py). Drivers connect them to the crowd Geometry Nodes,
  the belt material, the eye-bag shader and the hair shape key.
* Hero acting = pose-to-pose keys (authored below, frame numbers from
  timeline.E) + procedural layers (typing taps, nods, head snaps, breathing,
  blinks, nervous leg, handheld camera), solved by puppet.Solver and baked.
* Props, screens, lights and the industrial reveal are keyed from the same
  channels and events, so everything accelerates together.
"""

import math
import random

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import bl_util as U
from . import puppet as P
from . import speed as S
from . import timeline as T
from . import track as TR

E = T.E
CH = S.compute()
FRAMES = list(range(T.FRAME_START, T.FRAME_END + 1))
V = Vector


def ch(name, f):
    return S.value(CH, name, f)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def win(f, a, b, ramp=3):
    """1 inside [a, b] with soft ramps of `ramp` frames, else 0."""
    if f < a - ramp or f > b + ramp:
        return 0.0
    if f < a:
        return U.ease((f - (a - ramp)) / ramp, "smooth")
    if f > b:
        return 1 - U.ease((f - b) / ramp, "smooth")
    return 1.0


# ---------------------------------------------------------------------------
# Typing pose (shared by hero and crowd)
# ---------------------------------------------------------------------------

SEAT_HIPS = V((0, 0.06, -0.33))


def seated_legs(spread=0.11, fwd=-0.44):
    return {f"leg.{s}": dict(ankle=V((spread * k, fwd, 0.085)), pole=V((0.18 * k, -1, 0.6)), toe=V((0.08 * k, -1, -0.18)))
            for s, k in (("L", 1), ("R", -1))}


def typing_pose_char():
    p = dict(hips=(SEAT_HIPS.copy(), (0, 0, 0)), spine=(0.08, 0, 0), chest=(0.10, 0, 0), neck=(-0.04, 0, 0), head=(0.14, 0, 0))
    for s, k in (("L", 1), ("R", -1)):
        p[f"arm.{s}"] = dict(wrist=V((0.12 * k, -0.42, 0.78)), pole=V((0.55 * k, 0.35, 0.6)),
                             fdir=V((-0.08 * k, -1, -0.4)), palm=V((0, 0, -1)))
        p[f"fingers.{s}"] = dict(index=(0.35, 0.3), middle=(0.4, 0.3), ring=(0.45, 0.35), pinky=(0.5, 0.35), thumb=(0.2, 0.1))
    p.update(seated_legs())
    return p


def crowd_seated_pose(ch_):
    """Pose the crowd clone (static bake) and return char->station matrix."""
    P.bake_pose_track(ch_, [1, 2], lambda f: typing_pose_char())
    bpy.context.scene.frame_set(1)
    # station space: student faces +Y, chair behind the desk
    return Matrix.Translation((0, -0.02, 0.08)) @ Matrix.Rotation(math.pi, 4, 'Z')


# ---------------------------------------------------------------------------
# Controller + drivers
# ---------------------------------------------------------------------------

CHANNELS = ["speed", "typing_phase", "crowd_typing_phase", "belt_distance", "finish_gap", "stress",
            "clock_minutes", "cam_intensity", "light_pulse", "tempo_bpm", "beat_phase", "belt_speed"]


def build_controller(col):
    ctl = U.empty("SPEED_CONTROLLER", col, (0, -1.6, 2.4), display="SPHERE", size=0.15)
    for name in CHANNELS:
        ctl[name] = 0.0
    for name in CHANNELS:
        U.bake(ctl, f'["{name}"]', 0, FRAMES, [ch(name, f) for f in FRAMES])
    ctl["_doc"] = "Speed system channels, baked per frame from scripts/skill_issue/speed.py"
    return ctl


def drive(id_data, path, index, ctl, prop, expr="v"):
    fc = id_data.driver_add(path, index) if index is not None and index >= 0 else id_data.driver_add(path)
    d = fc.driver
    d.type = 'SCRIPTED'
    v = d.variables.new()
    v.name = "v"
    v.type = 'SINGLE_PROP'
    v.targets[0].id_type = 'OBJECT'
    v.targets[0].id = ctl
    v.targets[0].data_path = f'["{prop}"]'
    d.expression = expr
    return fc


# ---------------------------------------------------------------------------
# Helpers for world <-> character space
# ---------------------------------------------------------------------------

class RigPath:
    """World placement of the hero rig over time (seated / standing / walking / yanked)."""

    SEAT = (V((0.05, 0.80, 0.0)), math.pi)
    DOOR = (V((1.56, -0.93, 0.0)), math.pi / 2)

    def __init__(self):
        self.loc = U.Track()
        self.rot = U.Track()
        sl, sr = self.SEAT
        dl, dr = self.DOOR
        stand_loc = V((0.05, 0.64, 0.0))
        self.loc.key(1, tuple(sl)).key(E["stand_start"], tuple(sl))
        self.loc.key(E["stand_end"], tuple(stand_loc), "smooth")
        self.rot.key(1, sr).key(E["stand_end"], sr)
        # walk: three steps toward the door, turning
        w0, w1 = E["walk_start"], E["walk_end"]
        mid1 = V((0.55, 0.15, 0)); mid2 = V((1.10, -0.45, 0))
        self.loc.key(w0, tuple(stand_loc)).key(w0 + 5, tuple(mid1), "linear").key(w0 + 10, tuple(mid2), "linear")
        self.loc.key(w1, tuple(dl), "out")
        self.rot.key(w0 - 2, sr).key(w0 + 4, 0.84, "smooth").key(w1 - 2, 0.84).key(w1 + 2, dr, "smooth")
        # walls fall: startle, then he turns toward the light (+Y)
        self.rot.key(E["walls_land"] + 4, dr).key(E["walls_land"] + 16, math.pi, "smooth")
        self.loc.key(E["yank"], tuple(dl))
        # yanked: chair hits, both fly back to the desk
        self.loc.key(E["yank"] + 5, tuple(sl), "in")
        self.rot.key(E["yank"], math.pi).key(E["yank"] + 5, sr)
        self.loc.key(720, tuple(sl))

    def station_offset(self, f):
        return V((0.0, ch("belt_distance", f), 0.0))

    def matrix(self, f):
        loc = V(self.loc(f)) + self.station_offset(f)
        return Matrix.Translation(loc) @ Matrix.Rotation(self.rot(f), 4, 'Z')


def w2c(M, p):
    return M.inverted() @ V(p)


def d2c(M, d):
    return (M.to_3x3().inverted() @ V(d)).normalized()


# ---------------------------------------------------------------------------
# Generic keyed blend of callables
# ---------------------------------------------------------------------------

class SpecTrack:
    """keys: (frame, spec, ease). spec(f) -> tuple of Vectors/floats. Blends neighbours."""

    def __init__(self):
        self.keys = []

    def key(self, frame, spec, ease="smooth"):
        if not callable(spec):
            const = spec
            spec = (lambda f, c=const: c)
        self.keys.append((frame, spec, ease))
        self.keys.sort(key=lambda k: k[0])
        return self

    def __call__(self, f):
        ks = self.keys
        if f <= ks[0][0]:
            return ks[0][1](f)
        if f >= ks[-1][0]:
            return ks[-1][1](f)
        for (f0, s0, _), (f1, s1, e) in zip(ks, ks[1:]):
            if f0 <= f <= f1:
                t = U.ease((f - f0) / max(1e-9, f1 - f0), e)
                a, b = s0(f), s1(f)
                if t <= 0:
                    return a
                if t >= 1:
                    return b
                return tuple(_lerp(x, y, t) for x, y in zip(a, b))
        return ks[-1][1](f)


def _lerp(a, b, t):
    if isinstance(a, Vector):
        return a.lerp(b, t)
    if isinstance(a, dict):
        return {k: tuple(_lerp(x, y, t) for x, y in zip(a[k], b[k])) for k in a}
    if isinstance(a, tuple):
        return tuple(_lerp(x, y, t) for x, y in zip(a, b))
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# The hero performance
# ---------------------------------------------------------------------------

class Hero:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ch = ctx.hero
        self.room = ctx.room
        self.mc = ctx.machine
        self.path = RigPath()
        self.solver = P.Solver(self.ch)
        R = self.room
        bpy.context.view_layer.update()
        self.W = {}
        mw = lambda ob: ob.matrix_world.copy()
        self.W["laptop_screen"] = mw(R.laptop_screen).translation
        self.W["monitor_screen"] = mw(R.monitor_screen).translation
        self.W["notebook_page"] = mw(R.notebook_page).translation
        self.W["notebook_M"] = mw(R.notebook_page)
        self.W["mug"] = mw(R.mug).translation
        self.W["clock"] = mw(R.clock).translation + V((0, 0, 0.04))
        self.W["machine"] = mw(self.mc.root).translation + V((0, 0, 0.12))
        self.W["button"] = (mw(self.mc.button)).translation + V((0, 0, 0.03))
        self.W["trackpad"] = (mw(R.laptop) @ V((0, -0.07, 0.02)))
        self.W["door_handle"] = mw(R.door_handle).translation
        self.W["floor_scroll"] = V((-0.6, 0.3, 0.0))
        self.W["lid_top"] = (mw(R.laptop_hinge) @ V((0, 0.0, 0.215)))
        self.W["finish"] = V((0, 80, 6))
        self.W["display"] = V((-15.0, 24, 10.5))
        self.cam_pos = {}     # filled by cameras (for looking at the audience)
        self.build_tracks()

    # ---- hand presets (return char-space wrist, fdir, palm, pole) ---------------
    def kb(self, side):
        k = 1 if side == "L" else -1
        def spec(f):
            M = self.path.matrix(f)
            wx = -0.075 if side == "L" else 0.115
            w = w2c(M, (wx, 1.205, 0.79))
            return (w, d2c(M, (0.06 * k, 1, -0.42)), d2c(M, (0, 0, -1)), V((0.55 * k, 0.35, 0.6)))
        return spec

    def world_hand(self, side, wrist, fdir, palm, pole=None):
        k = 1 if side == "L" else -1
        pole = pole or V((0.55 * k, 0.3, 0.7))
        def spec(f):
            M = self.path.matrix(f)
            wv = wrist(f) if callable(wrist) else wrist
            return (w2c(M, wv), d2c(M, fdir), d2c(M, palm), pole)
        return spec

    def char_hand(self, side, wrist, fdir, palm, pole=None):
        k = 1 if side == "L" else -1
        pole = pole or V((0.55 * k, 0.3, 0.7))
        return lambda f: (V(wrist), V(fdir).normalized(), V(palm).normalized(), pole)

    def head_hand(self, side, offset, fdir, palm, pole=None):
        """Wrist relative to the solved head (sips, the Scream)."""
        k = 1 if side == "L" else -1
        pole = pole or V((0.6 * k, 0.2, 0.9))
        def spec(f):
            D = self.spine_cache(f)
            Hm = D["head"]
            return (Hm @ V(offset), (Hm.to_3x3() @ V(fdir)).normalized(), (Hm.to_3x3() @ V(palm)).normalized(), pole)
        return spec

    # pen tip path on the notebook page (page-local x, y in metres)
    def pen_tip_world(self, f):
        Mp = self.W["notebook_M"]
        def word(t, x0, x1, y, letters, amp):
            x = x0 + (x1 - x0) * t
            ph = t * letters
            return x + 0.006 * math.sin(ph * 2 * math.pi * 2), y + amp * (0.5 + 0.5 * math.sin(ph * 2 * math.pi))
        a, b = E["write1_start"], E["write1_end"]
        u0, u1 = E["underline1_start"], E["underline1_end"]
        c, d = E["write2_start"], E["write2_end"]
        lift = 0.0
        if f <= b:
            t = clamp((f - a) / (b - a))
            x, y = word(t, -0.075, 0.07, 0.045, 8, 0.03)
            lift = 0.0 if a <= f <= b else 0.03
        elif f <= u1:
            t = clamp((f - u0) / (u1 - u0))
            x, y = -0.08 + 0.16 * U.ease(t, "out"), 0.035 - 0.004 * t
            lift = 0.012 * (1 - win(f, u0, u1, 2))
        elif f <= d + 3:
            t = clamp((f - c) / (d - c))
            x, y = word(t, -0.085, 0.085, -0.015, 15, 0.026)
            lift = 0.0 if c <= f <= d else 0.025
        else:
            x, y, lift = 0.09, -0.05, 0.05
        p = Mp @ V((x, y, 0.0))
        return p + V((0, 0, 0.002 + lift))

    def write_spec(self):
        # hand frame: fingers point forward-left, palm down-left; the pen tip sits
        # ~11 cm along the fingers and 2 cm below the palm
        fdir_w = V((-0.35, 0.85, -0.55)).normalized()
        palm_w = V((-0.45, 0.1, -0.9)).normalized()
        def spec(f):
            M = self.path.matrix(f)
            tip = self.pen_tip_world(f)
            y = fdir_w
            x = (palm_w * -1 - y * (palm_w * -1).dot(y)).normalized()   # R hand: local x = -palm
            z = x.cross(y)
            Rm = Matrix((x, y, z)).transposed()
            wrist = tip - Rm @ V((0.012, 0.115, 0.012))
            return (w2c(M, wrist), d2c(M, fdir_w), d2c(M, palm_w), V((-0.6, 0.3, 0.6)))
        return spec

    def mug_grab_spec(self):
        mug = self.W["mug"]
        return self.world_hand("L", mug + V((-0.075, -0.01, 0.055)), (0.75, 0.6, -0.1), (0.95, 0.2, 0.0))

    def build_tracks(self):
        L, R = SpecTrack(), SpecTrack()
        kbL, kbR = self.kb("L"), self.kb("R")
        rest_desk_L = self.world_hand("L", V((0.20, 1.12, 0.775)), (0.25, 1, -0.25), (0, 0, -1))
        lapL = self.world_hand("L", V((-0.08, 0.98, 0.64)), (0.2, 1, -0.6), (0, 0, -1))
        lapR = self.world_hand("R", V((0.17, 0.98, 0.64)), (-0.2, 1, -0.6), (0, 0, -1))
        write = self.write_spec()
        mug_grab = self.mug_grab_spec()
        sipL = self.head_hand("L", (0.03, -0.20, -0.06), (-0.2, -0.3, 0.9), (-0.9, 0.1, 0.1))
        e = E
        # ---- Act I ----
        R.key(1, write).key(e["underline1_end"] + 6, write).key(e["sip1_start"] + 2, lapR, "smooth")
        R.key(e["notif1"] + 4, lapR).key(e["write2_start"] - 4, write, "smooth").key(e["write2_end"] + 2, write)
        L.key(1, rest_desk_L).key(e["sip1_start"] - 3, rest_desk_L).key(e["sip1_start"] + 2, mug_grab, "smooth")
        L.key(e["sip1_start"] + 6, sipL, "smooth").key(e["sip1_end"] - 4, sipL).key(e["sip1_end"], mug_grab, "smooth")
        L.key(e["sip1_end"] + 4, rest_desk_L, "smooth").key(e["write2_start"], rest_desk_L)
        # ---- Act II: typing ----
        R.key(e["typing_start"] - 2, kbR, "smooth")
        L.key(e["typing_start"] - 2, kbL, "smooth")
        hover = lambda spec: (lambda f: (spec(f)[0] + V((0, 0, 0.025)),) + spec(f)[1:])
        R.key(e["typing_stop"], kbR).key(e["typing_stop"] + 4, hover(kbR), "out")
        L.key(e["typing_stop"], kbL).key(e["typing_stop"] + 4, hover(kbL), "out")
        R.key(e["notif_better"], hover(kbR))
        L.key(e["notif_better"], hover(kbL))
        screamL = self.head_hand("L", (0.115, -0.04, -0.07), (0.1, 0.1, 1.0), (-1, 0, 0))
        screamR = self.head_hand("R", (-0.115, -0.04, -0.07), (-0.1, 0.1, 1.0), (1, 0, 0))
        L.key(e["scream_start"], screamL, "out").key(e["scream_end"], screamL)
        R.key(e["scream_start"], screamR, "out").key(e["scream_end"], screamR)
        # ---- Act III: build frantically over the machine area ----
        def build_hand(side, seed):
            base = self.W["machine"] + V((0.06 if side == "R" else -0.04, -0.12, -0.02))
            def wrist(f):
                ph = ch("typing_phase", f)
                return base + V((0.05 * math.sin(ph * 2.1 + seed), 0.04 * math.cos(ph * 1.7 + seed), 0.05 * abs(math.sin(ph * 3.3 + seed))))
            return self.world_hand(side, wrist, (0.0 if side == "L" else -0.3, 1, -0.8), (0, 0, -1))
        L.key(e["idea"] + 3, kbL).key(e["build_start"], build_hand("L", 0.0), "smooth").key(e["build_end"], build_hand("L", 0.0))
        R.key(e["idea"] + 3, kbR).key(e["build_start"], build_hand("R", 1.3), "smooth").key(e["build_end"], build_hand("R", 1.3))
        # the BIG BUTTON: left hand, anticipation up, slam down
        btn = self.W["button"]
        up = self.world_hand("L", btn + V((-0.02, -0.10, 0.20)), (0.1, 0.7, -0.7), (0, 0.2, -1))
        slam = self.world_hand("L", btn + V((-0.01, -0.075, 0.035)), (0.1, 0.75, -0.65), (0, 0.2, -1))
        L.key(e["machine_lights"] + 2, lapL, "smooth").key(e["button_press"] - 5, up, "smooth").key(e["button_press"], slam, "in")
        L.key(e["button_press"] + 4, slam).key(e["lean_back"] + 2, lapL, "smooth")
        R.key(e["machine_lights"] + 2, lapR, "smooth")
        # relief: lean back + sip (left), right on the lap
        L.key(e["sip2_start"], mug_grab, "smooth").key(e["sip2_start"] + 4, sipL, "smooth").key(e["sip2_end"], sipL)
        L.key(e["sip2_end"] + 5, mug_grab, "smooth").key(e["roadmap_open"] - 2, lapL, "smooth")
        # roadmap: right hand on the trackpad, index finger flicking
        tp = self.world_hand("R", self.W["trackpad"] + V((0.03, -0.08, 0.03)), (-0.15, 1, -0.35), (0, 0, -1))
        R.key(e["roadmap_open"] - 4, tp, "smooth").key(e["print_end"] + 2, tp)
        # looks + reach for coffee, frozen by ROADMAP OBSOLETE
        reach = self.world_hand("L", self.W["mug"] + V((-0.09, -0.06, 0.10)), (0.6, 0.8, -0.2), (0.7, 0.2, -0.6))
        L.key(e["reach_coffee"], lapL).key(e["notif_obsolete"], reach, "out").key(e["empty_face"] + 12, reach)
        R.key(e["empty_face"] + 12, tp)
        # ---- Act IV ----
        lid0 = self.world_hand("R", self.W["lid_top"] + V((0.0, -0.06, 0.02)), (0, 0.6, -0.8), (0, 0.4, -0.9))
        lid1 = self.world_hand("R", V((0.03, 1.22, 0.82)), (0, 1, -0.3), (0, 0, -1))
        R.key(e["close_laptop"], lid0, "smooth").key(e["close_laptop"] + 6, lid1, "in")
        L.key(e["close_laptop"] + 2, lapL, "smooth")
        push_L = self.world_hand("L", V((-0.12, 1.10, 0.77)), (0, 1, -0.3), (0, 0, -1))
        push_R = self.world_hand("R", V((0.22, 1.10, 0.77)), (0, 1, -0.3), (0, 0, -1))
        L.key(e["stand_start"], push_L, "smooth")
        R.key(e["stand_start"], push_R, "smooth")
        hangL = self.char_hand("L", (0.25, -0.02, 0.80), (0.02, -0.15, -1), (-1, 0, 0), V((0.5, 0.6, 1.0)))
        hangR = self.char_hand("R", (-0.25, -0.02, 0.80), (-0.02, -0.15, -1), (1, 0, 0), V((-0.5, 0.6, 1.0)))
        upL = self.char_hand("L", (0.16, 0.05, 1.98), (-0.2, 0.1, 1), (-0.3, -1, 0), V((1, 0.2, 1.4)))
        upR = self.char_hand("R", (-0.16, 0.05, 1.98), (0.2, 0.1, 1), (0.3, -1, 0), V((-1, 0.2, 1.4)))
        L.key(e["stand_end"], hangL, "smooth").key(e["stretch_start"] + 3, upL, "smooth").key(e["stretch_end"] - 2, upL).key(e["stretch_end"] + 4, hangL, "smooth")
        R.key(e["stand_end"], hangR, "smooth").key(e["stretch_start"] + 3, upR, "smooth").key(e["stretch_end"] - 2, upR).key(e["stretch_end"] + 4, hangR, "smooth")

        def swing(side, base, k):
            def spec(f):
                b = base(f)
                ph = (f - E["walk_start"]) / 10.0 * 2 * math.pi
                amt = win(f, E["walk_start"], E["walk_end"], 3)
                return (b[0] + V((0, -0.12 * math.sin(ph) * k * amt, 0.02 * amt)),) + b[1:]
            return spec
        L.key(e["walk_start"], swing("L", hangL, 1), "smooth").key(e["walk_end"] + 2, swing("L", hangL, 1))
        R.key(e["walk_start"], swing("R", hangR, -1), "smooth").key(e["walk_end"] + 2, swing("R", hangR, -1))
        handle = self.world_hand("R", self.W["door_handle"] + V((-0.07, 0.02, -0.01)), (1, -0.05, -0.15), (0, 0.2, -1), V((-0.5, 0.5, 0.6)))
        R.key(e["handle_turn"] - 7, handle, "smooth").key(e["handle_turn"] + 1, handle)
        # startle as the walls go
        guardL = self.char_hand("L", (0.18, -0.20, 1.25), (0, -0.3, 1), (0, -1, 0), V((0.6, 0.3, 0.8)))
        guardR = self.char_hand("R", (-0.18, -0.20, 1.25), (0, -0.3, 1), (0, -1, 0), V((-0.6, 0.3, 0.8)))
        L.key(e["walls_fall_start"] + 4, guardL, "out").key(e["walls_land"] + 6, guardL).key(e["walls_land"] + 18, hangL, "smooth")
        R.key(e["walls_fall_start"] + 4, guardR, "out").key(e["walls_land"] + 6, guardR).key(e["walls_land"] + 18, hangR, "smooth")
        # proud: hands on hips
        hipL = self.char_hand("L", (0.215, 0.03, 0.98), (-0.3, 0.4, -0.6), (-1, 0.2, 0.2), V((0.8, 0.4, 1.1)))
        hipR = self.char_hand("R", (-0.215, 0.03, 0.98), (0.3, 0.4, -0.6), (1, 0.2, 0.2), V((-0.8, 0.4, 1.1)))
        L.key(e["proud_start"] - 4, hangL).key(e["proud_start"] + 3, hipL, "back").key(e["display_flip"] + 1, hipL)
        R.key(e["proud_start"] - 4, hangR).key(e["proud_start"] + 3, hipR, "back").key(e["display_flip"] + 1, hipR)
        # yanked: arms fly forward, then hands slam onto the keyboard (laptop reopened)
        flL = self.char_hand("L", (0.30, -0.35, 1.45), (0.3, -0.3, 1), (0, -1, 0), V((0.6, 0.3, 1.2)))
        flR = self.char_hand("R", (-0.30, -0.35, 1.45), (-0.3, -0.3, 1), (0, -1, 0), V((-0.6, 0.3, 1.2)))
        L.key(e["yank"] + 2, flL, "out").key(e["yank"] + 7, kbL, "smooth").key(720, kbL)
        R.key(e["yank"] + 2, flR, "out").key(e["yank"] + 7, kbR, "smooth").key(720, kbR)
        self.L, self.R = L, R

        # ---- attention (look targets, world space) ----
        A = SpecTrack()
        Wp = self.W
        def at(p):
            return lambda f, p=p: (V(p),)
        def cam(f):
            c = self.cam_pos.get(f)
            return (V(c) if c is not None else V((0.03, 1.42, 1.02)),)
        page = at(Wp["notebook_page"])
        A.key(1, page).key(e["underline1_end"] + 4, page)
        A.key(e["smile_start"], cam, "smooth").key(e["notif1"] + 1, cam)
        A.key(e["glance1"] + 3, at(Wp["laptop_screen"]), "out").key(e["smile_fade_end"], at(Wp["laptop_screen"]))
        A.key(e["write2_start"] - 3, page, "smooth").key(e["write2_end"] + 2, page)
        A.key(e["typing_start"], at(Wp["laptop_screen"]), "smooth")
        # head snaps between the screens, accelerating
        targets = [Wp["monitor_screen"], Wp["laptop_screen"]]
        for i, sf in enumerate(e["snaps"]):
            A.key(sf - 1, at(targets[(i + 1) % 2]))
            A.key(sf + 1, at(targets[i % 2]), "out")
        A.key(e["snaps"][-1] + 3, at(Wp["laptop_screen"]), "out")
        A.key(e["tutorial_2x"], at(Wp["laptop_screen"]))
        A.key(e["nod_start"], cam, "smooth").key(e["nod_end"], cam)
        A.key(e["notif_do_that"], at(Wp["laptop_screen"]), "smooth")
        A.key(e["look_code1"] - 1, at(Wp["laptop_screen"])).key(e["look_code1"] + 4, at(Wp["monitor_screen"]), "smooth")
        A.key(e["look_notif"] - 1, at(Wp["monitor_screen"])).key(e["look_notif"] + 4, at(Wp["laptop_screen"]), "smooth")
        A.key(e["look_code2"] - 1, at(Wp["laptop_screen"])).key(e["look_code2"] + 4, at(Wp["monitor_screen"]), "smooth")
        A.key(e["notif_better"] - 1, at(Wp["monitor_screen"])).key(e["notif_better"] + 2, cam, "out")
        A.key(e["idea"] + 2, at(Wp["machine"] + V((0.1, 0.3, 0.3))), "smooth").key(e["build_start"], at(Wp["machine"]), "smooth")
        A.key(e["button_press"] + 6, at(Wp["machine"])).key(e["lean_back"] + 6, at(Wp["laptop_screen"] + V((0, 0, 0.1))), "smooth")
        A.key(e["sip2_start"] + 3, at(Wp["laptop_screen"] + V((0, 0, 0.15))))
        A.key(e["roadmap_open"], at(Wp["laptop_screen"]), "smooth").key(e["print_start"] - 2, at(Wp["laptop_screen"]))
        A.key(e["print_start"] + 6, at(Wp["machine"] + V((0, -0.2, -0.1))), "smooth").key(e["print_end"], at(Wp["floor_scroll"]), "smooth")
        A.key(e["look_scroll"], at(V((-0.5, 0.0, 0.0))), "out").key(e["look_machine"] - 1, at(V((-0.5, 0.0, 0.0))))
        A.key(e["look_machine"] + 1, at(Wp["machine"]), "out").key(e["look_audience"] - 1, at(Wp["machine"]))
        A.key(e["look_audience"] + 1, cam, "out").key(e["reach_coffee"], cam)
        A.key(e["notif_obsolete"] - 2, at(Wp["mug"]), "smooth").key(e["notif_obsolete"] + 2, at(Wp["laptop_screen"]), "out")
        A.key(e["close_laptop"] - 2, at(Wp["laptop_screen"]))
        A.key(e["stand_start"], at(V((1.0, -0.6, 1.5))), "smooth")
        A.key(e["walk_start"] + 2, at(V((2.0, -1.0, 1.4))), "smooth")
        A.key(e["walk_end"], at(V((2.2, -0.95, 1.55))), "smooth").key(e["handle_turn"], at(Wp["door_handle"] + V((0.3, 0, 0.4))), "smooth")
        A.key(e["walls_land"], at(V((3.0, -0.9, 2.0))))
        A.key(e["walls_land"] + 14, at(Wp["finish"]), "smooth").key(e["pa_start"], at(Wp["finish"]))
        A.key(e["pa_start"] + 8, at(V((1.5, 40, 14.0))), "smooth")
        A.key(e["realize"], at(Wp["finish"] + V((-20, 0, -3))), "smooth").key(e["proud_start"], at(Wp["display"] + V((0, 0, 2))), "smooth")
        A.key(e["display_flip"] + 2, at(Wp["display"]), "out")
        A.key(e["yank"] + 6, at(Wp["laptop_screen"]), "smooth")
        self.attention = A
        self._spine = {}

    # ---- body posture tracks (char-space eulers) ------------------------------
    def posture(self, f):
        e = E
        st = ch("stress", f)
        sp = ch("speed", f)
        lean = 0.08 + 0.10 * st
        hips_off = SEAT_HIPS.copy()
        hips_rot = [0.0, 0.0, 0.0]
        spine = [lean, 0.0, 0.0]
        chest = [0.10 + 0.06 * st, 0.0, 0.0]
        # Act I: upright, confident; the sip leans back a touch
        conf = win(f, 1, e["notif1"], 6)
        spine[0] -= 0.06 * conf
        chest[0] -= 0.08 * conf
        # Act II: hunched in, shoulders up with speed
        hunch = clamp((sp - 0.3) / 0.6) * win(f, e["typing_start"], e["notif_better"], 6)
        spine[0] += 0.10 * hunch
        chest[0] += 0.10 * hunch
        # the scream: rear back
        scr = win(f, e["scream_start"], e["scream_end"], 3)
        spine[0] -= 0.25 * scr
        chest[0] -= 0.15 * scr
        # Act III: lean in to build, slam, then lean back in relief
        build = win(f, e["build_start"], e["build_end"], 4)
        spine[0] += 0.10 * build
        slam = win(f, e["button_press"] - 5, e["button_press"] + 2, 3)
        spine[0] += 0.18 * slam
        chest[1] += 0.18 * slam
        relax = win(f, e["lean_back"], e["roadmap_open"] - 4, 6)
        hips_off += V((0, 0.06, -0.02)) * relax
        hips_rot[0] -= 0.12 * relax
        spine[0] -= 0.22 * relax
        chest[0] -= 0.12 * relax
        # Act IV: stand, stretch, walk, proud, yank
        stand = U.ease(clamp((f - e["stand_start"]) / (e["stand_end"] - e["stand_start"])), "smooth")
        unstand = U.ease(clamp((f - e["yank"]) / 4.0), "in")
        standing = stand * (1 - unstand)
        hips_off = hips_off.lerp(V((0, 0, 0.0)), standing)
        lean_stand = win(f, e["stand_start"] + 1, e["stand_start"] + 5, 2)
        spine[0] = spine[0] * (1 - standing) + 0.02 * standing + 0.35 * lean_stand
        chest[0] = chest[0] * (1 - standing) + 0.02 * standing
        stretch = win(f, e["stretch_start"] + 2, e["stretch_end"] - 2, 3)
        spine[0] -= 0.16 * stretch
        chest[0] -= 0.14 * stretch
        walk = win(f, e["walk_start"], e["walk_end"], 2)
        ph = (f - e["walk_start"]) / 10.0 * 2 * math.pi
        hips_off += V((0, 0, 0.018 * abs(math.sin(ph)) - 0.01)) * walk
        hips_rot[1] += 0.08 * math.sin(ph) * walk
        chest[1] -= 0.10 * math.sin(ph) * walk
        breath = win(f, e["breath"], e["breath"] + 6, 3)
        chest[0] -= 0.08 * breath
        startle = win(f, e["walls_fall_start"] + 2, e["walls_land"] + 4, 3)
        spine[0] += 0.12 * startle
        proud = win(f, e["proud_start"], e["display_flip"], 3)
        chest[0] -= 0.18 * proud
        spine[0] -= 0.06 * proud
        # after the yank: hunched, defeated, frantic
        defeat = clamp((f - e["yank"] - 4) / 4.0) if f < e["black"] else 0
        spine[0] += 0.12 * defeat
        chest[0] += 0.14 * defeat
        # breathing everywhere
        chest[0] += 0.012 * math.sin(f / 24.0 * 2 * math.pi * (0.25 + 0.6 * sp))
        return hips_off, hips_rot, spine, chest, standing

    def head_aim(self, f, D_chest_world, M):
        """Returns (neck, head) eulers + eye target world point."""
        tgt = self.attention(f)[0]
        head_pos = M @ (D_chest_world @ V((0, 0.0, 0.32)))
        d_world = (tgt - head_pos)
        d = (M.to_3x3().inverted() @ d_world).normalized()       # char space
        # char faces -Y: yaw positive turns toward +X(left)
        yaw = math.atan2(d.x, -d.y)
        pitch = math.atan2(-d.z, math.hypot(d.x, d.y))
        return yaw, pitch, tgt

    def spine_cache(self, f):
        if f in self._spine:
            return self._spine[f]
        P_ = self.pose(f, spine_only=True)
        D = self.solver.solve(P_)
        self._spine[f] = D
        return D

    def pose(self, f, spine_only=False):
        e = E
        M = self.path.matrix(f)
        hips_off, hips_rot, spine, chest, standing = self.posture(f)
        Pz = dict(hips=(hips_off, tuple(hips_rot)), spine=tuple(spine), chest=tuple(chest))
        # head aim: approximate chest frame from posture (use solver for accuracy)
        Dtmp = self.solver.solve(dict(Pz, neck=(0, 0, 0), head=(0, 0, 0)))
        yaw, pitch, _ = self.head_aim(f, Dtmp["chest"], M)
        yaw = max(-1.2, min(1.2, yaw))
        pitch = max(-0.7, min(0.9, pitch))
        # head takes ~75% of the turn, neck the rest
        neck = [pitch * 0.25 - 0.04, yaw * 0.3, 0.0]
        head = [pitch * 0.55, yaw * 0.55, 0.0]
        # procedural: nodding, the scream recoil, proud chin, defeated droop
        nod = win(f, e["nod_start"], e["nod_end"], 2)
        head[0] += 0.22 * math.sin((f - e["nod_start"]) * 2 * math.pi / 3.2) * nod
        idea = win(f, e["idea"], e["idea"] + 5, 2)
        head[0] -= 0.12 * idea
        scr = win(f, e["scream_start"], e["scream_end"], 2)
        head[0] -= 0.25 * scr
        head[2] += 0.04 * math.sin(f * 2.7) * scr
        proud = win(f, e["proud_start"], e["display_flip"], 3)
        head[0] -= 0.15 * proud
        empty = win(f, e["empty_face"], e["close_laptop"] - 2, 3)
        head[2] += 0.06 * empty
        defeat = clamp((f - e["defeat"]) / 4.0) if f < e["black"] else 0
        head[0] += 0.12 * defeat
        Pz.update(neck=tuple(neck), head=tuple(head))
        shrug = 0.12 * win(f, e["breath"], e["breath"] + 5, 2) + 0.10 * win(f, e["scream_start"], e["scream_end"], 2) \
            + 0.08 * clamp((ch("speed", f) - 0.5) * 2) * win(f, e["typing_start"], e["typing_stop"], 5)
        Pz["clav.L"] = (0, 0, -shrug)
        Pz["clav.R"] = (0, 0, shrug)
        if spine_only:
            return Pz
        # arms
        for side, track in (("L", self.L), ("R", self.R)):
            w, fd, pa, pole = track(f)
            Pz[f"arm.{side}"] = dict(wrist=V(w), pole=V(pole), fdir=V(fd), palm=V(pa))
        # typing layer
        self.typing_layer(f, Pz)
        # fingers: base curls per activity
        self.finger_layer(f, Pz)
        # legs
        self.leg_layer(f, Pz, standing, M)
        return Pz

    def typing_layer(self, f, Pz):
        act = ch("typing_active", f)
        if act <= 0:
            return
        ph = ch("typing_phase", f)
        for side, k, off in (("L", 1, 0.0), ("R", -1, 0.37)):
            a = Pz[f"arm.{side}"]
            tap = max(0.0, math.sin(2 * math.pi * (ph * 0.5 + off))) ** 3
            shuffle = U.noise1(ph * 0.35 + off * 10, 4 if side == "L" else 9)
            a["wrist"] = a["wrist"] + V((0.018 * shuffle * k, 0.010 * U.noise1(ph * 0.5, 2), 0.010 * tap))

    def finger_layer(self, f, Pz):
        e = E
        ph = ch("typing_phase", f)
        act = ch("typing_active", f)
        for side in ("L", "R"):
            fl = {"index": [0.35, 0.3], "middle": [0.4, 0.3], "ring": [0.45, 0.35], "pinky": [0.5, 0.35], "thumb": [0.2, 0.1]}
            if act > 0:
                for i, nm in enumerate(("index", "middle", "ring", "pinky")):
                    tap = max(0.0, math.sin(2 * math.pi * (ph * (0.9 + 0.13 * i) + i * 0.31 + (0.5 if side == "R" else 0)))) ** 4
                    fl[nm][0] += 0.55 * tap
                    fl[nm][1] += 0.45 * tap
            grip = 0.0
            if side == "L":
                grip = max(win(f, e["sip1_start"] + 2, e["sip1_end"], 2), win(f, e["sip2_start"], e["sip2_end"] + 5, 2))
            if side == "R":
                grip = max(win(f, 1, e["underline1_end"] + 6, 2), win(f, e["write2_start"] - 4, e["write2_end"] + 2, 2)) * 0.8
                if win(f, e["handle_turn"] - 4, e["handle_turn"] + 1, 2):
                    grip = max(grip, 0.9)
            fist = win(f, e["scream_start"], e["scream_end"], 2) * 0.0 + win(f, e["proud_start"], e["display_flip"], 3) * 0.6
            for nm in ("index", "middle", "ring", "pinky"):
                fl[nm][0] += 0.9 * grip + 0.6 * fist
                fl[nm][1] += 0.9 * grip + 0.8 * fist
            fl["thumb"][0] += 0.5 * grip
            # trackpad flick: right index extended, others curled
            if side == "R":
                pad = win(f, e["roadmap_open"], e["print_end"], 3)
                if pad:
                    fl["index"] = [0.15 + 0.35 * max(0, math.sin(f * 1.6)) * win(f, e["scroll_start"], e["print_start"], 2), 0.1]
                    for nm in ("middle", "ring", "pinky"):
                        fl[nm] = [fl[nm][0] * (1 - pad) + 1.2 * pad, fl[nm][1] * (1 - pad) + 1.1 * pad]
            # stretch: fingers splay open
            spl = win(f, e["stretch_start"] + 3, e["stretch_end"] - 2, 2) + win(f, e["scream_start"], e["scream_end"], 2)
            for nm in fl:
                fl[nm] = [fl[nm][0] * (1 - min(1, spl)) - 0.1 * spl, fl[nm][1] * (1 - min(1, spl))]
            Pz[f"fingers.{side}"] = {k: tuple(v) for k, v in fl.items()}

    def leg_layer(self, f, Pz, standing, M):
        e = E
        seated = seated_legs()
        ph = (f - e["walk_start"]) / 10.0 * 2 * math.pi
        walk = win(f, e["walk_start"], e["walk_end"], 1)
        for side, k in (("L", 1), ("R", -1)):
            sl = seated[f"leg.{side}"]
            stand_ankle = V((0.11 * k, -0.01, 0.085))
            ank = sl["ankle"].lerp(stand_ankle, standing)
            toe = sl["toe"].lerp(V((0.06 * k, -1, -0.25)), standing)
            if walk > 0:
                s_ = math.sin(ph + (0 if side == "L" else math.pi))
                ank = ank + V((0, -0.18 * s_, 0.07 * max(0.0, math.cos(ph + (0 if side == "L" else math.pi))))) * walk
            # nervous heel bounce while frantic
            if side == "R":
                nerv = clamp((ch("speed", f) - 0.4) * 2) * win(f, e["typing_start"] + 10, e["typing_stop"], 5) * (1 - standing)
                ank = ank + V((0, 0, 0.02 * max(0.0, math.sin(f * 1.9)))) * nerv
            pole = sl["pole"].lerp(V((0.1 * k, -1, 0.3)), standing)
            Pz[f"leg.{side}"] = dict(ankle=ank, pole=pole, toe=toe)

    # ---- face ------------------------------------------------------------------
    def face(self, f):
        e = E
        st = ch("stress", f)
        m = {k: 0.0 for k in ("Smile", "Grin", "Weak", "Frown", "Scream", "O", "Flat", "Proud")}

        def setk(**kw):
            for k, v in kw.items():
                m[k] = v
        # mouth by beat (soft cross-fades with win())
        segs = [
            (1, e["smile_start"] - 1, dict(Smile=0.35)),
            (e["smile_start"], e["sip1_start"] + 1, dict(Proud=0.9, Smile=0.3)),
            (e["sip1_start"] + 2, e["sip1_end"] - 2, dict(O=0.55)),
            (e["sip1_end"] - 1, e["smile_fade_start"], dict(Smile=0.85)),
            (e["smile_fade_start"] + 1, e["smile_fade_end"], dict(Weak=1.0)),
            (e["smile_fade_end"] + 1, e["typing_start"], dict(Flat=0.9)),
            (e["typing_start"] + 1, e["nod_start"] - 1, dict(Flat=0.7, Frown=0.15)),
            (e["nod_start"], e["nod_end"], dict(Grin=0.75)),
            (e["nod_end"] + 1, e["notif_do_that"] + 2, dict(Flat=0.7)),
            (e["notif_do_that"] + 3, e["notif_better"] - 1, dict(Flat=1.0, Frown=0.25)),
            (e["scream_start"], e["scream_end"], dict(Scream=1.0)),
            (e["idea"], e["build_start"], dict(Grin=0.8)),
            (e["build_start"] + 1, e["button_press"] - 1, dict(Flat=0.5, Grin=0.3)),
            (e["button_press"], e["lean_back"], dict(Grin=1.0)),
            (e["lean_back"] + 1, e["sip2_start"] + 1, dict(Smile=1.0)),
            (e["sip2_start"] + 2, e["sip2_end"], dict(O=0.5, Smile=0.3)),
            (e["sip2_end"] + 1, e["roadmap_open"] + 6, dict(Smile=0.9)),
            (e["roadmap_open"] + 7, e["print_start"], dict(Weak=0.9)),
            (e["print_start"] + 1, e["look_scroll"], dict(O=0.35, Weak=0.4)),
            (e["look_scroll"] + 1, e["notif_obsolete"] - 1, dict(Flat=0.9)),
            (e["notif_obsolete"], e["close_laptop"] - 1, dict(Flat=1.0)),
            (e["close_laptop"], e["stretch_start"], dict(Flat=0.5, Smile=0.2)),
            (e["stretch_start"] + 2, e["stretch_end"] - 2, dict(O=1.0)),     # yawn
            (e["stretch_end"] - 1, e["breath"] - 1, dict(Smile=0.5)),
            (e["breath"], e["whisper_start"] - 1, dict(O=0.25, Smile=0.4)),
            (e["whisper_start"], e["whisper_end"], dict(Smile=0.7)),
            (e["whisper_end"] + 1, e["walls_fall_start"] + 1, dict(Smile=0.8)),
            (e["walls_fall_start"] + 2, e["realize"] - 1, dict(O=0.9)),
            (e["realize"], e["proud_start"] - 1, dict(Flat=0.8, Frown=0.4)),
            (e["proud_start"], e["display_flip"], dict(Proud=1.0)),
            (e["display_flip"] + 1, e["yank"] - 1, dict(Flat=0.9, O=0.2)),
            (e["yank"], e["yank"] + 5, dict(Scream=0.7)),
            (e["yank"] + 6, 720, dict(Frown=0.9, Weak=0.5)),
        ]
        for a, b, vals in segs:
            w = win(f, a, b, 2)
            if w:
                for k, v in vals.items():
                    m[k] = max(m[k], v * w)
        # whisper syllables: Fi-nal-ly. I'm caught up.
        if e["whisper_start"] <= f <= e["whisper_end"]:
            sy = (f - e["whisper_start"]) / 3.2
            m["O"] = max(m["O"], 0.35 * max(0.0, math.sin(sy * math.pi)))
        # eyelids: base openness falls with stress; shocks open wide; blinks
        open_ = 0.98 - 0.24 * st
        wide = max(win(f, e["notif3"], e["notif3"] + 6, 2), win(f, e["notif_better"], e["scream_end"], 2),
                   win(f, e["idea"], e["idea"] + 6, 2), win(f, e["walls_fall_start"], e["realize"], 3),
                   win(f, e["display_flip"], e["yank"] + 4, 2), win(f, e["notif_obsolete"], e["notif_obsolete"] + 3, 1))
        open_ = open_ + (1.12 - open_) * wide
        bliss = max(win(f, e["sip2_start"] + 3, e["sip2_end"] - 1, 2), win(f, e["stretch_start"] + 3, e["stretch_end"] - 2, 2),
                    win(f, e["breath"] + 1, e["breath"] + 4, 1))
        open_ *= (1 - 0.92 * bliss)
        empty = win(f, e["empty_face"], e["close_laptop"] - 3, 3)
        open_ = open_ * (1 - empty) + 0.55 * empty
        proud = win(f, e["proud_start"], e["display_flip"], 2)
        open_ = open_ * (1 - proud) + 0.6 * proud
        for bf in (20, 63, 101, 150, 196, 236, 288, 344, 384, 430, 468, 528, 556, 604, 625, 658):
            if bf <= f <= bf + 3:
                open_ *= (0.1, 0.0, 0.25, 0.7)[f - bf]
        # brows: (raise, tilt) tilt>0 = worried (inner up)
        raise_ = 0.0
        tilt = 0.0
        raise_ += 0.004 * win(f, e["smile_start"], e["sip1_start"], 3)
        tilt += 0.6 * win(f, e["smile_fade_start"], e["typing_start"], 4)
        raise_ -= 0.003 * win(f, e["typing_start"], e["typing_stop"], 4) * ch("speed", f)
        tilt -= 0.4 * win(f, e["typing_start"] + 20, e["nod_start"], 4)
        raise_ += 0.007 * wide
        tilt += 0.8 * win(f, e["notif_do_that"] + 4, e["notif_better"], 4)
        tilt += 1.0 * win(f, e["scream_start"], e["scream_end"], 2)
        raise_ += 0.006 * win(f, e["lean_back"], e["roadmap_open"], 4)
        tilt += 0.5 * win(f, e["roadmap_open"] + 8, e["look_audience"], 4)
        raise_ -= 0.002 * empty
        tilt += 0.3 * win(f, e["whisper_start"], e["walls_fall_start"], 4) * -1
        tilt += 0.9 * win(f, e["realize"], e["proud_start"] - 1, 2)
        raise_ += 0.005 * proud
        tilt -= 0.4 * proud
        tilt += 1.0 * clamp((f - e["defeat"]) / 4.0) * (1 if f < e["black"] else 0)
        hair_messy = clamp(st * 0.75)
        hair_blown = win(f, e["scream_start"] + 1, e["scream_end"], 2) * 0.9 + win(f, e["accelerate"], e["black"], 2) * 0.6
        return m, open_, raise_, tilt, hair_messy, hair_blown


# ---------------------------------------------------------------------------
# Baking the hero
# ---------------------------------------------------------------------------

def bake_hero(ctx, hero):
    ch_ = hero.ch
    rig = ch_.rig
    # rig placement in the world
    mats = [hero.path.matrix(f) for f in FRAMES]
    U.bake_vec(rig, "location", FRAMES, [tuple(Mx.translation - hero.path.station_offset(f)) for Mx, f in zip(mats, FRAMES)])
    rots = [hero.path.rot(f) for f in FRAMES]
    U.bake_vec(rig, "rotation_euler", FRAMES, [(0.0, 0.0, r) for r in rots])
    Ds = P.bake_pose_track(ch_, FRAMES, hero.pose)
    hero.Ds = Ds
    hero.mats = mats
    # face
    faces = [hero.face(f) for f in FRAMES]
    kb = ch_.mouth.data.shape_keys.key_blocks
    for name in ("Smile", "Grin", "Weak", "Frown", "Scream", "O", "Flat", "Proud"):
        _bake_key(ch_.mouth.data.shape_keys, name, [min(1.0, fc[0][name]) for fc in faces])
    hk = ch_.hair.data.shape_keys
    _bake_key(hk, "Messy", [fc[4] for fc in faces])
    _bake_key(hk, "Blown", [fc[5] for fc in faces])
    # eyes look at the attention target (both converge), lids follow pitch
    for side in ("L", "R"):
        eye = ch_.eyes[side]
        lid = ch_.lids[side]
        low = ch_.lowlids[side]
        brow = ch_.brows[side]
        er, lr_, lowr, bl, br_ = [], [], [], [], []
        base_brow = brow.location.copy()
        for i, f in enumerate(FRAMES):
            D = Ds[i]
            Mw = mats[i]
            head_w = Mw @ D["head"]
            eye_rest = eye.location            # rest-space centre
            eye_w = head_w @ hero.solver.Rinv["head"] @ eye_rest
            tgt = hero.attention(f)[0]
            # direction in the head's rest frame
            Hrot = (head_w @ hero.solver.Rinv["head"]).to_3x3()
            d = (Hrot.inverted() @ (tgt - eye_w)).normalized()
            yaw = math.atan2(d.x, -d.y)
            pitch = math.atan2(-d.z, math.hypot(d.x, d.y))
            yaw = max(-0.6, min(0.6, yaw))
            pitch = max(-0.45, min(0.5, pitch))
            # micro saccades
            yaw += 0.02 * U.noise1(f * 0.4, 31 if side == "L" else 31)
            er.append((pitch, 0.0, yaw))
            m, open_, raise_, tilt, _, _ = faces[i]
            # rim elevation in degrees: open ~40, closed -90; follows pitch
            rim = -90 + (40 + 90) * clamp(open_, 0, 1.15) - math.degrees(pitch) * 0.6
            lr_.append((math.radians(-rim), 0.0, 0.0))
            squint = m["Smile"] * 0.5 + m["Grin"] * 0.6 + m["Proud"] * 0.4
            lowr.append((math.radians(55 - 18 * squint), 0.0, 0.0))
            k = 1 if side == "L" else -1
            bl.append(tuple(base_brow + V((0, 0, raise_ + 0.004 * tilt * 0.3))))
            br_.append((0.0, -0.35 * tilt * k, 0.0))
        U.bake_vec(eye, "rotation_euler", FRAMES, er)
        U.bake_vec(lid, "rotation_euler", FRAMES, lr_)
        U.bake_vec(low, "rotation_euler", FRAMES, lowr)
        U.bake_vec(brow, "location", FRAMES, bl)
        U.bake_vec(brow, "rotation_euler", FRAMES, br_)


def _bake_key(shape_keys, name, values):
    U.bake(shape_keys, f'key_blocks["{name}"].value', 0, FRAMES, values)


def hand_world(hero, i, side):
    return hero.mats[i] @ hero.Ds[i][f"hand.{side}"]


def head_world(hero, i):
    return hero.mats[i] @ hero.Ds[i]["head"]


# ---------------------------------------------------------------------------
# Props
# ---------------------------------------------------------------------------

def bake_props(ctx, hero):
    R = ctx.room
    e = E
    # pen: in the right hand while writing, otherwise resting on the notebook
    pen = R.pen
    bpy.context.view_layer.update()
    rest_pen = Matrix.Translation(hero.W["notebook_page"] + V((0.12, -0.10, 0.012))) @ Matrix.Rotation(math.radians(80), 4, 'Y') @ Matrix.Rotation(0.3, 4, 'X')
    locs, rots = [], []
    grip = Matrix.Translation((0.018, 0.045, 0.006)) @ Euler((math.radians(-60), 0, math.radians(8))).to_matrix().to_4x4()
    prev = None
    for i, f in enumerate(FRAMES):
        holding = (f <= e["underline1_end"] + 8) or (e["write2_start"] - 6 <= f <= e["write2_end"] + 3)
        if holding:
            # tip on the page where the ink is, shaft running up into the grip
            tip = hero.pen_tip_world(f)
            Hm = hand_world(hero, i, "R")
            grip_pt = Hm @ V((-0.016, 0.075, 0.026))
            axis = (grip_pt - tip).normalized()
            rot = axis.to_track_quat('Z', 'Y').to_matrix().to_4x4()
            Mx = Matrix.Translation(tip + axis * 0.012) @ rot
        else:
            Mx = rest_pen
        l, q, _ = Mx.decompose()
        e_ = q.to_euler('XYZ', prev) if prev else q.to_euler('XYZ')
        prev = e_
        locs.append(tuple(l)); rots.append(tuple(e_))
    U.bake_vec(pen, "location", FRAMES, locs)
    U.bake_vec(pen, "rotation_euler", FRAMES, rots)
    # hero mug: follows the left hand during sips (grab offset captured at grab time)
    mug = R.mug
    mug_rest = mug.matrix_world.copy()
    locs, rots = [], []
    holds = [(e["sip1_start"] + 2, e["sip1_end"]), (e["sip2_start"], e["sip2_end"] + 5)]
    offsets = {}
    prev = None
    cur = mug_rest
    for i, f in enumerate(FRAMES):
        Mx = mug_rest
        for a, b in holds:
            if a <= f <= b:
                if a not in offsets:
                    ia = FRAMES.index(a)
                    offsets[a] = hand_world(hero, ia, "L").inverted() @ mug_rest
                Mx = hand_world(hero, i, "L") @ offsets[a]
        l, q, _ = Mx.decompose()
        e_ = q.to_euler('XYZ', prev) if prev else q.to_euler('XYZ')
        prev = e_
        locs.append(tuple(l)); rots.append(tuple(e_))
    U.bake_vec(mug, "location", FRAMES, locs)
    U.bake_vec(mug, "rotation_euler", FRAMES, rots)
    # laptop lid: open, closes at close_laptop, reopens when he is yanked back
    lid = R.laptop_hinge
    tr = U.Track()
    tr.key(1, -18.0).key(e["close_laptop"] + 1, -18.0).key(e["close_laptop"] + 6, 88.0, "in")
    tr.key(e["yank"] + 5, 88.0).key(e["yank"] + 7, -18.0, "out")
    U.bake(lid, "rotation_euler", 0, FRAMES, [math.radians(tr(f)) for f in FRAMES])
    # chair: rolls back when he stands, chases him in the yank
    chair = R.chair
    c0 = V(chair.location)
    ct = U.Track().key(1, tuple(c0)).key(e["stand_start"], tuple(c0)).key(e["stand_end"] + 4, tuple(c0 + V((0.12, -0.22, 0))), "out")
    door = RigPath.DOOR[0]
    ct.key(e["yank"] - 2, tuple(c0 + V((0.12, -0.22, 0))))
    ct.key(e["yank"], tuple(door + V((0, 0.18, 0))), "in")
    ct.key(e["yank"] + 5, tuple(c0), "in")
    crt = U.Track().key(1, 0.0).key(e["stand_end"] + 4, 0.35, "out").key(e["yank"] - 2, 0.35).key(e["yank"], -1.2, "in").key(e["yank"] + 5, 0.0, "in")
    U.bake_vec(chair, "location", FRAMES, [ct(f) for f in FRAMES])
    U.bake(chair, "rotation_euler", 2, FRAMES, [crt(f) for f in FRAMES])
    # spawned clutter: books, cups, papers (from the speed system's spawners)
    spawn_clutter(ctx, hero)


def spawn_clutter(ctx, hero):
    R = ctx.room
    col = ctx.cols["Props"]
    rng = random.Random(77)
    top = R.top
    stacks = [V((0.86, 1.36, top)), V((-0.55, 0.92, 0.0)), V((0.62, 0.70, 0.0))]
    heights = [0.0] * len(stacks)
    from . import bl_util as UU
    for ev in CH["events"]["books"]:
        k = int(ev["r1"] * len(stacks)) % len(stacks)
        w, d, h = 0.16 + 0.08 * ev["r2"], 0.22 + 0.06 * ev["r3"], 0.025 + 0.03 * ev["r2"]
        b = UU.mesh_object(f"Book_Spawn_{ev['i']:02d}", UU.bm_rounded_box((w, d, h), 0.003, 1, (0, 0, h / 2)), col, R.book_material, smooth=False)
        land = ev["frame"] + T.SPAWN_LAND_OFFSET["books"]
        base = stacks[k] + V((0, 0, heights[k]))
        heights[k] += h
        rz = (ev["r3"] - 0.5) * 0.6
        start = base + V((0.05 * (ev["r1"] - 0.5), -0.1, 0.9))
        tr = U.Track().key(ev["frame"], tuple(start)).key(land, tuple(base), "in")
        sq = U.Track().key(1, 0.0).key(ev["frame"] - 1, 0.0).key(ev["frame"], 1.0, "step")
        locs = [tr(f) for f in FRAMES]
        U.bake_vec(b, "location", FRAMES, locs)
        U.bake_vec(b, "rotation_euler", FRAMES, [(0, 0, rz + (1 - min(1, max(0, (f - ev["frame"]) / 5))) * 1.5) for f in FRAMES])
        # squash on landing
        scl = []
        for f in FRAMES:
            if f < ev["frame"]:
                scl.append((0, 0, 0))
            else:
                t = f - land
                s = 1.0 + (0.25 * math.exp(-t / 1.5) * math.cos(t * 1.6) if t >= 0 else 0.0)
                scl.append((1 / s ** 0.5, 1 / s ** 0.5, s if t >= 0 else 1.05))
        U.bake_vec(b, "scale", FRAMES, scl)
    cup_spots = [V((0.74, 1.10, top)), V((-0.12, 1.12, top)), V((0.96, 1.18, top)), V((0.30, 1.70, top)),
                 V((-0.05, 1.66, top)), V((0.72, 1.40, top)), V((0.85, 1.55, top))]
    cup_mat = __import__("skill_issue.materials", fromlist=["x"]).random_color_material(
        "MAT_Cups", [(0.7, 0.68, 0.62, 1), (0.1, 0.25, 0.45, 1), (0.55, 0.1, 0.06, 1), (0.12, 0.12, 0.13, 1), (0.6, 0.5, 0.1, 1)], 0.3)
    from .room import _mug
    for ev, spot in zip(CH["events"]["cups"], cup_spots):
        m = _mug(f"Cup_Spawn_{ev['i']:02d}", col, cup_mat)
        m.location = spot
        m.rotation_euler = (0, 0, ev["r1"] * 6.28)
        a = ev["frame"]
        scl = []
        for f in FRAMES:
            t = f - a
            if t < 0:
                scl.append((0, 0, 0))
            else:
                s = 1.0 + 0.35 * math.exp(-t / 2.0) * math.cos(t * 1.4) - (0.35 if t == 0 else 0)
                scl.append((s, s, 1 / max(0.5, s)))
        U.bake_vec(m, "scale", FRAMES, scl)
    # papers slide in from the right edge of the desk
    from .room import _plane
    pm = __import__("skill_issue.materials", fromlist=["x"]).roadmap_paper()
    for ev in CH["events"]["papers"]:
        p = _plane(f"Paper_Spawn_{ev['i']:02d}", col, 0.21, 0.297, pm)
        end = V((0.30 + 0.5 * ev["r1"], 1.12 + 0.35 * ev["r2"], top + 0.002 + 0.0015 * ev["i"]))
        start = end + V((0.9, -0.1, 0.01))
        tr = U.Track().key(ev["frame"], tuple(start)).key(ev["frame"] + 6, tuple(end), "expo_out")
        U.bake_vec(p, "location", FRAMES, [tr(f) for f in FRAMES])
        rz0, rz1 = 1.2, (ev["r3"] - 0.5) * 0.9
        rt = U.Track().key(ev["frame"], rz0).key(ev["frame"] + 6, rz1, "expo_out")
        U.bake(p, "rotation_euler", 2, FRAMES, [rt(f) for f in FRAMES])
        U.bake_vec(p, "scale", FRAMES, [(0, 0, 0) if f < ev["frame"] else (1, 1, 1) for f in FRAMES], 'CONSTANT')


# ---------------------------------------------------------------------------
# The machine
# ---------------------------------------------------------------------------

def bake_machine(ctx):
    mc = ctx.machine
    e = E
    rng = random.Random(5)
    for k, part in enumerate(mc.parts):
        land = e["machine_parts"][k]
        loc1, rot1 = mc.final[part.name]
        d = V((rng.uniform(-1, 1), rng.uniform(-1, 0.2), rng.uniform(0.6, 1.2))).normalized() * 0.55
        loc0 = loc1 + d
        tr = U.Track().key(land - 6, tuple(loc0)).key(land, tuple(loc1), "back")
        U.bake_vec(part, "location", FRAMES, [tr(f) for f in FRAMES])
        spin = rng.uniform(-3, 3)
        U.bake_vec(part, "rotation_euler", FRAMES,
                   [(rot1.x + spin * (1 - U.ease(clamp((f - land + 6) / 6), "out")), rot1.y, rot1.z + spin * 0.5 * (1 - U.ease(clamp((f - land + 6) / 6), "out"))) for f in FRAMES])
        scl = []
        for f in FRAMES:
            t = f - land
            if f < land - 6:
                scl.append((0, 0, 0))
            elif t < 0:
                scl.append((1, 1, 1))
            else:
                s = 1 + 0.18 * math.exp(-t / 1.5) * math.cos(t * 2.0)
                scl.append((1 / s ** 0.5, 1 / s ** 0.5, s))
        U.bake_vec(part, "scale", FRAMES, scl)
    on = e["machine_lights"]
    # displays wake in sequence; core glow; light; spin
    for i, mat in enumerate(mc.displays):
        _bake_node_value(mat, "Power", [clamp((f - on - 2 * i) / 3.0) * (1.0 + 0.5 * win(f, e["button_press"], e["button_press"] + 4, 1)) for f in FRAMES])
        _bake_node_input(mat, "Scroll", "Location", 1, [-(f - on) * 0.05 * (1 + 3 * ch("speed", f)) for f in FRAMES])
    core = bpy.data.materials["MAT_CoreGlow"]
    core_v = []
    for f in FRAMES:
        base = 6.0 * U.ease(clamp((f - on) / 8.0), "smooth")
        flash = 30.0 * math.exp(-max(0, f - e["button_press"]) / 3.0) if f >= e["button_press"] else 0.0
        pulse = 1.0 + 0.25 * math.sin(ch("beat_phase", f) * 2 * math.pi)
        dead = 1.0 - 0.85 * win(f, e["notif_obsolete"], 720, 2)
        core_v.append((base * pulse + flash) * dead)
    _bake_emission(core, core_v)
    _bake_emission(bpy.data.materials["MAT_DataBead"], [8.0 * U.ease(clamp((f - on - 2) / 4.0)) for f in FRAMES])
    _bake_emission(bpy.data.materials["MAT_AntennaTip"], [(10.0 if (f // 6) % 2 == 0 else 1.0) * clamp((f - on) / 2) for f in FRAMES])
    U.bake(mc.glow.data, "energy", 0, FRAMES, [v * 0.25 for v in core_v])
    # rings + fan spin with speed; beads travel along the tubes
    ang = 0.0
    a_ring, a_fan = [], []
    for f in FRAMES:
        if f >= on:
            ang += 0.05 + 0.5 * ch("speed", f) + (0.3 if e["button_press"] <= f < e["notif_obsolete"] else 0)
        a_ring.append(ang)
        a_fan.append(ang * 3.0)
    for i, ring in enumerate(mc.rings):
        base = ring.rotation_euler.copy()
        U.bake_vec(ring, "rotation_euler", FRAMES, [(base.x, base.y + a * (1.0 if i == 0 else -1.4), base.z) for a in a_ring])
    U.bake(mc.fan, "rotation_euler", 1, FRAMES, a_fan)
    from .machine import tube_point
    bead_phase = 0.0
    phases = []
    for f in FRAMES:
        if f >= on + 2:
            bead_phase += 0.02 + 0.08 * ch("speed", f)
        phases.append(bead_phase)
    for bead, k, off in mc.beads:
        pts = mc.tube_curves[k]
        locs, scl = [], []
        for f, ph in zip(FRAMES, phases):
            t = (ph + off) % 1.0
            locs.append(tuple(tube_point(pts, t)))
            on_ = f >= on + 2 and f < e["notif_obsolete"]
            scl.append((1, 1, 1) if on_ else (0, 0, 0))
        U.bake_vec(bead, "location", FRAMES, locs)
        U.bake_vec(bead, "scale", FRAMES, scl, 'CONSTANT')
    # big button: depress + squash
    b = mc.button
    z0 = b.location.z
    bt = U.Track().key(e["button_press"] - 1, z0).key(e["button_press"] + 1, z0 - 0.013, "in").key(e["button_press"] + 6, z0, "back")
    U.bake(b, "location", 2, FRAMES, [bt(f) for f in FRAMES])
    # paper roll spins while printing
    r0 = mc.roll.rotation_euler.copy()
    spin = 0.0
    sp = []
    for f in FRAMES:
        if E["print_start"] <= f <= E["print_end"]:
            spin += 0.6 + 2.0 * ch("speed", f)
        sp.append(spin)
    U.bake(mc.roll, "rotation_euler", 0, FRAMES, [r0.x + s for s in sp])


def _bake_emission(mat, values):
    for n in mat.node_tree.nodes:
        if n.type == 'EMISSION':
            U.bake(mat.node_tree, f'nodes["{n.name}"].inputs[1].default_value', 0, FRAMES, values)
            return


def _bake_node_value(mat, node_name, values):
    U.bake(mat.node_tree, f'nodes["{node_name}"].outputs[0].default_value', 0, FRAMES, values)


def _bake_node_input(mat, node_name, inp, index, values):
    U.bake(mat.node_tree, f'nodes["{node_name}"].inputs["{inp}"].default_value', index, FRAMES, values)


# ---------------------------------------------------------------------------
# The roadmap scroll: a ribbon that grows along a path out of the door
# ---------------------------------------------------------------------------

SCROLL_PATH = [(-0.33, 1.33, 0.785), (-0.36, 1.20, 0.757), (-0.38, 1.10, 0.755), (-0.39, 1.06, 0.70),
               (-0.40, 1.03, 0.30), (-0.42, 0.96, 0.006), (-0.78, 0.55, 0.004), (-0.88, 0.02, 0.004),
               (-0.55, -0.48, 0.004), (0.15, -0.88, 0.004), (0.78, -0.66, 0.004), (1.12, -0.28, 0.004),
               (1.50, -0.30, 0.004), (1.78, -0.62, 0.004), (2.0, -0.72, 0.004), (2.6, -0.76, 0.004),
               (3.4, -0.4, 0.004), (3.6, 1.5, 0.004), (3.6, 9.0, 0.004), (3.3, 25.0, 0.004), (3.8, 60.0, 0.004)]


def build_scroll(ctx):
    import bmesh
    col = ctx.cols["Props"]
    from . import materials as M_
    pts = [V(p) for p in SCROLL_PATH]
    # Catmull-Rom resample
    P_ = [pts[0]] + pts + [pts[-1]]
    samples = []
    for i in range(1, len(P_) - 2):
        seg = (P_[i + 1] - P_[i]).length
        n = max(2, int(seg / 0.05))
        for k in range(n):
            t = k / n
            p0, p1, p2, p3 = P_[i - 1], P_[i], P_[i + 1], P_[i + 2]
            samples.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    samples.append(pts[-1])
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    dist = bm.verts.layers.float.new("dist")
    width = 0.21
    rows = []
    s_acc = 0.0
    prev_side = V((1, 0, 0))
    for i, p in enumerate(samples):
        if i > 0:
            s_acc += (p - samples[i - 1]).length
        t = (samples[min(i + 1, len(samples) - 1)] - samples[max(i - 1, 0)])
        h = V((t.x, t.y, 0))
        side = h.cross(V((0, 0, 1))).normalized() if h.length > 1e-4 else prev_side
        prev_side = side
        a = bm.verts.new(p - side * width / 2)
        b = bm.verts.new(p + side * width / 2)
        a[dist] = s_acc
        b[dist] = s_acc
        rows.append((a, b, s_acc))
    for (a0, b0, s0), (a1, b1, s1) in zip(rows, rows[1:]):
        f = bm.faces.new([a0, b0, b1, a1])
        for loop, uv in zip(f.loops, [(s0, 0), (s0, 1), (s1, 1), (s1, 0)]):
            loop[uvl].uv = uv
    ob = U.mesh_object("RoadmapScroll", bm, col, M_.roadmap_paper(), smooth=True)
    sol = ob.modifiers.new("Thickness", 'SOLIDIFY')
    sol.thickness = 0.0012
    # GN: delete everything beyond the printed length
    ng = bpy.data.node_groups.new("GN_ScrollGrow", 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Printed Length", in_out='INPUT', socket_type='NodeSocketFloat')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gi = ng.nodes.new('NodeGroupInput'); go = ng.nodes.new('NodeGroupOutput')
    na = ng.nodes.new('GeometryNodeInputNamedAttribute'); na.data_type = 'FLOAT'; na.inputs["Name"].default_value = "dist"
    cmp = ng.nodes.new('ShaderNodeMath'); cmp.operation = 'GREATER_THAN'
    ng.links.new(na.outputs[0], cmp.inputs[0]); ng.links.new(gi.outputs[1], cmp.inputs[1])
    dl = ng.nodes.new('GeometryNodeDeleteGeometry'); dl.domain = 'POINT'
    ng.links.new(gi.outputs[0], dl.inputs["Geometry"]); ng.links.new(cmp.outputs[0], dl.inputs["Selection"])
    ng.links.new(dl.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("Grow", 'NODES')
    mod.node_group = ng
    ob.modifiers.move(1, 0)
    total = s_acc
    a, b = E["print_start"], E["print_end"]
    vals = []
    L = 0.0
    for f in FRAMES:
        if a <= f:
            v = (0.6 + 9.0 * ch("speed", f) + 30.0 * clamp((f - a) / (b - a)) ** 2) / T.FPS * 2.2
            L = min(total, L + v) if f <= b + 30 else L
        vals.append(L)
    from .hall import input_id
    ident = input_id(mod, "Printed Length")
    U.bake(ob, f'modifiers["Grow"].properties.inputs.{ident}.value', 0, FRAMES, vals)
    ctx.scroll = ob
    return ob


# ---------------------------------------------------------------------------
# Lights, screens, environment
# ---------------------------------------------------------------------------

def bake_lights(ctx):
    Lg = ctx.lights
    e = E
    cool = V((0.55, 0.70, 1.0))
    red = V((1.0, 0.18, 0.12))
    cyan = V((0.2, 0.85, 1.0))
    lap_e, lap_c, mon_e, mon_c = [], [], [], []
    for f in FRAMES:
        pulse = ch("light_pulse", f)
        flick = 1.0 + 0.25 * ch("speed", f) * U.noise1(f * 0.9, 12)
        c = cool.copy()
        w_red = max(win(f, e["notif_better"], e["notif_better"] + 17, 1), win(f, e["notif_obsolete"], e["notif_obsolete"] + 10, 1) * 0.7)
        w_cy = win(f, e["build_start"], e["sip2_start"], 3)
        c = c.lerp(red, w_red).lerp(cyan, w_cy * 0.6)
        closed = clamp((f - e["close_laptop"] - 1) / 5.0) * (1 - clamp((f - e["yank"] - 5) / 2.0))
        lap_e.append(5.0 * (1 + 1.4 * pulse) * flick * (1 - closed) + 6.0 * w_red)
        lap_c.append(tuple(c))
        mc = cool.lerp(red, win(f, e["notif_better"], e["scream_end"], 1)).lerp(cyan, win(f, e["build_start"], e["print_end"], 4) * 0.7)
        mon_e.append(7.0 * (1 + 0.6 * pulse) * flick * (0.4 if f >= e["walls_land"] else 1.0))
        mon_c.append(tuple(mc))
    U.bake(Lg.laptop.data, "energy", 0, FRAMES, lap_e)
    U.bake_vec(Lg.laptop.data, "color", FRAMES, lap_c)
    U.bake(Lg.monitor.data, "energy", 0, FRAMES, mon_e)
    U.bake_vec(Lg.monitor.data, "color", FRAMES, mon_c)
    for mat_name, values in (("MAT_LaptopScreen", [1.0 - (lap_e and 0) for _ in FRAMES]),):
        pass
    # laptop screen goes dark when closed (also handled by black frames)
    # the idea: lamp flares like a lightbulb moment
    lamp = [60.0 * (1 + 1.3 * win(f, e["idea"], e["idea"] + 3, 1)) * (1 - 0.0) for f in FRAMES]
    U.bake(Lg.lamp_spot.data, "energy", 0, FRAMES, lamp)
    # hall lights come on as the walls fall (no leaks before that)
    hall_on = [U.ease(clamp((f - e["walls_fall_start"]) / 10.0)) for f in FRAMES]
    for lt in Lg.hall:
        U.bake(lt.data, "energy", 0, FRAMES, [12000.0 * h for h in hall_on])
    U.bake(Lg.hall_key.data, "energy", 0, FRAMES, [450.0 * h * (1 + 0.5 * win(f, e["pa_start"], e["display_flip"], 6)) for f, h in zip(FRAMES, hall_on)])
    U.bake(Lg.hall_fill.data, "energy", 0, FRAMES, [500.0 * h for h in hall_on])
    gate = ctx.hall.gate_light
    U.bake(gate.data, "energy", 0, FRAMES, [2.5e6 * h for h in hall_on])
    door = [U.ease(clamp((f - e["walk_start"]) / 8.0)) * (1 - U.ease(clamp((f - e["walls_land"]) / 6.0))) for f in FRAMES]
    U.bake(Lg.door_leak.data, "energy", 0, FRAMES, [40.0 * d for d in door])
    # room lights dim to nothing during the pullback (they're tiny in frame anyway)
    # window 'dawn' follows the racing clock
    city = bpy.data.materials["MAT_CityBacklight"]
    _bake_node_value(city, "Dawn", [clamp((ch("clock_minutes", f) - 21 * 60 - 330) / 240.0) * 0.8 for f in FRAMES])


def bake_environment(ctx, hero):
    """Walls fall, ceiling flies, station rides the belt, gate recedes, extras act."""
    e = E
    R = ctx.room
    # walls: hinge outward with a heavy bounce, staggered by a few frames
    order = {"Wall_Front": 0, "Wall_Right": 1, "Wall_Left": 3, "Wall_Back": 2}
    for name, w in R.walls.items():
        ob = w["ob"]
        base = ob.rotation_euler.copy()
        a = e["walls_fall_start"] + order[name] * 2
        b = e["walls_land"] - 2 + order[name]
        tr = U.Track().key(a, 0.0).key(b, -math.pi / 2 + 0.002, "bounce")
        U.bake_vec(ob, "rotation_euler", FRAMES, [(tr(f), base.y, base.z) for f in FRAMES])
    ct = U.Track().key(e["walls_fall_start"], 2.6).key(e["walls_land"] + 8, 30.0, "in")
    U.bake(R.ceiling, "location", 2, FRAMES, [ct(f) for f in FRAMES])
    # door handle turns
    h = R.door_handle
    hr = U.Track().key(e["handle_turn"] - 1, 0.0).key(e["handle_turn"] + 2, -0.6, "out").key(e["handle_turn"] + 8, -0.6)
    base = h.rotation_euler.copy()
    U.bake_vec(h, "rotation_euler", FRAMES, [(base.x, base.y + hr(f), base.z) for f in FRAMES])
    # the hero station rides the belt (everything bedroom-side is parented to it)
    st = ctx.station
    U.bake_vec(st, "location", FRAMES, [(0.0, ch("belt_distance", f), 0.0) for f in FRAMES])
    # finish gate along the track, always ahead and receding
    gate = ctx.hall.gate
    locs, rots = [], []
    prev = None
    for f in FRAMES:
        s = TR.HERO_S0 + ch("belt_distance", f) + ch("finish_gap", f)
        (x, y), t = TR.point(s)
        locs.append((x, y, 0.0))
        r = TR.heading(t)
        if prev is not None:
            while r - prev > math.pi:
                r -= 2 * math.pi
            while r - prev < -math.pi:
                r += 2 * math.pi
        prev = r
        rots.append((0.0, 0.0, r))
    U.bake_vec(gate, "location", FRAMES, locs)
    U.bake_vec(gate, "rotation_euler", FRAMES, rots)
    # fog: off in the bedroom, on in the hall; deep for the pull-back
    comp = ctx.scene.compositing_node_group
    fog = [0.0 if f < e["walls_fall_start"] else (0.85 if f < e["black"] else 0.0) for f in FRAMES]
    U.bake(comp, 'nodes["FogAmount"].outputs[0].default_value', 0, FRAMES, fog, 'CONSTANT')
    shutter = [0.06 if E["pullback_start"] <= f < E["black"] else 0.42 for f in FRAMES]
    U.bake(ctx.scene, "render.motion_blur_shutter", 0, FRAMES, shutter, 'CONSTANT')
    mist = U.Track().key(1, 260.0).key(e["pullback_start"], 260.0).key(e["black"] - 1, 3800.0, "in")
    U.bake(ctx.scene.world, "mist_settings.depth", 0, FRAMES, [mist(f) for f in FRAMES])


def connect_drivers(ctx, ctl):
    from .hall import input_id
    hl = ctx.hall
    belt = bpy.data.materials["MAT_Belt"]
    drive(belt.node_tree, 'nodes["BeltScroll"].inputs["Location"].default_value', 0, ctl, "belt_distance", "-v")
    for mod, items in ((hl.crowd_mod, (("Belt Distance", "belt_distance", "v"), ("Typing Phase", "crowd_typing_phase", "v"))),
                       (hl.far_mod, (("Belt Distance", "belt_distance", "v*1.0"), ("Finish Gap", "finish_gap", "v")))):
        for sock, prop, expr in items:
            ident = input_id(mod, sock)
            drive(mod.id_data, f'modifiers["{mod.name}"].properties.inputs.{ident}.value', -1, ctl, prop, expr)
    drive(bpy.data.materials["MAT_EyeBag"].node_tree, 'nodes["Stress"].outputs[0].default_value', -1, ctl, "stress", "v")


# ---------------------------------------------------------------------------
# Extras: one student reaches for the line, another runs on the belt
# ---------------------------------------------------------------------------

def build_extras(ctx):
    from . import character as C
    col = U.collection("Extras", ctx.cols["IndustrialReveal"])
    e = E
    out = []
    for name, base, kind in (("Extra_Reacher", V((4.0, 3.0, TR_STATION_Z())), "reach"), ("Extra_Runner", V((-2.75, 6.0, TR_STATION_Z())), "run")):
        exc = C.build_character(name, col, "crowd")
        solver = P.Solver(exc)
        rig = exc.rig

        def pose(f, kind=kind):
            Pz = dict(hips=(V((0, 0, 0)), (0, 0, 0)), spine=(0.05, 0, 0), chest=(0.05, 0, 0), neck=(0, 0, 0), head=(-0.15, 0, 0))
            if kind == "reach":
                r = win(f, e["reach_student"], 720, 4)
                Pz["spine"] = (-0.1 * r, 0, 0)
                Pz["arm.R"] = dict(wrist=V((-0.12, -0.45 - 0.1 * r, 1.55 + 0.25 * r + 0.02 * math.sin(f * 0.7))), pole=V((-0.6, 0.2, 1.0)),
                                   fdir=V((0, -1, 0.4)), palm=V((0, 0, -1)))
                Pz["arm.L"] = dict(wrist=V((0.25, -0.02, 0.82)), pole=V((0.5, 0.6, 1.0)), fdir=V((0, -0.1, -1)), palm=V((-1, 0, 0)))
                for s, k in (("L", 1), ("R", -1)):
                    Pz[f"leg.{s}"] = dict(ankle=V((0.11 * k, -0.01 - (0.12 * r if s == "R" else 0), 0.085)), pole=V((0.1 * k, -1, 0.3)), toe=V((0, -1, -0.2)))
            else:
                ph = f * 2 * math.pi / 9.0
                Pz["spine"] = (0.18, 0.1 * math.sin(ph), 0)
                for s, k, o in (("L", 1, 0), ("R", -1, math.pi)):
                    sw = math.sin(ph + o)
                    Pz[f"leg.{s}"] = dict(ankle=V((0.1 * k, -0.25 * sw, 0.085 + 0.18 * max(0.0, math.cos(ph + o)))), pole=V((0.1 * k, -1, 0.3)), toe=V((0, -1, -0.1)))
                    Pz[f"arm.{s}"] = dict(wrist=V((0.24 * k, 0.22 * sw, 1.0 + 0.06 * abs(sw))), pole=V((0.4 * k, 1.0, 0.8)), fdir=V((0, -1, 0.3)), palm=V((-k, 0, 0)))
                Pz["hips"] = (V((0, 0, 0.03 * abs(math.sin(ph)))), (0, 0, 0))
            return Pz
        P.bake_pose_track(exc, FRAMES, pose)
        rig.rotation_euler = (0, 0, math.pi)
        locs = [tuple(base + V((0, ch("belt_distance", f), 0))) for f in FRAMES]
        U.bake_vec(rig, "location", FRAMES, locs)
        out.append(exc)
    return out


def TR_STATION_Z():
    from .hall import STATION_Z
    return STATION_Z + 0.08


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(ctx):
    from . import cameras as CAM
    scene = ctx.scene
    ctl = build_controller(ctx.cols["ProceduralSystems"])
    ctx.controller = ctl
    # the hero station: parent the whole bedroom set + hero to it
    st = U.empty("HeroStation", ctx.cols["ProceduralSystems"], (0, 0, 0), display="CUBE", size=2.2)
    ctx.station = st
    for cname in ("Environment", "Props", "Screens", "Character", "Lighting"):
        for ob in ctx.cols[cname].objects:
            if ob.parent is None:
                if cname == "Lighting" and ob.name.startswith("LGT_Hall"):
                    continue
                ob.parent = st
    for ob in ctx.machine.parts + [ctx.machine.root]:
        pass
    hero = Hero(ctx)
    ctx.hero_perf = hero
    CAM.build(ctx, hero)          # cameras first: the 'look at the audience' target
    bake_hero(ctx, hero)
    bake_props(ctx, hero)
    bake_machine(ctx)
    build_scroll(ctx)
    bake_lights(ctx)
    bake_environment(ctx, hero)
    connect_drivers(ctx, ctl)
    build_extras(ctx)
    CAM.bake(ctx, hero)
    CAM.title(ctx)
    scene.frame_set(1)
