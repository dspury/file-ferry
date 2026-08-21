# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the ferry sidecar (plan §10.6.3).
# Builds a console executable that runs file_ferry.service on stdio.
#
# The sidecar reads newline-delimited JSON-RPC from stdin and writes
# responses to stdout; it must be a console app (no window on Windows).
# This spec keeps the bundle minimal — no bundled FFmpeg or Resolve,
# which remain detected at runtime per the plan's dependency policy.

import os

# Resolve the src root relative to this spec file so the build is
# independent of the invoking working directory.
SCRIPTS_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "src"))
ENTRY = os.path.join(ROOT, "file_ferry", "service", "cli.py")

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        "file_ferry.persistence.migrations.001_initial_legacy",
        "file_ferry.persistence.migrations.002_vnext_entities",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PySide2",
        "matplotlib",
        "pytest",
        "mypy",
    ],
    noarchive=False,
)

# Onefile mode: a single self-extracting executable at the output path.
# This matches what electron/sidecar-command.ts resolves
# (resources/sidecar/ferry-service) and keeps the packaged layout
# a single file rather than a onedir bundle.
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ferry-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
