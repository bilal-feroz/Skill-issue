"""Validate deliverables: frame sequence, final MP4, and (optionally) the .blend.

    python scripts/validate_project.py [--video renders/skill_issue_final.mp4] [--frames renders/frames]
    blender -b project/skill_issue.blend -P scripts/validate_project.py -- --blend
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK, BAD = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((OK if cond else BAD, name, detail))
    print(f"[{OK if cond else BAD}] {name} {detail}", flush=True)
    return cond


def frames(dirname):
    names = [f"frame_{i:04d}.png" for i in range(1, 721)]
    missing = [n for n in names if not os.path.exists(os.path.join(dirname, n))]
    check("frame sequence complete (720)", not missing, f"missing={len(missing)}")
    if missing:
        return
    sizes = [os.path.getsize(os.path.join(dirname, n)) for n in names]
    tiny = [i + 1 for i, s in enumerate(sizes) if s < 2000]
    check("no empty/placeholder frames", not tiny, f"tiny={tiny[:10]}")
    from PIL import Image
    dims = {Image.open(os.path.join(dirname, n)).size for n in names[::60] + [names[-1]]}
    check("consistent frame size", len(dims) == 1, str(dims))


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
                          "-of", "json", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def video(path):
    if not check("video exists", os.path.exists(path), path):
        return
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    check("H.264 video", v["codec_name"] == "h264", v["codec_name"])
    check("resolution 1920x1080", (v["width"], v["height"]) == (1920, 1080), f"{v['width']}x{v['height']}")
    check("24 fps", v["r_frame_rate"] in ("24/1", "24000/1000"), v["r_frame_rate"])
    check("720 frames", int(v.get("nb_read_frames", 0)) == 720, v.get("nb_read_frames"))
    check("yuv420p", v["pix_fmt"] == "yuv420p", v["pix_fmt"])
    dur = float(info["format"]["duration"])
    check("duration 30.0 s", abs(dur - 30.0) < 0.05, f"{dur:.3f}s")
    check("audio present (AAC)", bool(a) and a[0]["codec_name"] == "aac", a[0]["codec_name"] if a else "none")
    if a:
        adur = float(a[0].get("duration", 0))
        check("audio duration ~30 s", abs(adur - 30.0) < 0.06, f"{adur:.3f}s")
    err = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True, text=True).stderr
    check("decodes without errors", not err.strip(), err.strip()[:200])
    bd = subprocess.run(["ffmpeg", "-i", path, "-vf", "blackdetect=d=0.25:pix_th=0.04", "-an", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    blacks = [l for l in bd.splitlines() if "black_start" in l]
    # the title card is intentionally (mostly) black from 28.0 s
    unexpected = [l for l in blacks if float(l.split("black_start:")[1].split()[0]) < 27.9]
    check("no unintended black sections", not unexpected, "; ".join(unexpected)[:300])


def blend():
    import bpy
    sc = bpy.context.scene
    check("frame range 1-720", (sc.frame_start, sc.frame_end) == (1, 720), f"{sc.frame_start}-{sc.frame_end}")
    check("24 fps", sc.render.fps == 24 and sc.render.fps_base == 1.0)
    check("camera markers bound", all(m.camera for m in sc.timeline_markers) and len(sc.timeline_markers) >= 28,
          f"{len(sc.timeline_markers)} markers")
    missing = []
    for img in bpy.data.images:
        if img.source in ('FILE', 'SEQUENCE') and img.filepath:
            p = bpy.path.abspath(img.filepath)
            if not os.path.exists(p):
                missing.append(img.filepath)
    check("no missing image files", not missing, str(missing[:5]))
    fonts = [f.filepath for f in bpy.data.fonts if f.filepath and f.filepath != "<builtin>" and not f.packed_file
             and not os.path.exists(bpy.path.abspath(f.filepath))]
    check("no missing fonts", not fonts, str(fonts))
    check("speed controller present", "SPEED_CONTROLLER" in bpy.data.objects)
    check("crowd GN present", "GN_Crowd" in bpy.data.objects and bpy.data.objects["GN_Crowd"].modifiers)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if "--blend" in argv:
        blend()
    else:
        vpath = os.path.join(ROOT, "renders", "skill_issue_final.mp4")
        fdir = None
        for i, x in enumerate(argv):
            if x == "--video":
                vpath = argv[i + 1]
            if x == "--frames":
                fdir = argv[i + 1]
        if fdir:
            frames(fdir)
        video(vpath)
    bad = [r for r in results if r[0] == BAD]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    if bad and "--blend" not in argv:
        sys.exit(1)


if __name__ == "__main__":
    main()
