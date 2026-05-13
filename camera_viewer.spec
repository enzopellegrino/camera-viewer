# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# PySide6 Qt plugins we actually need
PYSIDE6_DIR = Path(".venv/lib/python3.14/site-packages/PySide6")
QT_PLUGINS_DIR = PYSIDE6_DIR / "Qt" / "plugins"

qt_plugins_needed = [
    "platforms",
    "imageformats",
    "iconengines",
    "styles",
    "tls",
    "networkinformation",
    "platforminputcontexts",
]

binaries = []
datas = []

# Include Qt plugins
for plugin in qt_plugins_needed:
    plugin_path = QT_PLUGINS_DIR / plugin
    if plugin_path.exists():
        for f in plugin_path.glob("*.dylib"):
            binaries.append((str(f), f"PySide6/Qt/plugins/{plugin}"))

# Include PySide6 Qt frameworks
qt_libs_dir = PYSIDE6_DIR / "Qt" / "lib"
if qt_libs_dir.exists():
    for fw in qt_libs_dir.glob("*.framework"):
        datas.append((str(fw), f"PySide6/Qt/lib/{fw.name}"))

# Include PySide6 Qt libexec (macdeployqt helper, rcc, etc.)
qt_libexec_dir = PYSIDE6_DIR / "Qt" / "libexec"
if qt_libexec_dir.exists():
    for f in qt_libexec_dir.iterdir():
        datas.append((str(f), "PySide6/Qt/libexec"))

datas += [("app/icon_128.png", "app")]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "cv2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["av", "sounddevice", "tkinter", "matplotlib", "numpy.testing"],
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
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Camera Viewer",
)

app = BUNDLE(
    coll,
    name="Camera Viewer.app",
    icon="icon.icns",
    bundle_identifier="com.enzo.camera-viewer",
    info_plist={
        "NSHighResolutionCapable": True,
        "NSCameraUsageDescription": "Accesso alle telecamere IP via RTSP",
        "LSMinimumSystemVersion": "12.0",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSApplicationCategoryType": "public.app-category.video",
    },
)
