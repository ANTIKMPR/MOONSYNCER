"""
UI components: buttons, progress bar, volume slider, track list, toasts.

Colors are no longer hardcoded as module constants — each component
receives the current theme palette (see settings.py: Settings.palette())
and draws itself in its colors. This allows switching between the
dark/light theme on the fly.
"""

import pygame


# ASCII replacements for symbols the fallback font may not support
ASCII_FALLBACK = {
    "▶": ">",
    "⏸": "||",
    "🔊": "Vol",
    "🔇": "Mute",
    "⚙": "Set",
}


class Button:
    def __init__(self, rect: pygame.Rect, label: str, small: bool = False):
        self.rect = rect
        self.label = label
        self.hovered = False
        self.small = small  # compact style for the toolbar at the top
        self.icon: pygame.Surface | None = None  # if set — drawn instead of the text label

    def draw(self, surface, font, palette: dict):
        base_color = palette["button_small_bg"] if self.small else palette["panel"]
        color = palette["accent"] if self.hovered else base_color
        radius = 6 if self.small else 8
        pygame.draw.rect(surface, color, self.rect, border_radius=radius)
        if self.small and not self.hovered:
            pygame.draw.rect(surface, palette["button_small_border"], self.rect, width=1, border_radius=radius)

        if self.icon is not None:
            icon_rect = self.icon.get_rect(center=self.rect.center)
            surface.blit(self.icon, icon_rect)
            return

        display_label = self.label
        # If the font lacks the symbol (metrics returns None) — draw an ASCII
        # replacement, so the user sees a meaningful sign instead of an empty "box"
        if display_label in ASCII_FALLBACK:
            metrics = font.metrics(display_label)
            if not metrics or any(m is None for m in metrics):
                display_label = ASCII_FALLBACK[display_label]

        text = font.render(display_label, True, palette["text"])
        text_rect = text.get_rect(center=self.rect.center)
        surface.blit(text, text_rect)

    def handle_hover(self, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)

    def is_clicked(self, mouse_pos, event):
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(mouse_pos)
        )


class VolumeSlider:
    """
    Horizontal volume slider with a round handle.
    Unlike ProgressBar, supports live dragging (the value updates the
    whole time the mouse button is held).
    """

    def __init__(self, rect: pygame.Rect):
        self.rect = rect
        self.handle_radius = rect.height  # handle slightly larger than the track, for easier mouse targeting

    def draw(self, surface, value: float, palette: dict):
        value = max(0.0, min(1.0, value))

        # Track
        pygame.draw.rect(surface, palette["progress_bg"], self.rect, border_radius=self.rect.height // 2)
        fill_width = int(self.rect.width * value)
        if fill_width > 0:
            fill_rect = pygame.Rect(self.rect.x, self.rect.y, fill_width, self.rect.height)
            pygame.draw.rect(surface, palette["progress_fill"], fill_rect, border_radius=self.rect.height // 2)

        # Handle
        handle_x = self.rect.x + fill_width
        handle_y = self.rect.centery
        pygame.draw.circle(surface, palette["text"], (handle_x, handle_y), self.handle_radius)
        pygame.draw.circle(surface, palette["accent"], (handle_x, handle_y), self.handle_radius - 2)

    def get_ratio_from_x(self, mouse_x: int) -> float:
        ratio = (mouse_x - self.rect.x) / self.rect.width
        return max(0.0, min(1.0, ratio))

    def hit_rect(self) -> pygame.Rect:
        """Click area slightly larger than the track itself (accounting for the protruding handle) — easier to hit with the mouse."""
        pad = self.handle_radius
        return pygame.Rect(self.rect.x - pad, self.rect.y - pad, self.rect.width + pad * 2, self.rect.height + pad * 2)

    def is_clicked(self, mouse_pos, event):
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.hit_rect().collidepoint(mouse_pos)
        )


class ProgressBar:
    def __init__(self, rect: pygame.Rect):
        self.rect = rect

    def draw(self, surface, progress_ratio: float, palette: dict):
        pygame.draw.rect(surface, palette["progress_bg"], self.rect, border_radius=4)
        fill_width = int(self.rect.width * max(0.0, min(1.0, progress_ratio)))
        if fill_width > 0:
            fill_rect = pygame.Rect(self.rect.x, self.rect.y, fill_width, self.rect.height)
            pygame.draw.rect(surface, palette["progress_fill"], fill_rect, border_radius=4)

    def get_ratio_from_click(self, mouse_x: int) -> float:
        ratio = (mouse_x - self.rect.x) / self.rect.width
        return max(0.0, min(1.0, ratio))

    def is_clicked(self, mouse_pos, event):
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(mouse_pos)
        )


