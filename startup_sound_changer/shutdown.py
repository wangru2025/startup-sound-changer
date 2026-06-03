from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import convert_to_wav
from .constants import app_data_dir
from .presets import resource_root

HELPER_EXE_NAME = "Windows-Shutdown-Helper.exe"
SERVICE_EXE_NAME = "Windows-Shutdown-Service.exe"
TASK_NAME = "Windows-Shutdown-Helper"
PRE_SHUTDOWN_TASK_NAME = "Windows-Shutdown-Helper-PreShutdown"
SERVICE_NAME = "Windows-Shutdown-Sound-Service"
SERVICE_DISPLAY_NAME = "Windows Shutdown Sound Service"
SETTINGS_NAME = "settings.json"
SHUTDOWN_SOUND_NAME = "shutdown_sound.wav"
PREPLAYED_NAME = "shutdown_preplayed.flag"
PLAY_MARKER_NAME = "shutdown_play_started.flag"
HELPER_DIR_NAME = "helper"
SOUNDS_DIR_NAME = "sounds"
PRESHUTDOWN_TIMEOUT_MS = 10000


@dataclass(slots=True)
class ShutdownApplyResult:
    sound_file: Path
    helper_file: Path
    service_file: Path
    settings_file: Path
    service_name: str


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_NAME


def helper_dir() -> Path:
    return app_data_dir() / HELPER_DIR_NAME


def helper_path() -> Path:
    return helper_dir() / HELPER_EXE_NAME


def service_path() -> Path:
    return helper_dir() / SERVICE_EXE_NAME


def shutdown_sounds_dir() -> Path:
    return app_data_dir() / SOUNDS_DIR_NAME


def shutdown_sound_path() -> Path:
    return shutdown_sounds_dir() / SHUTDOWN_SOUND_NAME


def preplayed_path() -> Path:
    return app_data_dir() / PREPLAYED_NAME


def play_marker_path() -> Path:
    return app_data_dir() / PLAY_MARKER_NAME


def shutdown_sound_installed() -> bool:
    return (
        helper_path().exists()
        and service_path().exists()
        and settings_path().exists()
        and _service_exists()
    )


def apply_shutdown_sound(source_audio: Path) -> ShutdownApplyResult:
    source_audio = Path(source_audio)
    if not source_audio.exists():
        raise FileNotFoundError(source_audio)

    app_data_dir().mkdir(parents=True, exist_ok=True)
    shutdown_sounds_dir().mkdir(parents=True, exist_ok=True)
    helper_dir().mkdir(parents=True, exist_ok=True)

    _stop_service()
    _stop_installed_helper()

    sound_file = convert_to_wav(source_audio, shutdown_sounds_dir(), target_name=SHUTDOWN_SOUND_NAME)
    installed_helper = _install_helper()
    installed_service = _install_service_exe()
    _write_settings(sound_file)
    _delete_task(TASK_NAME)
    _delete_task(PRE_SHUTDOWN_TASK_NAME)
    _ensure_service(installed_service)
    preplayed_path().unlink(missing_ok=True)
    play_marker_path().unlink(missing_ok=True)
    _start_service()

    return ShutdownApplyResult(
        sound_file=sound_file,
        helper_file=installed_helper,
        service_file=installed_service,
        settings_file=settings_path(),
        service_name=SERVICE_NAME,
    )


def remove_shutdown_sound() -> None:
    _stop_service()
    _delete_service()
    _stop_installed_helper()
    _delete_task(PRE_SHUTDOWN_TASK_NAME)
    _delete_task(TASK_NAME)
    settings_path().unlink(missing_ok=True)
    preplayed_path().unlink(missing_ok=True)
    play_marker_path().unlink(missing_ok=True)
    shutdown_sound_path().unlink(missing_ok=True)
    _remove_dir_if_empty(shutdown_sounds_dir())
    helper_path().unlink(missing_ok=True)
    service_path().unlink(missing_ok=True)
    _remove_dir_if_empty(helper_dir())
    _remove_dir_if_empty(app_data_dir())


def _write_settings(sound_file: Path) -> None:
    data = {
        "enabled": True,
        "shutdown_sound": str(sound_file),
    }
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _install_helper() -> Path:
    source = _find_embedded_file(HELPER_EXE_NAME)
    target = helper_path()
    shutil.copy2(source, target)
    return target


