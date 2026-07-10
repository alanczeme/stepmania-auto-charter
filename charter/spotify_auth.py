"""One-time browser login for Spotify's Authorization Code flow.

Spotify's Feb 2026 policy change means client-credentials (app-only) auth can
no longer read any playlist's items, including the user's own -- reading
playlist contents now requires a real logged-in user token. This opens a
local browser page for a one-time login, then caches a refresh token so
future runs don't need to log in again.
"""
from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPE = "playlist-read-private playlist-read-collaborative"
TOKEN_CACHE_PATH = Path.home() / ".config" / "stepmania-auto-charter" / "spotify_token.json"
LOGIN_REMINDER_SECONDS = 60


class SpotifyAuthError(Exception):
    pass


def get_user_access_token(client_id: str, client_secret: str, redirect_uri: str) -> str:
    """Return a valid user access token for playlist reads.

    Uses a cached refresh token if one exists; otherwise (or if the cached
    one no longer works) opens a one-time browser login.
    """
    cached = _load_cache()
    if cached and cached.get("refresh_token"):
        try:
            return _refresh(client_id, client_secret, cached["refresh_token"])
        except SpotifyAuthError:
            pass  # cached refresh token revoked/expired -- fall through to login

    return _login(client_id, client_secret, redirect_uri)


def _load_cache() -> Optional[dict]:
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return None


def _save_cache(data: dict) -> None:
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_PATH.write_text(json.dumps(data))
    TOKEN_CACHE_PATH.chmod(0o600)


def _refresh(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(client_id, client_secret),
        timeout=15,
    )
    if resp.status_code != 200:
        raise SpotifyAuthError(f"Spotify token refresh failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    # Spotify doesn't always issue a new refresh_token on refresh; keep the old one if so.
    _save_cache(
        {
            "refresh_token": data.get("refresh_token", refresh_token),
            "access_token": data["access_token"],
        }
    )
    return data["access_token"]


def _login(client_id: str, client_secret: str, redirect_uri: str) -> str:
    state = secrets.token_urlsafe(16)
    result: dict = {}
    done = threading.Event()
    callback_path = urlparse(redirect_uri).path or "/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            if qs.get("state", [None])[0] != state:
                self._respond("State mismatch (possible CSRF) -- close this tab and retry.")
                result["error"] = "state mismatch"
            elif "error" in qs:
                self._respond(f"Spotify login failed: {qs['error'][0]}. Close this tab and retry.")
                result["error"] = qs["error"][0]
            else:
                self._respond("Spotify login complete -- you can close this tab.")
                result["code"] = qs.get("code", [None])[0]
            done.set()

        def _respond(self, message: str) -> None:
            body = f"<html><body><p>{message}</p></body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    parsed_redirect = urlparse(redirect_uri)
    server = HTTPServer((parsed_redirect.hostname, parsed_redirect.port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    authorize_url = f"{AUTHORIZE_URL}?" + urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
        }
    )
    print(
        "\nSpotify now requires a real login to read playlist contents (a Feb 2026 "
        "API policy change -- this is one-time, cached for future runs)."
    )
    print(f"Opening browser to log in: {authorize_url}\n")
    webbrowser.open(authorize_url)

    waited = 0
    while not done.wait(timeout=LOGIN_REMINDER_SECONDS):
        waited += LOGIN_REMINDER_SECONDS
        print(f"Still waiting on Spotify login ({waited}s so far). Reopen if needed: {authorize_url}")

    server.shutdown()
    server.server_close()

    if result.get("error"):
        raise SpotifyAuthError(f"Spotify login failed: {result['error']}")
    if not result.get("code"):
        raise SpotifyAuthError("Spotify login did not return an authorization code.")

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=15,
    )
    if resp.status_code != 200:
        raise SpotifyAuthError(f"Spotify token exchange failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    _save_cache({"refresh_token": data["refresh_token"], "access_token": data["access_token"]})
    return data["access_token"]
