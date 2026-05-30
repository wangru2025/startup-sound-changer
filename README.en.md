# Startup Sound Changer

[中文](README.md) | English

A small Windows tool for changing the startup sound, with optional shutdown sound support.

The UI is intentionally simple: choose "set startup sound" or "set shutdown sound", then pick one of the bundled presets or choose your own audio file.

## Features

- Changes the Windows startup sound resource.
- Includes several classic Windows startup sound presets.
- Supports setting a shutdown sound.
- Uses a Windows Service plus a lightweight user-session helper to play the shutdown sound before shutdown or restart finishes.
- Audio preview runs on a separate thread. The preview button is disabled while preview is playing to avoid UI blocking and repeated playback.
- Removing the shutdown sound also removes the saved audio, config, helper, and service.

## Notes

Startup sound and shutdown sound are implemented differently.

Startup sound changes the system startup sound resource, so the app needs administrator privileges.

Since Windows 8, Windows no longer provides a stable classic shutdown sound entry point. This tool does not replace system files and does not intercept the power button. Instead, when Windows is preparing to shut down or restart, it tries to get a short window of time to play the selected sound. Normal shutdown or restart from the Start menu, shortcut menu, or command line will usually trigger it. Forced shutdown, power loss, holding the power button, system updates, audio service issues, or Windows timeout behavior may still cause the sound to be skipped or cut short.

## Audio Copyright

The bundled Windows preset sounds belong to Microsoft. They are included here only as nostalgic preset material for personal use. This project does not claim ownership of those audio files.

If you redistribute, commercialize, or reuse them in another project, please check the relevant licensing and risk yourself.

## Build

Requirements:

- Windows
- Python 3.12
- Go
- PowerShell

Install dependencies and build:

```powershell
scripts\build.ps1
```

If `.venv` already exists and dependencies are already installed:

```powershell
scripts\build.ps1 -SkipVenv
```

The built executable will be here:

```text
dist\startup-sound-changer.exe
```

## Project Layout

```text
app.py                         entry point
startup_sound_changer\          Python GUI and system modification logic
helper-go\main.go              shutdown sound helper in the user session
service-go\main.go             Windows Service
windows-sounds\                startup sound presets
shutdown-sounds\               shutdown sound presets
startup_sound_changer.spec      PyInstaller spec
scripts\build.ps1              build script
```

## Disclaimer

This is a small personal-use tool. It does not guarantee support for every Windows version, system policy, or shutdown path. Consider having a restore point or backup plan before using it, especially when changing the startup sound resource.
