"""Caption overlay for the whisper (composited in Blender's compositor).

    python scripts/generate_captions.py   ->  assets/screens/caption_whisper.png (1920x1080 RGBA)
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from skill_issue import timeline as T  # noqa: E402


def main():
    W, H = 1920, 1080
    text = "“" + T.WHISPER_LINE + "”"
    font = ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", "Inter.woff2"), 46)
    font.set_variation_by_axes([24, 420])
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tw = d.textlength(text, font=font)
    x, y = (W - tw) / 2, H - 150
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((x + 2, y + 3), text, font=font, fill=(0, 0, 0, 200))
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    img = Image.alpha_composite(shadow, img)
    ImageDraw.Draw(img).text((x, y), text, font=font, fill=(240, 238, 232, 255))
    out = os.path.join(ROOT, "assets", "screens", "caption_whisper.png")
    img.save(out)
    print(out)


if __name__ == "__main__":
    main()
