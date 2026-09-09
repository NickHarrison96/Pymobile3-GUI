# -*- mode: python ; coding: utf-8 -*-
"""
Pymobile3-GUI PyInstaller Spec
Onedir bundle (not onefile) — LGPL Qt compliance, replaceable libraries.
"""

import os
import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
# When running from spec file, __file__ is not defined. Use spec file location.
try:
    SPEC_DIR = Path(__file__).parent.resolve()
except NameError:
    SPEC_DIR = Path.cwd().resolve()

# The spec file lives at project root; source package is pymobile3_gui/
PROJECT_ROOT = SPEC_DIR
SRC_DIR = PROJECT_ROOT / "pymobile3_gui"
ASSETS_DIR = SRC_DIR / "assets"
RESOURCES_DIR = PROJECT_ROOT / "resources"  # shared with RootForgeKit if any

# Custom output path to avoid file locks
DISTPATH = str(PROJECT_ROOT / "dist_pymobile3")
WORKPATH = str(PROJECT_ROOT / "build_pymobile3")

# -----------------------------------------------------------------------------
# Data files (shipped read-only)
# -----------------------------------------------------------------------------
datas = [
    # UI assets: fonts, icons
    (str(ASSETS_DIR / "fonts"), "assets/fonts"),
    (str(ASSETS_DIR / "icons"), "assets/icons"),
]

# -----------------------------------------------------------------------------
# Binaries (shipped executables — platform-tools, etc.)
# These are copied into the bundle so they work offline.
# -----------------------------------------------------------------------------
binaries = []

# Platform tools (adb, fastboot) — optional, only if you ship them
# platform_tools_src = PROJECT_ROOT / "bin" / "platform-tools"
# if platform_tools_src.exists():
#     binaries.append((str(platform_tools_src), "bin/platform-tools"))

# -----------------------------------------------------------------------------
# Hidden imports (modules not detected by static analysis)
# -----------------------------------------------------------------------------
hiddenimports = [
    # PySide6 internals
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    # pymobiledevice3 submodules (dynamic imports)
    "pymobiledevice3",
    "pymobiledevice3.lockdown",
    "pymobiledevice3.usbmux",
    "pymobiledevice3.services.afc",
    "pymobiledevice3.services.diagnostics",
    "pymobiledevice3.remote",
    "pymobiledevice3.exceptions",
    # stdlib modules used dynamically
    "asyncio",
    "json",
    "subprocess",
    "threading",
    "inspect",
    "pathlib",
    # third-party
    "psutil",
    "nest_asyncio",
]

# -----------------------------------------------------------------------------
# Excludes (keep bundle lean)
# -----------------------------------------------------------------------------
excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "PIL",
    "pytest",
    "unittest",
    "http.server",
    "xmlrpc",
]

# -----------------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------------
a = Analysis(
    [str(SRC_DIR / "main.py")],
    pathex=[str(PROJECT_ROOT), str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
    distpath=DISTPATH,
    workpath=WORKPATH,
)

# Filter out unnecessary Qt plugins (keep only what we use)
# PySide6 plugins are large; we only need platforms, styles, iconengines, imageformats
def filter_qt_plugins(binaries_list):
    keep = {"platforms", "styles", "iconengines", "imageformats", "tls"}
    filtered = []
    for src, dest, typ in binaries_list:
        if "PySide6" in src and "plugins" in src:
            plugin_type = Path(src).parent.name
            if plugin_type in keep:
                filtered.append((src, dest, typ))
        else:
            filtered.append((src, dest, typ))
    return filtered

a.binaries = filter_qt_plugins(a.binaries)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Pymobile3-GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    distpath=DISTPATH,
    workpath=WORKPATH,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Pymobile3-GUI",
    distpath=DISTPATH,
    workpath=WORKPATH,
)