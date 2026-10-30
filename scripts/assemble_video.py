"""Mux rendered frames + soundtrack into the final MP4 with FFmpeg.

    python scripts/assemble_video.py [--frames renders/frames] [--audio audio/skill_issue_mix.wav]
                                     [--out renders/skill_issue_final.mp4] [--crf 16]
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=os.path.join(ROOT, "renders", "frames"))
    ap.add_argument("--audio", default=os.path.join(ROOT, "audio", "skill_issue_mix.wav"))
    ap.add_argument("--out", default=os.path.join(ROOT, "renders", "skill_issue_final.mp4"))
    ap.add_argument("--crf", default="16")
    ap.add_argument("--scale", default=None, help="e.g. 1920:1080 to force a size")
    a = ap.parse_args()
    missing = [f for f in range(1, 721) if not os.path.exists(os.path.join(a.frames, f"frame_{f:04d}.png"))]
    if missing:
        sys.exit(f"missing {len(missing)} frames, first: {missing[:10]}")
    vf = ["format=yuv420p"]
    if a.scale:
        vf.insert(0, f"scale={a.scale}:flags=lanczos")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", "24", "-start_number", "1", "-i", os.path.join(a.frames, "frame_%04d.png"),
           "-i", a.audio,
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", "slow", "-crf", a.crf, "-tune", "animation",
           "-vf", ",".join(vf), "-r", "24",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
           "-t", "30", "-movflags", "+faststart", a.out]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print("wrote", a.out, os.path.getsize(a.out) // 1024, "KB")


if __name__ == "__main__":
    main()
