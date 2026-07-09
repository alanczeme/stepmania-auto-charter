"""Configuration loading for the StepMania auto-charter.

Config comes from (in increasing priority): defaults, a JSON config file at
~/.config/stepmania-auto-charter/config.json, then environment variables.
Nothing here is required until a code path actually needs it (e.g. Spotify
credentials are only required when a Spotify link is passed in).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".config" / "stepmania-auto-charter" / "config.json"
DEFAULT_EXPORT_DIR = Path.home() / "StepMania Exports"


@dataclass
class Config:
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None
    autostepper_path: Optional[str] = None
    autostepper_python: str = "python3"
    export_dir: Path = DEFAULT_EXPORT_DIR
    stepmania_songs_dir: Optional[str] = None
    review_port: int = 0
    review_reminder_seconds: int = 300
    chart_timeout_seconds: int = 1800

    def require_spotify(self) -> None:
        if not self.spotify_client_id or not self.spotify_client_secret:
            raise ConfigError(
                "Spotify credentials are not configured. Create a free app at "
                "https://developer.spotify.com/dashboard and set spotify_client_id / "
                "spotify_client_secret in "
                f"{CONFIG_PATH} (or the SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET "
                "environment variables)."
            )

    def require_autostepper(self) -> str:
        if not self.autostepper_path:
            raise ConfigError(
                "AutoStepper-Python is not configured. Clone "
                "https://github.com/bkeath/Autostepper-Python and set autostepper_path "
                f"in {CONFIG_PATH} (or the AUTOSTEPPER_PATH environment variable) to "
                "point at the checkout containing AutoStepper.py."
            )
        script = Path(self.autostepper_path) / "AutoStepper.py"
        if not script.exists():
            raise ConfigError(f"AutoStepper.py not found at {script}")
        return str(script)


class ConfigError(Exception):
    pass


def load_config() -> Config:
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError as e:
            raise ConfigError(f"Could not parse {CONFIG_PATH}: {e}") from e

    cfg = Config(
        spotify_client_id=data.get("spotify_client_id"),
        spotify_client_secret=data.get("spotify_client_secret"),
        autostepper_path=data.get("autostepper_path"),
        autostepper_python=data.get("autostepper_python", "python3"),
        export_dir=Path(data.get("export_dir", str(DEFAULT_EXPORT_DIR))).expanduser(),
        stepmania_songs_dir=data.get("stepmania_songs_dir"),
        review_port=int(data.get("review_port", 0)),
        review_reminder_seconds=int(data.get("review_reminder_seconds", 300)),
        chart_timeout_seconds=int(data.get("chart_timeout_seconds", 1800)),
    )

    cfg.spotify_client_id = os.environ.get("SPOTIFY_CLIENT_ID", cfg.spotify_client_id)
    cfg.spotify_client_secret = os.environ.get(
        "SPOTIFY_CLIENT_SECRET", cfg.spotify_client_secret
    )
    cfg.autostepper_path = os.environ.get("AUTOSTEPPER_PATH", cfg.autostepper_path)
    cfg.autostepper_python = os.environ.get(
        "AUTOSTEPPER_PYTHON", cfg.autostepper_python
    )
    if os.environ.get("STEPMANIA_EXPORT_DIR"):
        cfg.export_dir = Path(os.environ["STEPMANIA_EXPORT_DIR"]).expanduser()
    cfg.stepmania_songs_dir = os.environ.get(
        "STEPMANIA_SONGS_DIR", cfg.stepmania_songs_dir
    )
    if os.environ.get("CHART_TIMEOUT_SECONDS"):
        cfg.chart_timeout_seconds = int(os.environ["CHART_TIMEOUT_SECONDS"])

    cfg.export_dir.mkdir(parents=True, exist_ok=True)
    return cfg
