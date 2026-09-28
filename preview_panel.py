"""
Live preview panel — shows, to the right of the form, how the VIBEMP3
screen will look with the current settings (theme + camera hits + glitch
effects), without exporting a .zip or opening the main player.

Uses the same engines as the player itself (camera_shake.py, effects.py —
this package's own copies, see their docstrings about VIBESYNCER being
self-contained), but not the player itself — the track is played directly
through pygame.mixer.music, and the "screen" is just a filled mini
rectangle with the file name and a progress line, which is enough to see
how the frame jerks/flashes under the effects.

Position is computed from the system clock since pygame.mixer.music.play()
— not perfectly accurate (doesn't account for decoder pauses), but enough
for previewing settings and doesn't pull in extra dependencies.
"""

import json
import os

import pygame

import camera_shake
import effects
from ui import Button


class PreviewPanel:
    def __init__(self, rect: pygame.Rect):
        self.rect = rect
        self._layout(rect)

        self.cam_shake = camera_shake.CameraShake()
        self.fx_engine = effects.EffectsEngine()

        self._audio_path: str | None = None
        self._duration_sec: float | None = None
        self._playing = False
        self._start_ticks = 0
        self._play_error: str | None = None

    def _layout(self, rect: pygame.Rect):
        """(Re)computes the geometry of child elements for rect — called
        from both __init__ and set_rect() when the window is resized."""
        self.rect = rect
        screen_w = rect.width - 40
        screen_h = min(round(screen_w * 0.62), rect.height - 90)
        self._mock_rect = pygame.Rect(rect.x + 20, rect.y + 20, screen_w, max(80, screen_h))

        btn_w, btn_h = 110, 34
        button_rect = pygame.Rect(rect.x + 20, self._mock_rect.bottom + 16, btn_w, btn_h)
        if hasattr(self, "_play_button"):
            self._play_button.rect = button_rect
        else:
            self._play_button = Button(button_rect, "Play")
        self._status_y = self._play_button.rect.bottom + 14

    def set_rect(self, new_rect: pygame.Rect):
        """Repositions the panel (the window was resized) without recreating
        the engines/playback state."""
        self._layout(new_rect)

    @property
    def bottom(self) -> int:
        """Y coordinate of the bottom edge of the panel's visible content —
        main.py places the "Build .zip" button right below it."""
        return self._play_button.rect.bottom

    @property
    def duration_sec(self) -> float | None:
        return self._duration_sec

    def set_audio(self, path: str | None):
        """Call every frame with the current path from audio_row — if the
        file changed, stops playback and recomputes the duration."""
        if path == self._audio_path:
            return
        if self._playing:
            pygame.mixer.music.stop()
            self._playing = False
        self._audio_path = path
        self._duration_sec = None
        self._play_error = None
        if path and os.path.isfile(path):
            try:
                self._duration_sec = pygame.mixer.Sound(path).get_length()
            except pygame.error:
                self._duration_sec = None  # duration unknown — BPM-based hit generation in the preview gets disabled

    def handle_hover(self, mouse_pos):
        self._play_button.handle_hover(mouse_pos)

    def handle_event(self, event, mouse_pos) -> bool:
        if self._play_button.is_clicked(mouse_pos, event):
            self._toggle_play()
            return True
        return False

    def _toggle_play(self):
        if self._playing:
            pygame.mixer.music.stop()
            self._playing = False
            return

        if not self._audio_path or not os.path.isfile(self._audio_path):
            self._play_error = "Select the track audio file first."
            return

        try:
            pygame.mixer.music.load(self._audio_path)
            pygame.mixer.music.play()
        except pygame.error as e:
            self._play_error = f"Could not play: {e}"
            return

        self._play_error = None
        self._playing = True
        self._start_ticks = pygame.time.get_ticks()

    def _position_sec(self) -> float:
        if not self._playing:
            return 0.0
        pos = (pygame.time.get_ticks() - self._start_ticks) / 1000.0
        if self._duration_sec is not None and pos >= self._duration_sec:
            pygame.mixer.music.stop()
            self._playing = False
            return 0.0
        return pos

    def update(self, camera_hits: list[float], effects_list: list[dict]):
        """camera_hits/effects_list — already computed from the current form
        values (see PackerApp._compute_preview_camera_hits). Recomputed
        every frame in the calling code — there's still cheap protection
        here against needless state resets via track_key below."""
        position = self._position_sec()

        track_key = (
            self._audio_path,
            tuple(camera_hits),
            json.dumps(effects_list, sort_keys=True),
        )
        self.cam_shake.set_hits(camera_hits, track_key=track_key)
        self.cam_shake.update(position)
        self.fx_engine.set_effects(effects_list, track_key=track_key)
        self.fx_engine.update(position)

    def draw(self, surface, font, font_small, palette: dict, theme_overrides: dict):
        mock_bg = theme_overrides.get("bg", palette["bg"])
        mock_accent = theme_overrides.get("accent", palette["accent"])
        mock_text = theme_overrides.get("text", palette["text"])

        label = font_small.render("PREVIEW", True, palette["text_dim"])
        surface.blit(label, (self.rect.x + 20, self.rect.y))

        mock = pygame.Surface(self._mock_rect.size)
        mock.fill(mock_bg)

        title = os.path.basename(self._audio_path) if self._audio_path else "No track selected"
        title_surf = font_small.render(title, True, mock_text)
        mock.blit(title_surf, title_surf.get_rect(center=(self._mock_rect.width // 2, self._mock_rect.height // 2 - 10)))

        # Progress line based on playback position
        if self._duration_sec:
            ratio = max(0.0, min(1.0, self._position_sec() / self._duration_sec))
            bar_w = self._mock_rect.width - 40
            bar_rect = pygame.Rect(20, self._mock_rect.height - 24, bar_w, 4)
            pygame.draw.rect(mock, palette["button_small_border"], bar_rect, border_radius=2)
            pygame.draw.rect(mock, mock_accent, (bar_rect.x, bar_rect.y, round(bar_w * ratio), bar_rect.height), border_radius=2)

        # Glitch effects + camera hits — the same engines as in the player
        mock = self.fx_engine.apply(mock)
        shake_scale = self.cam_shake.scale
        shake_dx, shake_dy = self.fx_engine.window_offset

        panel = pygame.Surface(self._mock_rect.size)
        panel.fill(mock_bg)
        if shake_scale != 1.0:
            scaled_w = round(self._mock_rect.width * shake_scale)
            scaled_h = round(self._mock_rect.height * shake_scale)
            scaled = pygame.transform.scale(mock, (scaled_w, scaled_h))
            panel.blit(
                scaled,
                ((self._mock_rect.width - scaled_w) // 2 + shake_dx, (self._mock_rect.height - scaled_h) // 2 + shake_dy),
            )
        else:
            panel.blit(mock, (shake_dx, shake_dy))

        surface.blit(panel, self._mock_rect.topleft)
        pygame.draw.rect(surface, palette["button_small_border"], self._mock_rect, width=1, border_radius=6)

        self._play_button.label = "Stop" if self._playing else "Play"
        self._play_button.draw(surface, font, palette)

        status_text = self._play_error
        if not status_text and self._duration_sec:
            pos = self._position_sec()
            status_text = f"{pos:0.1f} / {self._duration_sec:0.1f} s"
        if status_text:
            status_surf = font_small.render(status_text, True, (255, 110, 110) if self._play_error else palette["text_dim"])
            surface.blit(status_surf, (self._play_button.rect.right + 12, self._play_button.rect.centery - status_surf.get_height() // 2))
