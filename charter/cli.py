"""Phase orchestration: link -> queue -> review -> download/chart/package."""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from . import charting, matching, packaging, review_server, urls, youtube
from .config import Config, ConfigError, load_config
from .models import Song
from .spotify_auth import TOKEN_CACHE_PATH, SpotifyAuthError, get_user_access_token
from .spotify_client import SpotifyClient, SpotifyError
from .title_guess import guess_artist_title

DOWNLOAD_DELAY_SECONDS = 3
SEARCH_RESULTS_PER_SONG = 5


def build_queue(link: str, cfg: Config) -> List[Song]:
    kind = urls.classify(link)
    songs: List[Song] = []

    if kind == "youtube_video":
        info = youtube.get_video_info(link, cookies_from_browser=cfg.yt_dlp_cookies_from_browser)
        artist, title = guess_artist_title(info["title"], info["channel"])
        songs.append(
            Song(
                source="youtube_video",
                title=title,
                raw_title=info["title"],
                artist=artist,
                group="Singles",
                youtube_url=info["url"],
                thumbnail=info["thumbnail"],
            )
        )

    elif kind == "youtube_playlist":
        playlist_title, videos = youtube.list_playlist_videos(
            link, cookies_from_browser=cfg.yt_dlp_cookies_from_browser
        )
        group = playlist_title
        for v in videos:
            artist, title = guess_artist_title(v["title"], v["channel"])
            songs.append(
                Song(
                    source="youtube_playlist_item",
                    title=title,
                    raw_title=v["title"],
                    artist=artist,
                    group=group,
                    youtube_url=v["url"],
                    thumbnail=v["thumbnail"],
                )
            )

    elif kind == "spotify_track":
        cfg.require_spotify()
        client = SpotifyClient(cfg.spotify_client_id, cfg.spotify_client_secret)
        track = client.get_track(urls.spotify_id(link))
        song = _spotify_song(track, "spotify_track", "Singles", cfg)
        songs.append(song)

    elif kind == "spotify_playlist":
        cfg.require_spotify()
        user_token = get_user_access_token(
            cfg.spotify_client_id, cfg.spotify_client_secret, cfg.spotify_redirect_uri
        )
        client = SpotifyClient(
            cfg.spotify_client_id, cfg.spotify_client_secret, user_access_token=user_token
        )
        current_user = client.get_current_user()
        print(f"Logged into Spotify as: {current_user['display_name']} ({current_user['id']})")

        playlist_id = urls.spotify_id(link)
        meta = client.get_playlist_meta(playlist_id)
        group = meta["name"]
        owner_mismatch = (
            meta["owner_id"] is not None and meta["owner_id"] != current_user["id"]
        )
        if owner_mismatch:
            print(
                f"Warning: '{meta['name']}' is owned by '{meta['owner_name']}' "
                f"({meta['owner_id']}), not the logged-in account above. Playlist reads "
                "need the owner (or a collaborator) logged in -- this will likely return 0 "
                "tracks."
            )

        track_count = 0
        for track in client.get_playlist_items(playlist_id):
            songs.append(_spotify_song(track, "spotify_playlist_item", group, cfg))
            track_count += 1

        if track_count == 0 and owner_mismatch:
            raise SpotifyError(
                f"'{meta['name']}' is owned by '{meta['owner_name']}', but you're logged in "
                f"as '{current_user['display_name']}' -- that mismatch is why it returned 0 "
                f"tracks. Delete {TOKEN_CACHE_PATH} and rerun to log in again as "
                f"'{meta['owner_name']}'."
            )
        if track_count == 0:
            raw = client.debug_raw_items_page(playlist_id)
            raise SpotifyError(
                f"'{meta['name']}' returned 0 tracks even though you're logged in as its "
                f"owner and Spotify reports {meta['total_tracks']} track(s) on it. This "
                "isn't matching any cause I can already explain -- if you've already "
                "confirmed the app isn't stuck in Development Mode (Settings -> User "
                f"Management on https://developer.spotify.com/dashboard has "
                f"'{current_user['display_name']}' listed), this is the raw API response "
                f"for debugging:\n{raw}"
            )

    return songs


def _spotify_song(track: dict, source: str, group: str, cfg: Config) -> Song:
    song = Song(
        source=source,
        title=track["title"],
        artist=track["artist"],
        known_duration=track["duration"],
        group=group,
    )
    try:
        raw = youtube.search_candidates(
            f"{song.artist} {song.title}",
            limit=SEARCH_RESULTS_PER_SONG,
            cookies_from_browser=cfg.yt_dlp_cookies_from_browser,
        )
        song.candidates = matching.rank_candidates(song.known_duration, raw)
    except (youtube.YtDlpFailure, youtube.YtDlpNotFoundError) as e:
        print(f"  warning: YouTube search failed for '{song.title}': {e}", file=sys.stderr)
        song.candidates = []
    return song


