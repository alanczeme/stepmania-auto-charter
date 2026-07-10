"""Minimal Spotify Web API client: metadata only, never touches audio.

Track lookups use the client-credentials flow (app-only, no login). Playlist
item reads need a real user token (see spotify_auth.py) as of Spotify's Feb
2026 policy change, which restricted playlist contents to the authenticated
user's own playlists regardless of client-credentials or public/private
status. Either way this never touches actual audio -- Spotify's DRM stays
untouched, which is why YouTube is the audio source for the rest of the
pipeline.
"""
from __future__ import annotations

import json
import time
from typing import Iterator, Optional

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    pass


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, user_access_token: Optional[str] = None):
        """`user_access_token`, if given, is used as-is (a real logged-in user
        token from spotify_auth) instead of fetching a client-credentials
        (app-only) token. Playlist item reads require a user token as of
        Spotify's Feb 2026 policy change; track lookups don't.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = user_access_token
        self._token_expires_at: float = float("inf") if user_access_token else 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=15,
        )
        if resp.status_code != 200:
            raise SpotifyError(
                f"Spotify auth failed ({resp.status_code}): {resp.text}. "
                "Check spotify_client_id / spotify_client_secret."
            )
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def _get_url(self, url: str, params: Optional[dict] = None) -> dict:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._get_token()}"},
            params=params,
            timeout=15,
        )
        if resp.status_code == 404:
            raise SpotifyError(f"Not found on Spotify: {url}")
        if resp.status_code == 403:
            raise SpotifyError(
                f"Spotify refused access to {url} (403 Forbidden). Playlist reads need "
                "the logged-in user to actually own the playlist (or be a collaborator "
                "on it) -- make sure you logged in as the account that owns this "
                "playlist. One of Spotify's own algorithmic playlists (Discover Weekly, "
                "Daily Mix, etc.) will also always 403 here; those block third-party "
                "API access entirely."
            )
        if resp.status_code != 200:
            raise SpotifyError(f"Spotify API error {resp.status_code} for {url}: {resp.text}")
        return resp.json()

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._get_url(f"{API_BASE}{path}", params=params)

    def get_track(self, track_id: str) -> dict:
        data = self._get(f"/tracks/{track_id}")
        return _track_summary(data)

    def get_current_user(self) -> dict:
        data = self._get("/me")
        return {"id": data.get("id"), "display_name": data.get("display_name") or data.get("id")}

    def get_playlist_meta(self, playlist_id: str) -> dict:
        data = self._get(
            f"/playlists/{playlist_id}",
            params={"fields": "name,owner.id,owner.display_name,tracks.total"},
        )
        owner = data.get("owner") or {}
        return {
            "name": data.get("name") or "Spotify Playlist",
            "owner_id": owner.get("id"),
            "owner_name": owner.get("display_name") or owner.get("id") or "unknown",
            "total_tracks": (data.get("tracks") or {}).get("total", 0),
        }

    def get_playlist_items(self, playlist_id: str) -> Iterator[dict]:
        fields = "items(track(id,name,artists,duration_ms)),next"
        first_page = self._get(
            f"/playlists/{playlist_id}/items", params={"limit": 100, "fields": fields}
        )
        if not first_page.get("items"):
            # /items is a Feb 2026 rename of /tracks I couldn't independently verify
            # against Spotify's own docs (blocked from this environment) -- if it comes
            # back empty, fall back to the endpoint that's been stable for years rather
            # than assume the playlist is actually empty.
            first_page = self._get(
                f"/playlists/{playlist_id}/tracks", params={"limit": 100, "fields": fields}
            )

        url = None
        page = first_page
        while True:
            for item in page.get("items", []):
                track = item.get("track")
                if not track or not track.get("id"):
                    continue  # local files / removed tracks have no id
                yield _track_summary(track)
            url = page.get("next")
            if not url:
                return
            page = self._get_url(url)

    def debug_raw_items_page(self, playlist_id: str) -> str:
        """Unfiltered dump of the first items page, for diagnosing an
        unexpected-empty-result situation the classified error paths didn't
        already explain (e.g. a wrong endpoint/fields assumption)."""
        try:
            data = self._get(f"/playlists/{playlist_id}/items", params={"limit": 3})
            return f"/items response: {json.dumps(data)[:1500]}"
        except SpotifyError as e:
            return f"/items request itself failed: {e}"


def _track_summary(track: dict) -> dict:
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    return {
        "id": track["id"],
        "title": track["name"],
        "artist": artists,
        "duration": round(track["duration_ms"] / 1000),
    }
