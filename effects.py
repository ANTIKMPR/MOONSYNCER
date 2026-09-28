"""
VIBE-SYNC effects — a generalized version of the idea in camera_shake.py: a
list of timestamps in the track (defined in the package's sync.json, see
vibesync.py) at which a visual "glitch" fires for a given duration.

Unlike camera_shake.py (which supports exactly one effect — a zoom-punch),
here the list of effects and their parameters comes entirely from the
package — adding a new effect type doesn't require changes to the player,
just adding a renderer function to EFFECT_RENDERERS below.

Format of a single effect in sync.json's "effects" list:

    {
      "type": "rgb_split",       # type — see EFFECT_RENDERERS
      "at": 12.5,                # second in the track at which it triggers
      "duration": 0.3,           # how many seconds it lasts (defaults to DEFAULT_DURATION_SEC)
      "params": {"amplitude": 8} # parameters specific to this effect type
    }

Each renderer receives a pygame.Surface with the already-drawn frame, its
own params, and an intensity (1.0 at the moment it fires, smoothly decaying
to 0.0), and returns a new surface with the effect applied. window_shake is
a special case: it doesn't touch the frame's contents, instead it returns an
offset (dx, dy) for the final blit of the whole window (see window_offset
below, the same idea as cam_shake.scale in main.py).
"""

import random

import numpy as np
import pygame


DEFAULT_DURATION_SEC = 0.25     # effect duration if "duration" isn't set in the package
HIT_MATCH_WINDOW_SEC = 0.12     # how closely the track position must match the "at" marker
WINDOW_SHAKE_TYPE = "window_shake"  # special type — not rendered onto a surface, see window_offset


def _decay(progress: float) -> float:
    """Shared intensity decay curve for effects — a sharp peak at the
    start, fast falloff toward the end (same as camera_shake.py, so at high
    BPM effects don't blur together into constant noise)."""
    return (1.0 - progress) ** 2


def _render_rgb_split(surface: pygame.Surface, params: dict, intensity: float) -> pygame.Surface:
    """Chromatic aberration: splits the frame's R/G/B channels apart horizontally."""
    amplitude = round(params.get("amplitude", 8) * intensity)
    if amplitude <= 0:
        return surface

    w, h = surface.get_size()
    red = surface.copy()
    red.fill((255, 0, 0, 255), special_flags=pygame.BLEND_MULT)
    green = surface.copy()
    green.fill((0, 255, 0, 255), special_flags=pygame.BLEND_MULT)
    blue = surface.copy()
    blue.fill((0, 0, 255, 255), special_flags=pygame.BLEND_MULT)

    result = pygame.Surface((w, h))
    result.blit(red, (-amplitude, 0), special_flags=pygame.BLEND_ADD)
    result.blit(green, (0, 0), special_flags=pygame.BLEND_ADD)
    result.blit(blue, (amplitude, 0), special_flags=pygame.BLEND_ADD)
    return result


def _render_scanline_tear(surface: pygame.Surface, params: dict, intensity: float) -> pygame.Surface:
    """Tears the frame into horizontal bands and shifts each sideways —
    a classic VHS-style glitch."""
    max_offset = round(params.get("amplitude", 20) * intensity)
    band_height = max(2, int(params.get("band_height", 10)))
    if max_offset <= 0:
        return surface

    w, h = surface.get_size()
    result = pygame.Surface((w, h))
    result.fill((0, 0, 0))
    y = 0
    while y < h:
        band_h = min(band_height, h - y)
        offset = random.randint(-max_offset, max_offset)
        band = surface.subsurface((0, y, w, band_h))
        result.blit(band, (offset, y))
        y += band_h
    return result


def _render_chroma_noise(surface: pygame.Surface, params: dict, intensity: float) -> pygame.Surface:
    """Overlays colored digital noise on top of the frame, with opacity
    proportional to the effect's intensity."""
    strength = max(0.0, min(1.0, params.get("strength", 0.5))) * intensity
    if strength <= 0.01:
        return surface

    w, h = surface.get_size()
    noise = np.random.randint(0, 255, (w, h, 3), dtype=np.uint8)
    noise_surface = pygame.surfarray.make_surface(noise)
    noise_surface.set_alpha(round(255 * strength))

    result = surface.copy()
    result.blit(noise_surface, (0, 0))
    return result


# Registry of renderers by effect type — adding a new glitch type just
# means adding one function here, with no changes to the rest of EffectsEngine.
EFFECT_RENDERERS = {
    "rgb_split": _render_rgb_split,
    "scanline_tear": _render_scanline_tear,
    "chroma_noise": _render_chroma_noise,
}


