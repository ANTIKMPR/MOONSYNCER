"""
VIBE-SYNC Packer — a standalone utility for building .zip packages that the
main player's VIBE-SYNC loader understands (vibesync.py: load_package()).

Bundles a track + optionally a cover/video + optionally sync.json (theme,
bpm/camera_hits, bgvideo_sync) into a .zip of the right structure with a
single click.

Work can be paused and continued later: "Save Project" / "Open Project"
store the whole form plus the source files in a project .zip, and the form
is also autosaved and restored automatically on the next launch (see
project_io.py). A finished VIBE-SYNC package (.zip) can be opened with
"Open Project" too — it is imported into the form for further editing.

Built on plain pygame, with the same visual language as the main player:
reuses Button/Toast from ui.py, the app font via app_font.py, the window
icon and logo via resources/logo/ (the same loading approach as the
player's main.py — see load_app_icon()/load_logo() there) — only with added
form widgets (packer_widgets.py) that the player didn't have. System file
pickers go through tkinter.filedialog, on top of the pygame window (a
lightweight, standard way to get a native file picker without giving up
pygame for the rest of the UI).

A standalone utility — keeps its own copy of resources/ (logo/, font/),
doesn't depend on where the player's folder is located on disk.
"""

import json
import os
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import Button, Toast
from packer_widgets import Checkbox, ColorSwatchInput, EffectsEditor, FileRow, TextInput
from preview_panel import PreviewPanel
from vibesync_pack import (
    VibeSyncPackError,
    build_package,
    build_sync_json,
    fetch_spicylyrics,
    parse_camera_hits_text,
)
from palette_extract import PaletteExtractError, extract_palette
from project_io import (
    IMPORTED_PACKAGE_KEY,
    ProjectFileError,
    build_project_state,
    load_project_file,
    save_autosave_file,
    save_project_file,
)
import app_font
import logo_theme

# tkinter is used only for native open/save file dialogs —
# the GUI itself stays entirely on pygame
import tkinter as tk
from tkinter import filedialog


APP_NAME = "VIBE-SYNC Packer"
# Two columns: the form on the left, the live preview on the right — so the
# window height doesn't grow with every new form section (previously
# everything was stacked in a single column).
FORM_WIDTH = 560
PREVIEW_WIDTH = 360
COLUMN_GAP = 20
WINDOW_SIZE = (FORM_WIDTH + COLUMN_GAP + PREVIEW_WIDTH + 48, 840)
MIN_WINDOW_SIZE = (FORM_WIDTH + COLUMN_GAP + 300 + 48, 700)  # fixed-width form + minimum space for the preview
FPS = 60

AUTOSAVE_INTERVAL_MS = 5000  # how often the form is checked for changes and autosaved

# Resources (icon, logo, font) — a copy next to this file, the same way as
# in the main player (see BASE_DIR/resources/... in its main.py), but not
# dependent on where the player's folder is located on disk.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ICON_PATH = os.path.join(BASE_DIR, "resources", "logo", "icon.ico")
LOGO_PATH = os.path.join(BASE_DIR, "resources", "logo", "BigLogo.png")
SPICYLYRICS_KEY_PATH = os.path.join(BASE_DIR, ".spicylyrics_key")
AUTOSAVE_PATH = os.path.join(BASE_DIR, ".last_session.json")


