"""Rebuild StickLLM boot splash: brand upper third, lower band clear for menu."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ISO = os.path.join(ROOT, "boot", "isolinux", "splash.png")
OUT_GRUB = os.path.join(ROOT, "boot", "grub", "splash.png")

W, H = 640, 480
BG = (15, 20, 16)
BAR = (61, 204, 122)
INK = (232, 240, 233)
MUTED = (143, 163, 150)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        ("segoeuib.ttf", "segoeui.ttf"),
        ("arialbd.ttf", "arial.ttf"),
        ("calibrib.ttf", "calibri.ttf"),
    )
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for bold_name, regular in names:
        path = os.path.join(windir, "Fonts", bold_name if bold else regular)
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> None:
    os.makedirs(os.path.dirname(OUT_GRUB), exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 4], fill=BAR)

    ft_brand = font(64, bold=True)
    ft_tag = font(22, bold=False)
    brand, tag = "StickLLM", "Privacy AI USB"

    def center_text(y: int, text: str, fnt, fill) -> int:
        bbox = d.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text(((W - tw) // 2, y), text, font=fnt, fill=fill)
        return th

    # Upper third only — leave lower ~40% empty for vesamenu / GRUB entries.
    y_brand = 88
    center_text(y_brand, brand, ft_brand, INK)
    # Use fixed gap (textbbox height can under-count with some fonts).
    center_text(y_brand + 78, tag, ft_tag, MUTED)

    img.save(OUT_ISO, "PNG")
    img.save(OUT_GRUB, "PNG")
    print(f"wrote {OUT_ISO}")
    print(f"wrote {OUT_GRUB}")


if __name__ == "__main__":
    main()
