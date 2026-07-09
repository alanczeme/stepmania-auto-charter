# StepMania Auto-Charter

Personal command-line tool for macOS. Give it a YouTube video/playlist link
or a Spotify track/playlist link; it downloads audio, auto-generates a
5-difficulty StepMania chart, and packages a ready-to-drop-in song folder.

For anything Spotify-sourced, it finds candidate YouTube matches and shows a
local review page in your browser to confirm each one before any downloading
or charting starts.

```
python generate.py "<link>"
```

## Setup

1. **Git Clone repo, cd into repo, start virtual env, install Python 3.9+** and these packages:
   ```
   git clone <your-repo-url>
   cd <repo-folder-name>
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **yt-dlp** and **ffmpeg**:
   ```
   brew install yt-dlp ffmpeg
   ```
3. **AutoStepper-Python** (the actual chart generator) — clone it somewhere
   and set up its own venv per its README:
   ```
   git clone https://github.com/bkeath/Autostepper-Python.git
   ```
4. **Spotify Developer app** (only needed for Spotify links) — create a free
   app at https://developer.spotify.com/dashboard for a Client ID/Secret.
   No elevated scopes required; this only ever calls `search` / `get track`
   / `get playlist items` metadata endpoints.
5. Copy `config.example.json` to `~/.config/stepmania-auto-charter/config.json`
   and fill in:
   - `spotify_client_id` / `spotify_client_secret`
   - `autostepper_path` — folder containing `AutoStepper.py`
   - `autostepper_python` — path to the Python interpreter in AutoStepper's
     venv (or just `python3` if it's on PATH with its deps installed)
   - `export_dir` — defaults to `~/StepMania Exports`
   - `stepmania_songs_dir` — optional, auto-copies output into a local
     StepMania install's `Songs/` folder

   All of these can also be set via environment variables
   (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `AUTOSTEPPER_PATH`,
   `AUTOSTEPPER_PYTHON`, `STEPMANIA_EXPORT_DIR`, `STEPMANIA_SONGS_DIR`).

## Usage

```
python generate.py "https://www.youtube.com/watch?v=..."
python generate.py "https://www.youtube.com/playlist?list=..."
python generate.py "https://open.spotify.com/track/..."
python generate.py "https://open.spotify.com/playlist/..."
```

- YouTube links (video or playlist) go straight to the download queue — no
  review step, since there's nothing to match.
- Spotify links search YouTube for the top 2 duration-matched candidates per
  song, then open a local review page. Nothing downloads until you click
  **Confirm & Continue**. Closing the tab without submitting doesn't hang
  forever — it prints periodic reminders with the URL to reopen.
- Output lands in `~/StepMania Exports/<Group>/<Song Title>/`, exactly two
  folders deep as StepMania's song wheel requires. Re-running a playlist
  later only processes songs that don't already have an output folder.
- `--workers N` passes through to AutoStepper's `--workers` flag (e.g. `-1`
  for all cores).

## How it works

See the module layout in `charter/`:

- `urls.py` — classifies the input link
- `spotify_client.py` — Spotify Web API (client-credentials, metadata only)
- `youtube.py` — yt-dlp wrapper: playlist enumeration, search, download
- `matching.py` — ranks YouTube search hits by duration closeness
- `review_server.py` — the blocking local review page (phase 2)
- `charting.py` — shells out to AutoStepper-Python
- `packaging.py` — builds the final `Songs/<Group>/<Song>/` folder,
  dedupes titles, backfills artwork from the source thumbnail if needed
- `cli.py` — wires the three phases together, prints progress/summary

## Known limitations

- Auto-generated charts are drafts — expect to clean up patterns in
  ArrowVortex, especially on the hardest difficulty.
- yt-dlp needs occasional `yt-dlp -U` updates as YouTube changes things.
- Spotify-sourced songs depend on finding a matching YouTube upload; only
  the top 2 candidates are surfaced, by design.
