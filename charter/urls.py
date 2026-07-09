"""Classify an input link into one of the four supported kinds."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
SPOTIFY_HOSTS = {"open.spotify.com"}


class UnrecognizedLinkError(ValueError):
    pass


def clean(url: str) -> str:
    """Undo shell-escaping artifacts (zsh commonly backslash-escapes ?, &, =
    in pasted URLs). A raw backslash is never valid in a URL, so it's always
    safe to strip.
    """
    return url.strip().replace("\\", "")


def classify(url: str) -> str:
    """Return one of: youtube_video, youtube_playlist, spotify_track, spotify_playlist."""
    parsed = urlparse(clean(url))
    host = parsed.netloc.lower()

    if host in YOUTUBE_HOSTS:
        qs = parse_qs(parsed.query)
        path = parsed.path.rstrip("/")

        if host == "youtu.be":
            return "youtube_video"

        if path == "/playlist" and "list" in qs:
            return "youtube_playlist"

        if path in ("/watch",) and "v" in qs:
            return "youtube_video"

        raise UnrecognizedLinkError(
            f"Recognized youtube.com link but couldn't tell video from playlist: {url}"
        )

    if host in SPOTIFY_HOSTS:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "track":
            return "spotify_track"
        if len(parts) >= 2 and parts[0] == "playlist":
            return "spotify_playlist"
        raise UnrecognizedLinkError(
            f"Recognized open.spotify.com link but not a track or playlist: {url}"
        )

    raise UnrecognizedLinkError(
        f"Unrecognized link (expected a youtube.com/youtu.be or open.spotify.com URL): {url}"
    )


def spotify_id(url: str) -> str:
    parsed = urlparse(clean(url))
    parts = [p for p in parsed.path.split("/") if p]
    # last path segment is the id; strip any trailing query-string artifacts
    return parts[-1].split("?")[0]
