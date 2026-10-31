"""Lighting: warm amber practicals vs cool screen spill; a vast backlit hall."""

import math

import bpy
from mathutils import Vector

from . import bl_util as U


def _light(name, col, kind, loc, energy, color, size=0.5, size_y=None, target=None, rot=None, spot=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == 'AREA':
        ld.shape = 'RECTANGLE' if size_y else 'SQUARE'
        ld.size = size
        if size_y:
            ld.size_y = size_y
    elif kind in ('SPOT', 'POINT'):
        ld.shadow_soft_size = size
    if spot:
        ld.spot_size, ld.spot_blend = spot
    ob = bpy.data.objects.new(name, ld)
    col.objects.link(ob)
    ob.location = loc
    if target is not None:
        d = Vector(target) - Vector(loc)
        ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    elif rot is not None:
        ob.rotation_euler = rot
    return ob


class Lights:
    pass


def build(col, room, hall):
    L = Lights()
    warm = (1.0, 0.68, 0.40)
    cool = (0.55, 0.70, 1.0)
    # desk lamp: a shaped spot from inside the shade + a soft bounce
    bulb_w = room.lamp_bulb.matrix_world.translation if room.lamp_bulb.parent is None else None
    L.lamp_spot = _light("LGT_LampSpot", col, 'SPOT', (0.70, 1.52, 1.12), 60.0, warm, 0.05,
                         target=(0.15, 1.15, 0.76), spot=(math.radians(110), 0.55))
    L.lamp_bounce = _light("LGT_LampBounce", col, 'AREA', (0.55, 1.35, 1.35), 9.0, warm, 0.6, target=(0.1, 0.7, 1.0))
    # warm face key, motivated by the lamp: a large source (skill: a face key is never a bulb)
    L.face_key = _light("LGT_FaceKey", col, 'AREA', (0.55, 1.22, 1.62), 26.0, (1.0, 0.74, 0.50), 0.55, target=(0.05, 0.90, 1.15))
    # screens
    L.laptop = _light("LGT_LaptopSpill", col, 'AREA', (0.02, 1.36, 0.90), 5.0, cool, 0.30, 0.19, target=(0.05, 0.75, 1.15))
    L.monitor = _light("LGT_MonitorSpill", col, 'AREA', (0.47, 1.58, 1.16), 7.0, cool, 0.6, 0.34, target=(0.05, 0.8, 1.15))
    # window: cold moonlight through the 'city'
    L.window = _light("LGT_Window", col, 'AREA', (0.2, 1.70, 1.60), 14.0, (0.35, 0.45, 0.9), 1.2, 0.9, target=(0.0, -0.5, 0.9))
    # rim from behind (motivated by light leaking under the door / hallway)
    L.rim = _light("LGT_Rim", col, 'AREA', (-0.9, -1.2, 2.3), 26.0, (0.6, 0.65, 0.85), 1.0, target=(0.05, 0.85, 1.15))
    # soft room fill so the bedroom never goes to crushed black
    L.fill = _light("LGT_RoomFill", col, 'AREA', (-1.2, -1.0, 2.45), 18.0, (0.55, 0.6, 0.85), 2.5, target=(0.0, 0.5, 0.0))
    L.machine = None
    # soft overhead cheat for the paper-follow shot (S19), motivated by the desk lamp spill
    L.paper = _light("LGT_PaperFill", col, 'AREA', (-0.2, -0.1, 2.45), 0.0, (1.0, 0.82, 0.62), 2.6, rot=(0, 0, 0))
    # cold light leaking around the door: the outside world is brighter than it should be
    L.door_leak = _light("LGT_DoorLeak", col, 'AREA', (1.92, -0.82, 1.15), 0.0, (0.75, 0.82, 1.0), 0.9, 2.0,
                         rot=(0, 1.5708, 0))
    # the whisper at the door: the same cold door light, as a soft key on his upturned face
    L.whisper = _light("LGT_WhisperKey", col, 'AREA', (1.90, -1.22, 1.92), 0.0, (0.80, 0.87, 1.0), 0.5,
                       target=(1.60, -0.93, 1.62))
    # ---- hall -----------------------------------------------------------
    L.hall = []
    for i, y in enumerate((-36, -12, 12, 36)):
        for x in (-14, 14):
            L.hall.append(_light(f"LGT_HallWork_{i}_{x}", col, 'AREA', (x, y, 20.5), 0.0, (1.0, 0.86, 0.68), 10.0,
                                 rot=(0, 0, 0)))
    L.hall_key = _light("LGT_HallKeyHero", col, 'AREA', (6.0, 10.0, 9.0), 0.0, (1.0, 0.88, 0.7), 6.0, target=(1.6, -0.8, 1.4))
    L.hall_fill = _light("LGT_HallFill", col, 'AREA', (-8.0, -14.0, 7.0), 0.0, (0.45, 0.55, 0.8), 10.0, target=(1.6, -0.8, 1.0))
    return L


def world(scene):
    w = bpy.data.worlds.get("WORLD_SkillIssue") or bpy.data.worlds.new("WORLD_SkillIssue")
    scene.world = w
    nt = w.node_tree
    bg = nt.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.006, 0.008, 0.014, 1)
    bg.inputs["Strength"].default_value = 1.0
    w.mist_settings.start = 6.0
    w.mist_settings.depth = 260.0
    w.mist_settings.falloff = 'QUADRATIC'
    return w