def _load_spicylyrics_key() -> str:
    """The locally saved SpicyLyrics API key — so it doesn't have to be
    re-entered on every launch of the packer. Stored as a plain text file
    next to the program (not encrypted — if that's a problem on a shared
    computer, don't save the key and enter it manually each time)."""
    try:
        with open(SPICYLYRICS_KEY_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _save_spicylyrics_key(key: str) -> None:
    try:
        with open(SPICYLYRICS_KEY_PATH, "w", encoding="utf-8") as f:
            f.write(key.strip())
    except OSError:
        pass  # not critical — the key will just have to be entered again next time


# Logo in the window header — more compact than in the player itself (there
# it's 0.6 of the 760px window width), the form has little vertical space
# here, so it's narrower
LOGO_WIDTH = 260
LOGO_SOURCE_ASPECT = 330 / 2000  # original proportions of BigLogo.png
LOGO_HEIGHT = round(LOGO_WIDTH * LOGO_SOURCE_ASPECT)

# Dark palette in the style of the main player (the same set of keys that
# Button/Toast/TextInput from ui.py and packer_widgets.py expect)
PALETTE = {
    "bg": (18, 18, 24),
    "panel": (28, 28, 36),
    "accent": (180, 90, 255),
    "text": (235, 235, 240),
    "text_dim": (140, 140, 155),
    "button_small_bg": (38, 38, 48),
    "button_small_border": (60, 60, 74),
    "progress_bg": (40, 40, 50),
    "progress_fill": (180, 90, 255),
    "row_current": (48, 36, 64),
    "row_hover": (34, 34, 44),
    "remove_x": (220, 90, 90),
    "error": (220, 90, 90),
    "success": (110, 210, 140),
}

DEFAULT_THEME_RGB = {
    "bg": (20, 10, 30),
    "accent": (255, 80, 180),
    "text": (240, 240, 245),
}


def load_app_icon():
    """
    Loads the .ico for the window icon — the same logic as load_app_icon()
    in the main player (main.py): first try via Pillow (SDL_image can't
    always handle some internal BMP encodings of .ico), otherwise directly
    via pygame. None if the file is missing/unreadable — then the default
    icon just stays.
    """
    try:
        from PIL import Image
        img = Image.open(ICON_PATH).convert("RGBA")
        return pygame.image.frombuffer(img.tobytes(), img.size, "RGBA")
    except ImportError:
        pass
    except Exception as e:
        print(f"[VIBE-SYNC Packer] Pillow could not read the icon ({ICON_PATH}): {e}")

    try:
        return pygame.image.load(ICON_PATH)
    except Exception as e:
        print(f"[VIBE-SYNC Packer] Failed to load the app icon ({ICON_PATH}): {e}")
        return None


def load_logo():
    """
    Loads and scales the logo to LOGO_WIDTH x LOGO_HEIGHT for the packer
    window header. Always the light-on-dark version (the packer, unlike the
    player, has no dark/light theme switch) — see logo_theme.py, whose
    luminance-inversion principle is reused; here we just take the ready
    BigLogo.png as-is.
    Returns a Surface, or None if the file is missing — then a text
    fallback with the utility's name is drawn.
    """
    try:
        raw = pygame.image.load(LOGO_PATH).convert_alpha()
        return pygame.transform.smoothscale(raw, (LOGO_WIDTH, LOGO_HEIGHT))
    except Exception as e:
        print(f"[VIBE-SYNC Packer] Failed to load the logo ({LOGO_PATH}): {e}")
        return None


def _hidden_tk_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def _ask_audio_path() -> str | None:
    root = _hidden_tk_root()
    try:
        return filedialog.askopenfilename(
            title="Select the track audio file",
            filetypes=[("Audio", "*.mp3 *.ogg"), ("All files", "*.*")],
        )
    finally:
        root.destroy()


def _ask_image_path() -> str | None:
    root = _hidden_tk_root()
    try:
        return filedialog.askopenfilename(
            title="Select a cover",
            filetypes=[("Images", "*.png *.webp *.jpg *.jpeg"), ("All files", "*.*")],
        )
    finally:
        root.destroy()


def _ask_video_path() -> str | None:
    root = _hidden_tk_root()
    try:
        return filedialog.askopenfilename(
            title="Select a background video",
            filetypes=[("Video", "*.mp4"), ("All files", "*.*")],
        )
    finally:
        root.destroy()


def _ask_output_path(default_name: str) -> str | None:
    root = _hidden_tk_root()
    try:
        return filedialog.asksaveasfilename(
            title="Save the VIBE-SYNC package as",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("VIBE-SYNC package", "*.zip")],
        )
    finally:
        root.destroy()


def _ask_project_save_path(default_name: str) -> str | None:
    root = _hidden_tk_root()
    try:
        return filedialog.asksaveasfilename(
            title="Save the project as",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Packer project (.zip)", "*.zip")],
        )
    finally:
        root.destroy()


