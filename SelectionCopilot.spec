# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
metadata = []
for package in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
                "keyboard", "httpx", "python-dotenv", "pyttsx3", "pyperclip", "comtypes", "pywin32"):
    metadata += copy_metadata(package)

a = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=metadata,
    hiddenimports=["pyttsx3.drivers.sapi5"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SelectionCopilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "build" / "app.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SelectionCopilot")