def process_song(
    song: Song,
    cfg: Config,
    autostepper_script: str,
    workers: Optional[int],
    bpm_override: Optional[float] = None,
    offset_override: Optional[float] = None,
    synctime: Optional[float] = None,
) -> None:
    target = packaging.target_dir(cfg.export_dir, song.group, song.title)
    if packaging.already_done(target):
        song.status = "skipped"
        song.error = "already exists from a previous run"
        print(f"  already exists, skipping: {target}")
        return

    work_dir = Path(tempfile.mkdtemp(prefix="stepmania_dl_"))
    scratch_dir: Optional[Path] = None
    try:
        try:
            audio_path = Path(
                youtube.download_audio(
                    song.youtube_url,
                    str(work_dir / "audio"),
                    cookies_from_browser=cfg.yt_dlp_cookies_from_browser,
                )
            )
        except (youtube.VideoUnavailableError, youtube.YtDlpFailure, youtube.YtDlpNotFoundError) as e:
            song.status, song.error = "failed", str(e)
            print(f"  FAILED (download): {e}")
            return
        song.status = "downloaded"

        print("  downloaded, now charting (can take several minutes)...")
        try:
            chart_folder, scratch_dir = charting.generate_chart(
                audio_path,
                autostepper_script,
                cfg.autostepper_python,
                workers=workers,
                timeout_seconds=cfg.chart_timeout_seconds,
                bpm_override=bpm_override,
                offset_override=offset_override,
                synctime=synctime,
            )
        except charting.ChartingError as e:
            song.status, song.error = "failed", str(e)
            print(f"  FAILED (charting): {e}")
            return
        song.status = "charted"

        final_target = target
        if final_target.exists():
            final_target = packaging.unique_target_dir(cfg.export_dir, song.group, song.title)
        packaging.package(
            chart_folder, final_target, song.resolved_thumbnail(), song.title, song.artist
        )
        if cfg.stepmania_songs_dir:
            packaging.mirror_to_stepmania(final_target, song.group, cfg.stepmania_songs_dir)
        song.status = "packaged"
        print(f"  done -> {final_target}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if scratch_dir:
            shutil.rmtree(scratch_dir, ignore_errors=True)


def _print_summary(songs: List[Song]) -> None:
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    packaged = [s for s in songs if s.status == "packaged"]
    skipped = [s for s in songs if s.status == "skipped"]
    failed = [s for s in songs if s.status == "failed"]

    print(f"Completed: {len(packaged)}")
    print(f"Skipped:   {len(skipped)}")
    print(f"Failed:    {len(failed)}")

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  - {s.title}: {s.error or 'skipped in review'}")
    if failed:
        print("\nFailed:")
        for s in failed:
            print(f"  - {s.title}: {s.error}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate.py",
        description="Generate StepMania charts from a YouTube or Spotify link.",
    )
    parser.add_argument(
        "link", help="YouTube video/playlist URL or Spotify track/playlist URL"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="AutoStepper --workers passthrough (e.g. -1 for all cores)",
    )
    parser.add_argument(
        "--bpm-override",
        type=float,
        default=None,
        help=(
            "Force one flat BPM for every song charted this run, instead of "
            "AutoStepper's own tempo detection (which can be noisy/jittery on "
            "non-electronic material). Look up the song's real BPM first "
            "(e.g. tunebat.com/songbpm.com) -- meant for re-charting one "
            "specific song, not a whole playlist."
        ),
    )
    parser.add_argument(
        "--offset-override",
        type=float,
        default=None,
        help="Force this exact StepMania #OFFSET instead of AutoStepper's auto-aligned one.",
    )
    parser.add_argument(
        "--synctime",
        type=float,
        default=None,
        help="Nudge AutoStepper's auto-aligned offset earlier/later by this many seconds.",
    )
    args = parser.parse_args(argv)
    args.link = urls.clean(args.link)

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    try:
        songs = build_queue(args.link, cfg)
    except (
        urls.UnrecognizedLinkError,
        youtube.VideoUnavailableError,
        youtube.YtDlpFailure,
        youtube.YtDlpNotFoundError,
        SpotifyError,
        SpotifyAuthError,
        ConfigError,
    ) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not songs:
        print("Nothing to process.")
        return 0

    print(f"Phase 1 complete: {len(songs)} song(s) gathered.")

    review_server.run_review(
        songs, port=cfg.review_port, reminder_seconds=cfg.review_reminder_seconds
    )

    queue: List[Song] = []
    for s in songs:
        if s.needs_review():
            if s.chosen != "candidate1" and s.chosen != "candidate2":
                s.status = "skipped"
                s.error = s.error or (
                    "no candidates found" if not s.candidates else "skipped in review"
                )
                continue
            s.youtube_url = s.resolved_youtube_url()
        queue.append(s)

    print(f"Phase 2 complete: {len(queue)} song(s) queued for download & charting.\n")

    if not queue:
        _print_summary(songs)
        return 0

    try:
        autostepper_script = cfg.require_autostepper()
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    total = len(queue)
    for i, song in enumerate(queue, start=1):
        print(f'[{i}/{total}] Charting "{song.title}"...')
        process_song(
            song,
            cfg,
            autostepper_script,
            args.workers,
            bpm_override=args.bpm_override,
            offset_override=args.offset_override,
            synctime=args.synctime,
        )
        if i < total:
            time.sleep(DOWNLOAD_DELAY_SECONDS)

    _print_summary(songs)
    return 0
