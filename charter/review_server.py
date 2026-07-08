"""Phase 2: a throwaway local web server that blocks until the user confirms
YouTube matches for every Spotify-sourced song. No account, no persistence --
the server is torn down the moment Confirm & Continue is received.
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


def _render_song(idx: int, song: Song) -> str:
    meta = f"{html.escape(song.artist or '')} &middot; {_fmt_duration(song.known_duration)}"
    if not song.candidates:
        return f"""
<div class="song auto-skipped">
  <h2>{html.escape(song.title)}</h2>
  <div class="spotify-meta">{meta}</div>
  <p class="skip-note">No YouTube candidates found &mdash; auto-skipped.</p>
</div>"""

    candidate_html = "".join(
        _render_candidate(idx, n + 1, c) for n, c in enumerate(song.candidates)
    )
    return f"""
<div class="song">
  <h2>{html.escape(song.title)}</h2>
  <div class="spotify-meta">{meta}</div>
  <div class="candidates">{candidate_html}</div>
  <label class="choice">
    <input type="radio" name="song_{idx}" value="skip">
    Skip this song
  </label>
</div>"""


def run_review(songs: List[Song], port: int = 0, reminder_seconds: int = 300) -> None:
    """Show the review page and block until submitted. Mutates `song.chosen` in place."""
    review_songs = [s for s in songs if s.needs_review()]
    if not review_songs:
        return

    for s in review_songs:
        if not s.candidates:
            s.chosen = "skip"

    pending = [(idx, s) for idx, s in enumerate(review_songs) if s.candidates]
    if not pending:
        return  # everything was auto-skipped, nothing to actually review

    rows = "".join(_render_song(idx, s) for idx, s in enumerate(review_songs))
    template = TEMPLATE_PATH.read_text()
    page = template.replace("{{COUNT}}", str(len(pending))).replace("{{ROWS}}", rows)
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
    print(f"{len(pending)} song(s) need confirmation. Click 'Confirm & Continue' when done.\n")
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

    for idx, song in pending:
        song.chosen = decisions.get(f"song_{idx}", "skip")
