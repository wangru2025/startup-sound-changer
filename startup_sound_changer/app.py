from __future__ import annotations

from .ui import StartupSoundApp


def main() -> int:
    app = StartupSoundApp(False)
    app.MainLoop()
    return 0
