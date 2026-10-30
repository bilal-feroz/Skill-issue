"""Tile rendered frames into a labelled contact sheet for review.

    python scripts/contact_sheet.py <frames_dir> <out.jpg> [--cols 3] [--width 640] [frame numbers...]
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from skill_issue import timeline as T  # noqa: E402


def main():
    a = sys.argv[1:]
    src, out = a[0], a[1]
    cols, width = 3, 640
    frames = []
    i = 2
    while i < len(a):
        if a[i] == "--cols":
            cols = int(a[i + 1]); i += 1
        elif a[i] == "--width":
            width = int(a[i + 1]); i += 1
        else:
            frames.append(int(a[i]))
        i += 1
    files = sorted(f for f in os.listdir(src) if f.endswith(".png"))
    if frames:
        files = [f"frame_{n:04d}.png" for n in frames if os.path.exists(os.path.join(src, f"frame_{n:04d}.png"))]
    ims = []
    font = ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", "Inter.woff2"), 18)
    for f in files:
        im = Image.open(os.path.join(src, f)).convert("RGB")
        h = int(im.height * width / im.width)
        im = im.resize((width, h))
        n = int(f[6:10])
        d = ImageDraw.Draw(im)
        label = f"{n}  {T.shot_at(n)['id']}"
        d.rectangle((0, 0, 140, 26), fill=(0, 0, 0))
        d.text((6, 3), label, font=font, fill=(255, 220, 120))
        ims.append(im)
    rows = (len(ims) + cols - 1) // cols
    W = Image.new("RGB", (cols * width, rows * ims[0].height), (20, 20, 20))
    for k, im in enumerate(ims):
        W.paste(im, ((k % cols) * width, (k // cols) * im.height))
    W.save(out, quality=88)
    print(out, len(ims))


if __name__ == "__main__":
    main()
