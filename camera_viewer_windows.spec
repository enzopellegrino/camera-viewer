# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

block_cipher = None

pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all('PySide6')

datas = [("app/icon_128.png", "app")] + pyside6_datas

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=pyside6_binaries,
    datas=datas,
    hiddenimports=pyside6_hiddenimports + [
        "cv2",
        "cryptography",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["av", "sounddevice", "tkinter", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Camera Viewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Camera Viewer",
    contents_directory=".",
)