class Toast:
    """Popup notification at the bottom of the screen (errors, statuses) — disappears on its own after a while."""

    def __init__(self):
        self.message = ""
        self.is_error = False
        self.shown_at_ms = -1
        self.duration_ms = 3500

    def show(self, message: str, is_error: bool = False):
        self.message = message
        self.is_error = is_error
        self.shown_at_ms = pygame.time.get_ticks()

    def is_active(self) -> bool:
        if self.shown_at_ms < 0:
            return False
        return pygame.time.get_ticks() - self.shown_at_ms < self.duration_ms

    def draw(self, surface, font, window_width, window_height, palette: dict):
        if not self.is_active():
            return

        color = palette["error"] if self.is_error else palette["success"]
        # Multi-line messages (e.g. details of a decoding error)
        lines = self.message.split("\n")
        line_surfaces = [font.render(line, True, palette["text"]) for line in lines]
        max_width = max(s.get_width() for s in line_surfaces)

        padding = 14
        box_width = min(max_width + padding * 2, window_width - 40)
        box_height = len(lines) * 20 + padding * 2
        box_x = (window_width - box_width) // 2
        box_y = window_height - box_height - 20

        box_rect = pygame.Rect(box_x, box_y, box_width, box_height)
        pygame.draw.rect(surface, palette["panel"], box_rect, border_radius=8)
        pygame.draw.rect(surface, color, box_rect, width=2, border_radius=8)

        for i, line_surf in enumerate(line_surfaces):
            surface.blit(line_surf, (box_x + padding, box_y + padding + i * 20))


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


class TrackList:
    """
    Scrollable playlist track list with the current track highlighted and
    a small remove button (x) on each row on hover.
    """

    def __init__(self, rect: pygame.Rect):
        self.rect = rect
        self.line_height = 26
        self.scroll_offset = 0  # index of the first visible row
        self._row_rects: list[tuple[int, pygame.Rect, pygame.Rect]] = []  # (playlist_idx, row_rect, remove_btn_rect)

    def visible_count(self) -> int:
        return max(1, self.rect.height // self.line_height)

    def ensure_visible(self, index: int, total: int):
        """Scrolls so that the given index is visible (e.g. the currently playing track)."""
        vc = self.visible_count()
        if index < self.scroll_offset:
            self.scroll_offset = index
        elif index >= self.scroll_offset + vc:
            self.scroll_offset = index - vc + 1
        self.scroll_offset = max(0, min(self.scroll_offset, max(0, total - vc)))

    def scroll(self, delta: int, total: int):
        vc = self.visible_count()
        self.scroll_offset = max(0, min(self.scroll_offset + delta, max(0, total - vc)))

    def draw(self, surface, font, playlist_titles, current_index, mouse_pos, palette: dict, empty_text: str):
        pygame.draw.rect(surface, palette["panel"], self.rect, border_radius=8)
        self._row_rects = []

        if not playlist_titles:
            empty_surf = font.render(empty_text, True, palette["text_dim"])
            surface.blit(empty_surf, (self.rect.x + 12, self.rect.y + 10))
            return

        vc = self.visible_count()
        start_idx = self.scroll_offset
        end_idx = min(len(playlist_titles), start_idx + vc)

        # Clip drawing to the list bounds so rows don't spill outside the panel
        prev_clip = surface.get_clip()
        surface.set_clip(self.rect)

        for row, idx in enumerate(range(start_idx, end_idx)):
            y = self.rect.y + row * self.line_height
            title = playlist_titles[idx]
            is_current = idx == current_index

            row_rect = pygame.Rect(self.rect.x, y, self.rect.width, self.line_height)
            row_hovered = row_rect.collidepoint(mouse_pos)

            if is_current:
                pygame.draw.rect(surface, palette["row_current"], row_rect)
            elif row_hovered:
                pygame.draw.rect(surface, palette["row_hover"], row_rect)

            color = palette["accent"] if is_current else palette["text_dim"]
            # Truncate long titles so they don't overlap the remove button
            display_title = title if len(title) < 55 else title[:52] + "…"
            text = font.render(f"{idx + 1}. {display_title}", True, color)
            surface.blit(text, (self.rect.x + 12, y + 5))

            # Remove button (x) — shown only when hovering over the row
            remove_rect = pygame.Rect(self.rect.right - 30, y + 3, 20, 20)
            if row_hovered:
                remove_color = palette["remove_x"] if remove_rect.collidepoint(mouse_pos) else palette["text_dim"]
                x_text = font.render("×", True, remove_color)
                surface.blit(x_text, (remove_rect.x + 5, remove_rect.y - 2))

            self._row_rects.append((idx, row_rect, remove_rect))

        surface.set_clip(prev_clip)

    def handle_click(self, mouse_pos, event) -> tuple[str, int] | None:
        """
        Handles a click on the list. Returns ('play', idx) when a row is
        clicked, ('remove', idx) when the x button is clicked, otherwise None.
        """
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        for idx, row_rect, remove_rect in self._row_rects:
            if remove_rect.collidepoint(mouse_pos):
                return ("remove", idx)
            if row_rect.collidepoint(mouse_pos):
                return ("play", idx)
        return None
