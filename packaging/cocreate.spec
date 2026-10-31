# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the CoCreate desktop app (macOS .app / any-OS onedir).

Build:  pyinstaller --noconfirm packaging/cocreate.spec
Output: dist/CoCreate/
"""

import os

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # spec lives in packaging/

hiddenimports = (
    collect_submodules("anticipation")
    + collect_submodules("uvicorn")
    + collect_submodules("mido")
    + collect_submodules("webview")
)

_datas = [(os.path.join(ROOT, "cocreation", "static"), "cocreation/static")]
_version_file = os.path.join(ROOT, "cocreation", "VERSION")
if os.path.exists(_version_file):  # written by CI at release time
    _datas.append((_version_file, "cocreation"))

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tensorflow", "magenta", "note_seq", "tkinter"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="CoCreate",
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed: no terminal pops up on macOS
    # argv_emulation relaunches the process on every macOS "reopen"
    # AppleEvent (Dock click, `open`), which fights the single-instance
    # guard — we don't need Finder file-open events anyway.
    argv_emulation=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="CoCreate",
)

import sys
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="CoCreate.app",
        icon=None,
        bundle_identifier="com.cocreation.app",
        info_plist={
            "CFBundleName": "CoCreate",
            "CFBundleDisplayName": "CoCreate – Human–AI Melody Co-Creation",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
