from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


STARTUP_PRESET_DIR_NAME = "windows-sounds"
SHUTDOWN_PRESET_DIR_NAME = "shutdown-sounds"


@dataclass(frozen=True, slots=True)
class SoundPreset:
    label: str
    filename: str
    directory: str = STARTUP_PRESET_DIR_NAME

    @property
    def path(self) -> Path:
        return resource_root() / self.directory / self.filename


SOUND_PRESETS = (
    SoundPreset("Windows 11", "Windows_11.wav"),
    SoundPreset("Windows Vista / 7 / 8 / 10", "Windows_Vista_7_8_10.wav"),
    SoundPreset("Windows XP", "Windows_XP.wav"),
    SoundPreset("Windows NT 5.0", "Windows_NT_5.wav"),
    SoundPreset("Windows ME / 2000", "Windows_ME_2000.wav"),
    SoundPreset("Windows 98", "Windows_98.wav"),
    SoundPreset("Windows 95", "Windows_95.wav"),
)

SHUTDOWN_SOUND_PRESETS = (
    SoundPreset("Windows XP", "Windows_XP.wav", SHUTDOWN_PRESET_DIR_NAME),
    SoundPreset("Windows NT 5.0", "Windows_NT_5.wav", SHUTDOWN_PRESET_DIR_NAME),
    SoundPreset("Windows 2000", "Windows_2000.wav", SHUTDOWN_PRESET_DIR_NAME),
    SoundPreset("Windows 98", "Windows_98.wav", SHUTDOWN_PRESET_DIR_NAME),
    SoundPreset("Windows 7 / 8 / 10 / 11", "Windows_7_8_10_11.wav", SHUTDOWN_PRESET_DIR_NAME),
)


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent
