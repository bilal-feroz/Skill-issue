"""Build the complete SKILL ISSUE Blender project from code.

    blender -b --factory-startup -P scripts/build_scene.py -- [--preset preview|final|draft]
                                                              [--no-anim] [--out project/skill_issue.blend]

Prerequisites: python scripts/generate_screens.py, scripts/generate_clock.py
(image sequences referenced by the screen materials).
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import bpy  # noqa: E402

from skill_issue import (bl_util as U, character as C, hall as HALL, lighting as LGT,  # noqa: E402
                         machine as MCH, materials as M, render_setup as RS, room as ROOM)


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = dict(preset="preview", anim=True, out=os.path.join(ROOT, "project", "skill_issue.blend"))
    i = 0
    while i < len(a):
        if a[i] == "--preset":
            opts["preset"] = a[i + 1]; i += 1
        elif a[i] == "--no-anim":
            opts["anim"] = False
        elif a[i] == "--out":
            opts["out"] = a[i + 1]; i += 1
        i += 1
    return opts


class Ctx:
    pass


def build(opts):
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "SKILL_ISSUE"
    screen_dir = os.path.join(ROOT, "assets", "screens").replace("\\", "/")
    ctx = Ctx()
    ctx.root, ctx.screen_dir = ROOT, screen_dir
    ctx.cols = {k: U.collection(k) for k in (
        "Character", "Environment", "Props", "Screens", "Lighting", "Cameras",
        "ProceduralSystems", "IndustrialReveal", "RepeatedInstances", "Effects", "Title", "_Assets")}
    ctx.scene = scene
    LGT.world(scene)
    RS.configure(scene, opts["preset"], os.path.join(ROOT, "renders", "frames"))
    RS.compositor(scene)
    print(f"[build] scene base {time.time() - t0:.1f}s")

    ctx.room = ROOM.build(ctx.cols["Environment"], ctx.cols["Props"], ctx.cols["Screens"], screen_dir)
    print(f"[build] room {time.time() - t0:.1f}s")
    ctx.hero = C.build_character("Student", ctx.cols["Character"], "hero")
    print(f"[build] hero {time.time() - t0:.1f}s")
    ctx.machine = MCH.build(ctx.cols["Props"], ctx.room.top, origin=(-0.30, 1.40))
    ctx.machine.root.rotation_euler = (0, 0, -0.20)
    print(f"[build] machine {time.time() - t0:.1f}s")

    # crowd: a lightweight clone of the hero, posed sitting & typing, then baked
    crowd_col = U.collection("_CrowdBuild", ctx.cols["_Assets"])
    crowd = C.build_character("Clone", crowd_col, "crowd")
    from skill_issue import animate as A
    room_mats = (bpy.data.materials["MAT_DeskWood"], bpy.data.materials["MAT_BlackPlastic"],
                 bpy.data.materials["MAT_SteelDark"], M.emission("MAT_CrowdBulb", (1.0, 0.65, 0.35, 1), 30.0),
                 bpy.data.materials["MAT_ChairFabric"])
    ctx.hall = HALL.build(ctx.cols["IndustrialReveal"], ctx.cols["RepeatedInstances"], ctx.cols["_Assets"],
                          screen_dir, crowd, A.crowd_seated_pose, room_mats)
    # drop the temporary crowd rig (its meshes were baked into instances)
    for ob in list(crowd_col.objects):
        bpy.data.objects.remove(ob)
    bpy.data.collections.remove(crowd_col)
    print(f"[build] hall {time.time() - t0:.1f}s")
    ctx.lights = LGT.build(ctx.cols["Lighting"], ctx.room, ctx.hall)
    # exclude prototype assets from rendering (GN still instances them)
    lc = bpy.context.view_layer.layer_collection.children["_Assets"]
    lc.exclude = True
    if opts["anim"]:
        A.run(ctx)
        print(f"[build] animation {time.time() - t0:.1f}s")
    os.makedirs(os.path.dirname(opts["out"]), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=opts["out"], compress=True)
    bpy.ops.file.make_paths_relative()          # needs a saved file first
    bpy.ops.wm.save_as_mainfile(filepath=opts["out"], compress=True)
    print(f"[build] saved {opts['out']} in {time.time() - t0:.1f}s")
    return ctx


if __name__ == "__main__":
    build(args())
