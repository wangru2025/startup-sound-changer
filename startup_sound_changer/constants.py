from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "Startup Sound Changer"
SYSTEM32_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
IMAGERES_PATH = SYSTEM32_DIR / "imageres.dll"
IMAGERES_BACKUP_PATH = SYSTEM32_DIR / "imageres.dll.bak"
IMAGERES_OLD_PATH = SYSTEM32_DIR / "imageres.dll.old"

CONVERTED_NAME = "startup_sound.wav"
PREVIEW_NAME = "preview_sound.wav"
PATCHED_COPY_NAME = "imageres.patched.dll"
EXTRACTED_STARTUP_WAV_NAME = "startup-default.wav"
FFMPEG_OUTPUT_NAME = "ffmpeg-convert.wav"
ERROR_LOG_NAME = "app-error.log"

WAVE_RESOURCE_TYPE = "WAVE"
WAVE_RESOURCE_LANG = 1033
WAVE_RESOURCE_ID_VISTA = 5051
WAVE_RESOURCE_ID_MODERN = 5080


def app_data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return root / APP_NAME
