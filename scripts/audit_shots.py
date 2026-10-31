"""Shot visibility audit (after scenario-blender-previs-storyboard's eye-line check).

For every shot, at its first, middle and last frame, cast rays from the active camera
through the frame centre and four inner points. Anything hit well before the focus
distance is reported as a blocker (a camera inside a chair, a book tower, his hair...).

    blender -b project/skill_issue.blend -P scripts/audit_shots.py [-- --json out.json]
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from skill_issue import timeline as T  # noqa: E402

IGNORE = ("Title_", "Caption", "LGT_", "Far_", "GN_Far")


def frame_rays(cam, sc):
    cd = cam.data
    aspect = sc.render.resolution_x / sc.render.resolution_y
    half_w = (cd.sensor_width / 2) / cd.lens
    half_h = half_w / aspect
    M = cam.matrix_world.to_3x3()
    out = []
    for u, v in ((0, 0), (-0.45, -0.35), (0.45, -0.35), (-0.45, 0.35), (0.45, 0.35)):
        d = M @ Vector((u * 2 * half_w, v * 2 * half_h, -1.0))
        out.append(((u, v), d.normalized()))
    return out


def main():
    sc = bpy.context.scene
    report = []
    for sh in T.SHOTS:
        if sh["cam"] == "CAM_Title":
            continue
        for f in (sh["start"], (sh["start"] + sh["end"]) // 2, sh["end"]):
            sc.frame_set(f)
            cam = sc.camera
            dg = bpy.context.evaluated_depsgraph_get()
            focus = cam.data.dof.focus_distance
            o = cam.matrix_world.translation
            for (u, v), d in frame_rays(cam, sc):
                hit, loc, nrm, idx, ob, _ = sc.ray_cast(dg, o, d, distance=focus * 1.2)
                if not hit or any(ob.name.startswith(p) for p in IGNORE):
                    continue
                dist = (loc - o).length
                limit = 0.55 if (u, v) == (0, 0) else 0.30
                if dist < focus * limit:
                    report.append(dict(shot=sh["id"], frame=f, ray=(u, v), blocker=ob.name,
                                       dist=round(dist, 3), focus=round(focus, 3),
                                       backface=bool(nrm.dot(d) > 0)))
    for r in report:
        print(f"[audit] {r['shot']} f{r['frame']} ray{r['ray']} blocked by {r['blocker']} at {r['dist']} m "
              f"(focus {r['focus']} m){' INSIDE' if r['backface'] else ''}", flush=True)
    print(f"[audit] {len(report)} findings", flush=True)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--json" in argv:
        json.dump(report, open(argv[argv.index("--json") + 1], "w"), indent=1)


if __name__ == "__main__":
    main()
