"""
"Camera hits" — a short zoom-punch effect applied to the player screen at
moments defined by a VIBE-SYNC package (camera_hits: a list of seconds in
the track, either manual or generated from BPM — see vibesync.py). On a hit
the screen quickly zooms in (or out — see ZOOM_DIRECTION) and smoothly eases
back to normal scale — like a "pulse" in time with the music.
"""

import pygame


SHAKE_DURATION_MS = 180        # how long a single scale "pulse" lasts
ZOOM_MAX_DELTA = 0.06          # max scale change at the peak of a hit (0.06 = +-6%)
ZOOM_DIRECTION = 1             # 1 = zoom-in on a hit, -1 = zoom-out
HIT_MATCH_WINDOW_SEC = 0.12    # how closely the track position must match a hit marker

class CameraShake:
    """
    Tracks the list of hit markers (camera_hits) for the current track and
    keeps the current screen scale multiplier (1.0 = no effect), which
    main.py uses to scale the frame around its center for the "pulse"
    effect in time with the beat.
    """

    def __init__(self):
        self._hits: list[float] = []
        self._next_hit_idx = 0
        self._active_shake_started_at = None
        self._current_scale = 1.0
        self._track_key = None  # anything unique to the current track, to know when to reset state
        self._last_position_sec = None  # for auto-reset on a backward position jump — see update()

    def set_hits(self, hits: list[float], track_key):
        """
        Sets the list of hit markers (in seconds) for a new track. track_key
        is any value that uniquely identifies the track (e.g. the file
        path) — used so progress isn't reset if the same track is still
        playing (set_hits can be called every frame from main.py for
        simplicity — an actual reset only happens when the track changes).
        """
        if track_key == self._track_key:
            return
        self._track_key = track_key
        self._hits = sorted(hits) if hits else []
        self._next_hit_idx = 0
        self._active_shake_started_at = None
        self._current_scale = 1.0
        self._last_position_sec = None

    def clear(self):
        """Resets state (e.g. when the VIBE-SYNC track ends / has no hits)."""
        self._hits = []
        self._next_hit_idx = 0
        self._active_shake_started_at = None
        self._current_scale = 1.0
        self._track_key = None
        self._last_position_sec = None

    def update(self, position_sec: float):
        """
        Called every frame with the current playback position — advances
        the pointer through the hit markers and starts a new "pulse" when
        the position catches up to the next one. Doesn't rely on an exact
        match (the player isn't sample-accurate with the audio), just on
        "has the current position reached the nearest not-yet-triggered
        marker".

        If the position jumps BACKWARD (rewind, or the track was restarted
        with the same track_key — set_hits doesn't reset anything in that
        case, since it's still the same track) — we re-arm the pointer
        ourselves, same as notify_seek(). Without this, replaying the same
        track repeatedly would gradually exhaust _next_hit_idx and hits
        would stop triggering.
        """
        if self._last_position_sec is not None and position_sec < self._last_position_sec - HIT_MATCH_WINDOW_SEC:
            self.notify_seek(position_sec)
        self._last_position_sec = position_sec

        now = pygame.time.get_ticks()

        # Trigger every marker that is already "behind" the current
        # position — in case of an FPS drop or a position jump (e.g. after
        # a seek), don't silently skip a hit, just fire it once right away.
        while self._next_hit_idx < len(self._hits) and self._hits[self._next_hit_idx] <= position_sec + HIT_MATCH_WINDOW_SEC:
            self._trigger_shake(now)
            self._next_hit_idx += 1

        self._current_scale = self._compute_scale(now)

    def notify_seek(self, new_position_sec: float):
        """
        Called on a seek — recalculates which marker to continue from
        (otherwise, after seeking forward the player would try to
        "belatedly" fire every skipped hit at once, and after seeking
        backward it wouldn't replay markers already passed).
        """
        # Find the first marker that's still ahead of the new position
        idx = 0
        while idx < len(self._hits) and self._hits[idx] < new_position_sec:
            idx += 1
        self._next_hit_idx = idx
        self._active_shake_started_at = None
        self._current_scale = 1.0

    def _trigger_shake(self, now_ms: int):
        self._active_shake_started_at = now_ms

    def _compute_scale(self, now_ms: int) -> float:
        if self._active_shake_started_at is None:
            return 1.0

        elapsed = now_ms - self._active_shake_started_at
        if elapsed >= SHAKE_DURATION_MS:
            self._active_shake_started_at = None
            return 1.0

        progress = elapsed / SHAKE_DURATION_MS
        # Quadratic decay — a sharp scale jump at the start of the hit and
        # a fast ease back to normal size, which reads as a crisp "pulse"
        # rather than a slow breathing motion (important at high BPM,
        # where hits come often and shouldn't visually blur together).
        intensity = (1.0 - progress) ** 2
        return 1.0 + ZOOM_DIRECTION * ZOOM_MAX_DELTA * intensity

    @property
    def scale(self) -> float:
        """Current screen scale multiplier (1.0 = no effect) — use this to
        scale the frame up/down around its center when drawing."""
        return self._current_scale

    @property
    def is_active(self) -> bool:
        return self._active_shake_started_at is not None
