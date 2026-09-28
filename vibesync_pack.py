"""
Builds VIBE-SYNC packages (.zip) — the inverse of load_package() from the
main player's vibesync.py. Takes paths to the source files (track,
optionally cover/video) and the sync.json parameters collected in the GUI,
and writes a .zip with the structure load_package() expects:

    (music_name).zip
    ├── resources/
    │   ├── (cover).png / .webp / .jpg     — optional
    │   └── (video).mp4                     — optional
    ├── (track).mp3 / .ogg
    └── sync.json                           — optional, present if
                                               theme/bpm/camera_hits/bgvideo_sync are set

Knows nothing about the GUI — accepts already-validated plain types
(paths, numbers, booleans), so the packaging itself can be used from tests
and from another interface if needed.
"""

import json
import os
import re
import urllib.error
import urllib.request
import zipfile


AUDIO_EXTENSIONS = (".mp3", ".ogg")
IMAGE_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")
VIDEO_EXTENSIONS = (".mp4",)

THEME_COLOR_KEYS = ("bg", "accent", "text")

SPICYLYRICS_API_BASE = "https://api.spicylyrics.org/v1/lyrics/"
_SPOTIFY_TRACK_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")


class VibeSyncPackError(Exception):
    """The collected parameters do not produce a valid VIBE-SYNC package."""


