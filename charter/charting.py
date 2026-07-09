"""Phase 3 charting step: shell out to AutoStepper-Python for a single song.

AutoStepper-Python (github.com/bkeath/Autostepper-Python) operates on whole
input/output directories rather than one file at a time, so each song gets
its own scratch input/output pair to keep runs isolated.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple


class ChartingError(Exception):
    pass


def _tail(text: Optional[str], lines: int = 15) -> str:
    if not text or not text.strip():
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


def generate_chart(
    audio_path: Path,
    autostepper_script: str,
    autostepper_python: str,
    workers: Optional[int] = None,
    timeout_seconds: int = 1800,
) -> Tuple[Path, Path]:
    """Run AutoStepper on a single audio file.

    Returns (chart_folder, scratch_dir): chart_folder is the AutoStepper output
    folder containing the generated .sm + assets; scratch_dir is the whole temp
    tree the caller must clean up (via shutil.rmtree) once it has copied out
    whatever it needs.
    """
    scratch_dir = Path(tempfile.mkdtemp(prefix="autostepper_"))
    in_dir = scratch_dir / "songs"
    out_dir = scratch_dir / "output"
    in_dir.mkdir()
    out_dir.mkdir()

    shutil.copy2(audio_path, in_dir / audio_path.name)

    cmd = [
        autostepper_python,
        autostepper_script,
        "generate",
        f"--input={in_dir}",
        f"--output={out_dir}",
    ]
    if workers is not None:
        cmd.append(f"--workers={workers}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as e:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        tail = _tail(e.stdout) or _tail(e.stderr) or "(no output captured)"
        raise ChartingError(
            f"AutoStepper timed out after {timeout_seconds}s charting {audio_path.name}. "
            f"This can be a slow-but-legitimate run (first invocation pays a librosa/numba "
            f"warmup cost) -- raise chart_timeout_seconds in config.json if it's consistently "
            f"this slow. Last output before timeout:\n{tail}"
        ) from e

    if proc.returncode != 0:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        tail = _tail(proc.stderr) or _tail(proc.stdout) or "unknown error"
        raise ChartingError(f"AutoStepper failed on {audio_path.name}:\n{tail}")

    sm_files = list(out_dir.rglob("*.sm"))
    if not sm_files:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        raise ChartingError(f"AutoStepper produced no .sm file for {audio_path.name}")

    return sm_files[0].parent, scratch_dir
