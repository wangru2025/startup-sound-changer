from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

import imageio_ffmpeg
import soundfile as sf

from .constants import CONVERTED_NAME, FFMPEG_OUTPUT_NAME


class AudioConversionError(RuntimeError):
    pass


def convert_to_wav(source: Path, workspace: Path, target_name: str = CONVERTED_NAME, sample_rate: int = 44100) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / target_name
    try:
        data, detected_rate = sf.read(str(source), always_2d=True)
        output_rate = detected_rate if detected_rate and detected_rate > 0 else sample_rate
        sf.write(str(target), data, output_rate, subtype="PCM_16")
        return target
    except Exception:
        ffmpeg_target = workspace / FFMPEG_OUTPUT_NAME
        ffmpeg_target.unlink(missing_ok=True)
        _convert_with_ffmpeg(source, ffmpeg_target, sample_rate)
        ffmpeg_target.replace(target)
        return target


def supported_extensions() -> Iterable[str]:
    return (
        "wav",
        "mp3",
        "flac",
        "ogg",
        "aiff",
        "aif",
        "m4a",
        "aac",
        "opus",
        "wma",
    )


def _convert_with_ffmpeg(source: Path, target: Path, sample_rate: int) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AudioConversionError(completed.stderr.strip() or "ffmpeg conversion failed")
