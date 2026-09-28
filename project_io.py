"""
Project state save/load — lets a packer session be paused and resumed
later, without having to build a VIBE-SYNC package in between.

A project is a .zip archive:

    (name)_project.zip
    ├── project.json                — the form state (see build_project_state)
    └── media/
        ├── audio/(track).mp3       — copies of the source files, so the
        ├── image/(cover).png         project is self-contained and can be
        └── video/(video).mp4         moved to another folder/computer

A finished VIBE-SYNC package (the .zip this packer builds and the player
loads: track + resources/ + sync.json) can be opened too — it is imported
into the form so it can be edited and rebuilt (see _read_vibesync_package).

Used for two things in main.py:
  - the explicit "Save Project" / "Open Project" buttons (a .zip the user
    chooses the location of), and
  - the automatic "last session" autosave (a small plain .json that just
    references the original files — see save_autosave_file), restored on
    the next launch.

Knows nothing about the GUI — works with plain JSON-serializable types
only, like vibesync_pack.py, so the format can be reused/tested on its own.

Deliberately NOT stored: the SpicyLyrics API key. It's a secret and project
files are meant to be shareable; the key has its own local file (see
main.py: SPICYLYRICS_KEY_PATH).
"""

import json
import os
import zipfile

from vibesync_pack import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


PROJECT_FORMAT_VERSION = 1


class ProjectFileError(Exception):
    """The project file couldn't be read, written, or isn't a valid project."""


def build_project_state(
    audio_path: str,
    image_path: str,
    video_path: str,
    theme_overrides: dict,
    bpm_text: str,
    bpm_offset_text: str,
    camera_hits_text: str,
    bgvideo_sync: bool,
    effects: list[dict],
    spicylyrics_track_id: str,
    lyrics: dict | None,
) -> dict:
    """Packs the current form values into a JSON-serializable dict. The
    BPM/hits fields are kept as raw text (exactly what's typed in the
    inputs), so a half-filled form is restored exactly as it was left."""
    return {
        "format_version": PROJECT_FORMAT_VERSION,
        "audio_path": audio_path or "",
        "image_path": image_path or "",
        "video_path": video_path or "",
        "theme": {key: list(rgb) for key, rgb in (theme_overrides or {}).items()},
        "bpm_text": bpm_text or "",
        "bpm_offset_text": bpm_offset_text or "",
        "camera_hits_text": camera_hits_text or "",
        "bgvideo_sync": bool(bgvideo_sync),
        "effects": list(effects or []),
        "spicylyrics_track_id": spicylyrics_track_id or "",
        "lyrics": lyrics or None,
    }


PROJECT_JSON_NAME = "project.json"
# Set on the state returned for an imported VIBE-SYNC package (as opposed to
# a packer project) — main.py uses it so "Save Project" never defaults to
# overwriting the user's finished package.
IMPORTED_PACKAGE_KEY = "_imported_package"
MEDIA_KEYS = (("audio_path", "audio"), ("image_path", "image"), ("video_path", "video"))


def _atomic_write(path: str, writer) -> None:
    """Runs writer(tmp_path) and atomically renames the result over path —
    so a crash/disk error midway can't leave a half-written (unreadable)
    file under the real name."""
    tmp_path = path + ".tmp"
    try:
        out_dir = os.path.dirname(os.path.abspath(path))
        os.makedirs(out_dir, exist_ok=True)
        writer(tmp_path)
        os.replace(tmp_path, path)
    except OSError as e:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise ProjectFileError(f"Failed to save the project: {e}") from e


