"""Minimal Spotify Web API client: metadata only, client-credentials auth.

Uses the client-credentials OAuth flow (app-only, no user login, no elevated
scopes) to call `search` / `get track` / `get playlist items`. This never
touches actual audio -- Spotify's DRM stays untouched, which is why YouTube is
the audio source for the rest of the pipeline.
"""
from __future__ import annotations

import time
from typing import Iterator, Optional

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    pass


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

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
                f"Spotify refused access to {url} (403 Forbidden). This app uses "
                "app-only auth (no user login), which can only read PUBLIC playlists. "
                "This is most often either: a private/unlisted playlist -- open it on "
                "Spotify, use the ••• menu, and make sure 'Make public' is checked -- "
                "or one of Spotify's own algorithmic playlists (Discover Weekly, Daily "
                "Mix, etc.), which block third-party API access entirely regardless of "
                "visibility."
            )
        if resp.status_code != 200:
            raise SpotifyError(f"Spotify API error {resp.status_code} for {url}: {resp.text}")
        return resp.json()

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._get_url(f"{API_BASE}{path}", params=params)

    def get_track(self, track_id: str) -> dict:
        data = self._get(f"/tracks/{track_id}")
        return _track_summary(data)

    def get_playlist_name(self, playlist_id: str) -> str:
        data = self._get(f"/playlists/{playlist_id}", params={"fields": "name"})
        return data.get("name") or "Spotify Playlist"

    def get_playlist_items(self, playlist_id: str) -> Iterator[dict]:
        url = f"{API_BASE}/playlists/{playlist_id}/tracks"
        params = {"limit": 100, "fields": "items(track(id,name,artists,duration_ms)),next"}
        while url:
            data = self._get_url(url, params=params)
            for item in data.get("items", []):
                track = item.get("track")
                if not track or not track.get("id"):
                    continue  # local files / removed tracks have no id
                yield _track_summary(track)
            url = data.get("next")
            params = None  # `next` already carries its own query string


def _track_summary(track: dict) -> dict:
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    return {
        "id": track["id"],
        "title": track["name"],
        "artist": artists,
        "duration": round(track["duration_ms"] / 1000),
    }
