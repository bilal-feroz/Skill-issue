"""Capture genuine work-in-progress screenshots of the Blender UI.

Opens the real project in the Blender interface, arranges an editor layout,
waits for it to draw, saves a screenshot of the whole window and quits.

    blender project/skill_issue.blend --window-geometry 0 0 1920 1080 \
        -P scripts/capture_evidence.py -- <preset> <out.png>

presets: scene | character | procedural | timeline
"""

import os
import sys

import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["scene", "evidence.png"]
PRESET, OUT = ARGS[0], os.path.abspath(ARGS[1])
STATE = {"step": 0}


def areas(kind):
    return [a for a in bpy.context.window.screen.areas if a.type == kind]


def biggest():
    return max(bpy.context.window.screen.areas, key=lambda a: a.width * a.height)


def setup():
    sc = bpy.context.scene
    win = bpy.context.window
    main = biggest()
    main.type = 'VIEW_3D'
    sp = main.spaces.active
    sp.overlay.show_overlays = True
    if PRESET == "scene":
        sc.frame_set(20)
        sp.shading.type = 'SOLID'
        sp.shading.color_type = 'MATERIAL'
        sp.region_3d.view_perspective = 'PERSP'
        from mathutils import Euler, Vector
        r3 = sp.region_3d
        r3.view_location = Vector((0.2, 0.6, 0.9))
        r3.view_rotation = Euler((1.1, 0, -0.6)).to_quaternion()
        r3.view_distance = 2.8
        sp.lens = 24
    elif PRESET == "character":
        sc.frame_set(130)
        sp.shading.type = 'MATERIAL'
        sc.camera = bpy.data.objects["CAM_S05_WebcamDoubt"]
        sp.region_3d.view_perspective = 'CAMERA'
    elif PRESET == "procedural":
        sc.frame_set(604)
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        crowd = bpy.data.objects["GN_Crowd"]
        bpy.context.view_layer.objects.active = crowd
        crowd.select_set(True)
        sp.shading.type = 'SOLID'
        sp.region_3d.view_perspective = 'CAMERA'
        sc.camera = bpy.data.objects["CAM_S24_Reveal"]
        # bottom half of the main area becomes the node editor
        with bpy.context.temp_override(window=win, area=main):
            bpy.ops.screen.area_split(direction='HORIZONTAL', factor=0.5)
        new = [a for a in win.screen.areas if a.type == 'VIEW_3D' and a != main]
        tgt = min(new, key=lambda a: a.y) if new else main
        if main.y < tgt.y:
            main, tgt = tgt, main
        tgt.type = 'NODE_EDITOR'
        tgt.ui_type = 'GeometryNodeTree'
        ns = tgt.spaces.active
        ns.node_tree = bpy.data.node_groups["GN_CrowdStations"]
        ns.show_region_ui = False
        STATE["nodes_area"] = tgt
    elif PRESET == "timeline":
        sc.frame_set(248)
        ctl = bpy.data.objects["SPEED_CONTROLLER"]
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        bpy.context.view_layer.objects.active = ctl
        ctl.select_set(True)
        main.type = 'GRAPH_EDITOR'
        sp = main.spaces.active
        sp.dopesheet.show_only_selected = True
        sp.use_normalization = True
        # show the headline channels of the speed system
        keep = ('["speed"]', '["belt_distance"]', '["typing_phase"]', '["cam_intensity"]', '["finish_gap"]', '["stress"]')
        from bpy_extras import anim_utils
        ad = ctl.animation_data
        cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
        for fc in cb.fcurves:
            fc.hide = fc.data_path not in keep
        sad = sc.animation_data
        if sad and sad.action:
            scb = anim_utils.action_get_channelbag_for_slot(sad.action, sad.action_slot)
            for fc in scb.fcurves:
                fc.hide = True
    return main


def tick():
    STATE["step"] += 1
    if STATE["step"] == 1:
        STATE["main"] = setup()
        return 4.0 if PRESET == "character" else 2.0
    if STATE["step"] == 2:
        if PRESET == "timeline":
            main = STATE["main"]
            region = next(r for r in main.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(window=bpy.context.window, area=main, region=region):
                bpy.ops.graph.view_all()
        if PRESET == "procedural":
            for a in bpy.context.window.screen.areas:
                if a.type == 'NODE_EDITOR':
                    region = next(r for r in a.regions if r.type == 'WINDOW')
                    with bpy.context.temp_override(window=bpy.context.window, area=a, region=region):
                        bpy.ops.node.view_all()
        return 3.0 if PRESET == "character" else 1.5
    if STATE["step"] == 3:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with bpy.context.temp_override(window=bpy.context.window, area=STATE["main"]):
            bpy.ops.screen.screenshot(filepath=OUT)
        print("[evidence] saved", OUT, flush=True)
        return 0.5
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=6.0)
