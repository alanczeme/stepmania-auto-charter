"""Data classes shared across the pipeline phases."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Candidate:
    video_id: str
    url: str
    title: str
    channel: str
    duration: Optional[int]  # seconds, None if unknown
    thumbnail: str
    duration_matches: bool = False


@dataclass
class Song:
    """One song moving through the pipeline."""

    source: str  # youtube_video | youtube_playlist_item | spotify_track | spotify_playlist_item
    title: str
    group: str  # target Songs/<group>/ name
    artist: Optional[str] = None
    known_duration: Optional[int] = None  # spotify duration in seconds, if known
    raw_title: Optional[str] = None  # original YouTube video title, before cleanup guessing

    # Direct YouTube sources skip straight to the queue.
    youtube_url: Optional[str] = None
    thumbnail: Optional[str] = None

    # Spotify sources need review.
    candidates: List[Candidate] = field(default_factory=list)
    chosen: Optional[str] = None  # "candidate1" | "candidate2" | "skip"

    status: str = "pending"  # pending, queued, skipped, downloaded, charted, packaged, failed
    error: Optional[str] = None

    def needs_review(self) -> bool:
        return self.source in ("spotify_track", "spotify_playlist_item")

    def resolved_youtube_url(self) -> Optional[str]:
        if self.youtube_url:
            return self.youtube_url
        if self.chosen == "candidate1" and len(self.candidates) > 0:
            return self.candidates[0].url
        if self.chosen == "candidate2" and len(self.candidates) > 1:
            return self.candidates[1].url
        return None

    def resolved_thumbnail(self) -> Optional[str]:
        if self.thumbnail:
            return self.thumbnail
        if self.chosen == "candidate1" and len(self.candidates) > 0:
            return self.candidates[0].thumbnail
        if self.chosen == "candidate2" and len(self.candidates) > 1:
            return self.candidates[1].thumbnail
        return None
