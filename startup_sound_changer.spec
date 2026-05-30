# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_dir = Path.cwd()
datas = [
    (str(project_dir / "windows-sounds"), "windows-sounds"),
    (str(project_dir / "shutdown-sounds"), "shutdown-sounds"),
    (str(project_dir / "build-assets" / "helper" / "Windows-Shutdown-Helper.exe"), "helper"),
    (str(project_dir / "build-assets" / "helper" / "Windows-Shutdown-Service.exe"), "helper"),
]

hiddenimports = []

a = Analysis(
    ["app.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="startup-sound-changer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)