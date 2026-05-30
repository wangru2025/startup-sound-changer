from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .audio import convert_to_wav
from .constants import (
    EXTRACTED_STARTUP_WAV_NAME,
    IMAGERES_PATH,
    PATCHED_COPY_NAME,
    WAVE_RESOURCE_ID_MODERN,
    WAVE_RESOURCE_ID_VISTA,
    WAVE_RESOURCE_LANG,
    WAVE_RESOURCE_TYPE,
    app_data_dir,
)
from .native_resource import extract_resource, replace_resource
from .system_ops import ensure_backup, prepare_patch_target, restore_system_resource


@dataclass(slots=True)
class ApplyResult:
    converted_wav: Path
    patched_file: Path
    backup_file: Path


def workspace_dir() -> Path:
    path = app_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def apply_startup_sound(source_audio: Path) -> ApplyResult:
    workspace = workspace_dir()
    backup = prepare_patch_target()
    converted = convert_to_wav(source_audio, workspace)

    patched_copy = workspace / PATCHED_COPY_NAME
    patched_copy.write_bytes(IMAGERES_PATH.read_bytes())
    replace_resource(
        patched_copy,
        WAVE_RESOURCE_TYPE,
        wave_resource_id(),
        WAVE_RESOURCE_LANG,
        converted.read_bytes(),
    )
    IMAGERES_PATH.write_bytes(patched_copy.read_bytes())

    return ApplyResult(converted_wav=converted, patched_file=patched_copy, backup_file=backup)


def restore_startup_sound() -> Path:
    return restore_system_resource()


def extract_current_startup_sound() -> Path:
    workspace = workspace_dir()
    output = workspace / EXTRACTED_STARTUP_WAV_NAME
    source = IMAGERES_PATH if IMAGERES_PATH.exists() else ensure_backup()
    output.write_bytes(
        extract_resource(
            source,
            WAVE_RESOURCE_TYPE,
            wave_resource_id(),
            WAVE_RESOURCE_LANG,
        )
    )
    return output


def wave_resource_id() -> int:
    version = sys.getwindowsversion()
    if version.major > 6 or (version.major == 6 and version.minor >= 2):
        return WAVE_RESOURCE_ID_MODERN
    return WAVE_RESOURCE_ID_VISTA
