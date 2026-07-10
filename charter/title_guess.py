"""Best-effort cleanup of a YouTube video title into a song title + artist
guess. YouTube video titles are written for humans browsing YouTube, not for
song metadata -- "(Official Video)", "(4K Remaster)", channel name as the
only clue to who the artist is, etc. This is never authoritative; it just
gives the Phase 2 review page a better starting guess than the raw title.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

_JUNK_PATTERN = re.compile(
    r"[\(\[][^\)\]]*\b(official|video|audio|lyric|lyrics|mv|visualizer|"
    r"remaster(?:ed)?|hd|4k|hq|explicit|clean|music\s*video|video\s*oficial)"
    r"\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_TRAILING_PIPE = re.compile(r"\s*\|.*$")
_ARTIST_TITLE_SPLIT = re.compile(r"^\s*([^-–—]{1,60})[-–—]\s*(.+)$")
_CHANNEL_SUFFIX = re.compile(r"\s*-\s*(Topic|VEVO|Official)\s*$", re.IGNORECASE)


def clean_title(raw: str) -> str:
    cleaned = _JUNK_PATTERN.sub("", raw)
    cleaned = _TRAILING_PIPE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—")
    return cleaned or raw.strip()


def guess_artist_title(raw_title: str, channel: Optional[str]) -> Tuple[Optional[str], str]:
    """Return (artist_guess, title_guess). Neither is authoritative -- the
    review page shows both as editable, pre-filled fields.
    """
    cleaned = clean_title(raw_title)

    match = _ARTIST_TITLE_SPLIT.match(cleaned)
    if match:
        artist, title = match.group(1).strip(), match.group(2).strip()
        if artist and title:
            return artist, title

    artist = _CHANNEL_SUFFIX.sub("", channel).strip() if channel else None
    return (artist or None), cleaned
