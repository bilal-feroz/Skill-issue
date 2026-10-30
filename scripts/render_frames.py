"""Render frames from the saved project (resumable).

    blender -b project/skill_issue.blend -P scripts/render_frames.py -- \
        [--preset final|preview|draft] [--frames 1-720 | --frames 20,95,300] [--out renders/frames] [--overwrite]

With a frame range it renders the animation with Blender's placeholder/no-overwrite
mode, so an interrupted render resumes where it stopped. With a list it renders stills.
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import bpy  # noqa: E402

from skill_issue import render_setup as RS  # noqa: E402


def parse():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    o = dict(preset="preview", frames="1-720", out=os.path.join(ROOT, "renders", "frames"), overwrite=False)
    i = 0
    while i < len(a):
        if a[i] in ("--preset", "--frames", "--out"):
            o[a[i][2:]] = a[i + 1]
            i += 1
        elif a[i] == "--overwrite":
            o["overwrite"] = True
        i += 1
    return o


def main():
    o = parse()
    o["out"] = os.path.abspath(o["out"])
    sc = bpy.context.scene
    RS.configure(sc, o["preset"], o["out"])
    os.makedirs(o["out"], exist_ok=True)
    fr = o["frames"]
    t0 = time.time()
    if "-" in fr and "," not in fr:
        a, b = (int(x) for x in fr.split("-"))
        sc.frame_start, sc.frame_end = a, b
        sc.render.use_overwrite = o["overwrite"]
        sc.render.use_placeholder = not o["overwrite"]
        bpy.ops.render.render(animation=True)
    else:
        for f in [int(x) for x in fr.split(",")]:
            path = os.path.join(o["out"], f"frame_{f:04d}.png")
            if os.path.exists(path) and not o["overwrite"]:
                continue
            sc.frame_set(f)
            sc.render.filepath = path
            t = time.time()
            bpy.ops.render.render(write_still=True)
            print(f"[render] frame {f} {time.time() - t:.1f}s", flush=True)
    print(f"[render] done in {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
