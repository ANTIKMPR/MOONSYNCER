"""
Loads the app's custom font (Bildungswirkung-Regular.otf), falling back to
the system Arial if the file is missing or fails to load.

The font lives in resources/font/ next to the other resources (logo, icon) —
the path is resolved relative to main.py's location, not hardcoded to a
specific machine/user.
"""

import os
import pygame


_cache: dict[tuple[str, int, bool], pygame.font.Font] = {}


def get_font(base_dir: str, size: int, bold: bool = False) -> pygame.font.Font:
    """
    Returns the app's custom font at the requested size. Results are
    cached (creating a Font is not free, and the same size is usually
    requested every single frame).

    If the .otf file is missing or pygame fails to read it, this quietly
    falls back to the system Arial so the app doesn't crash on machines
    without that file in resources/font/.
    """
    cache_key = (base_dir, size, bold)
    if cache_key in _cache:
        return _cache[cache_key]

    font_path = os.path.join(base_dir, "resources", "font", "Bildungswirkung-Regular.otf")

    try:
        font = pygame.font.Font(font_path, size)
        # The custom .otf has no separate bold weight — emulate it via SDL
        if bold:
            font.set_bold(True)
    except Exception as e:
        print(f"[VIBEMP3] Failed to load font ({font_path}): {e}")
        font = pygame.font.SysFont("Arial", size, bold=bold)

    _cache[cache_key] = font
    return font
