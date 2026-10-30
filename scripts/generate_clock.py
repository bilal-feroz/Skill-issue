"""Digital desk-clock display frames, driven by the speed system's clock channel.

    python scripts/generate_clock.py      ->  assets/screens/clock/clock_0001.png .. 0720
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from skill_issue import speed as S, timeline as T  # noqa: E402

OUT = os.path.join(ROOT, "assets", "screens", "clock")
W, H = 260, 100
# seven-segment layout: (x0, y0, x1, y1) in a 40 x 70 cell
SEG = {
    "a": (6, 0, 34, 6), "b": (34, 4, 40, 33), "c": (34, 37, 40, 66), "d": (6, 64, 34, 70),
    "e": (0, 37, 6, 66), "f": (0, 4, 6, 33), "g": (6, 32, 34, 38),
}
DIGITS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
          "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", " ": ""}
ON = (255, 60, 40)
OFF = (38, 8, 6)


def draw_digit(d, ch, ox, oy, s=1.0):
    for name, (x0, y0, x1, y1) in SEG.items():
        col = ON if name in DIGITS[ch] else OFF
        d.rounded_rectangle((ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s), radius=2, fill=col)


def main():
    os.makedirs(OUT, exist_ok=True)
    c = S.compute()
    small = ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", "Inter.woff2"), 15)
    small.set_variation_by_axes([14, 700])
    for f in c["frames"]:
        mins = S.value(c, "clock_minutes", f)
        txt = S.clock_string(mins)               # e.g. "9:05 PM"
        hm, ampm = txt.split(" ")
        h, m = hm.split(":")
        digits = f"{int(h):>2}{m}"
        img = Image.new("RGB", (W, H), (4, 2, 2))
        d = ImageDraw.Draw(img)
        x = 14
        for i, ch in enumerate(digits):
            draw_digit(d, ch, x, 15, 1.0)
            x += 50
            if i == 1:
                blink = (f // 12) % 2 == 0 or S.value(c, "speed", f) > 0.3
                col = ON if blink else OFF
                d.ellipse((x - 6, 32, x, 38), fill=col)
                d.ellipse((x - 6, 52, x, 58), fill=col)
                x += 6
        d.text((222, 18), "PM", font=small, fill=ON if ampm == "PM" else OFF)
        d.text((222, 62), "AM", font=small, fill=ON if ampm == "AM" else OFF)
        img.save(os.path.join(OUT, f"clock_{f:04d}.png"), optimize=True)
    print("clock frames:", len(c["frames"]))


if __name__ == "__main__":
    main()
