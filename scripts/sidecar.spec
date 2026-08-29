# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the ferry sidecar (plan §10.6.3).
# Builds a console executable that runs file_ferry.service on stdio.
#
# The sidecar reads newline-delimited JSON-RPC from stdin and writes
# responses to stdout; it must be a console app (no window on Windows).
# This spec keeps the bundle minimal — no bundled FFmpeg or Resolve,
# which remain detected at runtime per the plan's dependency policy.

import glob
import os

# Resolve the src root relative to this spec file so the build is
# independent of the invoking working directory.
SCRIPTS_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "src"))
ENTRY = os.path.join(ROOT, "file_ferry", "service", "cli.py")

# Migrations are discovered at runtime with `pkgutil.iter_modules`
# (persistence/runner.py), which PyInstaller's static analysis cannot
# follow -- nothing imports them by name, so without help none are
# collected. They therefore have to be named as hidden imports.
#
# Globbed rather than hand-listed. The list WAS hand-listed, naming only
# 001 and 002, and 003 was added without it: the frozen sidecar then knew
# about two migrations, computed `target 2`, and refused to open any
# database at schema_version 3 -- which is every real one. The packaged
# app died on launch with "sidecar exited before announcing readiness"
# (#139). A hand-maintained list re-breaks on every future migration,
# silently, so it is derived from disk instead.
MIGRATIONS_DIR = os.path.join(ROOT, "file_ferry", "persistence", "migrations")
MIGRATION_MODULES = sorted(
    "file_ferry.persistence.migrations." + os.path.splitext(os.path.basename(path))[0]
    for path in glob.glob(os.path.join(MIGRATIONS_DIR, "[0-9][0-9][0-9]_*.py"))
)
if not MIGRATION_MODULES:
    raise SystemExit(f"sidecar.spec: no migrations found under {MIGRATIONS_DIR}")
print(f"sidecar.spec: bundling {len(MIGRATION_MODULES)} migrations: {MIGRATION_MODULES}")

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=MIGRATION_MODULES,
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
