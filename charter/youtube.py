"""yt-dlp wrapper: playlist enumeration, search, single-video validation, download.

Everything shells out to the `yt-dlp` binary rather than importing it as a
library, per the spec (and so `yt-dlp -U` self-updates keep working normally).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import List, Optional, Tuple

from .models import Candidate

YT_DLP_BIN = "yt-dlp"


class YtDlpNotFoundError(Exception):
    pass


class VideoUnavailableError(Exception):
    """Invalid, private, age-restricted, or otherwise unwatchable video."""


class YtDlpFailure(Exception):
    """Generic yt-dlp failure -- likely YouTube changed something upstream."""


def _ensure_binary() -> None:
    if shutil.which(YT_DLP_BIN) is None:
        raise YtDlpNotFoundError(
            "yt-dlp is not installed or not on PATH. Install it with "
            "`brew install yt-dlp` (or `pip install yt-dlp`)."
        )


def _cookie_args(cookies_from_browser: Optional[str]) -> List[str]:
    return ["--cookies-from-browser", cookies_from_browser] if cookies_from_browser else []


def _run_json(args: List[str], timeout: int = 60) -> dict:
    _ensure_binary()
    try:
        proc = subprocess.run(
            [YT_DLP_BIN, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise YtDlpFailure(f"yt-dlp timed out after {timeout}s running: {' '.join(args)}") from e

    if proc.returncode != 0:
        _raise_classified_error(proc.stderr)

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise YtDlpFailure(f"yt-dlp returned unparseable output: {e}") from e


def _raise_classified_error(stderr: str) -> None:
    lowered = stderr.lower()
    if "private video" in lowered:
        raise VideoUnavailableError("This video is private.")
    if "sign in to confirm your age" in lowered or "age-restricted" in lowered:
        raise VideoUnavailableError("This video is age-restricted and requires sign-in.")
    if "confirm you" in lowered and "not a bot" in lowered:
        raise YtDlpFailure(
            "YouTube is showing a bot-check to yt-dlp. Set "
            "yt_dlp_cookies_from_browser in config.json to a browser you're logged "
            'into YouTube with (e.g. "chrome", "safari", "firefox") so yt-dlp can '
            "borrow its cookies."
        )
    if "video unavailable" in lowered or "has been removed" in lowered:
        raise VideoUnavailableError("This video is unavailable (removed or invalid link).")
    if "unsupported url" in lowered:
        raise VideoUnavailableError("Not a playable video/playlist URL.")
    raise YtDlpFailure(
        "yt-dlp failed: "
        + (stderr.strip().splitlines()[-1] if stderr.strip() else "unknown error")
        + " -- try updating with `yt-dlp -U` (YouTube periodically changes things)."
    )


def get_video_info(url: str, cookies_from_browser: Optional[str] = None) -> dict:
    """Validate + fetch metadata for a single video. Raises VideoUnavailableError/YtDlpFailure."""
    data = _run_json([*_cookie_args(cookies_from_browser), "-J", "--no-playlist", url])
    return {
        "id": data.get("id"),
        "title": data.get("title", "Unknown title"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail", ""),
        "url": data.get("webpage_url", url),
        "channel": data.get("channel") or data.get("uploader") or "",
    }


def list_playlist_videos(
    url: str, cookies_from_browser: Optional[str] = None
) -> Tuple[str, List[dict]]:
    """Enumerate every video in a playlist without downloading (flat listing).

    Returns (playlist_title, videos).
    """
    data = _run_json([*_cookie_args(cookies_from_browser), "--flat-playlist", "-J", url])
    entries = data.get("entries") or []
    videos = []
    for entry in entries:
        if entry is None:
            continue  # deleted/private entries yt-dlp can't even flat-list
        video_id = entry.get("id")
        videos.append(
            {
                "id": video_id,
                "title": entry.get("title") or f"Unknown ({video_id})",
                "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
                "channel": entry.get("channel") or entry.get("uploader") or "",
            }
        )
    playlist_title = data.get("title") or "Playlist"
    return playlist_title, videos


def search_candidates(
    query: str, limit: int = 5, cookies_from_browser: Optional[str] = None
) -> List[Candidate]:
    """Run `ytsearch<limit>:"query"` and return raw candidates (unranked)."""
    data = _run_json([*_cookie_args(cookies_from_browser), "-J", f"ytsearch{limit}:{query}"])
    entries = data.get("entries") or []
    candidates = []
    for entry in entries:
        if not entry:
            continue
        thumb = entry.get("thumbnail", "")
        if not thumb and entry.get("thumbnails"):
            thumb = entry["thumbnails"][-1].get("url", "")
        candidates.append(
            Candidate(
                video_id=entry.get("id", ""),
                url=entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                title=entry.get("title") or "Unknown title",
                channel=entry.get("channel") or entry.get("uploader") or "Unknown channel",
                duration=entry.get("duration"),
                thumbnail=thumb,
            )
        )
    return candidates


def download_audio(
    url: str, out_path_no_ext: str, cookies_from_browser: Optional[str] = None
) -> str:
    """Download best audio for `url`, transcoded to mp3 at `out_path_no_ext.mp3`.

    Returns the final file path. Requires ffmpeg on PATH.
    """
    _ensure_binary()
    try:
        proc = subprocess.run(
            [
                YT_DLP_BIN,
                *_cookie_args(cookies_from_browser),
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "0",
                "-o",
                f"{out_path_no_ext}.%(ext)s",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as e:
        raise YtDlpFailure(f"yt-dlp download timed out for {url}") from e

    if proc.returncode != 0:
        _raise_classified_error(proc.stderr)

    return f"{out_path_no_ext}.mp3"
