"""One command to reproduce the film end to end.

    python scripts/run_pipeline.py [--blender PATH] [--preset final|preview|draft] [--skip-render]

Steps: screen graphics -> clock digits -> caption -> soundtrack -> build .blend ->
render frames (resumable) -> mux MP4 -> validate.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"


def run(cmd):
    print(">>", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=shutil.which("blender") or DEFAULT_BLENDER)
    ap.add_argument("--preset", default="final")
    ap.add_argument("--skip-render", action="store_true")
    a = ap.parse_args()
    py = sys.executable
    s = lambda name: os.path.join(ROOT, "scripts", name)
    run([py, s("generate_screens.py")])
    run([py, s("generate_clock.py")])
    run([py, s("generate_captions.py")])
    run([py, s("generate_audio.py")])
    run([a.blender, "-b", "--factory-startup", "-P", s("build_scene.py"), "--", "--preset", a.preset])
    if a.skip_render:
        return
    frames = os.path.join(ROOT, "renders", "frames")
    run([a.blender, "-b", os.path.join(ROOT, "project", "skill_issue.blend"), "-P", s("render_frames.py"),
         "--", "--preset", a.preset, "--frames", "1-720", "--out", frames])
    run([py, s("assemble_video.py"), "--frames", frames])
    run([py, s("validate_project.py"), "--frames", frames])


if __name__ == "__main__":
    main()