class _ActiveEffect:
    """A single currently-playing effect instance (an effect may have
    fired even if the track has since moved on to another hit — tracked
    independently of the marker list so nearby-in-time effects don't cut
    each other off)."""

    __slots__ = ("type", "params", "started_at_ms", "duration_ms")

    def __init__(self, effect_type: str, params: dict, started_at_ms: int, duration_ms: int):
        self.type = effect_type
        self.params = params
        self.started_at_ms = started_at_ms
        self.duration_ms = duration_ms

    def intensity(self, now_ms: int) -> float | None:
        """None — the effect has already finished and should be dropped
        from the active list."""
        elapsed = now_ms - self.started_at_ms
        if elapsed >= self.duration_ms:
            return None
        return _decay(elapsed / self.duration_ms)


class EffectsEngine:
    """
    Analogous to CameraShake, but for an arbitrary set of typed effects at
    once. Tracks the list of markers (effects) for the current track, each
    frame triggers any whose "at" marker is already behind the current
    position, and keeps the list of currently-active effects that need to
    be applied to the frame.
    """

    def __init__(self):
        self._effects: list[dict] = []
        self._next_idx = 0
        self._active: list[_ActiveEffect] = []
        self._track_key = None
        self._last_position_sec = None  # for auto-reset on a backward position jump — see update()

    def set_effects(self, effects: list[dict], track_key):
        """
        Sets the list of effects (in sync.json format, see the module
        docstring) for a new track. Like CameraShake.set_hits — can be
        called every frame, an actual reset only happens when track_key
        changes.
        """
        if track_key == self._track_key:
            return
        self._track_key = track_key
        self._effects = sorted(
            (e for e in (effects or []) if isinstance(e, dict) and "type" in e and "at" in e),
            key=lambda e: e["at"],
        )
        self._next_idx = 0
        self._active = []
        self._last_position_sec = None

    def clear(self):
        """Resets state (track with no effects / track ended)."""
        self._effects = []
        self._next_idx = 0
        self._active = []
        self._track_key = None
        self._last_position_sec = None

    def update(self, position_sec: float):
        """Called every frame with the current playback position — fires
        markers that have been reached and drops expired ones from the
        active list.

        If the position jumps BACKWARD (rewind, or the track was restarted
        with the same track_key — set_effects doesn't reset anything in
        that case, since it's treated as the same track) — we call
        notify_seek() ourselves, otherwise after replaying a track a few
        times _next_idx would run off the end of the list and effects
        would stop firing."""
        if self._last_position_sec is not None and position_sec < self._last_position_sec - HIT_MATCH_WINDOW_SEC:
            self.notify_seek(position_sec)
        self._last_position_sec = position_sec

        now = pygame.time.get_ticks()

        while (
            self._next_idx < len(self._effects)
            and self._effects[self._next_idx]["at"] <= position_sec + HIT_MATCH_WINDOW_SEC
        ):
            self._trigger(self._effects[self._next_idx], now)
            self._next_idx += 1

        self._active = [a for a in self._active if a.intensity(now) is not None]

    def notify_seek(self, new_position_sec: float):
        """Like CameraShake.notify_seek — recalculates which marker to
        continue from after a seek, and cuts off all currently-active
        effects."""
        idx = 0
        while idx < len(self._effects) and self._effects[idx]["at"] < new_position_sec:
            idx += 1
        self._next_idx = idx
        self._active = []

    def _trigger(self, effect: dict, now_ms: int):
        duration_ms = round(float(effect.get("duration", DEFAULT_DURATION_SEC)) * 1000)
        params = effect.get("params") or {}
        self._active.append(_ActiveEffect(effect["type"], params, now_ms, duration_ms))

    def apply(self, surface: pygame.Surface) -> pygame.Surface:
        """Runs the frame through every currently-active visual effect
        (except window_shake — see window_offset). If there are no active
        effects, returns the surface as-is, with no unnecessary copies."""
        if not self._active:
            return surface

        now = pygame.time.get_ticks()
        for active in self._active:
            renderer = EFFECT_RENDERERS.get(active.type)
            if renderer is None:
                continue  # window_shake and any unknown types are not rendered onto the frame
            intensity = active.intensity(now)
            if intensity is None:
                continue
            surface = renderer(surface, active.params, intensity)
        return surface

    @property
    def window_offset(self) -> tuple[int, int]:
        """Combined (dx, dy) offset for the window from any active
        window_shake effects — main.py adds this to the final blit
        position of the frame on screen (the same idea as cam_shake.scale)."""
        now = pygame.time.get_ticks()
        dx = dy = 0
        for active in self._active:
            if active.type != WINDOW_SHAKE_TYPE:
                continue
            intensity = active.intensity(now)
            if intensity is None:
                continue
            strength = round(active.params.get("strength", 6) * intensity)
            if strength > 0:
                dx += random.randint(-strength, strength)
                dy += random.randint(-strength, strength)
        return dx, dy

    @property
    def is_active(self) -> bool:
        return bool(self._active)