def _install_service_exe() -> Path:
    source = _find_embedded_file(SERVICE_EXE_NAME)
    target = service_path()
    shutil.copy2(source, target)
    return target


def _find_embedded_file(file_name: str) -> Path:
    candidates = [
        Path.cwd() / "build-assets" / "helper" / file_name,
        resource_root() / "helper" / file_name,
        resource_root() / file_name,
        Path.cwd() / "dist" / file_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{file_name} was not found. Build the helper/service first.")


def _start_helper(installed_helper: Path) -> None:
    subprocess.Popen(
        [str(installed_helper)],
        cwd=str(installed_helper.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _stop_installed_helper() -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", HELPER_EXE_NAME, "/T"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(0.8)


def _create_logon_task(installed_helper: Path) -> None:
    command = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/SC",
        "ONLOGON",
        "/TR",
        f'"{installed_helper}"',
        "/RL",
        "LIMITED",
        "/F",
    ]
    _run_checked(command)


def _delete_task(task_name: str) -> None:
    if not _task_exists(task_name):
        return
    _run_checked(["schtasks", "/Delete", "/TN", task_name, "/F"])


def _task_exists(task_name: str) -> bool:
    completed = subprocess.run(
        ["schtasks", "/Query", "/TN", task_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return completed.returncode == 0


def _ensure_service(installed_service: Path) -> None:
    if _service_exists():
        _run_checked(["sc.exe", "config", SERVICE_NAME, "binPath=", str(installed_service), "start=", "auto"])
        _run_checked(["sc.exe", "description", SERVICE_NAME, "Plays the configured shutdown sound before Windows finishes shutting down."])
    else:
        _run_checked([
            "sc.exe",
            "create",
            SERVICE_NAME,
            "binPath=",
            str(installed_service),
            "start=",
            "auto",
            "DisplayName=",
            SERVICE_DISPLAY_NAME,
        ])
        _run_checked(["sc.exe", "description", SERVICE_NAME, "Plays the configured shutdown sound before Windows finishes shutting down."])
    _set_service_preshutdown_timeout()


def _service_exists() -> bool:
    completed = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return completed.returncode == 0


def _start_service() -> None:
    completed = _run_service_command(["sc.exe", "start", SERVICE_NAME])
    if completed.returncode != 0 and "already" not in (completed.stdout + completed.stderr).lower() and "已启动" not in completed.stdout:
        _raise_process_error(completed, "service start failed")


def _stop_service() -> None:
    if not _service_exists():
        return
    completed = _run_service_command(["sc.exe", "stop", SERVICE_NAME])
    output = completed.stdout + completed.stderr
    if completed.returncode != 0 and "1062" not in output and "not been started" not in output.lower() and "没有启动" not in output:
        _raise_process_error(completed, "service stop failed")
    time.sleep(1.2)


def _delete_service() -> None:
    if not _service_exists():
        return
    completed = _run_service_command(["sc.exe", "delete", SERVICE_NAME])
    if completed.returncode != 0:
        _raise_process_error(completed, "service delete failed")


def _get_powershell_path() -> str:
    """Get the path to powershell.exe, with fallback options."""
    # Try common PowerShell locations in order
    candidates = [
        Path("C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"),
        Path("C:\\Program Files\\PowerShell\\7\\pwsh.exe"),
        Path("C:\\Program Files (x86)\\PowerShell\\7\\pwsh.exe"),
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    
    # Fallback to just "powershell" and let Windows search PATH
    return "powershell.exe"


def _set_service_preshutdown_timeout() -> None:
    script = "& { param($serviceName, $timeoutMs) $path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\' + $serviceName; New-ItemProperty -Path $path -Name PreshutdownTimeout -PropertyType DWord -Value $timeoutMs -Force | Out-Null; } "
    _run_checked([
        _get_powershell_path(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
        SERVICE_NAME,
        str(PRESHUTDOWN_TIMEOUT_MS),
    ])


def _run_service_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run_checked(command: list[str]) -> None:
    completed = _run_service_command(command)
    if completed.returncode != 0:
        _raise_process_error(completed, "command failed")


def _raise_process_error(completed: subprocess.CompletedProcess[str], fallback: str) -> None:
    message = completed.stderr.strip() or completed.stdout.strip() or fallback
    raise RuntimeError(message)


def _remove_dir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass
