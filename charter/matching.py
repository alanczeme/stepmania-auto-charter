"""Rank YouTube search results against a known Spotify track duration."""
from __future__ import annotations

from typing import List

from .models import Candidate

DURATION_MATCH_TOLERANCE_SECONDS = 3
TOP_N = 2


def rank_candidates(known_duration: int, raw_candidates: List[Candidate]) -> List[Candidate]:
    """Sort by closeness to `known_duration`, flag close matches, keep top N.

    Candidates with unknown duration sort last (they can't be verified, but
    are still surfaced rather than dropped since something is better than
    nothing for a manual review step).
    """

    def sort_key(c: Candidate):
        if c.duration is None:
            return (1, 0)
        return (0, abs(c.duration - known_duration))

    ranked = sorted(raw_candidates, key=sort_key)
    for c in ranked:
        c.duration_matches = (
            c.duration is not None
            and abs(c.duration - known_duration) <= DURATION_MATCH_TOLERANCE_SECONDS
        )
    return ranked[:TOP_N]
