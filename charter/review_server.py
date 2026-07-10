"""Phase 2: a throwaway local web server that blocks until the user confirms
every song's title/artist (and, for Spotify-sourced songs, its YouTube
match) before any downloading or charting starts. No account, no
persistence -- the server is torn down the moment Confirm & Continue is
received.
"""
from __future__ import annotations

import html
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List

from .models import Song

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "review.html"


def _fmt_duration(seconds) -> str:
    if seconds is None:
        return "unknown length"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _render_candidate(idx: int, cand_num: int, cand) -> str:
    match_class = "duration-match" if cand.duration_matches else "duration-mismatch"
    match_label = "✓ duration matches" if cand.duration_matches else "duration differs"
    checked = "checked" if cand_num == 1 else ""
    return f"""
    <div class="candidate">
      <img src="{html.escape(cand.thumbnail)}" alt="">
      <iframe src="https://www.youtube.com/embed/{html.escape(cand.video_id)}"
              allow="encrypted-media" allowfullscreen></iframe>
      <div class="title">{html.escape(cand.title)}</div>
      <div class="channel">{html.escape(cand.channel)}</div>
      <div class="{match_class}">{_fmt_duration(cand.duration)} &mdash; {match_label}</div>
      <label class="choice">
        <input type="radio" name="song_{idx}" value="candidate{cand_num}" {checked}>
        Choose this
      </label>
    </div>"""


def _render_title_artist_fields(idx: int, song: Song) -> str:
    origin_note = ""
    if song.raw_title and song.raw_title != song.title:
        origin_note = f'<div class="origin-note">from: {html.escape(song.raw_title)}</div>'
    return f"""
  <div class="fields">
    <label class="field">
      Title
      <input type="text" name="title_{idx}" value="{html.escape(song.title)}">
    </label>
    <label class="field">
      Artist
      <input type="text" name="artist_{idx}" value="{html.escape(song.artist or '')}"
             placeholder="(unknown)">
    </label>
    {origin_note}
  </div>"""


def _render_song(idx: int, song: Song) -> str:
    fields_html = _render_title_artist_fields(idx, song)

    if not song.needs_review():
        return f"""
<div class="song">
  <h2>{html.escape(song.title)}</h2>
  {fields_html}
</div>"""

    meta = f"{html.escape(song.artist or '')} &middot; {_fmt_duration(song.known_duration)}"
    if not song.candidates:
        return f"""
<div class="song auto-skipped">
  <h2>{html.escape(song.title)}</h2>
  <div class="spotify-meta">{meta}</div>
  {fields_html}
  <p class="skip-note">No YouTube candidates found &mdash; auto-skipped.</p>
</div>"""

    candidate_html = "".join(
        _render_candidate(idx, n + 1, c) for n, c in enumerate(song.candidates)
    )
    return f"""
<div class="song">
  <h2>{html.escape(song.title)}</h2>
  <div class="spotify-meta">{meta}</div>
  {fields_html}
  <div class="candidates">{candidate_html}</div>
  <label class="choice">
    <input type="radio" name="song_{idx}" value="skip">
    Skip this song
  </label>
</div>"""


def run_review(songs: List[Song], port: int = 0, reminder_seconds: int = 300) -> None:
    """Show the review page and block until submitted.

    Mutates every song's `title`/`artist` from the submitted form values, and
    `chosen` for Spotify-sourced songs that needed a YouTube match picked.
    """
    if not songs:
        return

    for s in songs:
        if s.needs_review() and not s.candidates:
            s.chosen = "skip"

    rows = "".join(_render_song(idx, s) for idx, s in enumerate(songs))
    template = TEMPLATE_PATH.read_text()
    page = template.replace("{{COUNT}}", str(len(songs))).replace("{{ROWS}}", rows)
    page_bytes = page.encode("utf-8")

    done = threading.Event()
    decisions: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path not in ("/", ""):
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page_bytes)))
            self.end_headers()
            self.wfile.write(page_bytes)

        def do_POST(self):
            if self.path != "/submit":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return
            decisions.update(payload)
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"\nOpening review page in your browser: {url}")
    print(f"{len(songs)} song(s) to confirm. Click 'Confirm & Continue' when done.\n")
    webbrowser.open(url)

    waited = 0
    while not done.wait(timeout=reminder_seconds):
        waited += reminder_seconds
        print(
            f"Still waiting on the review page ({waited}s so far). "
            f"If the tab got closed, reopen it at: {url}"
        )

    server.shutdown()
    server.server_close()

    for idx, song in enumerate(songs):
        title = decisions.get(f"title_{idx}", "").strip()
        if title:
            song.title = title
        artist = decisions.get(f"artist_{idx}", "").strip()
        song.artist = artist or None

        if song.needs_review() and song.candidates:
            song.chosen = decisions.get(f"song_{idx}", "skip")
