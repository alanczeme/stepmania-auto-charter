# StepMania Auto-Charter

## Setup from scratch (macOS)

New to this project? Run these in order in Terminal.

**1. Install Homebrew** (skip if `brew -v` already prints a version):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**2. Install Python 3:**
```bash
brew install python
```
macOS doesn't always have a bare `pip` command — use `pip3` below if `pip` isn't found.

**3. Clone this repo and cd into it** — it lives on GitHub; there's nothing to run until it's on your machine:
```bash
git clone https://github.com/alanczeme/stepmania-auto-charter.git
cd stepmania-auto-charter
```

**4. Create and activate a virtual environment:**
```bash
python3 -m venv venv
source venv/bin/activate
```
This avoids the "externally-managed-environment" error Homebrew's Python throws on a global `pip install`; you'll need to re-run `source venv/bin/activate` every new terminal session before running anything in this project.

**5. Install this project's Python dependencies** (only installs correctly with the venv active):
```bash
pip install -r requirements.txt
```

**6. Install the external command-line tools this project shells out to** (these aren't Python packages, so they're not in requirements.txt):
```bash
brew install yt-dlp ffmpeg
```

**7. Set up AutoStepper-Python.** This repo does not vendor it — it's a separate tool called over subprocess, so it needs its own clone and its own venv:
```bash
cd ..
git clone https://github.com/bkeath/Autostepper-Python.git
cd Autostepper-Python
python3 -m venv venv
source venv/bin/activate
pip install numpy librosa soundfile fire pydub
deactivate
cd ../stepmania-auto-charter
```
Note the full path to this `Autostepper-Python` folder and to its `venv/bin/python` — both are needed in the next step as `autostepper_path` and `autostepper_python`.

**8. Set up your config file:**
```bash
mkdir -p ~/.config/stepmania-auto-charter
cp config.example.json ~/.config/stepmania-auto-charter/config.json
nano ~/.config/stepmania-auto-charter/config.json
```
(`nano` is a simple terminal text editor — edit the values, then `Ctrl+O`, `Enter` to save, `Ctrl+X` to exit.)

Fields in that file:
- `spotify_client_id` / `spotify_client_secret` — from a free app at https://developer.spotify.com/dashboard (Dashboard → Create app → Settings shows both). **For Spotify playlist links**, also add `http://127.0.0.1:8899/callback` as a Redirect URI in that same app's Settings (must match `spotify_redirect_uri` below exactly) — Spotify now requires a real logged-in user to read playlist contents, so the first playlist run opens a one-time browser login; after that it's cached locally and you won't be asked again. Spotify track links don't need this.
- `autostepper_path` — full path to the `Autostepper-Python` folder from step 7 (the one containing `AutoStepper.py`)
- `autostepper_python` — full path to `Autostepper-Python/venv/bin/python` from step 7
- `export_dir` — where finished song folders get saved; `~/StepMania Exports` is fine as-is
- `stepmania_songs_dir` — optional; point at a local StepMania install's `Songs/` folder to auto-copy output there, or leave `""` to skip
- `review_port` — local port for the Phase 2 review page; `0` auto-picks a free port, leave as-is
- `review_reminder_seconds` — how often (seconds) to print a reminder if the review page is left open unconfirmed; `300` is fine as-is
- `chart_timeout_seconds` — how long to wait for AutoStepper on one song before giving up; `1800` (30 min) is fine as-is, raise it if you see timeout failures on longer songs or slower Macs
- `yt_dlp_cookies_from_browser` — optional; set to a browser name (e.g. `"chrome"`, `"safari"`, `"firefox"`) you're logged into YouTube with, to fix yt-dlp's `Sign in to confirm you're not a bot` error. Leave `""` unless you hit that error
- `spotify_redirect_uri` — must exactly match the Redirect URI added to your Spotify app above; `http://127.0.0.1:8899/callback` is fine as-is unless that port is taken on your Mac

**9. Verify the setup:**
```bash
python generate.py --help
```
If that prints usage instead of an error, the venv and dependencies are wired up correctly.

**10. Returning later**, every new terminal session just needs:
```bash
cd stepmania-auto-charter
source venv/bin/activate
python generate.py "<link>"
```
The venv doesn't stay active between sessions — reactivate it before every run.

## About

Personal command-line tool for macOS. Give it a YouTube video/playlist link
or a Spotify track/playlist link; it downloads audio, auto-generates a
5-difficulty StepMania chart, and packages a ready-to-drop-in song folder.

For anything Spotify-sourced, it finds candidate YouTube matches and shows a
local review page in your browser to confirm each one before any downloading
or charting starts.

```
python generate.py "<link>"
```

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
- Spotify **playlist** links open one extra one-time browser login (see
  config setup above) before Phase 1 can list the playlist's tracks at all —
  that's a separate step from the Phase 2 YouTube-match review page.
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
