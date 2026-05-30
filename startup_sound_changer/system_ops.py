from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

from .constants import IMAGERES_BACKUP_PATH, IMAGERES_OLD_PATH, IMAGERES_PATH


class SystemOperationError(RuntimeError):
    pass


CREATE_NO_WINDOW = 0x08000000
SUBPROCESS_TIMEOUT_SECONDS = 30


def ensure_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_backup() -> Path:
    if IMAGERES_BACKUP_PATH.exists():
        return IMAGERES_BACKUP_PATH

    _grant_full_control(IMAGERES_PATH.parent, is_directory=True)
    _grant_full_control(IMAGERES_PATH)

    shutil.move(IMAGERES_PATH, IMAGERES_BACKUP_PATH)
    shutil.copy2(IMAGERES_BACKUP_PATH, IMAGERES_PATH)
    return IMAGERES_BACKUP_PATH


def prepare_patch_target() -> Path:
    if not ensure_admin():
        raise SystemOperationError("修改 imageres.dll 需要管理员权限。")

    backup = ensure_backup()
    _grant_full_control(IMAGERES_PATH.parent, is_directory=True)
    _grant_full_control(IMAGERES_PATH)
    _grant_full_control(backup)

    try:
        if IMAGERES_OLD_PATH.exists():
            _grant_full_control(IMAGERES_OLD_PATH)
            IMAGERES_OLD_PATH.unlink()
    except OSError:
        pass

    try:
        shutil.move(IMAGERES_PATH, IMAGERES_OLD_PATH)
    except OSError:
        pass

    shutil.copy2(backup, IMAGERES_PATH)
    return backup


def restore_system_resource() -> Path:
    if not ensure_admin():
        raise SystemOperationError("恢复 imageres.dll 需要管理员权限。")
    if not IMAGERES_BACKUP_PATH.exists():
        raise SystemOperationError("还没有可用的系统备份，无法恢复。请先成功应用一次启动声音。")

    _grant_full_control(IMAGERES_PATH.parent, is_directory=True)
    _grant_full_control(IMAGERES_BACKUP_PATH)
    if IMAGERES_PATH.exists():
        _grant_full_control(IMAGERES_PATH)

    try:
        if IMAGERES_OLD_PATH.exists():
            _grant_full_control(IMAGERES_OLD_PATH)
            IMAGERES_OLD_PATH.unlink()
    except OSError:
        pass

    try:
        if IMAGERES_PATH.exists():
            shutil.move(IMAGERES_PATH, IMAGERES_OLD_PATH)
    except OSError:
        pass

    if IMAGERES_PATH.exists():
        IMAGERES_PATH.unlink()
    shutil.move(IMAGERES_BACKUP_PATH, IMAGERES_PATH)
    return IMAGERES_PATH


def _grant_full_control(path: Path, is_directory: bool = False) -> None:
    if not path.exists():
        return

    target = str(path)

    try:
        takeown = subprocess.run(
            ["takeown", "/a", "/f", target],
            capture_output=True,
            text=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemOperationError(f"接管所有权超时: {target}") from exc
    if takeown.returncode != 0:
        detail = takeown.stderr.strip() or takeown.stdout.strip() or f"无法接管所有权: {target}"
        raise SystemOperationError(detail)

    grant = "(OI)(CI)F" if is_directory else "F"
    try:
        icacls = subprocess.run(
            ["icacls", target, "/grant", f"*S-1-5-32-544:{grant}", "/c"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemOperationError(f"授予权限超时: {target}") from exc
    if icacls.returncode != 0:
        detail = icacls.stderr.strip() or icacls.stdout.strip() or f"无法授予管理员完全控制: {target}"
        raise SystemOperationError(detail)

    try:
        subprocess.run(
            ["attrib", "-r", target],
            capture_output=True,
            text=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pass
