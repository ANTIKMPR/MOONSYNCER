"""
Packer form widgets — the same visual language as ui.py of the main player
(drawn in the shared palette's colors, same corner radius and approach to
hover/active states), but of kinds the player didn't have: a text field
with focus and cursor, an RGB picker, a checkbox, and a file row (field +
"Browse" button).
"""

import time

import pygame


def _get_clipboard_text() -> str:
    """Text from the system clipboard via pygame.scrap — requires
    pygame.scrap.init() once at app start (main.py). Any error (clipboard
    empty/unavailable/scrap not initialized) — we just paste nothing and
    don't break input."""
    try:
        raw = pygame.scrap.get(pygame.SCRAP_TEXT)
    except (pygame.error, AttributeError):
        return ""
    if not raw:
        return ""
    return raw.decode("utf-8", errors="ignore").replace("\x00", "").replace("\r", "").replace("\n", "")


class TextInput:
    """
    Single-line text field with focus, a blinking cursor, and horizontal
    text scrolling if it doesn't fit the field width (toward the cursor,
    like ordinary input fields) — relevant for long file paths.
    """

    def __init__(self, rect: pygame.Rect, placeholder: str = "", numeric: bool = False):
        self.rect = rect
        self.placeholder = placeholder
        self.numeric = numeric  # allows only digits, dot, comma, space, minus
        self.text = ""
        self.focused = False
        self._cursor_visible_since = 0
        self._scroll_px = 0  # leftward text offset when it doesn't fit

    def set_text(self, text: str):
        self.text = text
        self._scroll_px = 0

    def _append_filtered(self, chars: str):
        for ch in chars:
            if self.numeric:
                if ch.isdigit() or ch in ".,- ":
                    self.text += ch
            elif ch.isprintable():
                self.text += ch

    def handle_event(self, event) -> bool:
        """Returns True if the event was handled by this field (the calling
        code needs this so the same click isn't passed further down)."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            was_focused = self.focused
            self.focused = self.rect.collidepoint(event.pos)
            if self.focused:
                self._cursor_visible_since = time.time()
            return self.focused or was_focused

        if not self.focused:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN or event.key == pygame.K_TAB:
                self.focused = False
            elif event.key == pygame.K_v and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                # Ctrl+V: with Ctrl held, pygame's event.unicode is empty,
                # so ordinary pasting via the unicode branch below never
                # got here — a separate explicit case is needed.
                self._append_filtered(_get_clipboard_text())
            elif event.unicode:
                self._append_filtered(event.unicode)
            self._cursor_visible_since = time.time()
            return True

        return False

    def draw(self, surface, font, palette: dict):
        bg = palette["button_small_bg"] if not self.focused else palette["panel"]
        pygame.draw.rect(surface, bg, self.rect, border_radius=6)
        border_color = palette["accent"] if self.focused else palette["button_small_border"]
        pygame.draw.rect(surface, border_color, self.rect, width=1, border_radius=6)

        pad = 8
        clip_rect = self.rect.inflate(-pad, -4)
        prev_clip = surface.get_clip()
        surface.set_clip(clip_rect)

        if self.text:
            text_surf = font.render(self.text, True, palette["text"])
            text_w = text_surf.get_width()
            avail_w = self.rect.width - pad * 2

            if text_w > avail_w:
                self._scroll_px = text_w - avail_w
            else:
                self._scroll_px = 0

            text_x = self.rect.x + pad - self._scroll_px
            text_y = self.rect.centery - text_surf.get_height() // 2
            surface.blit(text_surf, (text_x, text_y))

            if self.focused and int(time.time() * 2) % 2 == 0:
                cursor_x = text_x + text_w + 1
                pygame.draw.line(
                    surface, palette["text"],
                    (cursor_x, self.rect.y + 5), (cursor_x, self.rect.bottom - 5), 1,
                )
        else:
            placeholder_surf = font.render(self.placeholder, True, palette["text_dim"])
            surface.blit(placeholder_surf, (self.rect.x + pad, self.rect.centery - placeholder_surf.get_height() // 2))
            if self.focused and int(time.time() * 2) % 2 == 0:
                cursor_x = self.rect.x + pad
                pygame.draw.line(
                    surface, palette["text"],
                    (cursor_x, self.rect.y + 5), (cursor_x, self.rect.bottom - 5), 1,
                )

        surface.set_clip(prev_clip)


class FileRow:
    """
    File path field (a TextInput, content is effectively read-only — the
    path is set programmatically from the file dialog) + a "Browse" button
    next to it. The calling code decides which filedialog to open
    (audio/image/video/save) when the button is clicked.
    """

    def __init__(self, rect: pygame.Rect, placeholder: str, browse_label: str = "Browse"):
        browse_w = 74
        gap = 8
        input_rect = pygame.Rect(rect.x, rect.y, rect.width - browse_w - gap, rect.height)
        browse_rect = pygame.Rect(rect.right - browse_w, rect.y, browse_w, rect.height)

        self.input = TextInput(input_rect, placeholder=placeholder)
        self.input.focused = False
        self._browse_rect = browse_rect
        self.browse_label = browse_label
        self._browse_hovered = False

    @property
    def path(self) -> str:
        return self.input.text.strip()

    def set_path(self, path: str):
        self.input.set_text(path)

    def handle_hover(self, mouse_pos):
        self._browse_hovered = self._browse_rect.collidepoint(mouse_pos)

    def browse_clicked(self, mouse_pos, event) -> bool:
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._browse_rect.collidepoint(mouse_pos)
        )

    def draw(self, surface, font, palette: dict):
        # The path field is display-only (we don't give it focus on a text
        # click — the path always comes from the system file dialog, not typed)
        self.input.draw(surface, font, palette)

        color = palette["accent"] if self._browse_hovered else palette["button_small_bg"]
        pygame.draw.rect(surface, color, self._browse_rect, border_radius=6)
        if not self._browse_hovered:
            pygame.draw.rect(surface, palette["button_small_border"], self._browse_rect, width=1, border_radius=6)
        label_surf = font.render(self.browse_label, True, palette["text"])
        surface.blit(label_surf, label_surf.get_rect(center=self._browse_rect.center))


class ColorSwatchInput:
    """
    A single theme color (bg/accent/text): an "override" checkbox + three
    narrow numeric TextInputs (R, G, B) + a live color preview square.
    When the checkbox is unchecked, the fields are inactive and the key
    won't end up in sync.json — this way a package can override only part
    of the palette, as intended by the format (see vibesync.py's docstring).
    """

    def __init__(self, rect: pygame.Rect, label: str, default_rgb: tuple[int, int, int]):
        self.rect = rect
        self.label = label
        self.enabled = False
        self._default_rgb = default_rgb

        checkbox_size = 18
        self._checkbox_rect = pygame.Rect(rect.x, rect.centery - checkbox_size // 2, checkbox_size, checkbox_size)

        field_w = 46
        field_gap = 6
        fields_x = rect.x + 130
        self.r_input = TextInput(pygame.Rect(fields_x, rect.y, field_w, rect.height), numeric=True)
        self.g_input = TextInput(pygame.Rect(fields_x + (field_w + field_gap), rect.y, field_w, rect.height), numeric=True)
        self.b_input = TextInput(pygame.Rect(fields_x + (field_w + field_gap) * 2, rect.y, field_w, rect.height), numeric=True)
        for field, val in zip((self.r_input, self.g_input, self.b_input), default_rgb):
            field.set_text(str(val))

        swatch_size = rect.height
        self._swatch_rect = pygame.Rect(fields_x + (field_w + field_gap) * 3 + 10, rect.y, swatch_size, swatch_size)

    def set_value(self, rgb: tuple[int, int, int] | list[int] | None):
        """Programmatically sets the color: None disables the override
        (checkbox off, fields reset to the default); an (r, g, b) value
        enables it and fills the three fields. Used when restoring a
        saved project."""
        if rgb is None:
            self.enabled = False
            for field, val in zip((self.r_input, self.g_input, self.b_input), self._default_rgb):
                field.set_text(str(val))
            return
        self.enabled = True
        for field, val in zip((self.r_input, self.g_input, self.b_input), rgb):
            field.set_text(str(max(0, min(255, int(val)))))

    @property
    def rgb(self) -> tuple[int, int, int] | None:
        if not self.enabled:
            return None
        try:
            r = max(0, min(255, int(self.r_input.text or 0)))
            g = max(0, min(255, int(self.g_input.text or 0)))
            b = max(0, min(255, int(self.b_input.text or 0)))
            return (r, g, b)
        except ValueError:
            return None

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._checkbox_rect.collidepoint(event.pos):
                self.enabled = not self.enabled
                return True

        if not self.enabled:
            return False

        handled = False
        for field in (self.r_input, self.g_input, self.b_input):
            if field.handle_event(event):
                handled = True
        return handled

    def draw(self, surface, font, palette: dict):
        pygame.draw.rect(surface, palette["button_small_bg"], self._checkbox_rect, border_radius=4)
        pygame.draw.rect(surface, palette["button_small_border"], self._checkbox_rect, width=1, border_radius=4)
        if self.enabled:
            inner = self._checkbox_rect.inflate(-6, -6)
            pygame.draw.rect(surface, palette["accent"], inner, border_radius=2)

        label_color = palette["text"] if self.enabled else palette["text_dim"]
        label_surf = font.render(self.label, True, label_color)
        surface.blit(label_surf, (self._checkbox_rect.right + 10, self.rect.centery - label_surf.get_height() // 2))

        for field in (self.r_input, self.g_input, self.b_input):
            if not self.enabled:
                # Show the fields muted and don't draw the cursor when disabled
                prev_focused = field.focused
                field.focused = False
                field.draw(surface, font, palette)
                field.focused = prev_focused
            else:
                field.draw(surface, font, palette)

        swatch_rgb = self.rgb if self.enabled else self._default_rgb
        pygame.draw.rect(surface, swatch_rgb, self._swatch_rect, border_radius=4)
        pygame.draw.rect(surface, palette["button_small_border"], self._swatch_rect, width=1, border_radius=4)


EFFECT_TYPES = ("rgb_split", "scanline_tear", "chroma_noise", "window_shake")


def _parse_params_text(text: str) -> dict:
    """
    Parses a string like "amplitude=8, band_height=10" into {"amplitude": 8,
    "band_height": 10} — values that can't be converted to a number are
    kept as-is as strings (in case of future non-numeric parameters).
    An empty/broken pair is simply skipped — like camera_hits_text, an
    effect shouldn't break the whole editor because of a single typo.
    """
    params = {}
    if not text or not text.strip():
        return params
    for pair in text.split(","):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        try:
            params[key] = float(value) if "." in value else int(value)
        except ValueError:
            params[key] = value
    return params


def _params_to_text(params: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in (params or {}).items())


class EffectRow:
    """
    A single row of the glitch-effects editor: type (a toggle button that
    cycles on click), trigger moment "at" and "duration" in seconds,
    arbitrary effect parameters on one line ("amplitude=8"), and a row
    delete button. The format matches the main player's effects.py.
    """

    ROW_HEIGHT = 34

    def __init__(self, rect: pygame.Rect, effect: dict | None = None):
        self.rect = rect
        effect = effect or {}
        self._type_idx = max(0, EFFECT_TYPES.index(effect["type"]) if effect.get("type") in EFFECT_TYPES else 0)

        type_w = 118
        at_w = 56
        duration_w = 56
        remove_w = 28
        gap = 6
        params_x = rect.x + type_w + gap + at_w + gap + duration_w + gap
        params_w = rect.width - (type_w + at_w + duration_w + remove_w + gap * 4)

        self._type_rect = pygame.Rect(rect.x, rect.y, type_w, self.ROW_HEIGHT)
        self.at_input = TextInput(pygame.Rect(rect.x + type_w + gap, rect.y, at_w, self.ROW_HEIGHT), placeholder="at", numeric=True)
        self.duration_input = TextInput(
            pygame.Rect(rect.x + type_w + gap + at_w + gap, rect.y, duration_w, self.ROW_HEIGHT),
            placeholder="dur", numeric=True,
        )
        self.params_input = TextInput(pygame.Rect(params_x, rect.y, max(40, params_w), self.ROW_HEIGHT), placeholder="amplitude=8")
        self._remove_rect = pygame.Rect(rect.right - remove_w, rect.y, remove_w, self.ROW_HEIGHT)
        self._type_hovered = False
        self._remove_hovered = False

        if "at" in effect:
            self.at_input.set_text(str(effect["at"]))
        if "duration" in effect:
            self.duration_input.set_text(str(effect["duration"]))
        if effect.get("params"):
            self.params_input.set_text(_params_to_text(effect["params"]))

    @property
    def effect_type(self) -> str:
        return EFFECT_TYPES[self._type_idx]

    def set_position(self, new_rect: pygame.Rect):
        """Moves the row (and all its fields) to a new position without
        touching the entered text/focus — needed when a neighboring row
        above is deleted and all the lower rows must move up."""
        dx = new_rect.x - self.rect.x
        dy = new_rect.y - self.rect.y
        if dx == 0 and dy == 0:
            return
        self.rect = new_rect
        for r in (
            self._type_rect, self.at_input.rect, self.duration_input.rect,
            self.params_input.rect, self._remove_rect,
        ):
            r.x += dx
            r.y += dy

    def handle_hover(self, mouse_pos):
        self._type_hovered = self._type_rect.collidepoint(mouse_pos)
        self._remove_hovered = self._remove_rect.collidepoint(mouse_pos)

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._type_rect.collidepoint(event.pos):
                self._type_idx = (self._type_idx + 1) % len(EFFECT_TYPES)
                return True

        handled = False
        for field in (self.at_input, self.duration_input, self.params_input):
            if field.handle_event(event):
                handled = True
        return handled

    def remove_clicked(self, mouse_pos, event) -> bool:
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self._remove_rect.collidepoint(mouse_pos)
        )

    def to_dict(self) -> dict | None:
        """None — the row isn't filled in enough to become a valid effect
        (at least "at" is needed); we don't fail the package build because of it."""
        try:
            at = float((self.at_input.text or "").replace(",", "."))
        except ValueError:
            return None
        if at < 0:
            return None

        result = {"type": self.effect_type, "at": at}
        duration_text = (self.duration_input.text or "").replace(",", ".")
        if duration_text:
            try:
                result["duration"] = max(0.01, float(duration_text))
            except ValueError:
                pass
        params = _parse_params_text(self.params_input.text)
        if params:
            result["params"] = params
        return result

    def draw(self, surface, font, palette: dict):
        color = palette["accent"] if self._type_hovered else palette["button_small_bg"]
        pygame.draw.rect(surface, color, self._type_rect, border_radius=6)
        if not self._type_hovered:
            pygame.draw.rect(surface, palette["button_small_border"], self._type_rect, width=1, border_radius=6)
        type_surf = font.render(self.effect_type, True, palette["text"])
        surface.blit(type_surf, type_surf.get_rect(center=self._type_rect.center))

        for field in (self.at_input, self.duration_input, self.params_input):
            field.draw(surface, font, palette)

        remove_color = palette["accent"] if self._remove_hovered else palette["button_small_bg"]
        pygame.draw.rect(surface, remove_color, self._remove_rect, border_radius=6)
        if not self._remove_hovered:
            pygame.draw.rect(surface, palette["button_small_border"], self._remove_rect, width=1, border_radius=6)
        x_surf = font.render("x", True, palette["text"])
        surface.blit(x_surf, x_surf.get_rect(center=self._remove_rect.center))


class EffectsEditor:
    """
    A list of EffectRows with an "+ effect" button inside a scrollable area
    of fixed height (view_height) — an editor for sync.json's "effects"
    field. Unlike the previous version (a fixed number of visible rows
    with no scrolling), this widget's height in the form layout is now
    CONSTANT and doesn't depend on the number of added rows — previously,
    the mismatch between "how much space the form actually reserves" and
    "how much space the list actually occupies" was what made the "Build
    .zip" button overlap the effects list after several added rows.

    Scrolling — mouse wheel, when the cursor is over the list area.
    """

    ROW_GAP = 6
    ADD_BUTTON_HEIGHT = 30
    MAX_EFFECTS = 30  # reasonable cap for a manual editor; for more, edit sync.json directly

    def __init__(self, rect: pygame.Rect, view_height: int):
        self.rect = rect                      # x, y, width — the real position; height isn't used directly
        self.view_height = view_height        # fixed height of the visible scrollable area
        self.rows: list[EffectRow] = []
        self._scroll_y = 0                    # how many pixels the content is scrolled up
        self._add_hovered = False
        self._content_hovered = False
        self._reflow()

    @property
    def viewport_rect(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x, self.rect.y, self.rect.width, self.view_height)

    def _content_height(self) -> int:
        return len(self.rows) * (EffectRow.ROW_HEIGHT + self.ROW_GAP) + self.ADD_BUTTON_HEIGHT

    def _max_scroll(self) -> int:
        return max(0, self._content_height() - self.view_height)

    def _reflow(self):
        """Recomputes the positions of the rows and the "+" button within
        content coordinates (before scrolling is applied — the _scroll_y
        shift only happens in draw()/handle_event(), the rows' rects
        themselves keep the "logical", unscrolled position)."""
        y = self.rect.y
        for row in self.rows:
            row.set_position(pygame.Rect(self.rect.x, y, self.rect.width, EffectRow.ROW_HEIGHT))
            y += EffectRow.ROW_HEIGHT + self.ROW_GAP
        self._content_add_y = y
        self._scroll_y = min(self._scroll_y, self._max_scroll())

    def add_row(self, effect: dict | None = None) -> bool:
        if len(self.rows) >= self.MAX_EFFECTS:
            return False
        y = self.rect.y + len(self.rows) * (EffectRow.ROW_HEIGHT + self.ROW_GAP)
        self.rows.append(EffectRow(pygame.Rect(self.rect.x, y, self.rect.width, EffectRow.ROW_HEIGHT), effect))
        self._reflow()
        self._scroll_y = self._max_scroll()  # auto-scroll to the new row so it's immediately visible what was added
        return True

    def handle_hover(self, mouse_pos):
        self._content_hovered = self.viewport_rect.collidepoint(mouse_pos)
        offset_pos = (mouse_pos[0], mouse_pos[1] + self._scroll_y)
        self._add_hovered = self._content_hovered and self._add_rect().collidepoint(offset_pos)
        for row in self.rows:
            if self.viewport_rect.collidepoint(mouse_pos):
                row.handle_hover(offset_pos)
            else:
                row.handle_hover((-1, -1))

    def _add_rect(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x, self._content_add_y, self.rect.width, self.ADD_BUTTON_HEIGHT)

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEWHEEL and self._content_hovered:
            self._scroll_y = max(0, min(self._max_scroll(), self._scroll_y - event.y * 40))
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.viewport_rect.collidepoint(event.pos):
                return False
            offset_pos = (event.pos[0], event.pos[1] + self._scroll_y)
            if self._add_rect().collidepoint(offset_pos):
                self.add_row()
                return True
            for row in list(self.rows):
                if row.remove_clicked(offset_pos, event):
                    self.rows.remove(row)
                    self._reflow()
                    return True

        # Other events (keyboard for the focused text field, motion for the
        # cursor, etc.) are shifted by the scroll offset by position (if
        # present) and simply passed to the rows — TextInput decides
        # itself whether to react (via its own self.focused), an extra
        # forward here breaks nothing.
        shifted_event = event
        if hasattr(event, "pos"):
            shifted_event = pygame.event.Event(event.type, {**event.dict, "pos": (event.pos[0], event.pos[1] + self._scroll_y)})

        handled = False
        for row in self.rows:
            if row.handle_event(shifted_event):
                handled = True
        return handled

    def to_effects_list(self) -> list[dict]:
        return [d for d in (row.to_dict() for row in self.rows) if d is not None]

    def set_effects(self, effects_list: list[dict] | None):
        """Replaces all rows with the given effects (sync.json format).
        Used when restoring a saved project. Invalid entries are skipped
        so a hand-edited project file can't crash the editor."""
        self.rows = []
        self._scroll_y = 0
        for effect in effects_list or []:
            if isinstance(effect, dict) and not self.add_row(effect):
                break
        self._reflow()
        self._scroll_y = 0

    def draw(self, surface, font, palette: dict):
        viewport = self.viewport_rect
        prev_clip = surface.get_clip()
        surface.set_clip(viewport)

        for row in self.rows:
            drawn_rect = row.rect.move(0, -self._scroll_y)
            row.set_position(drawn_rect)
            row.draw(surface, font, palette)
            row.set_position(drawn_rect.move(0, self._scroll_y))  # restore the logical position

        can_add = len(self.rows) < self.MAX_EFFECTS
        add_rect = self._add_rect().move(0, -self._scroll_y)
        color = palette["accent"] if (self._add_hovered and can_add) else palette["button_small_bg"]
        pygame.draw.rect(surface, color, add_rect, border_radius=6)
        if not (self._add_hovered and can_add):
            pygame.draw.rect(surface, palette["button_small_border"], add_rect, width=1, border_radius=6)
        label = "+ effect" if can_add else f"maximum {self.MAX_EFFECTS} effects"
        label_surf = font.render(label, True, palette["text"] if can_add else palette["text_dim"])
        surface.blit(label_surf, label_surf.get_rect(center=add_rect.center))

        surface.set_clip(prev_clip)

        pygame.draw.rect(surface, palette["button_small_border"], viewport, width=1, border_radius=6)
        if self._max_scroll() > 0:
            track_h = viewport.height - 8
            thumb_h = max(24, round(track_h * viewport.height / self._content_height()))
            thumb_y = viewport.y + 4 + round((track_h - thumb_h) * (self._scroll_y / self._max_scroll()))
            thumb_rect = pygame.Rect(viewport.right - 6, thumb_y, 4, thumb_h)
            pygame.draw.rect(surface, palette["text_dim"], thumb_rect, border_radius=2)


class Checkbox:
    """A simple labeled checkbox (used for bgvideo_sync)."""

    def __init__(self, rect: pygame.Rect, label: str):
        checkbox_size = rect.height
        self._checkbox_rect = pygame.Rect(rect.x, rect.y, checkbox_size, checkbox_size)
        self.label = label
        self.checked = False
        self._label_x = rect.x + checkbox_size + 10

    def set_checked(self, checked: bool):
        self.checked = bool(checked)

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._checkbox_rect.collidepoint(event.pos):
                self.checked = not self.checked
                return True
        return False

    def draw(self, surface, font, palette: dict):
        pygame.draw.rect(surface, palette["button_small_bg"], self._checkbox_rect, border_radius=4)
        pygame.draw.rect(surface, palette["button_small_border"], self._checkbox_rect, width=1, border_radius=4)
        if self.checked:
            inner = self._checkbox_rect.inflate(-6, -6)
            pygame.draw.rect(surface, palette["accent"], inner, border_radius=2)

        label_surf = font.render(self.label, True, palette["text"])
        surface.blit(label_surf, (self._label_x, self._checkbox_rect.centery - label_surf.get_height() // 2))
