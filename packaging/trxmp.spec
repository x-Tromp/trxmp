# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Trxmp's Windows distribution.

Builds two entry points into one onedir bundle: ``Trxmp.exe`` (the GUI —
windowed, no console, mirroring the ``gui-scripts`` entry in
pyproject.toml) and ``trxmp-dsp.exe`` (the CLI — console-attached) next
to it in the same folder, so the documented ``trxmp-dsp preset ...``
commands work straight out of the zip.

onedir, not onefile: PySide6 ships its Qt plugins (platforms, styles,
imageformats — hundreds of small files) as data, not code. Onefile mode
would re-extract all of that to a temp directory on *every* launch,
trading a one-time unzip for a multi-second delay on every single run —
a bad trade for an app that's installed once and opened often.

Build with:  uv run pyinstaller packaging/trxmp.spec --distpath dist --workpath build
"""

import os

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("trxmp.infrastructure.reference_data", includes=["*.yaml"])

# Both entry points touch the exact same set of Windows-only,
# hook-less libraries (WASAPI + Core Audio bindings): PyInstaller's
# static import scan can't see into their C extensions, so what they
# pull in has to be named explicitly.
hidden_imports = ["pyaudiowpatch", "pycaw.pycaw", "comtypes.stream"]

# SPECPATH (injected by PyInstaller into this file's exec globals) is
# this directory, regardless of the shell's own cwd when the build was
# invoked from — resolving relative to it, not "." or "..", is what
# makes `pyinstaller packaging/trxmp.spec` work the same from anywhere.
gui_analysis = Analysis(
    [os.path.join(SPECPATH, "entry_gui.py")],
    datas=datas,
    hiddenimports=hidden_imports,
)

cli_analysis = Analysis(
    [os.path.join(SPECPATH, "..", "src", "trxmp", "cli.py")],
    datas=datas,
    hiddenimports=hidden_imports,
)

gui_pyz = PYZ(gui_analysis.pure)
cli_pyz = PYZ(cli_analysis.pure)

gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="Trxmp",
    console=False,
)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="trxmp-dsp",
    console=True,
)

coll = COLLECT(
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.zipfiles,
    gui_analysis.datas,
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.zipfiles,
    cli_analysis.datas,
    name="Trxmp",
)
