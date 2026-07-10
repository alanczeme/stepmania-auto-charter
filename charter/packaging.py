"""Phase 3 packaging: turn an AutoStepper output folder into a proper
Songs/<Group>/<Song Title>/ folder (exactly two levels deep, or StepMania
won't show it in the song wheel), with dedupe-by-suffix and a resume-skip
check for songs already packaged by an earlier run.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

import requests

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize(name: str) -> str:
    cleaned = _UNSAFE_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "Untitled"


def target_dir(export_dir: Path, group: str, title: str) -> Path:
    return export_dir / sanitize(group) / sanitize(title)


def already_done(target: Path) -> bool:
    return target.exists() and any(target.iterdir())


def unique_target_dir(export_dir: Path, group: str, title: str) -> Path:
    """First non-existing candidate, auto-suffixing " (2)", " (3)", ... on collision."""
    base = sanitize(title)
    group_dir = export_dir / sanitize(group)
    candidate = group_dir / base
    n = 2
    while candidate.exists():
        candidate = group_dir / f"{base} ({n})"
        n += 1
    return candidate


AUDIO_EXTS = (".mp3", ".ogg", ".wav", ".flac")
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
CHART_EXTS = (".sm", ".ssc")


def package(
    chart_folder: Path,
    final_target: Path,
    thumbnail_url: Optional[str],
    title: str,
    artist: Optional[str],
) -> Path:
    """Copy AutoStepper's output into final_target, rename files to match
    <Song Title>[.ext / -bg.ext / -jacket.ext] convention, backfill artwork
    from the source thumbnail if AutoStepper produced none, and rewrite the
    chart file's #TITLE/#ARTIST/#MUSIC/#BACKGROUND/#BANNER tags to match --
    StepMania reads the song's display name from those tags, not from
    filenames, and AutoStepper otherwise leaves #TITLE as the input file's
    name (always "audio", since that's what we name the downloaded file).
    """
    final_target.mkdir(parents=True, exist_ok=True)
    for item in chart_folder.iterdir():
        dest = final_target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    if not any(f.suffix.lower() in IMAGE_EXTS for f in final_target.iterdir() if f.is_file()):
        _fetch_fallback_artwork(final_target, thumbnail_url)

    rename_map, filenames = _rename_to_convention(final_target, sanitize(title))
    for chart_path in list(final_target.glob("*.sm")) + list(final_target.glob("*.ssc")):
        _patch_chart_tags(chart_path, title, artist, rename_map, filenames)

    return final_target


def _fetch_fallback_artwork(target: Path, thumbnail_url: Optional[str]) -> None:
    if not thumbnail_url:
        return
    try:
        resp = requests.get(thumbnail_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return  # best-effort only; missing art isn't fatal

    ext = ".jpg" if "jpg" in thumbnail_url or "jpeg" in thumbnail_url else ".png"
    (target / f"background{ext}").write_bytes(resp.content)
    shutil.copy2(target / f"background{ext}", target / f"banner{ext}")


def _rename_to_convention(target: Path, base: str):
    """Rename audio/chart/image files to <base>.ext / <base>-bg.ext /
    <base>-jacket.ext, matching this library's existing packs.

    Returns (rename_map, filenames): rename_map is every old filename -> new
    filename (used to repoint tags even when a file is renamed under a role
    different from what a tag originally called it -- e.g. AutoStepper
    pointing both #BACKGROUND and #BANNER at the same image); filenames is
    the new name for each role, for filling in tags that were blank.
    """
    rename_map: dict = {}
    filenames: dict = {"music": None, "background": None, "banner": None}

    for f in sorted(target.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        old_name = f.name
        if ext in AUDIO_EXTS:
            filenames["music"] = _rename(f, target / f"{base}{ext}")
            rename_map[old_name] = filenames["music"]
        elif ext in CHART_EXTS:
            new_name = _rename(f, target / f"{base}{ext}")
            rename_map[old_name] = new_name
        elif ext in IMAGE_EXTS:
            lowered = f.stem.lower()
            if "background" in lowered or lowered.endswith("-bg") or lowered == "bg":
                filenames["background"] = _rename(f, target / f"{base}-bg{ext}")
                rename_map[old_name] = filenames["background"]
            elif "banner" in lowered:
                filenames["banner"] = _rename(f, target / f"{base}-jacket{ext}")
                rename_map[old_name] = filenames["banner"]
            # anything else (e.g. a pre-existing cdtitle.png) is left as-is

    return rename_map, filenames


def _rename(src: Path, dest: Path) -> str:
    if src != dest:
        src.rename(dest)
    return dest.name


def _patch_chart_tags(
    chart_path: Path,
    title: str,
    artist: Optional[str],
    rename_map: dict,
    filenames: dict,
) -> None:
    text = chart_path.read_text(errors="replace")

    def get_tag(tag: str, content: str) -> str:
        match = re.search(rf"#{tag}:([^;]*);", content)
        return match.group(1).strip() if match else ""

    def set_tag(tag: str, value: str, content: str) -> str:
        safe_value = value.replace(";", ",").replace("\n", " ").strip()
        pattern = re.compile(rf"#{tag}:[^;]*;")
        replacement = f"#{tag}:{safe_value};"
        if pattern.search(content):
            return pattern.sub(replacement, content, count=1)
        return replacement + "\n" + content  # tag missing entirely -- prepend it

    text = set_tag("TITLE", title, text)
    text = set_tag("ARTIST", artist or "", text)

    for tag, role in (("MUSIC", "music"), ("BACKGROUND", "background"), ("BANNER", "banner")):
        old_value = get_tag(tag, text)
        if old_value in rename_map:
            # whatever file this tag pointed at got renamed -- follow it,
            # regardless of which role we classified that file under.
            text = set_tag(tag, rename_map[old_value], text)
        elif not old_value and filenames.get(role):
            # tag was blank and we have a file for this role (freshly
            # fetched fallback art has no "old name" to be in rename_map).
            text = set_tag(tag, filenames[role], text)
        elif role == "music" and filenames.get("music"):
            # there's always exactly one audio file; make sure MUSIC always
            # points at it even if the old value matched nothing above.
            text = set_tag(tag, filenames["music"], text)

    chart_path.write_text(text)


def mirror_to_stepmania(final_target: Path, group: str, stepmania_songs_dir: str) -> Path:
    """Optional convenience copy straight into a local StepMania install's Songs/ dir."""
    dest = Path(stepmania_songs_dir).expanduser() / sanitize(group) / final_target.name
    shutil.copytree(final_target, dest, dirs_exist_ok=True)
    return dest