def _ask_project_open_path() -> str | None:
    root = _hidden_tk_root()
    try:
        return filedialog.askopenfilename(
            title="Open a project or a VIBE-SYNC package",
            filetypes=[("Project / VIBE-SYNC package (.zip)", "*.zip"), ("All files", "*.*")],
        )
    finally:
        root.destroy()


def _as_str(value) -> str:
    return value if isinstance(value, str) else ""


class PackerApp:
    def __init__(self):
        pygame.init()

        # The icon must be set BEFORE set_mode() — otherwise on some systems
        # (especially Windows) it won't be applied to the already-created window.
        icon_surface = load_app_icon()
        if icon_surface is not None:
            pygame.display.set_icon(icon_surface)

        pygame.display.set_caption(APP_NAME)
        self.window_size = list(WINDOW_SIZE)
        self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        try:
            pygame.scrap.init()  # needed for Ctrl+V in text fields (packer_widgets.TextInput)
        except pygame.error:
            pass  # the fields still work without a clipboard, just without pasting
        self.clock = pygame.time.Clock()

        self.font = app_font.get_font(BASE_DIR, 15)
        self.font_bold = app_font.get_font(BASE_DIR, 17, bold=True)
        self.font_small = app_font.get_font(BASE_DIR, 12)

        self.logo_surface = load_logo()
        self._logo_area_h = (LOGO_HEIGHT + 20 + 16) if self.logo_surface is not None else 56

        self.toast = Toast()
        self.running = True
        self._lyrics_data: dict | None = None
        self._lyrics_status: str | None = None

        self._project_path: str | None = None  # the project file last saved/opened (shown in the window title)
        self._last_autosave_json: str | None = None
        self._last_autosave_ms = 0

        self._build_widgets()
        self._restore_last_session()

    def _build_widgets(self):
        pad = 24
        w = FORM_WIDTH
        row_h = 32
        y = self._logo_area_h + 20

        self.audio_row = FileRow(pygame.Rect(pad, y, w, row_h), "Track (.mp3 / .ogg)...")
        y += row_h + 14
        self.image_row = FileRow(pygame.Rect(pad, y, w, row_h), "Cover (optional)...")
        y += row_h + 14
        self.video_row = FileRow(pygame.Rect(pad, y, w, row_h), "Background video (optional)...")
        y += row_h + 34

        self._theme_section_y = y
        extract_btn_w, extract_btn_h = 168, 22
        self.extract_palette_button = Button(
            pygame.Rect(pad + w - extract_btn_w, y - 2, extract_btn_w, extract_btn_h),
            "Extract from cover",
            small=True,
        )
        y += 26

        self.theme_swatches = {}
        for key in ("bg", "accent", "text"):
            self.theme_swatches[key] = ColorSwatchInput(
                pygame.Rect(pad, y, w, row_h - 4), key, DEFAULT_THEME_RGB[key]
            )
            y += row_h + 6

        y += 20
        self._bpm_section_y = y
        y += 40

        bpm_w = 140
        self.bpm_input = TextInput(pygame.Rect(pad, y, bpm_w, row_h), placeholder="e.g. 128", numeric=True)
        self.bpm_offset_input = TextInput(
            pygame.Rect(pad + bpm_w + 90, y, bpm_w, row_h), placeholder="0.0", numeric=True
        )
        y += row_h + 14

        self.camera_hits_input = TextInput(
            pygame.Rect(pad, y, w, row_h), placeholder="or an explicit list of seconds: 0.5, 1.0, 1.5 ..."
        )
        y += row_h + 20

        self.bgvideo_sync_checkbox = Checkbox(pygame.Rect(pad, y, 18, 18), "bgvideo_sync (video is synced to the track)")
        y += 34 + 16

        self._effects_section_y = y
        y += 26
        # The viewport height is fixed (150px = ~3.5 rows) and doesn't grow
        # with the number of added effects — extras scroll, see handle_event.
        self.effects_editor = EffectsEditor(pygame.Rect(pad, y, w, 0), view_height=150)
        y += self.effects_editor.view_height + 24
        self._bottom_y = y

        preview_x = pad + w + COLUMN_GAP
        self.preview_panel = PreviewPanel(
            pygame.Rect(preview_x, self._logo_area_h + 20, self.window_size[0] - preview_x - pad, self.window_size[1] - self._logo_area_h - 40)
        )

        btn_w, btn_h = 220, 42
        self.build_button = Button(pygame.Rect(preview_x, 0, btn_w, btn_h), "Build .zip package")

        # Project buttons (top-right corner) — positioned in _reflow_right_column()
        self.open_project_button = Button(pygame.Rect(0, 0, 118, 26), "Open Project", small=True)
        self.save_project_button = Button(pygame.Rect(0, 0, 118, 26), "Save Project", small=True)

        # SpicyLyrics (developers.spicylyrics.org) — lyrics with per-syllable
        # sync: needs the track's Spotify track id + an API key (see the link
        # in the label). The key is saved locally so it isn't re-entered every time.
        self.spicylyrics_track_input = TextInput(pygame.Rect(preview_x, 0, 10, 32), placeholder="Spotify track id (22 characters)")
        self.spicylyrics_key_input = TextInput(pygame.Rect(preview_x, 0, 10, 32), placeholder="API key (sl_sk_... / sl_pk_...)")
        saved_key = _load_spicylyrics_key()
        if saved_key:
            self.spicylyrics_key_input.set_text(saved_key)
        self.fetch_lyrics_button = Button(pygame.Rect(preview_x, 0, 10, 34), "Fetch lyrics (SpicyLyrics)", small=True)

        self._reflow_right_column()

    def _reflow_right_column(self):
        """Recomputes the position/size of the preview panel, the build
        button, the SpicyLyrics block and the project buttons for the
        current self.window_size — called both from _build_widgets() and on
        every window resize (VIDEORESIZE)."""
        pad = 24
        preview_x = pad + FORM_WIDTH + COLUMN_GAP
        preview_w = max(240, self.window_size[0] - preview_x - pad)
        preview_h = self.window_size[1] - self._logo_area_h - 20 - 76  # leave room for the build button at the bottom
        self.preview_panel.set_rect(pygame.Rect(preview_x, self._logo_area_h + 20, preview_w, preview_h))

        self.build_button.rect.topleft = (preview_x, self.preview_panel.bottom + 16)
        self.build_button.rect.width = preview_w

        y = self.build_button.rect.bottom + 24
        self.spicylyrics_track_input.rect.update(preview_x, y, preview_w, 32)
        y += 32 + 8
        self.spicylyrics_key_input.rect.update(preview_x, y, preview_w, 32)
        y += 32 + 8
        self.fetch_lyrics_button.rect.update(preview_x, y, preview_w, 34)

        # Project buttons — anchored to the top-right corner of the window
        right_edge = self.window_size[0] - pad
        self.save_project_button.rect.topright = (right_edge, 20)
        self.open_project_button.rect.topright = (self.save_project_button.rect.left - 8, 20)

    # ------------------------------------------------------------------ #
    # Project state: save / open / autosave (continue working later)
    # ------------------------------------------------------------------ #

    def _current_theme_overrides(self) -> dict:
        overrides = {}
        for key, swatch in self.theme_swatches.items():
            rgb = swatch.rgb
            if rgb is not None:
                overrides[key] = rgb
        return overrides

    def _collect_project_state(self) -> dict:
        """Snapshot of the whole form. Raw texts are stored as-is (not
        validated), so even a half-filled form is restored exactly."""
        return build_project_state(
            audio_path=self.audio_row.path,
            image_path=self.image_row.path,
            video_path=self.video_row.path,
            theme_overrides=self._current_theme_overrides(),
            bpm_text=self.bpm_input.text,
            bpm_offset_text=self.bpm_offset_input.text,
            camera_hits_text=self.camera_hits_input.text,
            bgvideo_sync=self.bgvideo_sync_checkbox.checked,
            effects=self.effects_editor.to_effects_list(),
            spicylyrics_track_id=self.spicylyrics_track_input.text,
            lyrics=self._lyrics_data,
        )

    def _apply_project_state(self, data: dict) -> list[str]:
        """Restores the form from a project dict. Tolerant of missing/odd
        fields (a hand-edited project should still open with the rest
        intact). Returns the names of referenced files that no longer exist
        on disk, so the caller can warn about them."""
        self.audio_row.set_path(_as_str(data.get("audio_path")))
        self.image_row.set_path(_as_str(data.get("image_path")))
        self.video_row.set_path(_as_str(data.get("video_path")))

        theme = data.get("theme")
        theme = theme if isinstance(theme, dict) else {}
        for key, swatch in self.theme_swatches.items():
            value = theme.get(key)
            valid = (
                isinstance(value, (list, tuple))
                and len(value) == 3
                and all(isinstance(c, (int, float)) for c in value)
            )
            swatch.set_value(value if valid else None)

        self.bpm_input.set_text(_as_str(data.get("bpm_text")))
        self.bpm_offset_input.set_text(_as_str(data.get("bpm_offset_text")))
        self.camera_hits_input.set_text(_as_str(data.get("camera_hits_text")))
        self.bgvideo_sync_checkbox.set_checked(bool(data.get("bgvideo_sync")))

        effects = data.get("effects")
        self.effects_editor.set_effects(effects if isinstance(effects, list) else [])

        self.spicylyrics_track_input.set_text(_as_str(data.get("spicylyrics_track_id")))
        lyrics = data.get("lyrics")
        self._lyrics_data = lyrics if isinstance(lyrics, dict) and lyrics else None

        missing = []
        for label, row in (("track", self.audio_row), ("cover", self.image_row), ("video", self.video_row)):
            if row.path and not os.path.isfile(row.path):
                missing.append(label)
        return missing

    def _set_project_path(self, path: str | None):
        self._project_path = path
        if path:
            pygame.display.set_caption(f"{APP_NAME} - {os.path.basename(path)}")
        else:
            pygame.display.set_caption(APP_NAME)

    def _on_save_project_clicked(self):
        if self._project_path:
            default_name = os.path.basename(self._project_path)
        elif self.audio_row.path:
            default_name = os.path.splitext(os.path.basename(self.audio_row.path))[0] + "_project.zip"
        else:
            default_name = "project.zip"

        path = _ask_project_save_path(default_name)
        if not path:
            return

        try:
            not_bundled = save_project_file(path, self._collect_project_state())
        except ProjectFileError as e:
            self.toast.show(str(e), is_error=True)
            return

        self._set_project_path(path)
        if not_bundled:
            self.toast.show(
                f"Project saved: {os.path.basename(path)}\n"
                f"Not included (file not found): {', '.join(not_bundled)}.",
                is_error=True,
            )
        else:
            self.toast.show(f"Project saved: {os.path.basename(path)}", is_error=False)

    def _on_open_project_clicked(self):
        path = _ask_project_open_path()
        if not path:
            return

        try:
            data = load_project_file(path)
        except ProjectFileError as e:
            self.toast.show(str(e), is_error=True)
            return

        imported_package = bool(data.pop(IMPORTED_PACKAGE_KEY, False))
        missing = self._apply_project_state(data)
        # An imported finished package isn't a project file: don't remember its
        # path, so "Save Project" can't default to overwriting the package.
        self._set_project_path(None if imported_package else path)
        kind = "VIBE-SYNC package" if imported_package else "Project"
        if missing:
            self.toast.show(
                f"{kind} opened, but these files were not found: {', '.join(missing)}.\n"
                "Use Browse to point to their new location.",
                is_error=True,
            )
        else:
            self.toast.show(f"{kind} opened: {os.path.basename(path)}", is_error=False)

    def _autosave(self, force: bool = False):
        """Writes the current form to the "last session" file, only if it
        changed since the last autosave (so an idle app doesn't touch the
        disk). Never raises — autosave must not get in the way of work."""
        try:
            state_json = json.dumps(self._collect_project_state(), sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        if not force and state_json == self._last_autosave_json:
            return
        try:
            save_autosave_file(AUTOSAVE_PATH, json.loads(state_json))
            self._last_autosave_json = state_json
        except ProjectFileError:
            pass  # not critical — the next tick will try again

    def _restore_last_session(self):
        """On startup, restores the form from the last autosave (if any)."""
        if not os.path.isfile(AUTOSAVE_PATH):
            return
        try:
            data = load_project_file(AUTOSAVE_PATH)
        except ProjectFileError as e:
            print(f"[VIBE-SYNC Packer] Could not restore the last session: {e}")
            return

        has_content = any(data.get(k) for k in ("audio_path", "image_path", "video_path", "camera_hits_text", "effects"))
        missing = self._apply_project_state(data)
        # Baseline for change detection, so the just-restored state isn't rewritten immediately
        try:
            self._last_autosave_json = json.dumps(self._collect_project_state(), sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            self._last_autosave_json = None

        if has_content:
            if missing:
                self.toast.show(
                    f"Last session restored, but these files were not found: {', '.join(missing)}.",
                    is_error=True,
                )
            else:
                self.toast.show("Last session restored - continue where you left off.", is_error=False)

    # ------------------------------------------------------------------ #

    def _on_resize(self, new_size):
        self.window_size = [max(MIN_WINDOW_SIZE[0], new_size[0]), max(MIN_WINDOW_SIZE[1], new_size[1])]
        self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self._reflow_right_column()

    def run(self):
        while self.running:
            mouse_pos = pygame.mouse.get_pos()
            for event in pygame.event.get():
                if event.type == pygame.VIDEORESIZE:
                    self._on_resize(event.size)
                    continue
                self._handle_event(event, mouse_pos)

            self.build_button.handle_hover(mouse_pos)
            self.extract_palette_button.handle_hover(mouse_pos)
            self.open_project_button.handle_hover(mouse_pos)
            self.save_project_button.handle_hover(mouse_pos)
            self.audio_row.handle_hover(mouse_pos)
            self.image_row.handle_hover(mouse_pos)
            self.video_row.handle_hover(mouse_pos)
            self.effects_editor.handle_hover(mouse_pos)
            self.preview_panel.handle_hover(mouse_pos)
            self.fetch_lyrics_button.handle_hover(mouse_pos)

            self.preview_panel.set_audio(self.audio_row.path or None)
            self.preview_panel.update(self._compute_preview_camera_hits(), self.effects_editor.to_effects_list())

            now_ms = pygame.time.get_ticks()
            if now_ms - self._last_autosave_ms >= AUTOSAVE_INTERVAL_MS:
                self._last_autosave_ms = now_ms
                self._autosave()

            self._draw()
            self.clock.tick(FPS)

        self._autosave(force=True)  # final save on exit, so nothing typed since the last tick is lost
        pygame.quit()

    def _handle_event(self, event, mouse_pos):
        if event.type == pygame.QUIT:
            self.running = False
            return

        # Keyboard shortcuts: Ctrl+S = save project, Ctrl+O = open project
        if event.type == pygame.KEYDOWN and (pygame.key.get_mods() & pygame.KMOD_CTRL):
            if event.key == pygame.K_s:
                self._on_save_project_clicked()
                return
            if event.key == pygame.K_o:
                self._on_open_project_clicked()
                return

        if self.save_project_button.is_clicked(mouse_pos, event):
            self._on_save_project_clicked()
            return
        if self.open_project_button.is_clicked(mouse_pos, event):
            self._on_open_project_clicked()
            return

        if self.audio_row.browse_clicked(mouse_pos, event):
            path = _ask_audio_path()
            if path:
                self.audio_row.set_path(path)
            return
        if self.image_row.browse_clicked(mouse_pos, event):
            path = _ask_image_path()
            if path:
                self.image_row.set_path(path)
            return
        if self.video_row.browse_clicked(mouse_pos, event):
            path = _ask_video_path()
            if path:
                self.video_row.set_path(path)
            return

        if self.build_button.is_clicked(mouse_pos, event):
            self._on_build_clicked()
            return

        if self.preview_panel.handle_event(event, mouse_pos):
            return

        if self.fetch_lyrics_button.is_clicked(mouse_pos, event):
            self._on_fetch_lyrics_clicked()
            return

        if self.extract_palette_button.is_clicked(mouse_pos, event):
            self._on_extract_palette_clicked()
            return

        for swatch in self.theme_swatches.values():
            if swatch.handle_event(event):
                return

        self.bpm_input.handle_event(event)
        self.bpm_offset_input.handle_event(event)
        self.camera_hits_input.handle_event(event)
        self.bgvideo_sync_checkbox.handle_event(event)
        self.effects_editor.handle_event(event)
        self.spicylyrics_track_input.handle_event(event)
        self.spicylyrics_key_input.handle_event(event)

    def _on_fetch_lyrics_clicked(self):
        track_id = self.spicylyrics_track_input.text
        api_key = self.spicylyrics_key_input.text
        try:
            body = fetch_spicylyrics(track_id, api_key)
        except VibeSyncPackError as e:
            self._lyrics_data = None
            self.toast.show(str(e), is_error=True)
            return

        _save_spicylyrics_key(api_key)  # the key works since the request succeeded — save it for the future
        self._lyrics_data = body
        line_count = len(body.get("Content") or [])
        sync_type = body.get("Type", "?")
        self.toast.show(f"Lyrics fetched: {line_count} lines, {sync_type} sync.", is_error=False)

    def _compute_preview_camera_hits(self) -> list[float]:
        """The same priority logic as in build_sync_json/vibesync.py: an
        explicit list of seconds if set, otherwise generation from BPM (only
        if the track duration is already known — see PreviewPanel.set_audio)."""
        explicit = parse_camera_hits_text(self.camera_hits_input.text)
        if explicit:
            return explicit

        bpm_text = self.bpm_input.text.strip()
        duration = self.preview_panel.duration_sec
        if not bpm_text or not duration:
            return []
        try:
            bpm = float(bpm_text)
        except ValueError:
            return []
        if bpm <= 0:
            return []

        try:
            offset = max(0.0, float(self.bpm_offset_input.text.strip() or 0.0))
        except ValueError:
            offset = 0.0

        interval = 60.0 / bpm
        hits = []
        t = offset
        while t <= duration and len(hits) < 2000:
            hits.append(round(t, 3))
            t += interval
        return hits

    def _on_extract_palette_clicked(self):
        image_path = self.image_row.path
        if not image_path:
            self.toast.show("Select a cover first.", is_error=True)
            return
        if not os.path.isfile(image_path):
            self.toast.show(f"Cover file not found: {image_path}", is_error=True)
            return

        try:
            palette = extract_palette(image_path)
        except PaletteExtractError as e:
            self.toast.show(str(e), is_error=True)
            return

        for key, rgb in palette.items():
            self.theme_swatches[key].set_value(rgb)

        self.toast.show("Palette extracted from the cover.", is_error=False)

    def _on_build_clicked(self):
        audio_path = self.audio_row.path
        image_path = self.image_row.path or None
        video_path = self.video_row.path or None

        if not audio_path:
            self.toast.show("Select the track audio file first.", is_error=True)
            return

        default_name = os.path.splitext(os.path.basename(audio_path))[0] + ".zip"
        output_path = _ask_output_path(default_name)
        if not output_path:
            return

        theme_overrides = self._current_theme_overrides()

        bpm = None
        if self.bpm_input.text.strip():
            try:
                bpm = float(self.bpm_input.text.strip())
            except ValueError:
                self.toast.show("BPM must be a number.", is_error=True)
                return

        bpm_offset = 0.0
        if self.bpm_offset_input.text.strip():
            try:
                bpm_offset = float(self.bpm_offset_input.text.strip())
            except ValueError:
                self.toast.show("BPM offset must be a number.", is_error=True)
                return

        sync_data = build_sync_json(
            theme_overrides=theme_overrides,
            bpm=bpm,
            bpm_offset_sec=bpm_offset,
            camera_hits_text=self.camera_hits_input.text,
            bgvideo_sync=self.bgvideo_sync_checkbox.checked,
            effects=self.effects_editor.to_effects_list(),
            lyrics=self._lyrics_data,
        )

        try:
            build_package(
                audio_path=audio_path,
                output_path=output_path,
                image_path=image_path,
                video_path=video_path,
                sync_data=sync_data,
            )
        except VibeSyncPackError as e:
            self.toast.show(str(e), is_error=True)
            return

        self._autosave(force=True)
        self.toast.show(f"Done: {os.path.basename(output_path)}", is_error=False)

    # ------------------------------------------------------------------ #

    def _draw(self):
        self.screen.fill(PALETTE["bg"])

        if self.logo_surface is not None:
            logo_x = (self.window_size[0] - LOGO_WIDTH) // 2
            self.screen.blit(self.logo_surface, (logo_x, 20))
        else:
            title_surf = self.font_bold.render(APP_NAME, True, PALETTE["text"])
            self.screen.blit(title_surf, (24, 20))

        self.open_project_button.draw(self.screen, self.font_small, PALETTE)
        self.save_project_button.draw(self.screen, self.font_small, PALETTE)

        self._draw_section_label("Files", self._logo_area_h)
        self.audio_row.draw(self.screen, self.font, PALETTE)
        self.image_row.draw(self.screen, self.font, PALETTE)
        self.video_row.draw(self.screen, self.font, PALETTE)

        self._draw_section_label("Theme (sync.json - theme)", self._theme_section_y)
        self.extract_palette_button.draw(self.screen, self.font_small, PALETTE)
        for swatch in self.theme_swatches.values():
            swatch.draw(self.screen, self.font, PALETTE)

        self._draw_section_label("Camera hits (sync.json - bpm / camera_hits)", self._bpm_section_y)
        bpm_label = self.font_small.render("BPM", True, PALETTE["text_dim"])
        self.screen.blit(bpm_label, (self.bpm_input.rect.x, self.bpm_input.rect.y - 16))
        offset_label = self.font_small.render("Offset, sec", True, PALETTE["text_dim"])
        self.screen.blit(offset_label, (self.bpm_offset_input.rect.x, self.bpm_offset_input.rect.y - 16))
        self.bpm_input.draw(self.screen, self.font, PALETTE)
        self.bpm_offset_input.draw(self.screen, self.font, PALETTE)
        self.camera_hits_input.draw(self.screen, self.font, PALETTE)

        self.bgvideo_sync_checkbox.draw(self.screen, self.font, PALETTE)

        self._draw_section_label("Glitch effects (sync.json - effects)", self._effects_section_y)
        self.effects_editor.draw(self.screen, self.font_small, PALETTE)

        self.build_button.draw(self.screen, self.font_bold, PALETTE)

        self.preview_panel.draw(self.screen, self.font, self.font_small, PALETTE, self._current_theme_overrides())

        lyrics_label = self.font_small.render(
            "Lyrics (SpicyLyrics, developers.spicylyrics.org)", True, PALETTE["text_dim"],
        )
        self.screen.blit(lyrics_label, (self.spicylyrics_track_input.rect.x, self.spicylyrics_track_input.rect.y - 16))
        self.spicylyrics_track_input.draw(self.screen, self.font, PALETTE)
        self.spicylyrics_key_input.draw(self.screen, self.font, PALETTE)
        self.fetch_lyrics_button.draw(self.screen, self.font_small, PALETTE)
        if self._lyrics_data is not None:
            status = self.font_small.render(
                f"✓ lyrics loaded ({self._lyrics_data.get('Type', '?')})", True, PALETTE["accent"],
            )
            self.screen.blit(status, (self.fetch_lyrics_button.rect.x, self.fetch_lyrics_button.rect.bottom + 8))

        self.toast.draw(self.screen, self.font, self.window_size[0], self.window_size[1], PALETTE)

        pygame.display.flip()

    def _draw_section_label(self, text: str, y: int):
        surf = self.font_small.render(text.upper(), True, PALETTE["text_dim"])
        self.screen.blit(surf, (24, y))


def main():
    app = PackerApp()
    app.run()


if __name__ == "__main__":
    main()
