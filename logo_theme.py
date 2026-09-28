"""
Generates a light version of the logo from the dark original (BigLogo.png)
on the fly.

Idea: do NOT invert the RGB channels wholesale (that breaks colored accents —
e.g. purple would turn yellow-green). Instead, invert only the luminance,
keeping hue and transparency intact:
  - white/light pixels (usually the logo's text/lines on a dark background) -> dark
  - the alpha channel is left untouched, so transparency stays as-is

The result is cached to disk (BigLogo.light.png) next to the original, so it
isn't recomputed on every launch.
"""

import os
from PIL import Image, ImageOps


def get_logo_path_for_theme(dark_logo_path: str, theme: str) -> str:
    """
    Returns the logo path for the given theme ('dark' or 'light').
    For 'light' — generates (if not already generated) and caches the
    light version. If anything goes wrong (source missing, PIL error) —
    returns the original dark_logo_path as a safe fallback.
    """
    if theme != "light":
        return dark_logo_path

    base, ext = os.path.splitext(dark_logo_path)
    light_path = f"{base}.light{ext}"

    if os.path.isfile(light_path):
        return light_path

    if not os.path.isfile(dark_logo_path):
        return dark_logo_path

    try:
        _generate_light_logo(dark_logo_path, light_path)
        return light_path
    except Exception as e:
        print(f"[VIBEMP3] Failed to generate light logo: {e}")
        return dark_logo_path


def _generate_light_logo(src_path: str, dst_path: str):
    img = Image.open(src_path).convert("RGBA")
    r, g, b, a = img.split()

    rgb = Image.merge("RGB", (r, g, b))
    inverted_rgb = ImageOps.invert(rgb)

    result = Image.merge("RGBA", (*inverted_rgb.split(), a))
    result.save(dst_path)
