"""Character turnaround: builds only the student and renders front / three-quarter / profile /
back views with expressions, then lays them out on one sheet (the sculpting skill's review
renders, used for evidence/06_character_redesign.png).

    blender -b --factory-startup -P scripts/character_turnaround.py -- [--out evidence/06_character_redesign.png]
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from skill_issue import bl_util as U, character as C  # noqa: E402

VIEWS = [  # name, camera position, expression
    ("front", (0.0, -1.30, 1.58), {}),
    ("smile", (0.85, -1.0, 1.62), {"Smile": 1.0}),
    ("profile", (1.30, -0.05, 1.58), {}),
    ("grin", (-0.8, -1.0, 1.55), {"Grin": 1.0}),
    ("back", (-0.9, 0.95, 1.60), {}),
    ("scream", (0.45, -1.2, 1.60), {"Scream": 1.0}),
]


def light(sc, name, loc, energy, color, size=1.0):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy, ld.color, ld.size = energy, color, size
    ob = bpy.data.objects.new(name, ld)
    sc.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector((0, 0, 1.4)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "evidence", "06_character_redesign.png")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ch = C.build_character("Student", U.collection("Character"), "hero")
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x, sc.render.resolution_y = 960, 720
    sc.eevee.taa_render_samples = 48
    sc.view_settings.view_transform = 'AgX'
    w = bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.06, 1)
    light(sc, "Key", (1.2, -1.5, 2.0), 70, (1, 0.8, 0.6))
    light(sc, "Fill", (-1.5, -1.0, 1.5), 25, (0.6, 0.75, 1.0))
    light(sc, "Rim", (0, 1.5, 2.2), 120, (1, 1, 1))
    cd = bpy.data.cameras.new("Cam")
    cd.lens = 90
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    tmp = os.path.join(os.path.dirname(out), "_turnaround_tmp")
    os.makedirs(tmp, exist_ok=True)
    paths = []
    for name, loc, expr in VIEWS:
        for kb in ch.mouth.data.shape_keys.key_blocks[1:]:
            kb.value = expr.get(kb.name, 0.0)
        cam.location = loc
        cam.rotation_euler = (Vector((0, -0.05, 1.58)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(tmp, f"{name}.png")
        bpy.ops.render.render(write_still=True)
        paths.append(sc.render.filepath)
    # one sheet, 3 x 2
    sheet = bpy.data.images.new("Sheet", 960 * 3, 720 * 2)
    import numpy as np
    px = np.zeros((720 * 2, 960 * 3, 4), np.float32)
    for i, p in enumerate(paths):
        im = bpy.data.images.load(p)
        a = np.array(im.pixels[:], np.float32).reshape(720, 960, 4)
        r, c = 1 - i // 3, i % 3                       # Blender images are bottom-up
        px[r * 720:(r + 1) * 720, c * 960:(c + 1) * 960] = a
    sheet.pixels[:] = px.ravel()
    sheet.filepath_raw = out
    sheet.file_format = 'PNG'
    sheet.save()
    for p in paths:
        os.remove(p)
    os.rmdir(tmp)
    print("[turnaround] wrote", out)


if __name__ == "__main__":
    main()