def fetch_spicylyrics(track_id: str, api_key: str) -> dict:
    """
    Requests synced lyrics from the SpicyLyrics API
    (developers.spicylyrics.org) by Spotify track id. Returns the "Body"
    of the response — the same thing we put into sync.json under the
    "lyrics" key and that the main player's lyrics.py parses (Type:
    Syllable/Line/Static — sync precision, Content — a list of lines with
    timings in seconds, see lyrics.py).
    """
    track_id = (track_id or "").strip()
    if not _SPOTIFY_TRACK_ID_RE.match(track_id):
        raise VibeSyncPackError(
            "Spotify track id must be a string of 22 Latin letters/digits (from the track link)."
        )
    api_key = (api_key or "").strip()
    if not api_key:
        raise VibeSyncPackError("No SpicyLyrics API key provided (sl_sk_... or sl_pk_...).")

    request = urllib.request.Request(
        SPICYLYRICS_API_BASE + track_id,
        headers={
            "Authorization": f"Bearer {api_key}",
            # urllib's default User-Agent ("Python-urllib/3.x") is often
            # blocked by WAFs/CDNs even when the same request through curl
            # goes through fine — a custom UA fixes exactly that case.
            "User-Agent": "VIBESYNCER/1.0 (+https://github.com/)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        message = e.reason
        try:
            detail = json.loads(e.read().decode("utf-8"))
            message = detail.get("message") or detail.get("error") or message
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        raise VibeSyncPackError(f"SpicyLyrics API returned error {e.code}: {message}") from e
    except urllib.error.URLError as e:
        raise VibeSyncPackError(f"Could not reach the SpicyLyrics API: {e.reason}") from e
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise VibeSyncPackError(f"Could not parse the SpicyLyrics API response: {e}") from e

    body = payload.get("Body") if isinstance(payload, dict) else None
    if not body:
        raise VibeSyncPackError("SpicyLyrics API returned no lyrics (empty Body) for this track.")
    return body


def build_sync_json(
    theme_overrides: dict,
    bpm: float | None,
    bpm_offset_sec: float,
    camera_hits_text: str,
    bgvideo_sync: bool,
    effects: list[dict] | None = None,
    lyrics: dict | None = None,
) -> dict | None:
    """
    Builds the contents of sync.json from the GUI form parameters. Returns
    None if no field is set — in that case sync.json isn't put into the
    package at all (load_package() treats its absence as "a package with
    no timed theme").

    camera_hits_text — raw text from the input field: numbers separated by
    commas or spaces ("0.5, 1.0, 1.5"). If both camera_hits_text and bpm
    are set — the explicit list takes priority (same as in
    load_package()), so bpm isn't put into sync.json in that case, to
    avoid creating contradictory expectations for whoever opens sync.json
    by hand later.

    effects — an already-validated list of glitch effects from the GUI
    editor (see packer_widgets.EffectsEditor.to_effects_list()), in the
    same format the main player's effects.EffectsEngine understands.

    lyrics — the "Body" from the SpicyLyrics API response (see
    fetch_spicylyrics), as-is, unchanged — the player's lyrics.py parses
    it in this same form.
    """
    data: dict = {}

    if theme_overrides:
        data["theme"] = {k: list(v) for k, v in theme_overrides.items()}

    explicit_hits = _parse_camera_hits_text(camera_hits_text)
    if explicit_hits:
        data["camera_hits"] = explicit_hits
    elif bpm is not None and bpm > 0:
        data["bpm"] = bpm
        if bpm_offset_sec:
            data["bpm_offset_sec"] = bpm_offset_sec

    if bgvideo_sync:
        data["bgvideo_sync"] = True

    if effects:
        data["effects"] = effects

    if lyrics:
        data["lyrics"] = lyrics

    return data if data else None


def parse_camera_hits_text(text: str) -> list[float]:
    """Public wrapper around parsing the 'explicit list of seconds' field —
    needed by both build_sync_json and the preview panel (main.py), so the
    format isn't duplicated."""
    return _parse_camera_hits_text(text)


def _parse_camera_hits_text(text: str) -> list[float]:
    if not text or not text.strip():
        return []
    raw_parts = text.replace(",", " ").split()
    hits = []
    for part in raw_parts:
        try:
            sec = float(part)
            if sec >= 0:
                hits.append(sec)
        except ValueError:
            continue
    hits.sort()
    return hits


def validate_inputs(
    audio_path: str,
    image_path: str | None,
    video_path: str | None,
    output_path: str,
) -> None:
    """Raises VibeSyncPackError with a clear message if something is missing
    or the extensions aren't the ones the main player's load_package() expects."""
    if not audio_path:
        raise VibeSyncPackError("No track audio file selected (.mp3/.ogg).")
    if not os.path.isfile(audio_path):
        raise VibeSyncPackError(f"Audio file not found: {audio_path}")
    if not audio_path.lower().endswith(AUDIO_EXTENSIONS):
        raise VibeSyncPackError(
            f"The audio file must be .mp3 or .ogg, not {os.path.splitext(audio_path)[1]!r}."
        )

    if image_path:
        if not os.path.isfile(image_path):
            raise VibeSyncPackError(f"Cover file not found: {image_path}")
        if not image_path.lower().endswith(IMAGE_EXTENSIONS):
            raise VibeSyncPackError(
                f"The cover must be .png/.webp/.jpg, not {os.path.splitext(image_path)[1]!r}."
            )

    if video_path:
        if not os.path.isfile(video_path):
            raise VibeSyncPackError(f"Video file not found: {video_path}")
        if not video_path.lower().endswith(VIDEO_EXTENSIONS):
            raise VibeSyncPackError(
                f"The background video must be .mp4, not {os.path.splitext(video_path)[1]!r}."
            )

    if not output_path:
        raise VibeSyncPackError("No path specified for saving the .zip.")
    if not output_path.lower().endswith(".zip"):
        raise VibeSyncPackError("The output file must have a .zip extension.")


def build_package(
    audio_path: str,
    output_path: str,
    image_path: str | None = None,
    video_path: str | None = None,
    sync_data: dict | None = None,
) -> str:
    """
    Builds a .zip from the given paths. Returns output_path on success.
    Writes to a temporary file next to the target and atomically renames
    it at the end — like the unpacking in load_package(), so a build
    interrupted midway (disk error, program closed) doesn't leave a
    broken .zip under the final name.
    """
    validate_inputs(audio_path, image_path, video_path, output_path)

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    tmp_path = output_path + ".tmp"

    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            audio_arcname = os.path.basename(audio_path)
            zf.write(audio_path, audio_arcname)

            if image_path:
                zf.write(image_path, f"resources/{os.path.basename(image_path)}")

            if video_path:
                zf.write(video_path, f"resources/{os.path.basename(video_path)}")

            if sync_data:
                zf.writestr("sync.json", json.dumps(sync_data, ensure_ascii=False, indent=2))
    except OSError as e:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        raise VibeSyncPackError(f"Failed to write the .zip: {e}") from e

    os.replace(tmp_path, output_path)
    return output_path