def save_project_file(path: str, state: dict) -> list[str]:
    """Writes the project .zip: project.json plus a copy of every source
    file that still exists. Files that no longer exist stay referenced by
    their original path (nothing to bundle). Returns the kinds of files
    that could not be bundled (e.g. ["video"])."""
    state = dict(state)
    not_bundled: list[str] = []
    to_bundle: list[tuple[str, str]] = []  # (source path on disk, name inside the zip)

    for key, kind in MEDIA_KEYS:
        source = state.get(key) or ""
        if not source:
            continue
        if not os.path.isfile(source):
            not_bundled.append(kind)
            continue
        arcname = f"media/{kind}/{os.path.basename(source)}"
        state[key] = arcname
        to_bundle.append((source, arcname))

    def writer(tmp_path: str):
        with zipfile.ZipFile(tmp_path, "w") as zf:
            zf.writestr(
                PROJECT_JSON_NAME,
                json.dumps(state, ensure_ascii=False, indent=2),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            for source, arcname in to_bundle:
                # mp3/ogg/png/mp4 are already compressed — storing is much faster
                zf.write(source, arcname, compress_type=zipfile.ZIP_STORED)

    _atomic_write(path, writer)
    return not_bundled


def save_autosave_file(path: str, state: dict) -> None:
    """Plain .json for the automatic last-session save: it only references
    the original files (copying a big video every few seconds would be
    absurd), so it's small and fast."""
    def writer(tmp_path: str):
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    _atomic_write(path, writer)


def _read_json_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise ProjectFileError(f"Failed to read the project file: {e}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProjectFileError(f"The project file is not valid JSON: {e}") from e


def _extract_member(zf: zipfile.ZipFile, member: str, target_dir: str) -> str:
    """Unpacks one archive member into target_dir and returns the path.
    Only the base name is used, so a crafted archive can't write outside
    target_dir. An already-unpacked file of the same size is reused."""
    target = os.path.join(target_dir, os.path.basename(member))
    if not (os.path.isfile(target) and os.path.getsize(target) == zf.getinfo(member).file_size):
        os.makedirs(target_dir, exist_ok=True)
        with zf.open(member) as src_f, open(target, "wb") as dst_f:
            while True:
                chunk = src_f.read(1024 * 1024)
                if not chunk:
                    break
                dst_f.write(chunk)
    return target


def _format_number(value) -> str:
    """128.0 -> "128", 0.25 -> "0.25" — for filling the numeric text fields."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number == int(number) else str(number)


def _read_vibesync_package(zf: zipfile.ZipFile, members: list[str], extract_dir: str) -> dict:
    """Imports a finished VIBE-SYNC package (track at the root, cover/video
    in resources/, optional sync.json) as a project state, unpacking the
    media into extract_dir. Everything sync.json can hold maps back onto a
    form field, so the package can be edited and built again."""
    files = [m for m in members if not m.endswith("/")]

    def pick(extensions, in_resources):
        for name in files:
            lower = name.lower()
            if lower.endswith(extensions) and lower.startswith("resources/") == in_resources:
                return name
        return None

    audio = pick(AUDIO_EXTENSIONS, in_resources=False)
    if audio is None:
        raise ProjectFileError(
            "This .zip is neither a packer project (no project.json) nor a VIBE-SYNC package "
            "(no .mp3/.ogg track inside)."
        )

    sync: dict = {}
    if "sync.json" in members:
        try:
            loaded = json.loads(zf.read("sync.json").decode("utf-8"))
            if isinstance(loaded, dict):
                sync = loaded
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ProjectFileError(f"The package's sync.json is not valid JSON: {e}") from e

    image = pick(IMAGE_EXTENSIONS, in_resources=True)
    video = pick(VIDEO_EXTENSIONS, in_resources=True)

    theme = sync.get("theme") if isinstance(sync.get("theme"), dict) else {}
    hits = sync.get("camera_hits")
    hits_text = ", ".join(_format_number(h) for h in hits) if isinstance(hits, list) else ""
    effects = sync.get("effects")
    lyrics = sync.get("lyrics")

    return {
        "format_version": PROJECT_FORMAT_VERSION,
        "audio_path": _extract_member(zf, audio, os.path.join(extract_dir, "audio")),
        "image_path": _extract_member(zf, image, os.path.join(extract_dir, "image")) if image else "",
        "video_path": _extract_member(zf, video, os.path.join(extract_dir, "video")) if video else "",
        "theme": theme,
        "bpm_text": _format_number(sync.get("bpm")) if sync.get("bpm") else "",
        "bpm_offset_text": _format_number(sync.get("bpm_offset_sec")) if sync.get("bpm_offset_sec") else "",
        "camera_hits_text": hits_text,
        "bgvideo_sync": bool(sync.get("bgvideo_sync")),
        "effects": effects if isinstance(effects, list) else [],
        "spicylyrics_track_id": "",
        "lyrics": lyrics if isinstance(lyrics, dict) and lyrics else None,
        IMPORTED_PACKAGE_KEY: True,
    }


def _read_project_zip(path: str, extract_dir: str) -> dict:
    """Reads a .zip: either a packer project (project.json + media/) or a
    finished VIBE-SYNC package. Media is unpacked into extract_dir and the
    paths in the returned state point to the unpacked files."""
    try:
        with zipfile.ZipFile(path) as zf:
            members = zf.namelist()
            if PROJECT_JSON_NAME not in members:
                return _read_vibesync_package(zf, members, extract_dir)

            data = json.loads(zf.read(PROJECT_JSON_NAME).decode("utf-8"))
            if not isinstance(data, dict):
                raise ProjectFileError("The project file doesn't contain a project (expected a JSON object).")

            member_set = set(members)
            for key, kind in MEDIA_KEYS:
                ref = data.get(key)
                if not isinstance(ref, str) or not ref.startswith(f"media/{kind}/") or ref not in member_set:
                    continue  # not bundled (a plain path to an original file) — keep as-is
                data[key] = _extract_member(zf, ref, os.path.join(extract_dir, kind))
            return data
    except zipfile.BadZipFile as e:
        raise ProjectFileError(f"The file is not a valid .zip: {e}") from e
    except OSError as e:
        raise ProjectFileError(f"Failed to read the project file: {e}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProjectFileError(f"The project data is not valid JSON: {e}") from e


def load_project_file(path: str, extract_dir: str | None = None) -> dict:
    """Reads a project .zip, a finished VIBE-SYNC package .zip, or a plain
    autosave .json. Zip media is unpacked into extract_dir (by default a
    "(name)_files" folder next to the zip). Individual fields are validated later, when
    applied to the form — a project edited by hand with a missing/odd
    field should still open with the rest intact."""
    if zipfile.is_zipfile(path):
        if extract_dir is None:
            extract_dir = os.path.splitext(os.path.abspath(path))[0] + "_files"
        data = _read_project_zip(path, extract_dir)
    else:
        data = _read_json_file(path)

    if not isinstance(data, dict):
        raise ProjectFileError("The project file doesn't contain a project (expected a JSON object).")

    version = data.get("format_version")
    if isinstance(version, int) and version > PROJECT_FORMAT_VERSION:
        raise ProjectFileError(
            f"This project was saved by a newer version of the packer (format {version}); "
            f"this version understands up to format {PROJECT_FORMAT_VERSION}."
        )
    return data
