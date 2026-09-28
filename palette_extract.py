"""
Extracts a theme palette (bg/accent/text) from an album cover using a
simple color-quantization algorithm — no external ML models, so heavy
dependencies aren't dragged into the packer utility.

Approach:
  1. The image is downscaled and quantized by Pillow into a small number of
     dominant-color clusters (Image.quantize — a fast k-means-like method
     based on median cut).
  2. Each cluster is scored by (pixel share, saturation, brightness) in HSV
     to separate the roles:
       - bg     — the "heaviest" muted/dark cluster (low-to-medium
                  saturation, not the lightest) — what visually reads as
                  the "background" of the cover
       - accent — the cluster with the highest saturation among reasonably
                  visible ones (clusters covering < ACCENT_MIN_SHARE of
                  pixels are ignored — otherwise a stray noise pixel could
                  become the accent)
       - text   — not derived from a cover cluster, but computed as a
                  contrast to the already-chosen bg (black or white —
                  whichever gives the better WCAG contrast), because the
                  cover itself rarely contains a "good UI text color"
"""

import colorsys

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


QUANTIZE_COLORS = 8       # number of clusters to split the image into
RESIZE_MAX_SIDE = 150     # downscale before analysis — quantization doesn't need full resolution
ACCENT_MIN_SHARE = 0.02   # a cluster must cover at least 2% of pixels to qualify as accent


class PaletteExtractError(Exception):
    """Failed to extract a palette from the image."""


def extract_palette(image_path: str) -> dict[str, tuple[int, int, int]]:
    """
    Returns {"bg": (r,g,b), "accent": (r,g,b), "text": (r,g,b)} — a ready
    set to plug into all three ColorSwatchInputs at once. Raises
    PaletteExtractError if Pillow is unavailable or the image couldn't be
    read.
    """
    if not PIL_AVAILABLE:
        raise PaletteExtractError(
            "Palette extraction requires the Pillow module: pip install pillow"
        )

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        raise PaletteExtractError(f"Failed to open image: {e}") from e

    img.thumbnail((RESIZE_MAX_SIDE, RESIZE_MAX_SIDE))

    try:
        quantized = img.quantize(colors=QUANTIZE_COLORS, method=Image.MEDIANCUT)
    except Exception as e:
        raise PaletteExtractError(f"Failed to quantize image colors: {e}") from e

    palette_raw = quantized.getpalette()[: QUANTIZE_COLORS * 3]
    color_counts = quantized.getcolors(maxcolors=QUANTIZE_COLORS)  # [(count, palette_index), ...]
    if not color_counts:
        raise PaletteExtractError("The image contains no color data.")

    total_pixels = sum(count for count, _ in color_counts)

    clusters = []
    for count, idx in color_counts:
        r, g, b = palette_raw[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        clusters.append({
            "rgb": (r, g, b),
            "share": count / total_pixels,
            "hue": h,
            "sat": s,
            "val": v,
        })

    bg_cluster = _pick_bg_cluster(clusters)
    accent_cluster = _pick_accent_cluster(clusters, exclude_rgb=bg_cluster["rgb"])
    text_rgb = _contrasting_text_color(bg_cluster["rgb"])

    return {
        "bg": bg_cluster["rgb"],
        "accent": accent_cluster["rgb"],
        "text": text_rgb,
    }


def _pick_bg_cluster(clusters: list[dict]) -> dict:
    """
    bg — the most visible (by pixel share) cluster among those that don't
    look like a "bright accent splash": pure high saturation is penalized,
    so the background doesn't accidentally become the loudest color of the
    cover, even if it covers a large area.
    """
    def bg_score(c):
        # prefer a high pixel share, but lower the score for strongly
        # saturated and very light clusters — those are usually the
        # "accent" of a cover rather than its "background"
        saturation_penalty = c["sat"] * 0.5
        brightness_penalty = max(0.0, c["val"] - 0.85) * 0.5  # penalize only near-white
        return c["share"] - saturation_penalty - brightness_penalty

    return max(clusters, key=bg_score)


def _pick_accent_cluster(clusters: list[dict], exclude_rgb: tuple[int, int, int]) -> dict:
    """
    accent — the most saturated cluster among reasonably visible ones (not
    microscopic noise) that differs from the already-chosen bg. If all
    candidates get filtered out (a single-color cover) — take the most
    saturated of all, including small ones.
    """
    candidates = [c for c in clusters if c["rgb"] != exclude_rgb and c["share"] >= ACCENT_MIN_SHARE]
    if not candidates:
        candidates = [c for c in clusters if c["rgb"] != exclude_rgb] or clusters

    return max(candidates, key=lambda c: c["sat"] * (0.4 + c["val"]))


def _contrasting_text_color(bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """
    Returns near-white or near-black — whichever gives better contrast
    against bg_rgb by relative luminance (simplified WCAG luminance).
    Not pure #FFFFFF/#000000 but slightly softened tones (in the spirit of
    the default theme values in vibesync.py: text = (240, 240, 245)).
    """
    r, g, b = bg_rgb
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if luminance > 0.5:
        return (25, 25, 30)
    return (240, 240, 245)
