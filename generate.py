#!/usr/bin/env python3
"""StepMania Auto-Charter entrypoint.

Usage:
    python generate.py "<youtube-or-spotify-link>"
"""
import sys

from charter.cli import main

if __name__ == "__main__":
    sys.exit(main())
