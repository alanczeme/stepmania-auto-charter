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


def package(chart_folder: Path, final_target: Path, thumbnail_url: Optional[str]) -> Path:
    """Copy AutoStepper's output into final_target and backfill artwork if missing."""
    final_target.mkdir(parents=True, exist_ok=True)
    for item in chart_folder.iterdir():
        dest = final_target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    _ensure_artwork(final_target, thumbnail_url)
    return final_target


def _ensure_artwork(target: Path, thumbnail_url: Optional[str]) -> None:
    has_image = any(
        f.suffix.lower() in (".png", ".jpg", ".jpeg") for f in target.iterdir() if f.is_file()
    )
    if has_image or not thumbnail_url:
        return

    try:
        resp = requests.get(thumbnail_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return  # best-effort only; missing art isn't fatal

    ext = ".jpg" if "jpg" in thumbnail_url or "jpeg" in thumbnail_url else ".png"
    image_path = target / f"background{ext}"
    image_path.write_bytes(resp.content)
    shutil.copy2(image_path, target / f"banner{ext}")

    for sm_path in target.glob("*.sm"):
        _patch_sm_artwork_tags(sm_path, f"background{ext}", f"banner{ext}")


def _patch_sm_artwork_tags(sm_path: Path, background_name: str, banner_name: str) -> None:
    text = sm_path.read_text(errors="replace")

    def patch(tag: str, filename: str, content: str) -> str:
        pattern = re.compile(rf"(#{tag}:)([^;]*);")
        if re.search(pattern, content):
            match = re.search(pattern, content)
            if match.group(2).strip():
                return content  # already set to something, leave it alone
            return pattern.sub(rf"\g<1>{filename};", content, count=1)
        return content

    text = patch("BACKGROUND", background_name, text)
    text = patch("BANNER", banner_name, text)
    sm_path.write_text(text)


def mirror_to_stepmania(final_target: Path, group: str, stepmania_songs_dir: str) -> Path:
    """Optional convenience copy straight into a local StepMania install's Songs/ dir."""
    dest = Path(stepmania_songs_dir).expanduser() / sanitize(group) / final_target.name
    shutil.copytree(final_target, dest, dirs_exist_ok=True)
    return dest
